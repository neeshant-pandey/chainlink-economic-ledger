"""Ingestion progress state.

Two complementary APIs (the checkpoint API calls for both):

  - The `Checkpoint` class — used by the per-source ingestion loop. Tracks
    `(chain_id, source_name) → last_processed_block + hash` and replay queues.

  - Module-level `get_last_processed_block` / `set_last_processed_block`
    functions — the simpler `(chain_id, dag_id) → block_number` API the
    Airflow operators consult between runs. Backed by the same JSON store.

Storage backend is intentionally simple (JSON file in `RUN_METADATA_DIR` or
the project root) so unit tests don't need a database. The production wiring
swaps the JSON for a BQ table or a Postgres row.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Self


def _store_root() -> Path:
    p = Path(os.environ.get("CHECKPOINT_DIR", ".checkpoints"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _checkpoint_path(chain_id: int, key: str) -> Path:
    return _store_root() / f"{chain_id}_{key}.json"


def get_last_processed_block(chain_id: int, dag_id: str) -> int | None:
    """Return the last block number successfully processed for `(chain_id,
    dag_id)`, or None if no checkpoint has ever been written.

    Required by the checkpoint API.
    """
    p = _checkpoint_path(chain_id, f"dag_{dag_id}")
    if not p.exists():
        return None
    payload = json.loads(p.read_text())
    return int(payload.get("block_number", 0)) or None


def set_last_processed_block(
    chain_id: int,
    dag_id: str,
    block: int,
    run_partition_id: str,
) -> None:
    """Atomically write the new checkpoint. Idempotent — repeated writes with
    the same block number are no-ops at the contract level (the file is
    rewritten, but the visible state is unchanged).

    Required by the checkpoint API.
    """
    p = _checkpoint_path(chain_id, f"dag_{dag_id}")
    payload = {
        "chain_id": chain_id,
        "dag_id": dag_id,
        "block_number": int(block),
        "run_partition_id": run_partition_id,
    }
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(p)


@dataclass
class _CheckpointState:
    chain_id: int
    source_name: str
    last_block: int
    last_block_hash: str | None
    pending_replays: list[tuple[int, int]]


class Checkpoint:
    """Per (chain_id, source_name) ingestion cursor.

    `source_name` examples: "staking_v02_logs", "staking_v02_traces",
    "link_transfers", "pa_logs".
    """

    def __init__(self, store_path: str | Path) -> None:
        self.store_path = Path(store_path)
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict[tuple[int, str], _CheckpointState] = {}
        self._load()

    @classmethod
    def load(cls, store_path: str) -> Self:
        return cls(store_path)

    def _load(self) -> None:
        if not self.store_path.exists():
            return
        payload = json.loads(self.store_path.read_text() or "{}")
        for entry in payload.get("entries", []):
            key = (int(entry["chain_id"]), str(entry["source_name"]))
            self._state[key] = _CheckpointState(
                chain_id=key[0],
                source_name=key[1],
                last_block=int(entry.get("last_block", 0)),
                last_block_hash=entry.get("last_block_hash"),
                pending_replays=[(int(r[0]), int(r[1])) for r in entry.get("pending_replays", [])],
            )

    def save(self) -> None:
        payload = {
            "entries": [
                {
                    "chain_id": s.chain_id,
                    "source_name": s.source_name,
                    "last_block": s.last_block,
                    "last_block_hash": s.last_block_hash,
                    "pending_replays": s.pending_replays,
                }
                for s in self._state.values()
            ]
        }
        tmp = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.store_path)

    def last_processed_block(self, chain_id: int, source_name: str) -> int:
        s = self._state.get((chain_id, source_name))
        return s.last_block if s else 0

    def last_processed_block_hash(self, chain_id: int, source_name: str) -> str | None:
        s = self._state.get((chain_id, source_name))
        return s.last_block_hash if s else None

    def advance(
        self,
        chain_id: int,
        source_name: str,
        block_number: int,
        block_hash: str,
    ) -> None:
        """Idempotent: advancing to an equal or lower block is a no-op."""
        key = (chain_id, source_name)
        s = self._state.get(key)
        if s is None:
            self._state[key] = _CheckpointState(
                chain_id=chain_id,
                source_name=source_name,
                last_block=block_number,
                last_block_hash=block_hash,
                pending_replays=[],
            )
        elif block_number > s.last_block:
            s.last_block = block_number
            s.last_block_hash = block_hash
        self.save()

    def mark_replay(
        self,
        chain_id: int,
        source_name: str,
        from_block: int,
        to_block: int,
    ) -> None:
        key = (chain_id, source_name)
        s = self._state.setdefault(
            key,
            _CheckpointState(
                chain_id=chain_id,
                source_name=source_name,
                last_block=0,
                last_block_hash=None,
                pending_replays=[],
            ),
        )
        if (from_block, to_block) not in s.pending_replays:
            s.pending_replays.append((from_block, to_block))
        self.save()

    def pending_replays(self, chain_id: int, source_name: str) -> list[tuple[int, int]]:
        s = self._state.get((chain_id, source_name))
        return list(s.pending_replays) if s else []

    def clear_replay(
        self,
        chain_id: int,
        source_name: str,
        from_block: int,
        to_block: int,
    ) -> None:
        s = self._state.get((chain_id, source_name))
        if s is None:
            return
        s.pending_replays = [r for r in s.pending_replays if r != (from_block, to_block)]
        self.save()
