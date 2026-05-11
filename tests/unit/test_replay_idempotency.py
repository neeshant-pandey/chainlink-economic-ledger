"""replay-idempotency.

Runs the real decode pipeline twice against the real golden Stake fixture
with DIFFERENT `run_partition_id` values, simulating an Airflow replay.
Inserts each pass into an in-memory store keyed by entity_id (the canonical
sha256 fingerprint).

Asserts (per "replaying an overlapping block range
dedupes/replaces rows"):
  1. Row count after the second run is UNCHANGED — every entity_id from run B
     collides with the row run A already wrote (no new rows inserted).
  2. Every entity's `run_partition_id` column was UPDATED to the latest run
     (i.e. the merge updates the lineage column even though entity_id is the
     same).
  3. Every entity's CONTENT (every other column) is UNCHANGED between runs
     — only run_partition_id moved.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from decoder.event_decoder import compute_raw_log_id, decode_log
from decoder.types import Abi, RawLog
from lineage.run_metadata import compute_run_partition_id
from protocols.staking_v02.ledger_builder import (
    build_ledger_entries,
)
from protocols.staking_v02.semantics import (
    ActionKind,
    EconomicAction,
    compute_action_id,
)
from reconciliation.movement_builder import build_movements_from_transfer_logs

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "golden_stake_tx"

LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"
COMMUNITY_POOL = "0xbc10f2e862ed4502144c7d632a3459f49dfcdb5e"
STAKED_TOPIC0 = "0xb4caaf29adda3eefee3ad552a8e85058589bf834c7466cae4ee58787f70589ed"


def _load_logs() -> list[RawLog]:
    raw_logs = json.loads((FIXTURE / "logs.json").read_text())
    return [
        RawLog(
            chain_id=1,
            block_number=int(log["blockNumber"], 16),
            block_hash=log["blockHash"],
            tx_hash=log["transactionHash"],
            tx_index=int(log["transactionIndex"], 16),
            log_index=int(log["logIndex"], 16),
            address=log["address"].lower(),
            topics=log["topics"],
            data=log["data"],
        )
        for log in raw_logs
    ]


def _erc20_abi() -> Abi:
    return Abi(
        abi_version="erc20_v1",
        json_abi=[
            {
                "type": "event",
                "name": "Transfer",
                "anonymous": False,
                "inputs": [
                    {"name": "from", "type": "address", "indexed": True},
                    {"name": "to", "type": "address", "indexed": True},
                    {"name": "value", "type": "uint256", "indexed": False},
                ],
            }
        ],
    )


def _staking_abi() -> Abi:
    return Abi(
        abi_version="staking_pool_v02",
        json_abi=[
            {
                "type": "event",
                "name": "Staked",
                "anonymous": False,
                "inputs": [
                    {"name": "staker", "type": "address", "indexed": True},
                    {"name": "amount", "type": "uint256", "indexed": False},
                    {"name": "newPrincipal", "type": "uint256", "indexed": False},
                    {"name": "totalPoolPrincipal", "type": "uint256", "indexed": False},
                ],
            }
        ],
    )


def _run_decode_pipeline(run_partition_id: str) -> dict[str, dict[str, Any]]:
    """Decode the real fixture and return rows keyed by entity_id.

    Each row is a dict with the entity's content + a `run_partition_id`
    column (the lineage stamp the merge layer would write).
    """
    logs = _load_logs()
    erc20 = _erc20_abi()
    staking = _staking_abi()

    store: dict[str, dict[str, Any]] = {}

    # 1. raw_log rows
    for log in logs:
        raw_id = compute_raw_log_id(log)
        store[f"raw_log:{raw_id}"] = {
            "raw_log_id": raw_id,
            "chain_id": log.chain_id,
            "block_number": log.block_number,
            "tx_hash": log.tx_hash.lower(),
            "log_index": log.log_index,
            "address": log.address.lower(),
            "topic0": log.topics[0].lower() if log.topics else None,
            "run_partition_id": run_partition_id,
        }

    # 2. decoded_event rows + actions + ledger entries from Staked events
    link_transfers = []
    for log in logs:
        abi = staking if log.address.lower() == COMMUNITY_POOL else erc20
        res = decode_log(log, abi)
        if res.success and res.decoded is not None:
            de = res.decoded
            store[f"decoded_event:{de.decoded_event_id}"] = {
                "decoded_event_id": de.decoded_event_id,
                "raw_log_id": de.raw_log_id,
                "event_name": de.event_name,
                "contract_address": de.contract_address,
                "tx_hash": de.tx_hash,
                "log_index": de.log_index,
                "run_partition_id": run_partition_id,
            }
            if log.address.lower() == LINK:
                link_transfers.append(de)

            # If this is the Staked event, build action + ledger entries
            if (
                log.address.lower() == COMMUNITY_POOL
                and log.topics
                and log.topics[0].lower() == STAKED_TOPIC0
            ):
                action = EconomicAction(
                    action_id=compute_action_id(de, ActionKind.STAKE),
                    kind=ActionKind.STAKE,
                    chain_id=de.chain_id,
                    block_number=de.block_number,
                    tx_hash=de.tx_hash,
                    log_index=de.log_index,
                    contract_address=COMMUNITY_POOL,
                    pool_role="community_staking_pool",
                    wallet=de.indexed_params["staker"],
                    amount_link=int(de.data_params["amount"]),
                    source_event_signature=de.event_signature,
                    raw_log_id=de.raw_log_id,
                    decoded_event_id=de.decoded_event_id,
                )
                store[f"action:{action.action_id}"] = {
                    "action_id": action.action_id,
                    "kind": action.kind.value,
                    "amount_link": action.amount_link,
                    "wallet": action.wallet,
                    "tx_hash": action.tx_hash,
                    "run_partition_id": run_partition_id,
                }
                for entry in build_ledger_entries(action, []):
                    store[f"ledger_entry:{entry.entry_id}"] = {
                        "entry_id": entry.entry_id,
                        "action_id": entry.action_id,
                        "account": entry.account,
                        "direction": entry.direction.value,
                        "amount_link": entry.amount_link,
                        "tx_hash": entry.tx_hash,
                        "run_partition_id": run_partition_id,
                    }

    # 3. movement rows
    for m in build_movements_from_transfer_logs(link_transfers):
        store[f"movement:{m.movement_id}"] = {
            "movement_id": m.movement_id,
            "tx_hash": m.tx_hash,
            "token_address": m.token_address,
            "from_addr": m.from_addr,
            "to_addr": m.to_addr,
            "amount": m.amount,
            "run_partition_id": run_partition_id,
        }
    return store


def _merge_replay(
    canonical: dict[str, dict[str, Any]],
    replay: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Simulates the dbt incremental merge: by entity_id, the replay UPDATES
    the existing row's run_partition_id but otherwise preserves the row's
    content. New entity_ids would be inserted (this test asserts none are)."""
    merged = dict(canonical)
    for k, replay_row in replay.items():
        if k in merged:
            merged[k] = {**merged[k], "run_partition_id": replay_row["run_partition_id"]}
        else:
            merged[k] = replay_row
    return merged


def test_i3_replay_does_not_increase_row_count() -> None:
    """Two runs on the same fixture with different run_partition_ids produce
    the SAME set of entity_ids. After a merge, row count is UNCHANGED."""
    rpid_a = compute_run_partition_id(1, "staking_pipeline", "run_A", "src", "2026-05-11")
    rpid_b = compute_run_partition_id(1, "staking_pipeline", "run_B", "src", "2026-05-11")
    assert rpid_a != rpid_b

    run_a = _run_decode_pipeline(rpid_a)
    run_b = _run_decode_pipeline(rpid_b)

    # Same set of keys (no new entities)
    assert set(run_a) == set(run_b), (
        f"replay produced different entity_ids: "
        f"new={set(run_b) - set(run_a)} missing={set(run_a) - set(run_b)}"
    )

    canonical_pre = dict(run_a)
    canonical_post = _merge_replay(canonical_pre, run_b)
    assert len(canonical_post) == len(canonical_pre), (
        "merge must dedupe by entity_id — row count must not change"
    )


def test_i3_replay_updates_run_partition_id_column() -> None:
    """Every row's `run_partition_id` column is updated to the latest run."""
    rpid_a = compute_run_partition_id(1, "staking_pipeline", "run_A", "src", "2026-05-11")
    rpid_b = compute_run_partition_id(1, "staking_pipeline", "run_B", "src", "2026-05-11")

    run_a = _run_decode_pipeline(rpid_a)
    run_b = _run_decode_pipeline(rpid_b)
    merged = _merge_replay(run_a, run_b)

    for k, row in merged.items():
        assert row["run_partition_id"] == rpid_b, (
            f"row {k} did not pick up the latest run_partition_id"
        )


def test_i3_replay_preserves_row_content() -> None:
    """Every row's CONTENT (every column other than run_partition_id) is
    identical between runs. The merge only moves the lineage column."""
    rpid_a = compute_run_partition_id(1, "staking_pipeline", "run_A", "src", "2026-05-11")
    rpid_b = compute_run_partition_id(1, "staking_pipeline", "run_B", "src", "2026-05-11")

    run_a = _run_decode_pipeline(rpid_a)
    run_b = _run_decode_pipeline(rpid_b)

    for k in run_a:
        a = {col: v for col, v in run_a[k].items() if col != "run_partition_id"}
        b = {col: v for col, v in run_b[k].items() if col != "run_partition_id"}
        assert a == b, f"row {k} content drifted between replays: {a} vs {b}"


def test_i3_replay_with_overlapping_block_range() -> None:
    """The fixture is a single tx; treat 'overlapping range' as
    re-processing the same range twice. The contract is: row counts
    unchanged, content unchanged, only the lineage column updates."""
    rpid_a = compute_run_partition_id(1, "staking_pipeline", "run_overlap_A", "src", "2026-05-11")
    rpid_b = compute_run_partition_id(1, "staking_pipeline", "run_overlap_B", "src", "2026-05-11")

    canonical = _run_decode_pipeline(rpid_a)
    pre_count = len(canonical)

    replay = _run_decode_pipeline(rpid_b)
    canonical = _merge_replay(canonical, replay)

    post_count = len(canonical)
    assert pre_count == post_count, "replay must not insert duplicate rows"
    # At least all three layers are represented.
    assert any(k.startswith("raw_log:") for k in canonical)
    assert any(k.startswith("decoded_event:") for k in canonical)
    assert any(k.startswith("movement:") for k in canonical)
    assert any(k.startswith("ledger_entry:") for k in canonical)
