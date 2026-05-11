"""Payment Abstraction (the hero protocol).

Reconstructs the LINK fee → swap → Reserves accumulation flow.

Mainnet contracts:
  - Reserves        0x5680681ED3767B96914CE741a308155C7fB9171d
  - FeeAggregator   0xd6e39d42AceE7Abcc460E6Ea78a0844A0980E78f
  - SwapAutomator   0x36E827bA2B270535ca1B099a6Ba2B280DDc0315e

What makes this the hero: trace walking (fee batch → swap call), proxy
resolution (FeeAggregator is a proxy), ABI decoding of multi-arg events,
ERC-677 `transferAndCall` semantics, and CCIP cross-chain join when the
source chain is L2. Every Vector-1 differentiator surfaces here.
"""
