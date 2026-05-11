# golden_stake_tx fixtures (REAL mainnet)

Cached raw RPC artifacts for a REAL Chainlink Community Staking Pool v0.2 Stake
transaction from Ethereum mainnet. These are the inputs for the H1/K2 golden
decoding test and serve as the project's "validated" reference.

## Reference tx

| Field        | Value                                                                                 |
| ------------ | ------------------------------------------------------------------------------------- |
| `tx_hash`    | `0x08c2902756cb2808c056499225d6dbd40c3e656a3b53fe9d31679fcb8dc15e96`                  |
| `block`      | `18671459` (`0x11ce763`)                                                              |
| `from`       | `0xedacecf45dd8137b499c902e271751130f4ade27` (staker EOA)                             |
| `to`         | `0x3feb1e09b4bb0e7f0387cee092a52e85797ab889` (Stake.link router)                      |
| `pool`       | `0xBc10f2E862ED4502144c7d632a3459F49DFCDB5e` (Community Staking Pool v0.2)            |
| `status`     | `0x1` (success)                                                                       |
| Source RPC   | `https://ethereum.publicnode.com` (public, free)                                       |
| Explorer     | https://etherscan.io/tx/0x08c2902756cb2808c056499225d6dbd40c3e656a3b53fe9d31679fcb8dc15e96 |

The Staked event signature emitted on this contract is
`keccak256("Staked(address,uint256,uint256,uint256)")` =
`0xb4caaf29adda3eefee3ad552a8e85058589bf834c7466cae4ee58787f70589ed` — the
indexed `staker` is `topics[1]`, and the three uint256 values in `data` are
`(amount, newPrincipal, totalPoolPrincipal)`.

## Files

- `tx.json` — `eth_getTransactionByHash` response (REAL)
- `receipt.json` — `eth_getTransactionReceipt` response, includes 10 logs (REAL)
- `block.json` — `eth_getBlockByNumber(blockNumber, false)` header (REAL)
- `logs.json` — `receipt.logs` extracted for convenience (REAL)
- `trace.json` — `debug_traceTransaction(tx_hash, {tracer: "callTracer"})` — currently
  an empty JSON array `[]`. The public RPC endpoints used here do not expose
  `debug_traceTransaction`. The trace will be populated when an archive-tier
  RPC URL (Alchemy / QuickNode / Infura archive / etc.) is available — see
  `docs/protocol-validation.md` § Stake reference tx. The H1 test does NOT
  depend on `trace.json` — it derives all movements from `receipt.logs`.

## What the H1 unit test asserts (against these files)

1. Loading `logs.json` and running `decoder.event_decoder.decode_log` over each
   log decodes ≥1 `Staked` event whose indexed `staker` matches the tx's
   `from` field.
2. ≥1 ERC-20 `Transfer` log has `to == 0xBc10f2…` (the pool) and a positive
   amount.
3. Running the LINK Transfer logs through `reconciliation.movement_builder`
   followed by `protocols.staking_v02.ledger_builder` produces ledger entries
   that balance per tx (`SUM(debit) == SUM(credit)`).
