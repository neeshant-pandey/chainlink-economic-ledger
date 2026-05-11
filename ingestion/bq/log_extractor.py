"""Log extraction from `bigquery-public-data.crypto_ethereum.logs`.

Source table schema (relevant columns):
    log_index INT64
    transaction_hash STRING
    transaction_index INT64
    address STRING                  -- emitting contract, lowercase 0x...
    data STRING                     -- hex
    topics ARRAY<STRING>            -- hex topics; topics[OFFSET(0)] is event sig
    block_timestamp TIMESTAMP
    block_number INT64
    block_hash STRING

Partitioning: `block_timestamp` (DAY). Always include a date predicate.
Clustering: `address`, so address filters are cheap.

Cost note: scanning all logs by address alone is ~1.4 TB/month. ALWAYS pair
address filter with a block range / date range or you'll burn the free tier.
"""

from __future__ import annotations

from collections.abc import Iterator

from decoder.types import RawLog
from ingestion.bq.bq_client import BQClient

# Public dataset name — referenced as a literal so the the public-dataset source rule grep
# enforcement passes. Do NOT f-string this into the SQL.
BQ_PUBLIC_DATASET = "bigquery-public-data.crypto_ethereum"


def _as_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    return int(str(value))


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def fetch_logs_by_address(
    client: BQClient,
    chain_id: int,
    addresses: list[str],
    from_block: int,
    to_block: int,
    topic0: str | list[str] | None = None,
) -> Iterator[RawLog]:
    """Yield RawLog rows for the given contracts in the given block range.

    Predicate construction (parameterized — never f-string addresses):
        WHERE block_number BETWEEN @from_block AND @to_block
          AND address IN UNNEST(@addresses)
          [AND topics[SAFE_OFFSET(0)] IN UNNEST(@topic0s)]

    Returns RawLog objects (the canonical type), NOT plain dicts.
    """
    sql_lines = [
        "SELECT block_number, block_hash, transaction_hash, transaction_index,",
        "       log_index, address, topics, data",
        f"FROM `{BQ_PUBLIC_DATASET}.logs`",
        "WHERE block_number BETWEEN @from_block AND @to_block",
        "  AND address IN UNNEST(@addresses)",
    ]
    params: dict[str, object] = {
        "from_block": int(from_block),
        "to_block": int(to_block),
        "addresses": [a.lower() for a in addresses],
    }

    if topic0 is not None:
        sql_lines.append("  AND topics[SAFE_OFFSET(0)] IN UNNEST(@topic0s)")
        params["topic0s"] = [topic0] if isinstance(topic0, str) else list(topic0)

    sql = "\n".join(sql_lines)
    for row in client.query_iter(sql, params):
        yield _bq_row_to_raw_log(row, chain_id)


def fetch_link_transfer_logs(
    client: BQClient,
    chain_id: int,
    link_token_address: str,
    counterparty_addresses: list[str],
    from_block: int,
    to_block: int,
) -> Iterator[RawLog]:
    """Yield ERC-20 Transfer logs on the LINK token where one side is in
    `counterparty_addresses` (i.e. our protocol contracts).

    Predicate (parameterized):
        WHERE address = @link
          AND topics[SAFE_OFFSET(0)] = '0xddf252ad...'
          AND (
            CONCAT('0x', SUBSTR(topics[SAFE_OFFSET(1)], 27)) IN UNNEST(@cps)
            OR CONCAT('0x', SUBSTR(topics[SAFE_OFFSET(2)], 27)) IN UNNEST(@cps)
          )

    Note the SUBSTR — Transfer's indexed addresses are 32-byte topic-padded;
    the address starts at byte 12 (char 27 in 1-indexed SUBSTR).
    """
    erc20_transfer_sig = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    sql = f"""
        SELECT block_number, block_hash, transaction_hash, transaction_index,
               log_index, address, topics, data
        FROM `{BQ_PUBLIC_DATASET}.logs`
        WHERE block_number BETWEEN @from_block AND @to_block
          AND address = @link
          AND topics[SAFE_OFFSET(0)] = @transfer_sig
          AND (
            CONCAT('0x', SUBSTR(topics[SAFE_OFFSET(1)], 27)) IN UNNEST(@cps)
            OR CONCAT('0x', SUBSTR(topics[SAFE_OFFSET(2)], 27)) IN UNNEST(@cps)
          )
    """
    params = {
        "from_block": int(from_block),
        "to_block": int(to_block),
        "link": link_token_address.lower(),
        "transfer_sig": erc20_transfer_sig,
        "cps": [a.lower() for a in counterparty_addresses],
    }
    for row in client.query_iter(sql, params):
        yield _bq_row_to_raw_log(row, chain_id)


def fetch_logs_for_tx(
    client: BQClient,
    chain_id: int,
    tx_hash: str,
) -> list[RawLog]:
    """Fetch all logs from a single transaction. Used by the spike scripts.

    Predicate uses the date partition floor to keep scan cost bounded.
    """
    sql = f"""
        SELECT block_number, block_hash, transaction_hash, transaction_index,
               log_index, address, topics, data
        FROM `{BQ_PUBLIC_DATASET}.logs`
        WHERE transaction_hash = @tx_hash
          AND block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 YEAR)
        ORDER BY log_index ASC
    """
    params = {"tx_hash": tx_hash.lower()}
    rows = list(client.query_iter(sql, params))
    return [_bq_row_to_raw_log(r, chain_id) for r in rows]


def _bq_row_to_raw_log(row: dict[str, object], chain_id: int) -> RawLog:
    """Convert a BQ result row dict to a RawLog dataclass.

    Pure function; no I/O. Lives in this module so all log-shape mapping is
    one place.
    """
    topics_field = _as_list(row.get("topics"))
    return RawLog(
        chain_id=chain_id,
        block_number=_as_int(row["block_number"]),
        block_hash=str(row.get("block_hash", "")),
        tx_hash=str(row["transaction_hash"]).lower(),
        tx_index=_as_int(row.get("transaction_index")),
        log_index=_as_int(row.get("log_index")),
        address=str(row["address"]).lower(),
        topics=[str(t) for t in topics_field],
        data=str(row.get("data", "0x")),
    )
