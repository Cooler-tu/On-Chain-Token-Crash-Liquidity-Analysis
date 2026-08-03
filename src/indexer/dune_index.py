"""Dune-backed event indexing: call ``query(sql_name)`` and normalize rows."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from web3 import Web3

from ..data.dune import DuneError, query
from ..models import VerifiedPool

ProgressFn = Callable[[str], None]

_LIQ_SQL = (
    "liquidity_uniswap_v2_mint",
    "liquidity_uniswap_v2_burn",
    "liquidity_uniswap_v3_mint",
    "liquidity_uniswap_v3_burn",
)


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
        "block_timestamp": _parse_block_timestamp(
            row.get("block_timestamp") or row.get("block_time")
        ),
        "transaction_hash": str(row.get("transaction_hash") or ""),
        "log_index": int(row.get("log_index") or 0),
        "protocol": str(row.get("protocol") or "").lower(),
        "version": str(row.get("version") or "").lower(),
        "pool_address": _checksum(row.get("pool_address") or ""),
        "event_type": "SWAP",
        "actor": _checksum(row.get("actor") or row.get("tx_from") or ""),
        "recipient": _checksum(row.get("recipient") or row.get("actor") or ""),
        "token0_amount": sold,
        "token1_amount": bought,
        "liquidity_delta": "0",
        "source_event": str(row.get("source_event") or "dex.trades"),
        "verified": True,
        "nft_token_id": None,
    }


def _normalize_liquidity(row: dict[str, Any]) -> dict[str, Any]:
    version = str(row.get("version") or "").lower()
    delta_raw = str(row.get("liquidity_delta") or "0")
    event_type = str(row.get("event_type") or "")
    if not event_type and version in ("v4", "4"):
        try:
            delta = int(delta_raw)
            event_type = "LIQUIDITY_ADD" if delta >= 0 else "LIQUIDITY_REMOVE"
        except (TypeError, ValueError):
            event_type = "LIQUIDITY_ADD"
    nft_id = row.get("nft_token_id")
    if nft_id is None and row.get("salt") is not None:
        try:
            s = str(row["salt"])
            nft_id = int(s, 16) if s.startswith("0x") else int(s)
        except Exception:
            nft_id = None
    pool_addr = str(row.get("pool_address") or row.get("pool_id") or "")
    # V4 poolId is bytes32 — do not EIP-55 checksum it.
    if pool_addr.startswith("0x") and len(pool_addr) == 66:
        pool_out = pool_addr.lower()
    else:
        pool_out = _checksum(pool_addr)
    return {
        "block_number": int(row.get("block_number") or 0),
        "block_timestamp": _parse_block_timestamp(
            row.get("block_timestamp") or row.get("block_time")
        ),
        "transaction_hash": str(row.get("transaction_hash") or ""),
        "log_index": int(row.get("log_index") or 0),
        "protocol": str(row.get("protocol") or "").lower(),
        "version": version,
        "pool_address": pool_out,
        "event_type": event_type,
        "actor": _checksum(row.get("actor") or ""),
        "recipient": _checksum(row.get("recipient") or ""),
        "token0_amount": str(row.get("token0_amount") or "0"),
        "token1_amount": str(row.get("token1_amount") or "0"),
        "liquidity_delta": delta_raw,
        "source_event": str(row.get("source_event") or ""),
        "verified": True,
        "nft_token_id": nft_id,
    }


def _normalize_transfer(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "block_number": int(row.get("block_number") or 0),
        "block_timestamp": _parse_block_timestamp(
            row.get("block_timestamp") or row.get("block_time")
        ),
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
    }


def _pool_addrs_for_liquidity(verified_pools: list[VerifiedPool]) -> list[str]:
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


def _v4_pool_ids(verified_pools: list[VerifiedPool]) -> list[str]:
    out: list[str] = []
    for p in verified_pools:
        if not p.verified:
            continue
        if p.protocol == "uniswap" and str(p.version).lower() in ("v4", "4"):
            pid = p.pool_id or p.pool_address
            if pid and str(pid).startswith("0x") and len(str(pid)) == 66:
                out.append(str(pid).lower())
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
    token = Web3.to_checksum_address(target_token)
    common = dict(
        cache_dir=dune_dir,
        force_refresh=force_refresh,
        token=token,
        from_block=int(from_block),
        to_block=int(to_block),
    )

    _progress(
        "Dune index: swaps + V2/V3 Mint/Burn + V4 ModifyLiquidity + ERC20 Transfer "
        "(cache {}) ...".format(dune_dir),
        on_progress,
    )

    liq_pools = _pool_addrs_for_liquidity(verified_pools)
    v4_ids = _v4_pool_ids(verified_pools)

    # Heavy event pulls: always chunk by block so free-tier quotas don't
    # force an RPC fallback on wide windows.
    heavy = dict(common, chunk_blocks=2000, min_chunk_blocks=200)

    _progress("Dune: fetching swaps for token ...", on_progress)
    raw_swaps = query("swaps", pool_filter="", **heavy)
    swaps = [_normalize_swap(r) for r in raw_swaps]
    _progress("Dune: {} swap(s)".format(len(swaps)), on_progress)

    _progress(
        "Dune: fetching V2/V3 liquidity for {} pool(s) ...".format(len(liq_pools)),
        on_progress,
    )
    raw_liq: list[dict] = []
    if liq_pools:
        for sql_name in _LIQ_SQL:
            try:
                raw_liq.extend(
                    query(sql_name, pool_list=liq_pools[:40], **heavy)
                )
            except DuneError as exc:
                _progress("Dune: skip {}: {}".format(sql_name, exc), on_progress)

    if v4_ids:
        _progress(
            "Dune: fetching V4 ModifyLiquidity for {} poolId(s) ...".format(
                len(v4_ids)
            ),
            on_progress,
        )
        # Batch poolIds so one IN-list does not explode row counts.
        batch = 8
        for i in range(0, len(v4_ids[:40]), batch):
            chunk_ids = v4_ids[i : i + batch]
            try:
                raw_liq.extend(
                    query(
                        "liquidity_uniswap_v4_modify",
                        pool_id_list=chunk_ids,
                        **heavy,
                    )
                )
            except DuneError as exc:
                _progress(
                    "Dune: skip V4 liquidity batch {}-{}: {}".format(
                        i, i + len(chunk_ids), exc
                    ),
                    on_progress,
                )

    liquidity = [_normalize_liquidity(r) for r in raw_liq]
    _progress("Dune: {} liquidity event(s)".format(len(liquidity)), on_progress)

    transfers: list[dict] = []
    if index_token_transfer:
        _progress("Dune: fetching ERC20 transfers ...", on_progress)
        try:
            raw_xfer = query("transfers", **heavy)
            transfers = [_normalize_transfer(r) for r in raw_xfer]
        except DuneError as exc:
            _progress("Dune: transfers warning: {}".format(exc), on_progress)
        _progress("Dune: {} transfer(s)".format(len(transfers)), on_progress)

    events_all = sorted(
        swaps + liquidity + transfers,
        key=lambda e: (int(e.get("block_number") or 0), int(e.get("log_index") or 0)),
    )

    _write_json(out / "swaps.json", swaps)
    _write_json(out / "liquidity_events.json", liquidity)
    _write_json(out / "transfers.json", transfers)
    _write_json(out / "events_all.json", events_all)
    _write_json(
        out / "index_source.json",
        {
            "source": "dune",
            "from_block": from_block,
            "to_block": to_block,
            "token": token,
            "dune_cache": str(dune_dir),
            "counts": {
                "swaps": len(swaps),
                "liquidity_events": len(liquidity),
                "transfers": len(transfers),
            },
            "notes": [
                "Swaps from dex.trades (all DEXes, filtered by token).",
                "Liquidity from Uniswap V2/V3 Mint/Burn + V4 ModifyLiquidity.",
                "V4 poolIds from pools_v4.sql (Swap⋈Initialize), not PoolManager.",
            ],
        },
    )

    _progress(
        "Dune indexing done: {} swaps, {} liquidity, {} transfers".format(
            len(swaps), len(liquidity), len(transfers)
        ),
        on_progress,
    )
    return {
        "swaps": swaps,
        "liquidity_events": liquidity,
        "transfers": transfers,
    }
