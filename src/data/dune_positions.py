"""Dune helpers for LP position discovery (tokenIds)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from web3 import Web3

from .dune_collector import (
    DuneCollectorError,
    DuneSqlClient,
    FetchContext,
    LocalJsonStore,
    SqlTemplateLoader,
    _dune_addr_literal,
    _safe_int,
    _ZERO,
)


def fetch_v3_npm_token_ids_for_pools(
    pool_addresses: list[str],
    npm_address: str,
    from_block: int,
    to_block: int,
    *,
    cache_dir: Optional[str | Path] = None,
    token_hint: str = _ZERO,
) -> list[dict[str, Any]]:
    """Return ``[{nft_token_id, pool_address, owner}, ...]`` for in-window mints.

    Joins Uniswap V3 pool Mint events to NPM ERC-721 Transfer(from=0) in the
    same transaction — this is how we recover tokenIds without scanning the
    entire NonfungiblePositionManager via RPC.
    """
    pools = [_dune_addr_literal(p) for p in pool_addresses if p]
    if not pools:
        return []

    out_dir = Path(cache_dir) if cache_dir else Path("dune_cache") / "positions"
    store = LocalJsonStore(out_dir)
    sql = SqlTemplateLoader()
    client = DuneSqlClient(store=store)
    ctx = FetchContext(
        token=Web3.to_checksum_address(token_hint) if token_hint != _ZERO else Web3.to_checksum_address(_ZERO),
        from_block=int(from_block),
        to_block=int(to_block),
    )
    rendered = sql.render(
        "liquidity_uniswap_v3_npm_token_ids",
        **{
            **ctx.base_params(),
            "pool_list": ", ".join(pools),
            "npm": _dune_addr_literal(npm_address),
        },
    )
    try:
        rows = client.execute(
            rendered,
            label="v3_npm_token_ids",
            cache_parts={
                "sql_file": "liquidity_uniswap_v3_npm_token_ids",
                "pools": pools,
                "npm": _dune_addr_literal(npm_address),
                "from_block": from_block,
                "to_block": to_block,
            },
        )
    except DuneCollectorError:
        raise

    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for r in rows:
        try:
            tid = _safe_int(r.get("nft_token_id"))
        except Exception:
            continue
        if tid <= 0 or tid in seen:
            continue
        seen.add(tid)
        out.append({
            "nft_token_id": tid,
            "pool_address": str(r.get("pool_address") or ""),
            "owner": str(r.get("owner") or ""),
        })
    return out
