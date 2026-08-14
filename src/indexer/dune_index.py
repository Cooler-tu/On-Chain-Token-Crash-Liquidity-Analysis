"""Dune-backed event indexing: call ``query(sql_name)`` and normalize rows."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from web3 import Web3

from ..data.artifacts import validate_artifact_environment, write_table
from ..data.dune import DuneError, query
from ..models import VerifiedPool

ProgressFn = Callable[[str], None]

_LIQ_SQL = (
    "liquidity_uniswap_v2_mint",
    "liquidity_uniswap_v2_burn",
    "liquidity_uniswap_v3_mint",
    "liquidity_uniswap_v3_burn",
)

# SQL no longer returns these constants — fill locally from the template name.
_LIQ_META: dict[str, dict[str, str]] = {
    "liquidity_uniswap_v2_mint": {
        "protocol": "uniswap",
        "version": "v2",
        "event_type": "LIQUIDITY_ADD",
        "source_event": "Mint",
    },
    "liquidity_uniswap_v2_burn": {
        "protocol": "uniswap",
        "version": "v2",
        "event_type": "LIQUIDITY_REMOVE",
        "source_event": "Burn",
    },
    "liquidity_uniswap_v3_mint": {
        "protocol": "uniswap",
        "version": "v3",
        "event_type": "LIQUIDITY_ADD",
        "source_event": "Mint",
    },
    "liquidity_uniswap_v3_burn": {
        "protocol": "uniswap",
        "version": "v3",
        "event_type": "LIQUIDITY_REMOVE",
        "source_event": "Burn",
    },
    "liquidity_uniswap_v4_modify": {
        "protocol": "uniswap",
        "version": "v4",
        "event_type": "",
        "source_event": "ModifyLiquidity",
    },
}


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
        "token0_address": _checksum(row.get("token_sold") or row.get("token0_address") or ""),
        "token1_address": _checksum(row.get("token_bought") or row.get("token1_address") or ""),
        "amount_usd": float(row.get("amount_usd") or 0),
        "token0_amount": sold,
        "token1_amount": bought,
        "liquidity_delta": "0",
        "source_event": str(row.get("source_event") or "dex.trades"),
        "verified": True,
        "nft_token_id": None,
    }


def _normalize_liquidity(
    row: dict[str, Any],
    sql_name: str = "",
) -> dict[str, Any]:
    meta = _LIQ_META.get(sql_name, {})
    version = str(row.get("version") or meta.get("version") or "").lower()
    delta_raw = str(row.get("liquidity_delta") or "0")
    event_type = str(row.get("event_type") or meta.get("event_type") or "")
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
    actor = _checksum(row.get("actor") or "")
    recipient = _checksum(row.get("recipient") or "") or actor
    return {
        "block_number": int(row.get("block_number") or 0),
        "block_timestamp": _parse_block_timestamp(
            row.get("block_timestamp") or row.get("block_time")
        ),
        "transaction_hash": str(row.get("transaction_hash") or ""),
        "log_index": int(row.get("log_index") or 0),
        "protocol": str(row.get("protocol") or meta.get("protocol") or "").lower(),
        "version": version,
        "pool_address": pool_out,
        "event_type": event_type,
        "actor": actor,
        "recipient": recipient,
        "token0_amount": str(row.get("token0_amount") or "0"),
        "token1_amount": str(row.get("token1_amount") or "0"),
        "liquidity_delta": delta_raw,
        "source_event": str(
            row.get("source_event") or meta.get("source_event") or ""
        ),
        "tick_lower": row.get("tick_lower"),
        "tick_upper": row.get("tick_upper"),
        "salt": row.get("salt"),
        "nft_token_id": nft_id,
        "event_count": max(1, int(row.get("event_count") or 1)),
        "aggregation_scope": str(row.get("aggregation_scope") or ""),
        "verified": True,
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
    artifact_format: str = "json",
    on_progress: Optional[ProgressFn] = None,
) -> dict[str, list]:
    """Pull swaps / liquidity / transfers from Dune and write indexer outputs."""
    artifact_mode = validate_artifact_environment(artifact_format)
    if artifact_mode == "parquet":
        raise ValueError(
            "Parquet-only analysis is not available during migration; use "
            "artifact_format='both' so legacy JSON readers keep working"
        )
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
        "Dune index: swaps + pool/block liquidity aggregates + ERC20 Transfer "
        "(cache {}) ...".format(dune_dir),
        on_progress,
    )

    liq_pools = _pool_addrs_for_liquidity(verified_pools)
    v4_ids = _v4_pool_ids(verified_pools)

    # Heavy event pulls: always chunk by block so free-tier quotas don't
    # force an RPC fallback on wide windows.
    heavy = dict(common, chunk_blocks=2000, min_chunk_blocks=200)

    # Wave 1 — independent sections (no cross-deps):
    #   swaps | V2/V3 mint/burn ×4 | transfers | V4 modify batches
    jobs: list[tuple[str, Callable[[], Any]]] = []

    def _fetch_swaps() -> list[dict]:
        return [_normalize_swap(r) for r in query("swaps", pool_filter="", **heavy)]

    jobs.append(("swaps", _fetch_swaps))

    if liq_pools:
        pools_slice = liq_pools[:40]

        def _make_liq(sql_name: str):
            def _run() -> tuple[str, list[dict]]:
                rows = query(sql_name, pool_list=pools_slice, **heavy)
                return sql_name, [_normalize_liquidity(r, sql_name) for r in rows]

            return _run

        for sql_name in _LIQ_SQL:
            jobs.append((sql_name, _make_liq(sql_name)))

    if v4_ids:
        batch = 8
        v4_name = "liquidity_uniswap_v4_modify"
        for i in range(0, len(v4_ids[:40]), batch):
            chunk_ids = v4_ids[i : i + batch]
            start = i

            def _make_v4(ids: list[str], idx: int):
                def _run() -> tuple[str, list[dict]]:
                    rows = query(v4_name, pool_id_list=ids, **heavy)
                    return (
                        "{}[{}]".format(v4_name, idx),
                        [_normalize_liquidity(r, v4_name) for r in rows],
                    )

                return _run

            jobs.append(
                ("{}[{}]".format(v4_name, start), _make_v4(chunk_ids, start))
            )

    if index_token_transfer:
        def _fetch_transfers() -> list[dict]:
            return [
                _normalize_transfer(r) for r in query("transfers", **heavy)
            ]

        jobs.append(("transfers", _fetch_transfers))

    _progress(
        "Dune: fetching {} independent query job(s) in parallel ...".format(
            len(jobs)
        ),
        on_progress,
    )

    swaps: list[dict] = []
    liquidity: list[dict] = []
    transfers: list[dict] = []

    def _consume(label: str, payload: Any) -> None:
        nonlocal swaps, liquidity, transfers
        if label == "swaps":
            swaps = payload
            return
        if label == "transfers":
            transfers = payload
            return
        # liquidity helpers return (name, rows)
        if isinstance(payload, tuple) and len(payload) == 2:
            _name, rows = payload
            liquidity.extend(rows)
            return
        if isinstance(payload, list):
            liquidity.extend(payload)

    max_workers = min(6, max(1, len(jobs)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        fut_map = {ex.submit(fn): label for label, fn in jobs}
        for fut in as_completed(fut_map):
            label = fut_map[fut]
            try:
                _consume(label, fut.result())
                _progress("Dune: {} done".format(label), on_progress)
            except DuneError as exc:
                # Soft-fail liquidity / transfers; swaps failure is fatal.
                if label == "swaps":
                    raise
                _progress(
                    "Dune: skip {}: {}".format(label, exc), on_progress
                )

    _progress("Dune: {} swap(s)".format(len(swaps)), on_progress)
    _progress("Dune: {} liquidity event(s)".format(len(liquidity)), on_progress)
    if index_token_transfer:
        _progress("Dune: {} transfer(s)".format(len(transfers)), on_progress)

    events_all = sorted(
        swaps + liquidity + transfers,
        key=lambda e: (int(e.get("block_number") or 0), int(e.get("log_index") or 0)),
    )

    table_artifacts = {
        "swaps": write_table(
            "swaps", swaps, out, artifact_format=artifact_mode
        ),
        "liquidity_events": write_table(
            "liquidity_events", liquidity, out, artifact_format=artifact_mode
        ),
        "transfers": write_table(
            "transfers", transfers, out, artifact_format=artifact_mode
        ),
    }
    _write_json(out / "events_all.json", events_all)
    _write_json(
        out / "index_source.json",
        {
            "source": "dune",
            "from_block": from_block,
            "to_block": to_block,
            "token": token,
            "artifact_format": artifact_mode,
            "artifacts": table_artifacts,
            "dune_cache": str(dune_dir),
            "parallel_jobs": [label for label, _ in jobs],
            "counts": {
                "swaps": len(swaps),
                "liquidity_events": len(liquidity),
                "transfers": len(transfers),
            },
            "notes": [
                "Swaps from dex.trades (all DEXes, filtered by token).",
                (
                    "Liquidity is aggregated by pool and block on Dune "
                    "(V2/V3 Mint/Burn + V4 signed ModifyLiquidity); "
                    "individual LP actors are not downloaded."
                ),
                "V4 poolIds from pools_v4.sql (Swap⋈Initialize), not PoolManager.",
                "Independent Dune sections fetched in parallel.",
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
