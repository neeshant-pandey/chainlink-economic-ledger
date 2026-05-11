# golden_pa_tx fixtures (REAL mainnet)

Cached raw artifacts for a REAL Payment Abstraction Reserves deposit on
Ethereum mainnet. The flow this fixture exercises end-to-end:

    keeper -> SwapAutomator (initiates) -> [DEX/transfer hop] ->
    LINK Transfer (FeeAggregator -> SwapAutomator) ->
    LINK Transfer (SwapAutomator -> Reserves)  <-- the PA inflow we model

## Reference tx

| Field         | Value                                                                                          |
| ------------- | ---------------------------------------------------------------------------------------------- |
| `tx_hash`     | `0x92359883d1f38f36c619247ac9e0e6049cb5fcc7282012fc78ecf4089434ed91`                           |
| `block`       | `24139066` (`0x170553a`)                                                                       |
| `from`        | `0x4ef3c3dc7fbd1eda22e6f85241bd22f2c2013721` (keeper/caller EOA)                               |
| `to`          | `0x6593c7de001fc8542bb1703532ee1e5aa0d458fd` (entry contract)                                  |
| `status`      | `0x1` (success)                                                                                |
| `LINK`        | `0x514910771AF9Ca656af840dff83E8264EcF986CA`                                                   |
| `FeeAggregator` | `0xd6e39d42AceE7Abcc460E6Ea78a0844A0980E78f`                                                 |
| `SwapAutomator` | `0x36E827bA2B270535ca1B099a6Ba2B280DDc0315e`                                                 |
| `Reserves`    | `0x5680681ED3767B96914CE741a308155C7fB9171d`                                                   |
| Source RPC    | `https://ethereum.publicnode.com` (public, free)                                               |
| Explorer      | https://etherscan.io/tx/0x92359883d1f38f36c619247ac9e0e6049cb5fcc7282012fc78ecf4089434ed91     |

## Receipt log layout

The receipt contains 4 logs:

1. ERC-20 `Transfer` on LINK: `FeeAggregator -> SwapAutomator`
2. FeeAggregator event (custom): `SwapAutomator` indexed, LINK token indexed
3. ERC-20 `Transfer` on LINK: `SwapAutomator -> Reserves` (the PA inflow)
4. Entry contract custom event

## Files

- `tx.json` — `eth_getTransactionByHash` response (REAL)
- `receipt.json` — `eth_getTransactionReceipt` response (REAL, 4 logs)
- `block.json` — `eth_getBlockByNumber(blockNumber, false)` header (REAL)
- `logs.json` — `receipt.logs` extracted for convenience (REAL)
- `trace.json` — `debug_traceTransaction(tx_hash, {tracer: "callTracer"})` — currently
  an empty JSON array `[]`. The public RPC endpoint used here does not expose
  `debug_traceTransaction`. The trace will be added when an archive-tier RPC
  is available. The H2 test does NOT depend on `trace.json` — it derives PA
  inflows from the LINK `Transfer` log whose `to == Reserves`.

## What the H2 unit test asserts (against these files)

1. Loading `logs.json` and decoding via `decoder.event_decoder.decode_log`
   recovers ≥1 LINK `Transfer` whose `to == Reserves`.
2. The PA semantics layer (`protocols.payment_abstraction.semantics`)
   classifies the inflow as a `RESERVES_DEPOSIT` action with the correct
   sender (`SwapAutomator`) and a positive amount.
3. The proxy resolver returns the expected configured implementation when
   handed a phase entry with `implementation_address`.
