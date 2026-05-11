"""Protocol-specific semantics.

Each subpackage encodes how a specific Chainlink protocol's on-chain events
map to economic actions and ledger entries. Adding a new protocol = adding a
new subpackage; the ingestion / decoder / reconciliation / storage layers stay
protocol-agnostic.
"""
