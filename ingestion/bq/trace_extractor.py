"""Trace extraction from `bigquery-public-data.crypto_ethereum.traces`.

Source table schema (relevant columns):
    transaction_hash STRING
    transaction_index INT64
    trace_address STRING            -- comma-joined ints, e.g. "0,2,1"; ROOT = ""
    trace_type STRING               -- "call" | "create" | "suicide" | ...
    call_type STRING                -- "call" | "callcode" | "delegatecall" | ...
    from_address STRING
    to_address STRING
    value STRING                    -- BIGNUMERIC encoded; cast carefully
    gas INT64
    gas_used INT64
    input STRING                    -- hex
    output STRING                   -- hex
    error STRING                    -- non-null if the call reverted
    status INT64                    -- 1 = success, 0 = failure
    block_number INT64
    block_timestamp TIMESTAMP

The KEY DIFFERENCE vs RPC `debug_traceTransaction`: BQ stores traces as a
*flat list of rows*, one per call frame, indexed by `trace_address`. The
nested call-tree shape (parent.calls[i].calls[j]) must be reconstructed in
Python — `decoder.trace_tree.build_call_tree`.

That reconstruction is itself a Vector-1 demonstration: it shows the
implementation handles the trace data model below the convenience of the
callTracer JSON. Don't shortcut it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ingestion.bq.bq_client import BQClient

# Public dataset — referenced as a literal so the the public-dataset source rule / D9 grep
# enforcement passes. Do NOT f-string this into the SQL.
BQ_PUBLIC_DATASET = "bigquery-public-data.crypto_ethereum"


def fetch_traces_by_to_address(
    client: BQClient,
    chain_id: int,
    addresses: list[str],
    from_block: int,
    to_block: int,
    successful_only: bool = True,
) -> Iterator[dict[str, Any]]:
    """Yield trace ROWS (flat, not tree-shaped) for calls *to* the given
    addresses in the block range.

    Returns plain row dicts so the call-tree builder stage can sort + group
    them. Conversion to the nested `RawTrace` happens in
    `decoder.trace_tree.build_call_tree`, NOT here.

    Cost note: traces table is ~3 TB. Always use block range. Address filter
    alone is not enough.
    """
    sql_lines = [
        "SELECT block_number, block_hash, block_timestamp,",
        "       transaction_hash, transaction_index, trace_address,",
        "       trace_type, call_type, from_address, to_address, value,",
        "       gas, gas_used, input, output, error, status, subtraces",
        f"FROM `{BQ_PUBLIC_DATASET}.traces`",
        "WHERE block_number BETWEEN @from_block AND @to_block",
        "  AND to_address IN UNNEST(@addresses)",
    ]
    if successful_only:
        sql_lines.append("  AND status = 1")
    sql_lines.append(
        "ORDER BY block_number, transaction_hash, "
        "ARRAY_LENGTH(SPLIT(trace_address, ',')), trace_address"
    )
    sql = "\n".join(sql_lines)
    params = {
        "from_block": int(from_block),
        "to_block": int(to_block),
        "addresses": [a.lower() for a in addresses],
    }
    yield from client.query_iter(sql, params)
    _ = chain_id  # chain_id is stamped onto RawTrace by trace_tree.build_call_tree


def fetch_traces_for_tx(
    client: BQClient,
    chain_id: int,
    tx_hash: str,
) -> list[dict[str, Any]]:
    """Fetch ALL trace rows for a single tx, ordered by trace_address depth.

    Used by Phase 1 spike. Predicate must include the date partition floor:
        WHERE transaction_hash = @tx_hash
          AND block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 YEAR)

    Sorted by depth ascending (root first, leaves last) so the call-tree
    builder can attach children to parents in one pass.
    """
    sql = f"""
        SELECT block_number, block_hash, block_timestamp,
               transaction_hash, transaction_index, trace_address,
               trace_type, call_type, from_address, to_address, value,
               gas, gas_used, input, output, error, status, subtraces
        FROM `{BQ_PUBLIC_DATASET}.traces`
        WHERE transaction_hash = @tx_hash
          AND block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 YEAR)
        ORDER BY ARRAY_LENGTH(SPLIT(trace_address, ',')), trace_address
    """
    params = {"tx_hash": tx_hash.lower()}
    _ = chain_id
    return list(client.query_iter(sql, params))


def fetch_internal_link_transfers(
    client: BQClient,
    chain_id: int,
    link_token_address: str,
    parent_addresses: list[str],
    from_block: int,
    to_block: int,
) -> Iterator[dict[str, Any]]:
    """Yield trace rows that are ERC-20 transfer/transferFrom calls into LINK,
    scoped to traces whose top-level tx touches `parent_addresses`.

    These are the "internal LINK transfers" that don't always emit a Transfer
    log. Surfacing them is the whole point of the trace ingestion path.

    Selectors:
        transfer(address,uint256)             0xa9059cbb
        transferFrom(address,address,uint256) 0x23b872dd

    The subquery scopes to txs that hit our protocol contracts so we don't
    pull every LINK transfer ever (which is what a Dune analyst would do —
    we're not that).
    """
    sql = f"""
        SELECT block_number, block_hash, transaction_hash, transaction_index,
               trace_address, call_type, from_address, to_address, value,
               input, output, error, status, gas, gas_used, subtraces
        FROM `{BQ_PUBLIC_DATASET}.traces`
        WHERE block_number BETWEEN @from_block AND @to_block
          AND to_address = @link
          AND status = 1
          AND (
            STARTS_WITH(input, '0xa9059cbb')
            OR STARTS_WITH(input, '0x23b872dd')
          )
          AND transaction_hash IN (
            SELECT transaction_hash
            FROM `{BQ_PUBLIC_DATASET}.traces`
            WHERE block_number BETWEEN @from_block AND @to_block
              AND to_address IN UNNEST(@parents)
              AND trace_address = ''
          )
        ORDER BY block_number, transaction_hash,
                 ARRAY_LENGTH(SPLIT(trace_address, ',')), trace_address
    """
    params = {
        "from_block": int(from_block),
        "to_block": int(to_block),
        "link": link_token_address.lower(),
        "parents": [a.lower() for a in parent_addresses],
    }
    _ = chain_id
    yield from client.query_iter(sql, params)
