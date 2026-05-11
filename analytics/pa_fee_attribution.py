"""Payment Abstraction fee attribution by Chainlink service.

Inputs are PA action rows from the marts. Partitions them by upstream service
contract address (VRF, Functions, Data Streams, CCIP, or other) and sums the
LINK that landed in Reserves. Used by the Economics team for service-level
profitability.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeeAttribution:
    snapshot_date: str
    service: str  # "vrf" | "functions" | "data_streams" | "ccip" | "other"
    source_address: str  # the upstream contract that paid the fee
    inflow_link: int  # raw uint256 — total LINK that flowed via this source


# Known Chainlink service contract addresses (placeholders; verify on
# Etherscan during Phase 1). The mapping below classifies the upstream of a
# PA fee event into a service bucket.
KNOWN_SERVICE_ADDRESSES: dict[str, str] = {
    # VRF v2.5 coordinator (mainnet)
    "0x271682deb8c4e0901d1a1550ad2e64d568e69909": "vrf",
    # Functions Router (mainnet)
    "0x65dcc24f8ff9e51f10dcc7ed1e4e2a61e6e14bd6": "functions",
    # Data Streams verifier (TBD — verify via docs)
    "0x0000000000000000000000000000000000000001": "data_streams",
    # CCIP Router (mainnet)
    "0x80226fc0ee2b096224eeac085bb9a8cba1146f7d": "ccip",
}


def classify_service(source_address: str) -> str:
    """Map an upstream address to a known Chainlink service name.

    Falls back to `other` for unknown addresses. Lowercased internally.
    """
    return KNOWN_SERVICE_ADDRESSES.get(source_address.lower(), "other")


def attribute_pa_fees(
    pa_actions: list[dict],
    snapshot_date: str,
) -> list[FeeAttribution]:
    """Group PA actions by upstream service and sum LINK inflows.

    `pa_actions` rows must contain at least:
      - `counterparty` (str): upstream contract address
      - `output_amount` (int): LINK amount that landed in Reserves

    Returns one FeeAttribution per (service, source_address). Attributions
    are sorted by inflow descending.
    """
    bucket: dict[tuple[str, str], int] = {}
    for action in pa_actions:
        cp = str(action.get("counterparty", "")).lower()
        if not cp:
            continue
        amount = int(action.get("output_amount", action.get("amount_link", 0)))
        service = classify_service(cp)
        key = (service, cp)
        bucket[key] = bucket.get(key, 0) + amount

    out = [
        FeeAttribution(
            snapshot_date=snapshot_date,
            service=service,
            source_address=src,
            inflow_link=amount,
        )
        for (service, src), amount in bucket.items()
    ]
    out.sort(key=lambda x: x.inflow_link, reverse=True)
    return out
