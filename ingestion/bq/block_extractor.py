"""Block extraction from `bigquery-public-data.crypto_ethereum.blocks`.

Source schema:
    number INT64, hash STRING, parent_hash STRING, miner STRING,
    timestamp TIMESTAMP, base_fee_per_gas INT64, transaction_count INT64

Partitioning is by block_timestamp (DAY). Always include either a block range
or a date predicate.
"""

from __future__ import annotations

from collections.abc import Iterator

from decoder.types import BlockHeader
from ingestion.bq.bq_client import BQClient

# Public dataset name — referenced as a literal so the public-dataset source rule grep passes.
BQ_PUBLIC_DATASET = "bigquery-public-data.crypto_ethereum"


def fetch_blocks_in_range(
    client: BQClient,
    chain_id: int,
    from_block: int,
    to_block: int,
) -> Iterator[BlockHeader]:
    """Yield BlockHeader rows for `[from_block, to_block]` inclusive.

    Predicate uses `number BETWEEN ...` for cost.
    """
    sql = f"""
        SELECT number, hash, parent_hash, miner, UNIX_SECONDS(timestamp) AS ts,
               base_fee_per_gas
        FROM `{BQ_PUBLIC_DATASET}.blocks`
        WHERE number BETWEEN @from_block AND @to_block
        ORDER BY number ASC
    """
    params = {"from_block": int(from_block), "to_block": int(to_block)}
    for row in client.query_iter(sql, params):
        yield BlockHeader(
            chain_id=chain_id,
            block_number=int(row["number"]),
            block_hash=str(row["hash"]),
            parent_hash=str(row.get("parent_hash", "")),
            timestamp=int(row.get("ts", 0) or 0),
            miner=(str(row["miner"]) if row.get("miner") else None),
            base_fee_per_gas=(
                int(row["base_fee_per_gas"]) if row.get("base_fee_per_gas") is not None else None
            ),
        )


def fetch_block_by_hash(
    client: BQClient,
    chain_id: int,
    block_hash: str,
) -> BlockHeader | None:
    """Return the BlockHeader with the given hash, or None if not in BQ."""
    sql = f"""
        SELECT number, hash, parent_hash, miner, UNIX_SECONDS(timestamp) AS ts,
               base_fee_per_gas
        FROM `{BQ_PUBLIC_DATASET}.blocks`
        WHERE hash = @block_hash
          AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 YEAR)
        LIMIT 1
    """
    rows = list(client.query_iter(sql, {"block_hash": block_hash}))
    if not rows:
        return None
    row = rows[0]
    return BlockHeader(
        chain_id=chain_id,
        block_number=int(row["number"]),
        block_hash=str(row["hash"]),
        parent_hash=str(row.get("parent_hash", "")),
        timestamp=int(row.get("ts", 0) or 0),
        miner=(str(row["miner"]) if row.get("miner") else None),
        base_fee_per_gas=(
            int(row["base_fee_per_gas"]) if row.get("base_fee_per_gas") is not None else None
        ),
    )
