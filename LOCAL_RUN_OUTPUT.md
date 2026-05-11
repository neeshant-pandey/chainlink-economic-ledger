# Local end-to-end demo run output

Captured from `make dbt-build-local` against a fresh `dbt/target/local.duckdb`
on 2026-05-11.

## Pipeline summary

```
seed_to_local: running real decode pipeline on golden fixtures…
  golden_stake_tx → 30 total rows
  golden_pa_tx    → 29 total rows

seed_to_local: writing CSVs to dbt/seeds/
  wrote    7 rows to dbt/seeds/seed_decoded_events.csv
  wrote   25 rows to dbt/seeds/seed_decoded_trace_calls.csv
  wrote    7 rows to dbt/seeds/seed_link_transfers.csv
  wrote    2 rows to dbt/seeds/seed_canonical_blocks.csv
  wrote    1 rows to dbt/seeds/seed_economic_actions.csv
  wrote    8 rows to dbt/seeds/seed_token_movements.csv
  wrote    3 rows to dbt/seeds/seed_action_movement_edges.csv
  wrote    6 rows to dbt/seeds/seed_ledger_entries.csv

seed_to_local: done. Real ledger entries: 6 actions: 1 movements: 8
seed_to_local: per-tx ledger invariant holds for 2 txs.
```

## dbt stage tallies

| Stage        | Result                                                           |
| ------------ | ---------------------------------------------------------------- |
| `dbt seed`   | 8 PASS / 0 FAIL — 0.11s (`CREATE` for every seed file)           |
| `dbt run`    | 29 PASS / 0 FAIL — 1.38s (10 incremental models, 19 views)       |
| `dbt test`   | 73 PASS / 0 FAIL — 0.43s                                         |

## Mart row counts (DuckDB at `dbt/target/local.duckdb`)

```
=== local mart row counts ===
main_analytics.apy_realized_by_pool                          2 rows
main_analytics.fee_attribution_by_source                     0 rows
main_analytics.staker_reward_sustainability                  1 rows
main_analytics.weekly_reserve_accumulation                   1 rows
main_intermediate.int_action_movement_recon                  2 rows
main_intermediate.int_decode_failures                        0 rows
main_intermediate.int_economic_actions                       1 rows
main_intermediate.int_pool_balance_deltas                    0 rows
main_intermediate.int_token_movements                        8 rows
main_intermediate.int_unknown_signatures                     0 rows
main_marts.ledger_entries                                    6 rows
main_marts.pool_economics                                    1 rows
main_marts.reconciliation_status                             1 rows
main_marts.staking_link_flows                                1 rows
main_marts.wallet_economics                                  1 rows
main_raw.raw_balance_snapshots                               0 rows
main_raw.raw_blocks                                          2 rows
main_raw.raw_logs                                            7 rows
main_raw.raw_receipts                                        0 rows
main_raw.raw_traces                                          0 rows
main_raw.raw_transactions                                    0 rows
main_seed.seed_action_movement_edges                         3 rows
main_seed.seed_canonical_blocks                              2 rows
main_seed.seed_decoded_events                                7 rows
main_seed.seed_decoded_trace_calls                          25 rows
main_seed.seed_economic_actions                              1 rows
main_seed.seed_ledger_entries                                6 rows
main_seed.seed_link_transfers                                7 rows
main_seed.seed_token_movements                               8 rows
main_staging.stg_action_movement_edges                       3 rows
main_staging.stg_balance_snapshots                           0 rows
main_staging.stg_canonical_blocks                            2 rows
main_staging.stg_decoded_trace_calls                        25 rows
main_staging.stg_link_transfers                              5 rows
main_staging.stg_shadow_tip_blocks                           0 rows
main_staging.stg_staking_calls                               0 rows
main_staging.stg_staking_events                              1 rows
```

## Headline marts

### `marts.ledger_entries` — every LINK movement booked double-entry

```
  idx=0 debit      146.00 LINK -> wallet:0xedacecf45dd8137b499c902e271751130f4ade27   tx=0x08c2902756cb2808…
  idx=1 credit     146.00 LINK -> community_staking_pool:0xbc10f2e862ed4502144c7d632  tx=0x08c2902756cb2808…
  idx=0 debit     9463.18 LINK -> pa_swap_automator:0x36e827ba2b270535ca1b099a6ba2b2  tx=0x92359883d1f38f36…
  idx=1 credit    9463.18 LINK -> forwarded_to:0xd6e39d42acee7abcc460e6ea78a0844a098  tx=0x92359883d1f38f36…
  idx=0 debit     9463.18 LINK -> upstream:0x36e827ba2b270535ca1b099a6ba2b280ddc0315  tx=0x92359883d1f38f36…
  idx=1 credit    9463.18 LINK -> pa_reserves:0x5680681ed3767b96914ce741a308155c7fb9  tx=0x92359883d1f38f36…
```

Both txs balance per the per-tx invariant `Σ debit == Σ credit`:
- `0x08c2902756cb2808…` (Stake): 146 LINK debit/credit — REAL Community
  Staking Pool stake.
- `0x92359883d1f38f36…` (PA): 9,463.18 LINK debit/credit — REAL PA Reserves
  deposit.

### `marts.staking_link_flows`

```
  wallet=0xedacecf45dd8137b… type=stake        146.00 LINK status=exact
```

### `analytics.weekly_reserve_accumulation`

```
  week_start            inflow_source    link_inflow      tx_count
  2025-12-29 00:00:00   other_inflow     9463.18 LINK     1
```

(The week is `2025-12-29` because the PA fixture tx is from block
24,139,066 / timestamp 1767261899 = 2025-12-31 UTC.  `inflow_source` is
classified as `other_inflow` because the LINK Transfer to Reserves doesn't
have a corresponding `pa_fee_aggregator:` ledger entry in the same tx —
the FA→SwapAutomator hop produced a `service_contract:`-style account
instead in our minimal demo.)

### `analytics.fee_attribution_by_source`

Empty in the local demo — the WHERE clause requires `account LIKE
'service_contract:%'`, and no such account is produced by the current
PA semantics + ledger_builder pair on the FeeAggregator's
`AssetTransferredForSwap` event. Production data, where the PA
contracts emit the expected `Deposited` / `FeesReceived` events that
the semantics layer maps to `FEE_RECEIVED` actions, will populate this
mart.

### `marts.reconciliation_status`

```
  chain=1  blocks=18671459..24139066  pass_rate=1.00
  counts={"exact":3,"partial":0,"unmatched":0,"not_expected":0,"unexpected":0,"ambiguous":0}
```

Every action ↔ movement edge in the demo is `exact`.

## Last 30 lines of the verification command

```
20:17:59  73 of 73 PASS unique_stg_staking_events_decoded_event_id ....................... [PASS in 0.01s]

20:17:59  Finished running 73 data tests in 0 hours 0 minutes and 0.43 seconds (0.43s).

20:17:59  Completed successfully

20:17:59  Done. PASS=73 WARN=0 ERROR=0 SKIP=0 NO-OP=0 TOTAL=73

=== local mart row counts ===
main_analytics.apy_realized_by_pool                          2 rows
main_analytics.fee_attribution_by_source                     0 rows
main_analytics.staker_reward_sustainability                  1 rows
main_analytics.weekly_reserve_accumulation                   1 rows
main_intermediate.int_action_movement_recon                  2 rows
main_intermediate.int_decode_failures                        0 rows
main_intermediate.int_economic_actions                       1 rows
main_intermediate.int_pool_balance_deltas                    0 rows
main_intermediate.int_token_movements                        8 rows
main_intermediate.int_unknown_signatures                     0 rows
main_marts.ledger_entries                                    6 rows
main_marts.pool_economics                                    1 rows
main_marts.reconciliation_status                             1 rows
main_marts.staking_link_flows                                1 rows
main_marts.wallet_economics                                  1 rows
```
