# Reproduction guide

## Prereqs

- Python 3.11
- Docker + Docker Compose
- An archive Ethereum RPC with `debug_traceTransaction` (Alchemy free tier works)
- A GCP project with BigQuery + GCS enabled, and a service account with
  `BigQuery Data Editor` + `Storage Object Admin`

## Setup

```bash
cp .env.example .env       # fill in RPC_URL, GCP_PROJECT, GCS_BUCKET, GOOGLE_APPLICATION_CREDENTIALS
make install               # pip install -e '.[dev,airflow,dbt]' + dbt deps
cp dbt/profiles.yml.example dbt/profiles.yml   # fill in your project + service-account path
```

## Reviewer path (the one-command reproduction)

```bash
./scripts/repro.sh         # backfill + dbt build + recon + idempotency check
```

That runs end-to-end on a small (~10k block) range. Total runtime ~20-30 min.

## Inspect the result

```sql
-- Healthcheck
SELECT * FROM `{project}.staking_marts.reconciliation_status` ORDER BY block_range_end DESC LIMIT 5;

-- Wallet flows
SELECT * FROM `{project}.staking_marts.staking_link_flows`
WHERE wallet = LOWER('0xYourWallet')
ORDER BY block_number;

-- Ledger
SELECT direction, account, amount_link, tx_hash
FROM `{project}.staking_marts.ledger_entries`
WHERE tx_hash = '0x...'
ORDER BY entry_index;
```

## Forensic walkthrough

```bash
make golden-walkthrough TX=0x...
```

Prints the full reconstruction path: receipt → decoded events → token movements
(log + trace) → economic actions → reconciliation edges → ledger entries.

## Idempotency proof

```bash
make idempotency-check RANGE=18800000:18810000
```

Replays the range with a new `run_partition_id` and asserts every mart has
identical hashes pre/post. This is the single most important check for
demonstrating production-grade DE craft — it proves the pipeline is
deterministic and replay-safe.

## Implementation order

Six phases. Each phase has a clear "done when" check — don't move to the
next until that check is met. The order is optimized for **early protocol
validation, then horizontal expansion, then production hardening** — not for
dependency-graph cleanliness.

### Phase 1 — Protocol spike
Validate every assumption against a real mainnet Stake transaction before
building infrastructure on top of guesses. This is the single most likely
phase to be skipped and the single biggest cause of project derail.

- Pick one clean Stake tx from Etherscan
- Hand-write `spikes/one_tx_protocol_probe.py` that pulls receipt + logs +
  trace via RPC, decodes them, prints the action + movements + ledger entries
- Cache raw artifacts as JSON in `tests/fixtures/golden_stake_tx/` so future
  tests don't need live RPC
- Document confirmed contract addresses, event signatures, ABI shape, and
  trace structure in `docs/protocol-validation.md`

**Done when**: the script's printout proves the protocol is understood
end-to-end on a real tx.

### Phase 2 — In-memory production spine
Wire validated knowledge into the scaffold. **Includes LINK Transfer
reconciliation from the start** — `Staked` decoded → ledger entry without a
matching token movement is self-referential and not impressive.

- All 5 ID functions: `compute_raw_log_id`, `compute_decoded_event_id`,
  `compute_action_id`, `compute_movement_id`, `compute_ledger_entry_id`
- `decode_log` returning structured `DecodeResult`
- `staking_v02_semantics`: just `Staked` for now
- `movement_builder.build_movements_from_transfer_logs` (logs only)
- `economic_reconciler.match_action_to_movements` (just `EXACT` and
  `UNMATCHED` statuses; defer `PARTIAL` / `AMBIGUOUS`)
- `ledger_builder.build_ledger_entries` + `verify_double_entry`

No parquet, no GCS, no BigQuery yet.

**Done when**: `golden_tx_walkthrough.py` reconciles the same tx from Phase 1
through the scaffold modules — Staked event matched against LINK Transfer,
balanced ledger entries.

### Phase 3 — Storage + dbt marts (full-refresh)
Persist the in-memory pipeline output into BigQuery via dbt. Skip incremental
materialization but **keep grain-correct keys + `run_partition_id` columns**
so flipping to incremental later is a config change, not a rewrite.

- `storage/dataset_writer.write_logs_parquet`,
  `storage/bigquery_loader.load_parquet_to_bq`, `storage/manifest`
- dbt: `raw_logs`, `stg_staking_events`, `stg_link_transfers`,
  `int_economic_actions`, `int_token_movements`, **`ledger_entries`** mart
- Mart contract on `ledger_entries` enforced

**Done when**: a real BigQuery `ledger_entries` table contains reconciled
rows from a small block range, queryable by tx_hash.

### Phase 4 — Reliability-lite
Add the production-grade behaviors that distinguish this from a hobby project.
Replay-after-delete idempotency is the headline proof.

- Receipt status filter (reverted tx → no movements)
- Finality watermark
- `reorg_handler` with canonical/shadow tables
- `stg_canonical_blocks` dbt model
- Flip dbt models to `materialized='incremental'`, merge by stable entity ID
- Traces: add `trace_fetcher` + `trace_decoder` + slashing reconciliation
  IF a clean slashing tx is available; otherwise document as a known stretch

**Done when**: `scripts/replay_partition.py --assert-stable` passes — replaying
any range produces hash-identical marts.

### Phase 5 — Orchestration
Start with the simplest possible Airflow DAG — a `BashOperator` wrapping the
working manual command. Only refactor into custom operators after the simple
DAG is green.

- Simple wrapper DAG first
- Refactor into `EvmLogExtract` / `EvmTraceExtract` / `EvmBalanceSnapshot`
  operators
- Checkpoint store
- Backfill from Staking v0.2 deploy block to recent

**Done when**: incremental DAG runs unattended and `reconciliation_check` DAG
is green.

### Phase 6 — Polish + stretch
Everything that makes the repo public-shareable.

- Monitoring metrics + alerts
- CI workflow active (mypy / ruff / sqlfluff / pytest)
- Databricks parity job
- Blog post: *"Reconstructing a Chainlink Staking economic event from raw EVM
  data"*
- README forensic walkthrough finalized
- Public commit / share

**Done when**: anyone can clone + `./scripts/repro.sh` and reproduce a
reconciled mart from raw RPC.

## What to commit when

- After Phase 1: first commit, label honestly as WIP
- After Phase 2: shareable but quiet
- After Phase 3: start sharing publicly
- After Phase 6: polished portfolio piece

## The trap to avoid

**Don't infrastructure your way around protocol uncertainty.** Phase 1 exists
to remove "I assume the ABI looks like X" guesses before modules get built on
top of them. The protocol/RPC swamp — wrong addresses, ABI fields differing
from docs, traces unavailable, slashing rarer than expected — is the single
biggest derail risk. Mitigate by:

- Picking ONE clean Stake tx and reconciling it fully end-to-end before adding
  a second event type
- Caching raw artifacts as JSON fixtures so tests don't need live RPC
- Treating slashing/migration as stretch unless found early in the spike
