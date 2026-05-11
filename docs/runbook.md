# Runbook

How to respond when an alert fires. Each section maps to one CheckResult name.

## `freshness_lag_exceeded`
**Symptom**: `monitoring.metrics.freshness_lag_seconds` exceeds `FRESHNESS_MAX_LAG_SECONDS` (default 30 min).

**Likely causes**:
1. Airflow scheduler stalled
2. RPC provider rate-limit
3. `staking_incremental` DAG failed silently and retries are exhausted

**Diagnose**:
```sql
SELECT chain_id, source_name, last_processed_block, last_processed_block_hash
FROM `{project}.staking_intermediate.checkpoints`;
```
Compare `last_processed_block` against the current chain head.

**Recover**:
1. Inspect Airflow → `staking_incremental` last run logs
2. If RPC rate-limited: rotate `RPC_FALLBACK_URL`
3. If checkpoint stuck: trigger `staking_backfill` DAG with `RANGE = checkpoint_block:current_head`

## `decode_failure_rate_high`
**Symptom**: ratio of `failure_reason='unknown_topic'` over total decode attempts > 0.5%.

**Likely cause**: contract upgrade or new event signature not in `config/contracts/staking_v02.yaml`.

**Diagnose**:
```sql
SELECT contract_address, topic0, COUNT(*) AS n, MIN(block_number), MAX(block_number)
FROM `{project}.staking_intermediate.int_unknown_signatures`
ORDER BY n DESC LIMIT 20;
```

**Recover**:
1. Find the contract on Etherscan
2. Add the new event signature to `config/contracts/staking_v02.yaml`
3. Add a phase entry if the ABI version changed
4. Drop new ABI JSON into `config/abis/`
5. Replay affected partitions: `make idempotency-check RANGE=...`

## `unmatched_economic_actions`
**Symptom**: `reconciliation_status.counts_by_status.unmatched > 0` for a partition.

**Likely cause**: An action produced no observable movement — could be:
- Trace fetching failed/skipped for that tx
- New action kind not in `staking_v02_semantics.classify_event_as_action`
- Movement happens via a contract path we don't model (e.g., flash-claim)

**Recover**:
1. Drill into `int_action_movement_recon` to find the offending tx
2. Run `make golden-walkthrough TX=<tx>` to see the full decode/recon path
3. If trace was missing: re-run `EvmTraceExtractOperator` for that tx
4. If new flow: extend `staking_v02_semantics` and replay

## `ledger_unbalanced_per_tx`
**Symptom**: `assert_ledger_balanced_per_tx` fails — `SUM(debits) != SUM(credits)` for some tx.

**This is a bug, not a data quality issue.** A balanced ledger is an invariant
of the construction logic in `protocol.ledger_builder.build_ledger_entries`.

**Recover**:
1. Identify offending tx from the failed test output
2. Reproduce locally: `make golden-walkthrough TX=<tx>`
3. Fix `build_ledger_entries` for the offending action kind
4. Add a unit test fixture in `tests/fixtures/known_txs.yml`
5. Replay the partition

## `pool_balance_mismatch`
**Symptom**: `assert_pool_delta_matches_net_movement` fails — observed `balanceOf` delta ≠ sum of canonical movements.

**Likely cause**: A movement is missing — could be:
- An internal call we didn't trace
- A non-`Transfer` LINK movement (e.g., `transferAndCall`, mint, burn)
- A reward distribution that bypasses Transfer events

**Recover**:
1. Pin down the partition and pool with the mismatch
2. Inspect the trace for any txs in the partition where `balanceOf(pool)` changed
3. Extend the movement model if a new flow is found
4. Replay

## `reorg_detected`
**Symptom**: `monitoring.metrics.reorg_event_count > 0`.

**Recover**:
1. Pipeline already auto-marked the affected partition for replay
2. Verify `staking_incremental` next run replays successfully
3. If a deep reorg (depth > 64): manual investigation — should not happen post-merge

## `databricks_parity_diff_critical`
**Symptom**: parity check found row/hash diff in a critical mart.

**Recover**:
1. The Delta side and BQ side were materialized from the SAME parquet — diffs
   indicate either (a) materialization difference (cast/precision) or
   (b) one warehouse loaded a different run_partition_id
2. Re-run `gcs_parquet_to_delta` with explicit run_partition_id filter
3. If still divergent: file an incident; treat as data integrity issue
