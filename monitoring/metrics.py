"""Time-series metric emission.

Backend is GCP Cloud Monitoring (Stackdriver). All metrics share the namespace
`METRICS_NAMESPACE` from settings (default: `chainlink_staking_ledger`).

Naming convention: `{namespace}/{module}/{metric}` — e.g.
`chainlink_staking_ledger/decoder/decode_failure_rate`.
"""

from __future__ import annotations


def emit_decode_failure_rate(
    chain_id: int,
    source_name: str,
    failures: int,
    attempts: int,
) -> None:
    raise NotImplementedError("Planned production sink: Cloud Monitoring metric emitter.")


def emit_freshness_lag(chain_id: int, source_name: str, lag_seconds: int) -> None:
    raise NotImplementedError("Planned production sink: Cloud Monitoring metric emitter.")


def emit_reconciliation_pass_rate(
    chain_id: int,
    partition_id: str,
    pass_rate: float,
) -> None:
    raise NotImplementedError("Planned production sink: Cloud Monitoring metric emitter.")


def emit_reorg_event_count(chain_id: int, count: int, depth_max: int) -> None:
    raise NotImplementedError("Planned production sink: Cloud Monitoring metric emitter.")


def emit_unknown_signature_count(chain_id: int, count: int, signatures: list[str]) -> None:
    raise NotImplementedError("Planned production sink: Cloud Monitoring metric emitter.")
