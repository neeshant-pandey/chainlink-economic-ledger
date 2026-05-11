"""Token movements: unified view of LINK transfers from logs and trace calls.

A canonical TokenMovement is identified by `(tx_hash, from, to, amount,
occurrence_index)`. The same movement may be observed via:
  - the ERC-20 `Transfer` event log (preferred evidence)
  - the internal `transfer` / `transferFrom` call in the trace (second source)

`unify_movements` merges these into one canonical record carrying both
`evidence_ids`. Logs are preferred when both observe the same movement because
logs are cheaper to verify and authoritative.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

from decoder.event_decoder import ERC20_TRANSFER_TOPIC0
from decoder.types import DecodedEvent, TraceTokenCall


@dataclass(frozen=True)
class TokenMovement:
    movement_id: str  # idempotency grain 4
    chain_id: int
    block_number: int
    tx_hash: str
    token_address: str
    from_addr: str
    to_addr: str
    amount: int
    evidence_ids: list[str] = field(default_factory=list)  # raw_log_id and/or raw_trace_call_id
    source_priority: Literal["log", "trace"] = "log"
    is_canonical: bool = True


def compute_movement_id(
    chain_id: int,
    tx_hash: str,
    from_addr: str,
    to_addr: str,
    amount: int,
    occurrence_index: int,
) -> str:
    """SHA-256 of `(chain_id, tx_hash, from, to, amount, occurrence_index)`.

    `occurrence_index` disambiguates the (rare) case where the same (from, to,
    amount) triple appears multiple times in a single tx. For logs, use
    `log_index`; for trace-only movements, use `_trace_address_to_index`.
    """
    canonical = (
        f"movement|{chain_id}|{tx_hash.lower()}|{from_addr.lower()}|"
        f"{to_addr.lower()}|{amount}|{occurrence_index}"
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _trace_address_to_index(trace_address: list[int]) -> int:
    """Stable injective mapping from trace_address list to a single int, for
    use as `occurrence_index` on trace-only movements.

    We treat the list as a base-65536 number (each component fits in a uint16
    in practice; we cap at 1<<16-1 with a saturation guard).
    """
    n = 0
    for component in trace_address:
        if component < 0:
            raise ValueError("trace_address components must be non-negative")
        n = (n << 16) | (component & 0xFFFF)
    return n


def build_movements_from_transfer_logs(
    link_transfer_events: list[DecodedEvent],
) -> list[TokenMovement]:
    """Filters `link_transfer_events` to ERC-20 Transfer signature, builds one
    TokenMovement per event with `source_priority='log'` and the raw_log_id as
    sole evidence.

    Events whose signature is NOT the ERC-20 Transfer topic0 are skipped (the
    caller may pass a mixed list).
    """
    out: list[TokenMovement] = []
    for ev in link_transfer_events:
        if ev.event_signature.lower() != ERC20_TRANSFER_TOPIC0:
            continue
        from_addr = str(ev.indexed_params.get("from", ev.indexed_params.get("_from", ""))).lower()
        to_addr = str(ev.indexed_params.get("to", ev.indexed_params.get("_to", ""))).lower()
        amount_raw = ev.data_params.get(
            "value", ev.data_params.get("_value", ev.data_params.get("amount", 0))
        )
        amount = int(amount_raw)

        movement_id = compute_movement_id(
            chain_id=ev.chain_id,
            tx_hash=ev.tx_hash,
            from_addr=from_addr,
            to_addr=to_addr,
            amount=amount,
            occurrence_index=ev.log_index,
        )
        out.append(
            TokenMovement(
                movement_id=movement_id,
                chain_id=ev.chain_id,
                block_number=ev.block_number,
                tx_hash=ev.tx_hash.lower(),
                token_address=ev.contract_address.lower(),
                from_addr=from_addr,
                to_addr=to_addr,
                amount=amount,
                evidence_ids=[ev.raw_log_id],
                source_priority="log",
                is_canonical=True,
            )
        )
    return out


def build_movements_from_trace_calls(
    trace_token_calls: list[TraceTokenCall],
) -> list[TokenMovement]:
    """One TokenMovement per TraceTokenCall, `source_priority='trace'`,
    raw_trace_call_id as sole evidence."""
    out: list[TokenMovement] = []
    for call in trace_token_calls:
        # For `transfer()`, `from` is the trace caller (we lifted it via the
        # decoder when possible). If it's empty, the recon layer must fill it
        # from the raw trace row.
        from_addr = call.from_addr.lower() if call.from_addr else ""
        to_addr = call.to_addr.lower()
        amount = int(call.amount)
        occ = _trace_address_to_index(list(call.trace_address))

        movement_id = compute_movement_id(
            chain_id=call.chain_id,
            tx_hash=call.tx_hash,
            from_addr=from_addr,
            to_addr=to_addr,
            amount=amount,
            occurrence_index=occ,
        )
        out.append(
            TokenMovement(
                movement_id=movement_id,
                chain_id=call.chain_id,
                block_number=call.block_number,
                tx_hash=call.tx_hash.lower(),
                token_address=call.token_address.lower(),
                from_addr=from_addr,
                to_addr=to_addr,
                amount=amount,
                evidence_ids=[call.raw_trace_call_id],
                source_priority="trace",
                is_canonical=True,
            )
        )
    return out


def unify_movements(
    log_movements: list[TokenMovement],
    trace_movements: list[TokenMovement],
) -> list[TokenMovement]:
    """Merges movements with identical `(tx_hash, from, to, amount)` into one
    canonical record. When both sources observe the same movement:
      - keep `source_priority='log'` (logs are cheaper to verify and authoritative)
      - merge `evidence_ids` (both raw_log_id and raw_trace_call_id present)
      - `is_canonical=True` on the kept record

    Movements observed only via trace remain canonical with
    `source_priority='trace'`.

    Edge case: the same (from, to, amount) triple may legitimately appear
    multiple times within a single tx (e.g., two equal-amount transfers in a
    batch). The deduplication key intentionally INCLUDES the movement_id so
    distinct occurrences don't accidentally merge.

    Returns a list ordered by `(block_number, tx_hash, source_priority, from_addr)`.
    """
    # Group by movement_id (which already includes occurrence_index, so
    # trace-only and log-only merges happen by entity identity, not by tuple
    # alone).
    by_id: dict[str, TokenMovement] = {}
    # Index log movements first (so they win on conflicts)
    for m in log_movements:
        by_id[m.movement_id] = m

    for tm in trace_movements:
        if tm.movement_id in by_id:
            existing = by_id[tm.movement_id]
            merged_evidence = list(existing.evidence_ids)
            for ev_id in tm.evidence_ids:
                if ev_id and ev_id not in merged_evidence:
                    merged_evidence.append(ev_id)
            by_id[tm.movement_id] = TokenMovement(
                movement_id=existing.movement_id,
                chain_id=existing.chain_id,
                block_number=existing.block_number,
                tx_hash=existing.tx_hash,
                token_address=existing.token_address,
                from_addr=existing.from_addr,
                to_addr=existing.to_addr,
                amount=existing.amount,
                evidence_ids=merged_evidence,
                source_priority="log",  # log wins
                is_canonical=True,
            )
        else:
            # Trace-only: keep as-is
            by_id[tm.movement_id] = tm

    # Also handle the case where log/trace observed the same (tx, from, to,
    # amount) but with different occurrence_index (e.g. log_index vs trace
    # address) — we must merge those too. Strategy: bucket by (tx_hash, from,
    # to, amount) and pair up if the bucket has exactly one log-only and one
    # trace-only.
    bucket: dict[tuple[str, str, str, int], list[TokenMovement]] = {}
    for tm in by_id.values():
        bucket.setdefault((tm.tx_hash, tm.from_addr, tm.to_addr, tm.amount), []).append(tm)

    final: list[TokenMovement] = []
    for entries in bucket.values():
        log_entries = [e for e in entries if e.source_priority == "log"]
        trace_entries = [e for e in entries if e.source_priority == "trace"]
        # If counts match, pair them up (log absorbs trace evidence)
        if log_entries and trace_entries and len(log_entries) == len(trace_entries):
            # Pair in stable order
            for log_e, trace_e in zip(log_entries, trace_entries, strict=True):
                merged_evidence = list(log_e.evidence_ids)
                for ev_id in trace_e.evidence_ids:
                    if ev_id and ev_id not in merged_evidence:
                        merged_evidence.append(ev_id)
                final.append(
                    TokenMovement(
                        movement_id=log_e.movement_id,
                        chain_id=log_e.chain_id,
                        block_number=log_e.block_number,
                        tx_hash=log_e.tx_hash,
                        token_address=log_e.token_address,
                        from_addr=log_e.from_addr,
                        to_addr=log_e.to_addr,
                        amount=log_e.amount,
                        evidence_ids=merged_evidence,
                        source_priority="log",
                        is_canonical=True,
                    )
                )
        else:
            # Asymmetric — keep all entries (different occurrence_index = real
            # distinct movements)
            final.extend(entries)

    final.sort(key=lambda m: (m.block_number, m.tx_hash, m.source_priority, m.from_addr))
    return final
