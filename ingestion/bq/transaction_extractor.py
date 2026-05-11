"""Transaction extraction from `bigquery-public-data.crypto_ethereum.transactions`.

Source schema:
    hash STRING, block_number INT64, block_hash STRING,
    transaction_index INT64, from_address STRING, to_address STRING,
    value NUMERIC, gas INT64, gas_price INT64, input STRING, nonce INT64,
    max_fee_per_gas INT64, max_priority_fee_per_gas INT64

Partitioning: block_timestamp (DAY) — always include a block range. The full
table is ~1.3 TB.
"""

from __future__ import annotations

from collections.abc import Iterator

from decoder.types import Transaction
from ingestion.bq.bq_client import BQClient

BQ_PUBLIC_DATASET = "bigquery-public-data.crypto_ethereum"


def fetch_transactions_in_range(
    client: BQClient,
    chain_id: int,
    from_block: int,
    to_block: int,
) -> Iterator[Transaction]:
    """Yield Transaction rows for the inclusive block range.

    Costly. Use only when needed (the decode pipeline doesn't always need
    full tx bodies — receipts + logs are usually sufficient).
    """
    sql = f"""
        SELECT hash, block_number, block_hash, transaction_index,
               from_address, to_address, value, gas, gas_price, input, nonce,
               max_fee_per_gas, max_priority_fee_per_gas
        FROM `{BQ_PUBLIC_DATASET}.transactions`
        WHERE block_number BETWEEN @from_block AND @to_block
        ORDER BY block_number, transaction_index
    """
    params = {"from_block": int(from_block), "to_block": int(to_block)}
    for row in client.query_iter(sql, params):
        yield _row_to_transaction(row, chain_id)


def fetch_transaction_by_hash(
    client: BQClient,
    chain_id: int,
    tx_hash: str,
) -> Transaction | None:
    """Return the Transaction with the given hash, or None if not in BQ."""
    sql = f"""
        SELECT hash, block_number, block_hash, transaction_index,
               from_address, to_address, value, gas, gas_price, input, nonce,
               max_fee_per_gas, max_priority_fee_per_gas
        FROM `{BQ_PUBLIC_DATASET}.transactions`
        WHERE hash = @tx_hash
          AND block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 YEAR)
        LIMIT 1
    """
    rows = list(client.query_iter(sql, {"tx_hash": tx_hash.lower()}))
    if not rows:
        return None
    return _row_to_transaction(rows[0], chain_id)


def _row_to_transaction(row: dict[str, object], chain_id: int) -> Transaction:
    return Transaction(
        chain_id=chain_id,
        block_number=int(row["block_number"]),  # type: ignore[arg-type]
        block_hash=str(row.get("block_hash", "")),
        tx_hash=str(row["hash"]).lower(),
        tx_index=int(row.get("transaction_index", 0) or 0),  # type: ignore[arg-type]
        from_addr=str(row.get("from_address", "")).lower(),
        to_addr=(str(row["to_address"]).lower() if row.get("to_address") else None),
        value=int(row.get("value", 0) or 0),  # type: ignore[arg-type]
        input_data=str(row.get("input", "0x")),
        gas=int(row.get("gas", 0) or 0),  # type: ignore[arg-type]
        gas_price=(int(row["gas_price"]) if row.get("gas_price") is not None else None),
        max_fee_per_gas=(
            int(row["max_fee_per_gas"]) if row.get("max_fee_per_gas") is not None else None
        ),
        max_priority_fee_per_gas=(
            int(row["max_priority_fee_per_gas"])
            if row.get("max_priority_fee_per_gas") is not None
            else None
        ),
        nonce=int(row.get("nonce", 0) or 0),  # type: ignore[arg-type]
    )
