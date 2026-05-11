"""ID determinism across separate Python subprocesses.

Runs the real decode pipeline (event_decoder.decode_log -> movement_builder ->
ledger_builder) against the real golden Stake fixture inside a fresh Python
subprocess, captures every `*_id` field, asserts byte-identical IDs across
two independent subprocesses. Catches accidental use of `hash()`
(PYTHONHASHSEED-randomized), `id(...)`, `time.time()`, `uuid`, or any other
non-pure source.

Also asserts that changing `run_partition_id` between runs leaves entity IDs
(`raw_log_id`, `decoded_event_id`, `action_id`, `movement_id`,
`ledger_entry_id`) unchanged; only the `run_partition_id` column itself differs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

# Project root — used as cwd for subprocess so `from decoder…` imports resolve.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Pipeline body — runs the real decoder against the real fixture and prints
# every *_id field as a JSON object. The `RUN_PARTITION_TAG` env var feeds the
# only piece of input that differs between replays.
PIPELINE_BODY = textwrap.dedent(
    """
    import json
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path.cwd()))

    from decoder.event_decoder import decode_log
    from decoder.types import Abi, RawLog
    from lineage.run_metadata import compute_run_partition_id
    from protocols.staking_v02.ledger_builder import (
        build_ledger_entries,
        compute_ledger_entry_id,
    )
    from protocols.staking_v02.semantics import (
        ActionKind,
        EconomicAction,
        compute_action_id,
    )
    from reconciliation.movement_builder import build_movements_from_transfer_logs

    FIXTURE = Path("tests/fixtures/golden_stake_tx")
    LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"
    COMMUNITY_POOL = "0xbc10f2e862ed4502144c7d632a3459f49dfcdb5e"
    STAKED_TOPIC0 = (
        "0xb4caaf29adda3eefee3ad552a8e85058589bf834c7466cae4ee58787f70589ed"
    )

    tx_json = json.loads((FIXTURE / "tx.json").read_text())
    raw_logs_json = json.loads((FIXTURE / "logs.json").read_text())
    logs = [
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
        for log in raw_logs_json
    ]

    erc20_abi = Abi(
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
    staking_abi = Abi(
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

    raw_log_ids = []
    decoded_event_ids = []
    staked_decoded = None
    for log in logs:
        abi = staking_abi if log.address.lower() == COMMUNITY_POOL else erc20_abi
        res = decode_log(log, abi)
        if res.success and res.decoded is not None:
            raw_log_ids.append(res.decoded.raw_log_id)
            decoded_event_ids.append(res.decoded.decoded_event_id)
            if (
                log.address.lower() == COMMUNITY_POOL
                and log.topics
                and log.topics[0].lower() == STAKED_TOPIC0
            ):
                staked_decoded = res.decoded

    link_transfers = []
    for log in logs:
        if log.address.lower() != LINK:
            continue
        res = decode_log(log, erc20_abi)
        if res.success and res.decoded is not None:
            link_transfers.append(res.decoded)
    movements = build_movements_from_transfer_logs(link_transfers)
    movement_ids = [m.movement_id for m in movements]

    action_id = None
    ledger_entry_ids = []
    if staked_decoded is not None:
        action = EconomicAction(
            action_id=compute_action_id(staked_decoded, ActionKind.STAKE),
            kind=ActionKind.STAKE,
            chain_id=staked_decoded.chain_id,
            block_number=staked_decoded.block_number,
            tx_hash=staked_decoded.tx_hash,
            log_index=staked_decoded.log_index,
            contract_address=COMMUNITY_POOL,
            pool_role="community_staking_pool",
            wallet=staked_decoded.indexed_params["staker"],
            amount_link=int(staked_decoded.data_params["amount"]),
            source_event_signature=staked_decoded.event_signature,
            raw_log_id=staked_decoded.raw_log_id,
            decoded_event_id=staked_decoded.decoded_event_id,
        )
        action_id = action.action_id
        entries = build_ledger_entries(action, [])
        ledger_entry_ids = [e.entry_id for e in entries]
        assert ledger_entry_ids == [
            compute_ledger_entry_id(action.action_id, i) for i in range(len(entries))
        ]

    run_partition_tag = os.environ.get("RUN_PARTITION_TAG", "run_default")
    run_partition_id = compute_run_partition_id(
        1, "staking_pipeline", run_partition_tag, "src", "2026-05-11"
    )

    print(
        json.dumps(
            {
                "raw_log_ids": raw_log_ids,
                "decoded_event_ids": decoded_event_ids,
                "movement_ids": movement_ids,
                "action_id": action_id,
                "ledger_entry_ids": ledger_entry_ids,
                "run_partition_id": run_partition_id,
            }
        )
    )
    """
)


def _run_subprocess(run_partition_tag: str = "run_default") -> dict:
    """Run the real decode pipeline in a fresh subprocess. The
    `RUN_PARTITION_TAG` env var changes only the run_partition_id input."""
    env = os.environ.copy()
    env["RUN_PARTITION_TAG"] = run_partition_tag
    env.pop("PYTHONHASHSEED", None)
    proc = subprocess.run(
        [sys.executable, "-c", PIPELINE_BODY],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"subprocess failed: rc={proc.returncode}\nstderr={proc.stderr}\nstdout={proc.stdout}"
        )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_id_determinism_across_processes() -> None:
    """Two independent subprocesses produce byte-identical entity IDs from
    the real golden fixture."""
    a = _run_subprocess(run_partition_tag="run_one")
    b = _run_subprocess(run_partition_tag="run_one")
    for field in (
        "raw_log_ids",
        "decoded_event_ids",
        "movement_ids",
        "action_id",
        "ledger_entry_ids",
        "run_partition_id",
    ):
        assert a[field] == b[field], f"mismatch on {field}: {a[field]!r} vs {b[field]!r}"


def test_run_partition_change_does_not_affect_entity_ids() -> None:
    """Changing only RUN_PARTITION_TAG between runs leaves entity IDs
    (raw_log_id, decoded_event_id, movement_id, action_id, ledger_entry_id)
    UNCHANGED — only `run_partition_id` differs. (the lineage replay check.)"""
    a = _run_subprocess(run_partition_tag="run_alpha")
    b = _run_subprocess(run_partition_tag="run_beta")
    assert a["run_partition_id"] != b["run_partition_id"], (
        "different RUN_PARTITION_TAG must produce different run_partition_id"
    )
    assert a["raw_log_ids"] == b["raw_log_ids"]
    assert a["decoded_event_ids"] == b["decoded_event_ids"]
    assert a["movement_ids"] == b["movement_ids"]
    assert a["action_id"] == b["action_id"]
    assert a["ledger_entry_ids"] == b["ledger_entry_ids"]


def test_id_format_is_64_char_lowercase_hex() -> None:
    """Every ID emitted by the pipeline is a 64-char lowercase hex string
    (sha256 hexdigest)."""
    out = _run_subprocess()
    for field in ("raw_log_ids", "decoded_event_ids", "movement_ids", "ledger_entry_ids"):
        for v in out[field]:
            assert isinstance(v, str)
            assert len(v) == 64, f"{field}: expected 64-char id, got {len(v)}"
            assert all(c in "0123456789abcdef" for c in v), f"{field}: non-hex char"
    for v in (out["action_id"], out["run_partition_id"]):
        assert isinstance(v, str)
        assert len(v) == 64
        assert all(c in "0123456789abcdef" for c in v)
