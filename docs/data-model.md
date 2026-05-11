# Data model

## Mart contracts (enforced by dbt)

### `ledger_entries`
Double-entry economic ledger. Source of truth for all wallet/pool LINK accounting.

| Column | Type | Constraints |
|---|---|---|
| `entry_id` | STRING | PK, deterministic from `(action_id, entry_index)` |
| `action_id` | STRING | NOT NULL |
| `entry_index` | INT64 | NOT NULL; 0-based within an action |
| `account` | STRING | NOT NULL; wallet address OR pool role |
| `direction` | STRING | NOT NULL; `debit` or `credit` |
| `amount_link` | NUMERIC | NOT NULL; raw uint256 (1e18) |
| `chain_id`, `block_number`, `tx_hash` | NOT NULL |
| `run_partition_id` | STRING | lineage only |

**Per-tx invariant**: `SUM(amount_link WHERE direction='debit') == SUM(amount_link WHERE direction='credit')`. Enforced by `assert_ledger_balanced_per_tx.sql`.

### `staking_link_flows`
Per-event wallet flow surface. One row per `decoded_event_id`. Includes the
reconciliation status from the action's edges so analysts can filter to clean rows.

| Column | Type | Notes |
|---|---|---|
| `event_id` | STRING | PK |
| `wallet` | STRING | NOT NULL |
| `flow_type` | STRING | one of: stake, unstake_requested, unstake_finalized, reward_claimed, reward_accrued, slashed, migrated_from_v01 |
| `amount_link` | NUMERIC | raw 1e18 |
| `tx_hash`, `block_number` | | |
| `reconciliation_status` | STRING | exact / partial / ... |
| `run_partition_id` | STRING | lineage only |

### `wallet_economics`
Daily per-wallet rollup.

PK: `(wallet, snapshot_date)`. Columns: total_staked, total_claimed, total_slashed, net_flow.

### `pool_economics`
Daily per-pool rollup.

PK: `(pool_address, snapshot_date)`. Columns: rewards_distributed, slashes_applied, end_of_day_balance.

### `reconciliation_status`
Per-partition health record produced by Python.

| Column | Type | Notes |
|---|---|---|
| `partition_id` | STRING | PK |
| `chain_id` | INT64 | |
| `block_range_start`, `block_range_end` | INT64 | |
| `pass_rate` | FLOAT64 | fraction of txs with overall_status = exact |
| `counts_by_status` | JSON | `{exact: N, partial: M, ...}` |

## Staking v0.2 events (TODO during implementation)

Verify each against the deployed contract ABI and Etherscan. Populate
`config/contracts/staking_v02.yaml::event_signatures` with the actual topic0s.

| Event | Maps to ActionKind | Token movement expected? |
|---|---|---|
| `Staked(staker, amount, ...)` | `STAKE` | yes — wallet → pool |
| `UnstakeRequested(staker, amount, ...)` | `UNSTAKE_REQUESTED` | no (cooldown only) |
| `Unstaked(staker, amount, ...)` | `UNSTAKE_FINALIZED` | yes — pool → wallet |
| `RewardClaimed(staker, amount)` | `REWARD_CLAIMED` | yes — reward_vault → wallet |
| `RewardAdded(amount, ...)` | `REWARD_ACCRUED` | no (off-token; ledger entry only) |
| `Slashed(operator, amount, ...)` | `SLASHED` | sometimes — internal call within tx; trace-evidenced |
| `Migrated(staker, amount, ...)` | `MIGRATED_FROM_V01` | yes — v0.1 pool → v0.2 pool (debit/credit pair) |
| `PoolConfigChanged(...)` | `POOL_CONFIG_CHANGED` | no (admin event) |

## Reconciliation status semantics

- `exact` — action has a 1:1 movement with matching amount
- `partial` — action sums to N>1 movements (batched ops); allocation tracked per edge
- `unmatched` — action expected a movement but none found → investigate
- `not_expected` — action correctly has no movement (e.g., `UNSTAKE_REQUESTED`); `method` is NULL
- `unexpected` — movement with no matching action → investigate (could be unmodeled flow)
- `ambiguous` — multiple equally-valid movement assignments; raise to operator

## Reconciliation method

How the movement was observed (only meaningful when status ≠ `not_expected`):
- `event_log` — observed in `LINK Transfer` log
- `trace` — observed only via internal call (no top-level Transfer log emitted)
- `balance_inferred` — derived from balance delta when neither log nor trace present
- `manual_rule` — protocol-specific exception (e.g., admin balance correction)
