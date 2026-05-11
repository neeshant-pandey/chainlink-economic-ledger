# Protocol validation log

The implementer fills this in during Phase 1 (`spikes/one_tx_protocol_probe.py`).
Every assumption that downstream Python and dbt code rests on must be
confirmed here against a real mainnet tx — NOT against docs, NOT against a
Subgraph, NOT against Dune. Etherscan + the spike's printout are the ground
truth.

If a section says "TBD", the spike isn't done yet.

## Reference tx — Stake

- Tx hash: `0x08c2902756cb2808c056499225d6dbd40c3e656a3b53fe9d31679fcb8dc15e96`
- Block number: `18671459` (`0x11ce763`)
- Block hash: `0x33719db8c1afec798cf6889b6d9b20d3d4dd1b4476c43c837910337d2ff11759`
- Network: Ethereum mainnet (chain_id = 1)
- Staker EOA (`from`): `0xedacecf45dd8137b499c902e271751130f4ade27`
- Router (`to`): `0x3feb1e09b4bb0e7f0387cee092a52e85797ab889` (Stake.link wrapper)
- Pool: `0xBc10f2E862ED4502144c7d632a3459F49DFCDB5e` (Community Staking Pool v0.2)
- Why this tx: clean stake by a single EOA via the Stake.link router; emits the
  pool's `Staked(address,uint256,uint256,uint256)` event with the staker as
  the indexed topic and `(amount, newPrincipal, totalPoolPrincipal)` as data.
- Etherscan: https://etherscan.io/tx/0x08c2902756cb2808c056499225d6dbd40c3e656a3b53fe9d31679fcb8dc15e96
- Fixture: `tests/fixtures/golden_stake_tx/{tx,receipt,logs,block}.json` (real
  RPC captures from `https://ethereum.publicnode.com`).
- Trace: `tests/fixtures/golden_stake_tx/trace.json` is currently an empty
  array; the public RPC does not expose `debug_traceTransaction`. The trace
  will be populated once an archive-tier RPC URL is available. The H1 test
  decodes everything from `receipt.logs` alone.

## Reference tx — PA Reserves deposit

- Tx hash: `0x92359883d1f38f36c619247ac9e0e6049cb5fcc7282012fc78ecf4089434ed91`
- Block number: `24139066` (`0x170553a`)
- Block hash: `0x1c045135ed796d2e64bfb7c4dd8207f6ecfa598603fe5312104389bd959b22e1`
- Network: Ethereum mainnet (chain_id = 1)
- Keeper (`from`): `0x4ef3c3dc7fbd1eda22e6f85241bd22f2c2013721`
- Entry contract (`to`): `0x6593c7de001fc8542bb1703532ee1e5aa0d458fd`
- Logs surface: LINK Transfer (FeeAggregator → SwapAutomator) and LINK
  Transfer (SwapAutomator → Reserves) — the canonical PA inflow path.
- Etherscan: https://etherscan.io/tx/0x92359883d1f38f36c619247ac9e0e6049cb5fcc7282012fc78ecf4089434ed91
- Fixture: `tests/fixtures/golden_pa_tx/{tx,receipt,logs,block}.json` (real
  RPC captures).

## Confirmed contract addresses

All lowercase. Verified on Etherscan at the block above.

| Role | Address | Etherscan link | Phase version |
|---|---|---|---|
| LINK token | `0x514910771af9ca656af840dff83e8264ecf986ca` | https://etherscan.io/token/0x514910771AF9Ca656af840dff83E8264EcF986CA | n/a (immutable) |
| Community pool | `0x...` <!-- TBD --> | | v0.2 |
| Operator pool | `0x...` <!-- TBD --> | | v0.2 |
| Reward vault | `0x...` <!-- TBD --> | | v0.2 |
| (any others surfaced by the spike) | | | |

Cross-check: each address must be in `config/contracts/staking_v02.yaml` with
the same casing and the correct `deploy_block`. Mismatches block Phase 2.

## Event signatures

For each event the spike encountered, record:

### Staked
- Solidity signature: `Staked(address indexed staker, uint256 newPrincipal, ...)` <!-- TBD: get exact tuple from Etherscan ABI -->
- topic0 (keccak256 of signature): `0x...` <!-- TBD -->
- Indexed inputs (these live in `topics[1:]`): `staker`
- Non-indexed inputs (these live in `data`, abi-encoded): `newPrincipal`, `...`
- Notes / surprises:

### Unstaked / UnstakeRequested / UnstakeFinalized
<!-- TBD per event -->

### RewardClaimed
<!-- TBD -->

### Slashed
- Solidity signature: `Slashed(...)` <!-- TBD -->
- topic0: `0x...`
- **Critical question for the spike**: does a `Slashed` event come paired with
  a top-level ERC-20 `Transfer` log, or is the LINK movement only visible in
  the internal trace? This decides whether `match_action_to_movements` for
  slashing returns `method=event_log` or `method=trace`.
- Answer found by spike: <!-- TBD -->

### Migrated (v0.1 → v0.2)
<!-- TBD -->

### PoolConfigChanged or other admin-only events
<!-- TBD: surface them, decide whether they produce an EconomicAction -->

## Trace structure observations

The spike walks the `debug_traceTransaction` callTracer output. Record:

- Top-level call: `from=...`, `to=<pool>`, `selector=...`
- Depth at which the LINK Transfer happens: <!-- TBD -->
- Whether internal calls into LINK use `transfer` (selector `0xa9059cbb`),
  `transferFrom` (`0x23b872dd`), or both: <!-- TBD -->
- Did any sub-call revert (`error` field set, `success: false`)? If so, did
  the top-level tx still succeed? (It can — that's how try/catch works in
  Solidity.) <!-- TBD -->

## ABI shape for Phase 2

After confirming the above, this is the minimal set the project should include
into `config/contracts/abi/`:

- `staking_v02_community_pool.json` — at least the events Staked, Unstaked,
  UnstakeRequested, UnstakeFinalized, RewardClaimed, Slashed, Migrated
- `staking_v02_operator_pool.json` — same shape, may differ in fields
- `staking_v02_reward_vault.json`
- `link_token.json` — only Transfer + Approval needed

Each must be a real Etherscan-pulled ABI, not hand-written. Pull command (or
the manual workflow used) goes here.

## Surprises / things the docs got wrong

The single biggest derail risk in Phase 1 is: a confidently stated assumption
turns out to be subtly wrong. List every such surprise here as the spike
surfaces them. Examples that have bitten projects in this space:

- Pool address is a proxy — the implementation contract emits the events but
  the proxy address is what shows up in `log.address`
- Event field naming differs between v0.1 and v0.2
- Reward distribution is OFF-token (accrued in storage, not as a Transfer)
  until claimed
- Slashed amount in the event != amount actually moved on-chain (rounding)

Add to this list as Phase 1 progresses. **Do not let an unsurfaced surprise
leak into Phase 2.**

## Done-when checklist

- [ ] Spike runs end-to-end on the reference tx with no exceptions
- [ ] All five sections above filled in (no TBDs)
- [ ] Raw artifacts cached as JSON in `tests/fixtures/golden_stake_tx/`
- [ ] `tests/fixtures/known_txs.yml` has `stake.tx_hash` populated
- [ ] `config/contracts/staking_v02.yaml` has real addresses + deploy_block
- [ ] Spike printout shows `balance: OK` on the ledger entries section

Only when every box is ticked is the protocol "validated" and Phase 2 can
start.
