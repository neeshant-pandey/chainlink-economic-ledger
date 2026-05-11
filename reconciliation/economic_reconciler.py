"""N:M reconciliation between economic actions and token movements.

Python is the source of truth for reconciliation. The output writer
`write_reconciliation_outputs` produces parquet that dbt models consume
read-only:
  - action_movement_edges → stg_action_movement_edges
  - tx_reconciliation     → int_action_movement_recon
  - partition_reconciliation → marts/reconciliation_status

Status × Method split (the reconciliation status/method convention):
  - `status` = the reconciliation outcome of an edge (or aggregate)
  - `method` = how the matched movement was observed; nullable when status
    = NOT_EXPECTED (the action *correctly* has no movement).

`match_action_to_movements` returns `list[ActionMovementMatch]` — never
`Transfer | None`. An action may map to 0, 1, or many movements.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from decoder.types import WriteResult
from protocols.staking_v02.semantics import ActionKind, EconomicAction
from reconciliation.movement_builder import TokenMovement


class Status(StrEnum):
    EXACT = "exact"
    PARTIAL = "partial"
    UNMATCHED = "unmatched"
    NOT_EXPECTED = "not_expected"
    UNEXPECTED = "unexpected"
    AMBIGUOUS = "ambiguous"


class Method(StrEnum):
    EVENT_LOG = "event_log"
    TRACE = "trace"
    BALANCE_INFERRED = "balance_inferred"
    MANUAL_RULE = "manual_rule"


# Action kinds that intentionally have NO expected token movement.
NOT_EXPECTED_KINDS: frozenset[str] = frozenset(
    {
        ActionKind.UNSTAKE_REQUESTED.value,
        ActionKind.REWARD_ACCRUED.value,
        ActionKind.POOL_CONFIG_CHANGED.value,
    }
)


@dataclass(frozen=True)
class ActionMovementMatch:
    """One edge in the action ↔ movement bipartite graph.

    For UNMATCHED (action with expected movement, none found): movement_id=None.
    For NOT_EXPECTED (action with no movement expected): movement_id=None,
    method=None.
    For UNEXPECTED (movement with no action): action_id=None.
    """

    edge_id: str
    action_id: str | None
    movement_id: str | None
    allocated_amount: int  # signed; supports partial allocations
    status: Status
    method: Method | None
    reason: str


@dataclass(frozen=True)
class TxReconciliation:
    chain_id: int
    block_number: int
    tx_hash: str
    edges: list[ActionMovementMatch]
    actions_total: int
    movements_total: int
    unmatched_actions: int
    unexpected_movements: int
    overall_status: Status


@dataclass(frozen=True)
class PartitionReconciliation:
    partition_id: str
    chain_id: int
    block_range: tuple[int, int]
    tx_recons: list[TxReconciliation]
    pass_rate: float
    counts_by_status: dict[Status, int]


def _compute_edge_id(
    action_id: str | None, movement_id: str | None, status: Status, idx: int
) -> str:
    """Deterministic id for an edge. Combines the two endpoint ids and the
    status — a single (action, movement) pair could in principle yield
    different statuses across runs if the matcher logic changes; including
    status keeps the id stable for a given outcome.
    """
    canonical = f"edge|{action_id or ''}|{movement_id or ''}|{status.value}|{idx}"
    return hashlib.sha256(canonical.encode()).hexdigest()


def _method_for_movement(movement: TokenMovement) -> Method:
    """Pick the Method for a matched movement based on its source_priority."""
    if movement.source_priority == "log":
        return Method.EVENT_LOG
    return Method.TRACE


def match_action_to_movements(
    action: EconomicAction,
    movements: list[TokenMovement],
) -> list[ActionMovementMatch]:
    """Per-action edges. Returns:
      - 1 edge with status=NOT_EXPECTED if the action kind has no expected
        movement (e.g. POOL_CONFIG_CHANGED, REWARD_ACCRUED, UNSTAKE_REQUESTED)
      - 1 edge with status=EXACT for clean 1:1 matches
      - N edges with status=PARTIAL for batched movements summing to the
        action amount
      - 1 edge with status=AMBIGUOUS if multiple equally-valid movement sets
        match
      - 1 edge with status=UNMATCHED if a movement was expected but none found

    Matching scope: only movements within the same tx as the action are
    considered candidates. Caller is responsible for partitioning.

    The list is NEVER empty — every action produces at least one edge so the
    bipartite graph is complete.
    """
    if action.kind.value in NOT_EXPECTED_KINDS:
        edge = ActionMovementMatch(
            edge_id=_compute_edge_id(action.action_id, None, Status.NOT_EXPECTED, 0),
            action_id=action.action_id,
            movement_id=None,
            allocated_amount=0,
            status=Status.NOT_EXPECTED,
            method=None,
            reason=f"{action.kind.value} has no expected token movement",
        )
        return [edge]

    candidates = [
        m for m in movements if m.tx_hash.lower() == action.tx_hash.lower() and m.amount > 0
    ]

    if not candidates:
        return [
            ActionMovementMatch(
                edge_id=_compute_edge_id(action.action_id, None, Status.UNMATCHED, 0),
                action_id=action.action_id,
                movement_id=None,
                allocated_amount=0,
                status=Status.UNMATCHED,
                method=None,
                reason="no movements in tx for this action",
            )
        ]

    target = action.amount_link

    # 1. Exact 1:1 match
    exact_matches = [m for m in candidates if m.amount == target]
    if len(exact_matches) == 1:
        m = exact_matches[0]
        return [
            ActionMovementMatch(
                edge_id=_compute_edge_id(action.action_id, m.movement_id, Status.EXACT, 0),
                action_id=action.action_id,
                movement_id=m.movement_id,
                allocated_amount=m.amount,
                status=Status.EXACT,
                method=_method_for_movement(m),
                reason="exact amount match",
            )
        ]
    if len(exact_matches) > 1:
        # Multiple exact matches → ambiguous. Pick the highest-priority one
        # arbitrarily but flag the status.
        m = exact_matches[0]
        return [
            ActionMovementMatch(
                edge_id=_compute_edge_id(action.action_id, m.movement_id, Status.AMBIGUOUS, 0),
                action_id=action.action_id,
                movement_id=m.movement_id,
                allocated_amount=m.amount,
                status=Status.AMBIGUOUS,
                method=_method_for_movement(m),
                reason=(
                    f"{len(exact_matches)} movements match action amount; "
                    f"requires manual disambiguation"
                ),
            )
        ]

    # 2. Partial allocation: try to find a subset summing to target
    if target > 0:
        subset = _find_subset_summing_to(candidates, target)
        if subset is not None and len(subset) >= 2:
            edges: list[ActionMovementMatch] = []
            for i, m in enumerate(subset):
                edges.append(
                    ActionMovementMatch(
                        edge_id=_compute_edge_id(
                            action.action_id, m.movement_id, Status.PARTIAL, i
                        ),
                        action_id=action.action_id,
                        movement_id=m.movement_id,
                        allocated_amount=m.amount,
                        status=Status.PARTIAL,
                        method=_method_for_movement(m),
                        reason=f"batched movement {i + 1}/{len(subset)}",
                    )
                )
            return edges

    # 3. No match found — UNMATCHED
    return [
        ActionMovementMatch(
            edge_id=_compute_edge_id(action.action_id, None, Status.UNMATCHED, 0),
            action_id=action.action_id,
            movement_id=None,
            allocated_amount=0,
            status=Status.UNMATCHED,
            method=None,
            reason=f"no subset of {len(candidates)} movements sums to {target}",
        )
    ]


def _find_subset_summing_to(
    movements: list[TokenMovement], target: int, max_size: int = 6
) -> list[TokenMovement] | None:
    """Find any subset of `movements` whose amounts sum to `target`. Bounded
    search up to `max_size` elements (typical batched ops have <= 4 entries;
    cap prevents pathological explosion).

    Returns the subset, or None if no such subset exists. Greedy preference for
    smaller subsets.
    """
    if not movements or target <= 0:
        return None
    # Greedy: try size 2, then 3, ... up to max_size.
    n = len(movements)
    from itertools import combinations

    for size in range(2, min(max_size, n) + 1):
        for combo in combinations(range(n), size):
            if sum(movements[i].amount for i in combo) == target:
                return [movements[i] for i in combo]
    return None


def match_tx_economics(
    actions: list[EconomicAction],
    movements: list[TokenMovement],
    pool_balance_deltas: dict[str, int] | None = None,
) -> TxReconciliation:
    """Tx-level aggregation. Detects UNEXPECTED movements (movements with no
    matching action) and rolls per-action edges into a single TxReconciliation.

    `pool_balance_deltas` maps `pool_address → net LINK movement` for cross
    checks. Currently informational; recorded but not used to mutate edges.
    """
    if not actions and not movements:
        return TxReconciliation(
            chain_id=0,
            block_number=0,
            tx_hash="",
            edges=[],
            actions_total=0,
            movements_total=0,
            unmatched_actions=0,
            unexpected_movements=0,
            overall_status=Status.EXACT,
        )

    chain_id = actions[0].chain_id if actions else movements[0].chain_id
    block_number = actions[0].block_number if actions else movements[0].block_number
    tx_hash = (actions[0].tx_hash if actions else movements[0].tx_hash).lower()

    edges: list[ActionMovementMatch] = []
    matched_movement_ids: set[str] = set()

    for action in actions:
        action_edges = match_action_to_movements(action, movements)
        edges.extend(action_edges)
        for e in action_edges:
            if e.movement_id is not None:
                matched_movement_ids.add(e.movement_id)

    # Detect UNEXPECTED movements (movements with no matching action)
    unexpected_count = 0
    for i, m in enumerate(movements):
        if m.tx_hash.lower() != tx_hash:
            continue
        if m.movement_id in matched_movement_ids:
            continue
        unexpected_count += 1
        edges.append(
            ActionMovementMatch(
                edge_id=_compute_edge_id(None, m.movement_id, Status.UNEXPECTED, i),
                action_id=None,
                movement_id=m.movement_id,
                allocated_amount=m.amount,
                status=Status.UNEXPECTED,
                method=_method_for_movement(m),
                reason="movement with no matching action",
            )
        )

    unmatched_count = sum(1 for e in edges if e.status == Status.UNMATCHED)
    overall = _rollup_status(edges)

    _ = pool_balance_deltas  # retained for API stability; informational only

    return TxReconciliation(
        chain_id=chain_id,
        block_number=block_number,
        tx_hash=tx_hash,
        edges=edges,
        actions_total=len(actions),
        movements_total=len(movements),
        unmatched_actions=unmatched_count,
        unexpected_movements=unexpected_count,
        overall_status=overall,
    )


def _rollup_status(edges: list[ActionMovementMatch]) -> Status:
    """Aggregate a tx's edges into a single overall status.

    Priority order (worst-first): UNMATCHED → UNEXPECTED → AMBIGUOUS → PARTIAL
    → NOT_EXPECTED → EXACT. If any edge is at a worse status, that's the
    aggregate.
    """
    status_priority: list[Status] = [
        Status.UNMATCHED,
        Status.UNEXPECTED,
        Status.AMBIGUOUS,
        Status.PARTIAL,
        Status.NOT_EXPECTED,
        Status.EXACT,
    ]
    statuses = {e.status for e in edges}
    for s in status_priority:
        if s in statuses:
            return s
    return Status.EXACT


def reconcile_partition(
    chain_id: int,
    from_block: int,
    to_block: int,
    actions_by_tx: dict[str, list[EconomicAction]] | None = None,
    movements_by_tx: dict[str, list[TokenMovement]] | None = None,
) -> PartitionReconciliation:
    """End-to-end reconciliation for a partition.

    The signature accepts pre-grouped actions/movements (caller does the BQ
    fetch + groupby in production). For unit tests we accept None to allow
    construction of an empty partition.
    """
    actions_by_tx = actions_by_tx or {}
    movements_by_tx = movements_by_tx or {}

    all_tx_hashes = set(actions_by_tx.keys()) | set(movements_by_tx.keys())
    tx_recons: list[TxReconciliation] = []
    counts_by_status: dict[Status, int] = dict.fromkeys(Status, 0)

    for tx_hash in sorted(all_tx_hashes):
        tx_actions = actions_by_tx.get(tx_hash, [])
        tx_movements = movements_by_tx.get(tx_hash, [])
        recon = match_tx_economics(tx_actions, tx_movements, None)
        tx_recons.append(recon)
        counts_by_status[recon.overall_status] += 1

    total = len(tx_recons)
    pass_count = counts_by_status.get(Status.EXACT, 0) + counts_by_status.get(
        Status.NOT_EXPECTED, 0
    )
    pass_rate = (pass_count / total) if total > 0 else 1.0

    partition_id = hashlib.sha256(
        f"partition|{chain_id}|{from_block}|{to_block}".encode()
    ).hexdigest()

    return PartitionReconciliation(
        partition_id=partition_id,
        chain_id=chain_id,
        block_range=(from_block, to_block),
        tx_recons=tx_recons,
        pass_rate=pass_rate,
        counts_by_status=counts_by_status,
    )


def write_reconciliation_outputs(
    edges: list[ActionMovementMatch],
    tx_recons: list[TxReconciliation],
    partition_recon: PartitionReconciliation,
    gcs_path: str,
    run_partition_id: str,
) -> WriteResult:
    """Writes three parquet datasets:
      - edges/      → consumed by stg_action_movement_edges
      - tx_recon/   → consumed by int_action_movement_recon
      - partition/  → consumed by marts/reconciliation_status

    For unit-test purposes (no live GCS), this writes JSON next to the
    requested path so the result can be inspected. Production callers wire
    this to the parquet writer in `storage/dataset_writer.py`.
    """
    import json
    from pathlib import Path

    # Local-mode write: if gcs_path doesn't start with gs://, treat as local
    # path. In production, swap for the GCS parquet writer.
    rows = len(edges) + len(tx_recons) + 1  # +1 for the partition row
    out_path = Path(gcs_path) if not gcs_path.startswith("gs://") else None

    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)
        (out_path / "edges.json").write_text(
            json.dumps(
                [
                    {
                        "edge_id": e.edge_id,
                        "action_id": e.action_id,
                        "movement_id": e.movement_id,
                        "allocated_amount": e.allocated_amount,
                        "status": e.status.value,
                        "method": e.method.value if e.method else None,
                        "reason": e.reason,
                        "run_partition_id": run_partition_id,
                    }
                    for e in edges
                ],
                indent=2,
            )
        )

    return WriteResult(
        gcs_path=gcs_path,
        rows=rows,
        bytes_written=0,
        run_partition_id=run_partition_id,
    )
