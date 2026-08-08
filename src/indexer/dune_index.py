"""Dune-backed event indexing for the analyze pipeline.

Uses ``DuneDataCollector`` (SQL in ``src/data/dune_sql/``) to pull swaps,
Uniswap V2/V3 liquidity events, and ERC-20 transfers — then writes the same
``swaps.json`` / ``liquidity_events.json`` / ``transfers.json`` /
``events_all.json`` shape that the RPC indexer produces.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from web3 import Web3

from ..data.dune_collector import DuneCollectorError, DuneDataCollector
from ..models import VerifiedPool

ProgressFn = Callable[[str], None]


def _progress(msg: str, on_progress: Optional[ProgressFn] = None) -> None:
    if on_progress is not None:
        on_progress(msg)
    else:
        print("  {}".format(msg), flush=True)


def _parse_block_timestamp(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        pass
    # "2026-05-01 12:34:56.000 UTC" / ISO
    s2 = s.replace(" UTC", "").replace("Z", "+00:00")
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(s2, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    try:
        return int(datetime.fromisoformat(s2).timestamp())
    except Exception:
        return 0


def _checksum(addr: str) -> str:
    if not addr:
        return ""
    try:
        return Web3.to_checksum_address(addr)
    except Exception:
        return str(addr)


def _normalize_swap(row: dict[str, Any]) -> dict[str, Any]:
    bought = str(row.get("token_bought_amount_raw") or row.get("token1_amount") or "0")
    sold = str(row.get("token_sold_amount_raw") or row.get("token0_amount") or "0")
    return {
        "block_number": int(row.get("block_number") or 0),
        "block_timestamp": _parse_block_timestamp(row.get("block_timestamp") or row.get("block_time")),
        "transaction_hash": str(row.get("transaction_hash") or ""),
        "log_index": int(row.get("log_index") or 0),
        "protocol": str(row.get("protocol") or "").lower(),
        "version": str(row.get("version") or "").lower(),
        "pool_address": _checksum(row.get("pool_address") or ""),
        "event_type": "SWAP",
        "actor": _checksum(row.get("actor") or ""),
        "recipient": _checksum(row.get("recipient") or row.get("actor") or ""),
        "token0_address": _checksum(row.get("token_sold") or row.get("token0_address") or ""),
        "token1_address": _checksum(row.get("token_bought") or row.get("token1_address") or ""),
        "amount_usd": float(row.get("amount_usd") or 0),
        "token0_amount": sold,
        "token1_amount": bought,
        "liquidity_delta": "0",
        "source_event": str(row.get("source_event") or "dex.trades"),
        "verified": True,
        "nft_token_id": None,
        "_stream": "dune:swap",
    }


def _normalize_liquidity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "block_number": int(row.get("block_number") or 0),
        "block_timestamp": _parse_block_timestamp(row.get("block_timestamp") or row.get("block_time")),
        "transaction_hash": str(row.get("transaction_hash") or ""),
        "log_index": int(row.get("log_index") or 0),
        "protocol": str(row.get("protocol") or "").lower(),
        "version": str(row.get("version") or "").lower(),
        "pool_address": _checksum(row.get("pool_address") or ""),
        "event_type": str(row.get("event_type") or ""),
        "actor": _checksum(row.get("actor") or ""),
        "recipient": _checksum(row.get("recipient") or ""),
        "token0_amount": str(row.get("token0_amount") or "0"),
        "token1_amount": str(row.get("token1_amount") or "0"),
        "liquidity_delta": str(row.get("liquidity_delta") or "0"),
        "source_event": str(row.get("source_event") or ""),
        "verified": True,
        "nft_token_id": row.get("nft_token_id"),
        "_stream": "dune:liq",
    }


def _normalize_transfer(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "block_number": int(row.get("block_number") or 0),
        "block_timestamp": _parse_block_timestamp(row.get("block_timestamp") or row.get("block_time")),
        "transaction_hash": str(row.get("transaction_hash") or ""),
        "log_index": int(row.get("log_index") or 0),
        "protocol": "",
        "version": "",
        "pool_address": "",
        "event_type": "TOKEN_TRANSFER",
        "actor": _checksum(row.get("actor") or ""),
        "recipient": _checksum(row.get("recipient") or ""),
        "token0_amount": str(row.get("token0_amount") or row.get("amount_raw") or "0"),
        "token1_amount": "0",
        "liquidity_delta": "0",
        "source_event": "Transfer",
        "verified": True,
        "nft_token_id": None,
        "_stream": "dune:xfer",
    }


def _pool_addrs_for_liquidity(verified_pools: list[VerifiedPool]) -> list[str]:
    """V2/V3 (and Curve) pool contracts — not V4/Balancer singletons."""
    out: list[str] = []
    for p in verified_pools:
        if not p.verified:
            continue
        if p.protocol == "uniswap" and p.version in ("v2", "v3", "v1"):
            if p.pool_address:
                out.append(p.pool_address)
        elif p.protocol == "curve" and p.pool_address:
            out.append(p.pool_address)
    return out


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    tmp.replace(path)


def index_events_from_dune(
    verified_pools: list[VerifiedPool],
    target_token: str,
    from_block: int,
    to_block: int,
    output_dir: str | Path = "output",
    index_token_transfer: bool = True,
    force_refresh: bool = False,
    on_progress: Optional[ProgressFn] = None,
) -> dict[str, list]:
    """Pull swaps / liquidity / transfers from Dune and write indexer outputs."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    dune_dir = out / "dune_cache" / "index_{}_{}".format(from_block, to_block)

    _progress(
        "Dune index: querying dex.trades + pool Mint/Burn + ERC20 Transfer "
        "(cache {}) ...".format(dune_dir),
        on_progress,
    )

    collector = DuneDataCollector(
        out_dir=dune_dir,
        force_refresh=force_refresh,
    )
    ctx_token = Web3.to_checksum_address(target_token)
    from ..data.dune_collector import FetchContext

    ctx = FetchContext(
        token=ctx_token,
        from_block=int(from_block),
        to_block=int(to_block),
    )

    liq_pools = _pool_addrs_for_liquidity(verified_pools)
    # Swaps: token filter only (covers V4 via PoolManager + all DEXes).
    # Do NOT restrict to pool_address IN (...): V4 uses the singleton address.
    _progress("Dune: fetching swaps for token ...", on_progress)
    try:
        raw_swaps = collector.swaps.fetch(ctx, pool_addresses=None)
    except DuneCollectorError:
        raise
    swaps = [_normalize_swap(r) for r in raw_swaps]
    _progress("Dune: {} swap(s)".format(len(swaps)), on_progress)

    _progress(
        "Dune: fetching V2/V3 liquidity for {} pool(s) ...".format(len(liq_pools)),
        on_progress,
    )
    try:
        raw_liq = collector.liquidity.fetch(ctx, pool_addresses=liq_pools)
    except DuneCollectorError as exc:
        _progress("Dune: liquidity fetch warning: {}".format(exc), on_progress)
        raw_liq = []
    liquidity = [_normalize_liquidity(r) for r in raw_liq]
    _progress("Dune: {} liquidity event(s)".format(len(liquidity)), on_progress)

    transfers: list[dict] = []
    if index_token_transfer:
        _progress("Dune: fetching ERC20 transfers ...", on_progress)
        try:
            raw_xfer = collector.transfers.fetch(ctx)
        except DuneCollectorError as exc:
            _progress("Dune: transfers fetch warning: {}".format(exc), on_progress)
            raw_xfer = []
        transfers = [_normalize_transfer(r) for r in raw_xfer]
        _progress("Dune: {} transfer(s)".format(len(transfers)), on_progress)

    # Strip internal _stream before writing public JSON (keep events_all clean)
    def _public(rows: list[dict]) -> list[dict]:
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]

    pub_swaps = _public(swaps)
    pub_liq = _public(liquidity)
    pub_xfer = _public(transfers)
    events_all = sorted(
        pub_swaps + pub_liq + pub_xfer,
        key=lambda e: (int(e.get("block_number") or 0), int(e.get("log_index") or 0)),
    )

    _write_json(out / "swaps.json", pub_swaps)
    _write_json(out / "liquidity_events.json", pub_liq)
    _write_json(out / "transfers.json", pub_xfer)
    _write_json(out / "events_all.json", events_all)
    _write_json(
        out / "index_source.json",
        {
            "source": "dune",
            "from_block": from_block,
            "to_block": to_block,
            "token": ctx_token,
            "dune_cache": str(dune_dir),
            "counts": {
                "swaps": len(pub_swaps),
                "liquidity_events": len(pub_liq),
                "transfers": len(pub_xfer),
            },
            "notes": [
                "Swaps from dex.trades (all DEXes, filtered by token).",
                "Liquidity from Uniswap V2/V3 Mint/Burn tables for verified pools.",
                "V4/Balancer/Curve LP events are not fully covered here yet.",
            ],
        },
    )

    _progress(
        "Dune indexing done: {} swaps, {} liquidity, {} transfers".format(
            len(pub_swaps), len(pub_liq), len(pub_xfer)
        ),
        on_progress,
    )
    return {
        "swaps": pub_swaps,
        "liquidity_events": pub_liq,
        "transfers": pub_xfer,
    }
