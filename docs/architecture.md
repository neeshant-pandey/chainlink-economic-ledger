# Architecture

## Layering principle

**Python is the source of truth for decoded and reconciled data.** dbt models read
Python output; dbt does not re-decode events or re-implement reconciliation logic.
The split exists because:

- N:M reconciliation needs explainable graph matching, evidence merging, and
  partial allocations — not naturally expressed in SQL
- Decoding ABIs in SQL (UDFs / hand-rolled) is fragile and slow at scale
- Persisting structured decode failures + edges is easier as Python-authored parquet

dbt owns: medallion layering, query optimization, mart contracts, cross-row
invariants (`assert_ledger_balanced_per_tx`, `assert_pool_delta_matches_net_movement`),
freshness checks, and lineage exposures.

## Data flow

```
                    Ethereum mainnet (RPC)
                            │
                            ▼
        ┌──────────────────────────────────────────┐
        │  ingestion/                              │
        │   ├─ block_fetcher                       │
        │   ├─ transaction_fetcher                 │
        │   ├─ log_fetcher  (windowed + adaptive)  │
        │   ├─ receipt_fetcher                     │
        │   ├─ trace_fetcher  (slashing/migration) │
        │   ├─ balance_fetcher                     │
        │   ├─ finality + reorg_handler            │
        │   └─ checkpoint                          │
        └──────────────────────────────────────────┘
                            │ parquet
                            ▼
        gs://bucket/raw/{table}/chain_id=…/block_date=…/run_partition_id=…/*.parquet
                            │
                            ▼
        ┌──────────────────────────────────────────┐
        │  decoder/                                │
        │   ├─ abi_registry  (config-driven)       │
        │   ├─ event_decoder  (DecodeResult)       │
        │   ├─ calldata_decoder                    │
        │   ├─ trace_decoder  (filters reverts)    │
        │   └─ contract_registry                   │
        └──────────────────────────────────────────┘
                            │ decoded parquet + decode_failures
                            ▼
        ┌──────────────────────────────────────────┐
        │  protocol/                               │
        │   ├─ staking_v02_semantics               │
        │   │     events → EconomicAction[]        │
        │   └─ ledger_builder                      │
        │         action + movements → entries     │
        └──────────────────────────────────────────┘
                            │
                            ▼
        ┌──────────────────────────────────────────┐
        │  reconciliation/                         │
        │   ├─ movement_builder  (log ∪ trace)     │
        │   ├─ economic_reconciler  (N:M edges)    │
        │   └─ balance_reconciler                  │
        └──────────────────────────────────────────┘
                            │ recon parquet
                            ▼
        ┌──────────────────────────────────────────┐
        │  storage/                                │
        │   ├─ dataset_writer  (parquet → GCS)     │
        │   ├─ bigquery_loader  (GCS → BQ)         │
        │   └─ manifest                            │
        └──────────────────────────────────────────┘
                            │
                            ▼
                 BigQuery — raw datasets
                            │
                            ▼
        ┌──────────────────────────────────────────┐
        │  dbt/                                    │
        │   raw → staging → intermediate → marts   │
        │   (with macros, mart contracts, tests)   │
        └──────────────────────────────────────────┘
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
        Looker Studio          Databricks parity
        (reconciliation        (Delta materialization
         dashboard)             of marts; row+hash diff)
```

## Idempotency grains

Every grain has a deterministic ID function. Replays produce identical IDs and
therefore identical hashes.

| Grain | ID function | Module |
|-------|------------|--------|
| raw log | `compute_raw_log_id(log)` | `decoder.event_decoder` |
| decoded event | `compute_decoded_event_id(event)` | `decoder.event_decoder` |
| raw trace call | `compute_raw_trace_call_id(tx, trace_addr)` | `decoder.trace_decoder` |
| token movement | `compute_movement_id(...)` | `reconciliation.movement_builder` |
| economic action | `compute_action_id(event, kind)` | `protocol.staking_v02_semantics` |
| ledger entry | `compute_ledger_entry_id(action_id, idx)` | `protocol.ledger_builder` |
| run partition | `compute_run_partition_id(chain, dag, run, source, partition)` | `lineage.run_metadata` |

`run_partition_id` is **lineage metadata only** — present as a column on every row,
NOT part of any mart's `unique_key`. Marts merge by stable entity ID; replay
overwrites by ID with `run_partition_id` updated to the latest run.

## Reorg model

- Above finality watermark → `shadow_tip_*` raw tables (visibility, not promoted)
- Below finality watermark → `canonical_*` tables
- `promote_finalized_blocks(...)` moves rows from shadow → canonical when they
  fall below the watermark, recording any `block_hash` conflicts as `ReorgEvent`s
- ReorgEvents → `mark_partition_for_replay` → re-ingestion on the next DAG run

The pipeline only emits mart-grade data for canonical blocks. Shadow tip is for
operator visibility and freshness monitoring.

## Reconciliation model

```
EconomicAction ──┐
                 │ N:M
TokenMovement ───┴──→ ActionMovementMatch (edge)
                                │
                                ▼
                       TxReconciliation (per-tx aggregate)
                                │
                                ▼
                  PartitionReconciliation (per-partition health)
```

Status × Method:
- `Status` = outcome of an edge (exact / partial / unmatched / not_expected /
  unexpected / ambiguous)
- `Method` = how the matched movement was observed (event_log / trace /
  balance_inferred / manual_rule); nullable when `status = not_expected`

## Cross-warehouse parity

Databricks Delta materializes the same parquet that BigQuery loads from. Daily
parity job compares row counts and full-row hashes for the 5 marts. Critical
mismatch (`ledger_entries`, `staking_link_flows`, `wallet_economics`) fails the
job and pages.
