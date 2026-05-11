# AGENTS.md

Contract for any AI agent (or human) writing code in this repo. Read this
before touching anything. The parent `../CLAUDE.md` carries broader project
context (Payment Abstraction hero + Staking sister, name-don't-write workflow);
this file scopes what's specific to the **Staking v0.2 ledger scaffold**.

## What this is

A reorg-safe, idempotent, reconciliation-first data pipeline that reconstructs
the LINK economic flows of Chainlink Staking v0.2 directly from raw EVM data
(events, internal traces, token transfers) and materializes them into a
double-entry ledger in BigQuery via dbt.

Architecture: see `docs/architecture.md`. Data model: see `docs/data-model.md`.
Implementation order: `docs/reproduction.md`.

## Working mode

**Name-don't-write.** Default behavior:

1. Claude/agent names the function, signature, types, contract docstring, and
   gotchas. The user writes the body.
2. **One function at a time.** Don't queue several up. Wait for the user to
   finish before moving on.
3. **Teach blockchain concepts inline** the first time they appear (block, log,
   internal trace, topic, ABI, selector, proxy, ERC-20, ERC-677, OCR, finality,
   reorg, etc.) — 3-6 sentences. User says "skip" if they already know it.
4. **Review on request, never silently rewrite.** When the user pastes an
   implementation, review for correctness, edge cases, and concept-level
   mistakes. Don't reformat or refactor without ask.
5. **No surprise scope.** Don't generalize, don't add abstractions the user
   didn't ask for, don't pre-write helper functions.

Override only if the user says "write it for me", "stub it", or "show me a
reference impl".

## Non-negotiable invariants

These are the design contracts. Breaking any of them silently breaks the
pipeline's correctness story.

### 1. Python is authoritative for decoding and reconciliation
- All ABI decoding lives in Python (`decoder/`)
- All N:M reconciliation lives in Python (`reconciliation/`)
- dbt models READ Python output and aggregate / test / materialize. dbt does
  NOT decode events or implement matching logic.
- `stg_staking_events.sql` is a passthrough from `decoded_events` parquet, NOT
  a SQL-level decoder.

### 2. Seven idempotency grains, each with a deterministic ID
| Grain | ID function | Module |
|-------|-------------|--------|
| raw log | `compute_raw_log_id` | `decoder.event_decoder` |
| decoded event | `compute_decoded_event_id` | `decoder.event_decoder` |
| raw trace call | `compute_raw_trace_call_id` | `decoder.trace_decoder` |
| token movement | `compute_movement_id` | `reconciliation.movement_builder` |
| economic action | `compute_action_id` | `protocol.staking_v02_semantics` |
| ledger entry | `compute_ledger_entry_id` | `protocol.ledger_builder` |
| run partition | `compute_run_partition_id` | `lineage.run_metadata` |

ID functions must be **pure deterministic functions** of their inputs. No
timestamps, no UUIDs, no `hash()` (which is randomized per Python process), no
object identity. Two replays produce identical IDs.

### 3. `run_partition_id` is lineage-only
It appears as a column on every row in canonical tables but is **NOT** part of
any mart's `unique_key`. Marts merge by stable entity ID (`entry_id`,
`event_id`, etc.) so a replay overwrites the existing canonical row by ID with
`run_partition_id` updated to the latest run.

### 4. Reconciliation is N:M, not 1:1
`match_action_to_movements` returns `list[ActionMovementMatch]`, not a single
`Transfer | None`. An action may map to 0, 1, or many movements (batched ops,
slashing without immediate transfer, internal-call-only flows). Status × Method
split:
- `Status` = outcome (`exact`, `partial`, `unmatched`, `not_expected`,
  `unexpected`, `ambiguous`)
- `Method` = how the matched movement was observed (`event_log`, `trace`,
  `balance_inferred`, `manual_rule`); nullable when `Status = NOT_EXPECTED`

### 5. Reverted txs produce zero movements
`extract_erc20_transfer_calls` filters by `call.success && parent.success &&
receipt.status == 1`. A failed top-level tx must NOT contribute any
TokenMovement, even if internal calls "succeeded" in the trace tree.

### 6. LINK amounts are raw uint256
Stored as `NUMERIC` (BigQuery) or `DECIMAL(38,0)` (Databricks). **Never
`FLOAT64`** for accounting columns. The `link_amount_normalize` macro is for
display only.

### 7. Mart contracts are enforced
`ledger_entries`, `staking_link_flows`, `wallet_economics`, `pool_economics`,
`reconciliation_status` have `contract: enforced: true` in dbt schema.yml.
Adding/removing columns is a contract change — flag it explicitly.

### 8. Per-tx double-entry invariant
For every (chain_id, tx_hash) in `ledger_entries`:
`SUM(amount_link) WHERE direction='debit' == SUM(amount_link) WHERE direction='credit'`.
Enforced by `dbt/tests/assert_ledger_balanced_per_tx.sql` and
`protocol.ledger_builder.verify_double_entry`. If a new action kind violates
this, the action's `build_ledger_entries` is wrong — fix the builder, don't
loosen the test.

### 9. Aggregator phases are config-driven only
`config/contracts/*.yaml` is the source of truth for contract addresses,
deploy blocks, and ABI version per block range. There is no runtime
`register_phase()` API. Phase changes are deploy-time decisions, recorded in
git.

### 10. Custom Airflow operators are narrow
Only three exist: `EvmLogExtract`, `EvmTraceExtract`, `EvmBalanceSnapshot`. dbt
runs via `BashOperator`. BigQuery loads via the Google provider operators. Do
NOT add a `DbtRunOperator` or `LoadToBigQueryOperator`.

## Implementation order
See `docs/reproduction.md`. Six phases: protocol spike → in-memory spine →
storage + dbt marts → reliability-lite → orchestration → polish. Don't move to
the next phase until the current phase's "done when" criterion is met.

## Project layout

```
ingestion/      raw EVM fetchers (block, tx, log, receipt, trace, balance) +
                finality + reorg + checkpoint
decoder/        ABI registry, event/calldata/trace decoders, types (THE contracts)
storage/        parquet writers, BigQuery loader, manifests
protocol/       Chainlink Staking v0.2 semantics, ledger builder
reconciliation/ movement builder, N:M reconciler, balance reconciler, checks
lineage/        run metadata, source manifests
monitoring/     metrics, alerts
airflow/        DAGs + 3 custom operators
dbt/            raw → staging → intermediate → marts + macros + custom tests
databricks/     parity job + 2 notebooks (parity-only, not a duplicate pipeline)
tests/          unit + integration + fixtures
config/         contract YAMLs, ABI JSON, gcp.yaml, settings.yaml
scripts/        repro.sh, replay_partition.py, golden_tx_walkthrough.py
docs/           architecture, data-model, runbook, reproduction
spikes/         throwaway protocol-validation scripts (Phase 1; commit them)
```

## Run / test

```bash
make install             # deps
make up                  # local Airflow + Postgres
make test                # pytest unit + integration
make lint                # ruff + mypy + sqlfluff
make dbt-build           # full dbt build with tests
make idempotency-check   # the headline DE-craft proof
make golden-walkthrough TX=0x...   # forensic decode of one tx
```

## Conventions

- Python 3.12 (per `pyproject.toml` and `.python-version`); type hints required (`mypy --strict`)
- Lowercase EVM addresses everywhere internally; checksum addresses are display-only
- Block numbers, amounts: `int` (Python), `INT64` / `NUMERIC` (BQ). Never `float`.
- Timestamps: unix seconds (raw layer) or UTC ISO-8601 ms (display)
- Test fixtures over live RPC — golden tx artifacts cached as JSON
- Emojis: not used unless explicitly requested

## What NOT to do

- Don't decode in dbt
- Don't change a `compute_*_id` function's hashing scheme without flagging — it
  invalidates every downstream materialization
- Don't add `run_partition_id` to a mart's `unique_key`
- Don't widen reconciliation to 1:1 returns
- Don't add features to `ingestion/` until the protocol spike is done
- Don't refactor the scaffold module structure without an explicit ask
- Don't create new top-level packages without an explicit ask
- Don't pre-write function bodies (see "Working mode" above)
- Don't use Dune / Subgraphs / Covalent as a source of truth — only as
  validation references
- Don't claim `debug_traceTransaction` decomposes OCR oracle responses (it
  doesn't — that misunderstanding kills credibility in interviews)

## When in doubt

Re-read `docs/architecture.md` and `docs/data-model.md`. The contracts encoded
in `decoder/types.py` are authoritative — when a docstring conflicts with the
dataclass, trust the dataclass.
