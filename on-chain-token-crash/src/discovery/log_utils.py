"""Chunked event-log fetching for large block ranges."""
from __future__ import annotations

from typing import Any, Optional

from web3 import Web3

# Alchemy Free and similar tiers cap eth_getLogs at 10 blocks per request.
DEFAULT_CHUNK_SIZE = 10
MIN_CHUNK_SIZE = 1


def get_logs_chunked(
    event,
    from_block: int,
    to_block: int,
    argument_filters: Optional[dict] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[dict[str, Any]]:
    """Fetch event logs in block-range chunks to avoid RPC limits."""
    if from_block > to_block:
        return []

    logs: list[dict[str, Any]] = []
    start = from_block

    while start <= to_block:
        end = min(start + chunk_size - 1, to_block)
        try:
            entries = event.get_logs(
                from_block=start,
                to_block=end,
                argument_filters=argument_filters or {},
            )
            logs.extend(entries)
        except Exception:
            if chunk_size > MIN_CHUNK_SIZE:
                logs.extend(
                    get_logs_chunked(
                        event,
                        start,
                        end,
                        argument_filters,
                        chunk_size=max(chunk_size // 2, MIN_CHUNK_SIZE),
                    )
                )
        start = end + 1

    return logs


def dedupe_pools(pools: list) -> list:
    """Deduplicate pool candidates by pool_address."""
    seen: set[str] = set()
    result = []
    for pool in pools:
        addr = Web3.to_checksum_address(pool.pool_address)
        if addr in seen:
            continue
        seen.add(addr)
        result.append(pool)
    return result
