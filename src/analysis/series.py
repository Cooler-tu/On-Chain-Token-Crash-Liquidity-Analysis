"""Build research-ready, bucket-aligned market and liquidity time series.

The dashboard timelines are presentation artifacts.  This module creates a
separate analytical contract with explicit state-vs-flow semantics:

* TVL is the last observation for each pool/bucket and may be carried forward.
* Swap volume and liquidity actions are summed within a bucket.
* OHLC uses transaction order; VWAP uses target-token volume as the weight.
* Missing quantified liquidity amounts remain unknown rather than becoming 0.
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from ..models import VerifiedPool


@dataclass(frozen=True)
class _PoolMeta:
    identifier: str
    custody_address: str
    protocol: str
    version: str
    token0: str
    token1: str


_QUOTE_META = {
    "0x0000000000000000000000000000000000000000": (18, "ETH"),
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": (18, "WETH"),
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": (6, "USDC"),
    "0xdac17f958d2ee523a2206206994597c13d831ec7": (6, "USDT"),
    "0x6b175474e89094c44da98d954eedeac495271d0f": (18, "DAI"),
}


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _pool_value(pool: VerifiedPool | dict[str, Any], key: str, default: Any = "") -> Any:
    if isinstance(pool, dict):
        return pool.get(key, default)
    return getattr(pool, key, default)


def _pool_registry(
    verified_pools: Iterable[VerifiedPool | dict[str, Any]],
) -> tuple[
    dict[str, _PoolMeta],
    dict[str, set[str]],
    dict[tuple[str, str], set[str]],
]:
    pools: dict[str, _PoolMeta] = {}
    aliases: dict[str, set[str]] = defaultdict(set)
    pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for pool in verified_pools or []:
        if not bool(_pool_value(pool, "verified", True)):
            continue
        pool_address = _lower(_pool_value(pool, "pool_address"))
        pool_id = _lower(_pool_value(pool, "pool_id"))
        identifier = pool_id or pool_address
        if not identifier:
            continue
        meta = _PoolMeta(
            identifier=identifier,
            custody_address=_lower(_pool_value(pool, "custody_address")),
            protocol=str(_pool_value(pool, "protocol") or "").lower(),
            version=str(_pool_value(pool, "version") or "").lower(),
            token0=_lower(_pool_value(pool, "token0")),
            token1=_lower(_pool_value(pool, "token1")),
        )
        pools[identifier] = meta
        for alias in {identifier, pool_address, pool_id, meta.custody_address}:
            if alias:
                aliases[alias].add(identifier)
        if meta.token0 and meta.token1:
            pairs[tuple(sorted((meta.token0, meta.token1)))].add(identifier)
    return pools, aliases, pairs


def _resolve_pool(
    row: dict[str, Any],
    pools: dict[str, _PoolMeta],
    aliases: dict[str, set[str]],
    pairs: dict[tuple[str, str], set[str]],
) -> Optional[_PoolMeta]:
    raw = _lower(row.get("pool_address") or row.get("pool_id"))
    if raw in pools:
        return pools[raw]
    alias_matches = aliases.get(raw, set()) if raw else set()
    if len(alias_matches) == 1:
        return pools[next(iter(alias_matches))]

    token0 = _lower(row.get("token0_address"))
    token1 = _lower(row.get("token1_address"))
    pair_matches = pairs.get(tuple(sorted((token0, token1))), set()) if (
        token0 and token1
    ) else set()
    if len(pair_matches) == 1:
        return pools[next(iter(pair_matches))]
    if raw and pair_matches:
        narrowed = pair_matches.intersection(alias_matches)
        if len(narrowed) == 1:
            return pools[next(iter(narrowed))]
    return None


def _target_amount(
    row: dict[str, Any],
    meta: Optional[_PoolMeta],
    target_token: str,
    scale: int,
) -> Optional[float]:
    target = _lower(target_token)
    row_token0 = _lower(row.get("token0_address")) or (
        meta.token0 if meta else ""
    )
    row_token1 = _lower(row.get("token1_address")) or (
        meta.token1 if meta else ""
    )
    try:
        if row_token0 == target:
            raw = abs(int(row.get("token0_amount") or 0))
        elif row_token1 == target:
            raw = abs(int(row.get("token1_amount") or 0))
        else:
            return None
    except (TypeError, ValueError):
        return None
    return raw / scale


def _event_order(row: dict[str, Any]) -> tuple[int, int, int]:
    return (
        _int(row.get("block_number")),
        _int(row.get("log_index")),
        _int(row.get("block_timestamp")),
    )


def _bucket(timestamp: Any, bucket_seconds: int) -> int:
    ts = _int(timestamp)
    return (ts // bucket_seconds) * bucket_seconds if ts > 0 else 0


def _new_flow() -> dict[str, Any]:
    return {
        "price_open": None,
        "price_high": None,
        "price_low": None,
        "price_close": None,
        "_price_open_order": None,
        "_price_close_order": None,
        "_price_close_ts": None,
        "_priced_token_volume": 0.0,
        "_priced_value": 0.0,
        "_priced_trade_count": 0,
        "_price_unit": None,
        "_price_source": None,
        "volume_token": 0.0,
        "volume_usd": 0.0,
        "_volume_usd_known": False,
        "swap_count": 0,
        "_traders": set(),
        "liquidity_added_token": 0.0,
        "liquidity_removed_token": 0.0,
        "_add_events": 0,
        "_remove_events": 0,
        "_add_quantified": 0,
        "_remove_quantified": 0,
        "_lp_actors": set(),
        "_lp_identity_events": 0,
    }


def _update_swap_flow(
    flow: dict[str, Any],
    row: dict[str, Any],
    target_amount: float,
    meta: Optional[_PoolMeta],
    target_token: str,
) -> None:
    event_count = max(1, _int(row.get("event_count"), 1))
    flow["swap_count"] += event_count
    flow["volume_token"] += target_amount
    amount_usd = _float(row.get("amount_usd"))
    if amount_usd is not None and amount_usd > 0:
        flow["volume_usd"] += amount_usd
        flow["_volume_usd_known"] = True
    actor = _lower(row.get("actor") or row.get("recipient"))
    if actor:
        flow["_traders"].add(actor)

    if target_amount <= 0:
        return
    price: Optional[float] = None
    price_unit = ""
    price_source = ""
    if amount_usd is not None and amount_usd > 0:
        price = amount_usd / target_amount
        price_unit = "USD"
        price_source = "amount_usd"
    elif meta is not None:
        target = _lower(target_token)
        row_token0 = _lower(row.get("token0_address")) or meta.token0
        row_token1 = _lower(row.get("token1_address")) or meta.token1
        try:
            if row_token0 == target:
                quote_address = row_token1
                quote_raw = abs(int(row.get("token1_amount") or 0))
            elif row_token1 == target:
                quote_address = row_token0
                quote_raw = abs(int(row.get("token0_amount") or 0))
            else:
                quote_address = ""
                quote_raw = 0
        except (TypeError, ValueError):
            quote_address = ""
            quote_raw = 0
        quote_meta = _QUOTE_META.get(quote_address)
        if quote_meta and quote_raw > 0:
            quote_decimals, price_unit = quote_meta
            price = (quote_raw / (10 ** quote_decimals)) / target_amount
            price_source = "pool_swap_ratio"
    if price is None or price <= 0:
        return
    if flow["_price_unit"] is None:
        flow["_price_unit"] = price_unit
        flow["_price_source"] = price_source
    elif flow["_price_unit"] != price_unit:
        # A token-total bucket may contain pools quoted in incompatible units.
        # Keep volume, but do not mix those prices into OHLC/VWAP.
        return
    elif flow["_price_source"] != price_source:
        flow["_price_source"] = "mixed"
    order = _event_order(row)
    if flow["_price_open_order"] is None or order < flow["_price_open_order"]:
        flow["_price_open_order"] = order
        flow["price_open"] = price
    if flow["_price_close_order"] is None or order >= flow["_price_close_order"]:
        flow["_price_close_order"] = order
        flow["_price_close_ts"] = _int(row.get("block_timestamp"))
        flow["price_close"] = price
    flow["price_high"] = (
        price if flow["price_high"] is None else max(flow["price_high"], price)
    )
    flow["price_low"] = (
        price if flow["price_low"] is None else min(flow["price_low"], price)
    )
    flow["_priced_token_volume"] += target_amount
    flow["_priced_value"] += price * target_amount
    flow["_priced_trade_count"] += event_count


def _liquidity_is_quantified(row: dict[str, Any]) -> bool:
    status = str(row.get("quantification_status") or "").lower()
    if status:
        return status == "quantified"
    if row.get("amounts_available") is False:
        return False
    version = str(row.get("version") or "").lower()
    source = str(row.get("source_event") or "").lower()
    delta = _int(row.get("liquidity_delta"))
    amounts_zero = (
        _int(row.get("token0_amount")) == 0
        and _int(row.get("token1_amount")) == 0
    )
    return not (version in {"v4", "4"} and source == "modifyliquidity" and delta and amounts_zero)


def _update_liquidity_flow(
    flow: dict[str, Any], row: dict[str, Any], target_amount: Optional[float]
) -> None:
    event_type = str(row.get("event_type") or "").upper()
    event_count = max(1, _int(row.get("event_count"), 1))
    is_add = event_type == "LIQUIDITY_ADD"
    is_remove = event_type == "LIQUIDITY_REMOVE"
    if not (is_add or is_remove):
        return
    if is_add:
        flow["_add_events"] += event_count
    else:
        flow["_remove_events"] += event_count

    actor = _lower(row.get("actor") or row.get("recipient"))
    if actor:
        flow["_lp_actors"].add(actor)
        flow["_lp_identity_events"] += event_count

    if not _liquidity_is_quantified(row) or target_amount is None:
        return
    if is_add:
        flow["liquidity_added_token"] += target_amount
        flow["_add_quantified"] += event_count
    else:
        flow["liquidity_removed_token"] += target_amount
        flow["_remove_quantified"] += event_count


def _finish_flow(flow: Optional[dict[str, Any]]) -> dict[str, Any]:
    value = flow or _new_flow()
    priced_volume = float(value["_priced_token_volume"] or 0)
    add_events = int(value["_add_events"] or 0)
    remove_events = int(value["_remove_events"] or 0)
    lp_events = add_events + remove_events
    add_amount: Optional[float] = float(value["liquidity_added_token"] or 0)
    remove_amount: Optional[float] = float(value["liquidity_removed_token"] or 0)
    if add_events and not value["_add_quantified"]:
        add_amount = None
    if remove_events and not value["_remove_quantified"]:
        remove_amount = None
    net_amount = (
        add_amount - remove_amount
        if add_amount is not None and remove_amount is not None
        else None
    )
    return {
        "price_open": value["price_open"],
        "price_high": value["price_high"],
        "price_low": value["price_low"],
        "price_close": value["price_close"],
        "price_vwap": (
            value["_priced_value"] / priced_volume if priced_volume > 0 else None
        ),
        "price_unit": value["_price_unit"],
        "price_source": value["_price_source"],
        "price_trade_count": int(value["_priced_trade_count"]),
        "_price_close_ts": value["_price_close_ts"],
        "volume_token": float(value["volume_token"] or 0),
        "volume_usd": (
            float(value["volume_usd"] or 0)
            if value["_volume_usd_known"]
            else None
        ),
        "swap_count": int(value["swap_count"]),
        "active_trader_count": len(value["_traders"]),
        "liquidity_added_token": add_amount,
        "liquidity_removed_token": remove_amount,
        "net_lp_flow_token": net_amount,
        "lp_add_event_count": add_events,
        "lp_remove_event_count": remove_events,
        "active_lp_count": (
            len(value["_lp_actors"])
            if lp_events == int(value["_lp_identity_events"] or 0)
            else None
        ),
        "lp_identity_coverage": (
            float(value["_lp_identity_events"] or 0) / lp_events
            if lp_events
            else None
        ),
        "liquidity_add_amount_coverage": (
            float(value["_add_quantified"] or 0) / add_events
            if add_events
            else None
        ),
        "withdrawal_amount_coverage": (
            float(value["_remove_quantified"] or 0) / remove_events
            if remove_events
            else None
        ),
    }


def build_analysis_series(
    swaps: Iterable[dict[str, Any]],
    liquidity_events: Iterable[dict[str, Any]],
    tvl_timeline: Iterable[dict[str, Any]],
    verified_pools: Iterable[VerifiedPool | dict[str, Any]],
    target_token: str,
    token_decimals: int,
    *,
    token_symbol: str = "",
    chain_id: int = 1,
    bucket_seconds: int = 3600,
    tvl_source: str = "",
    lp_identity_available: bool = True,
) -> list[dict[str, Any]]:
    """Return pool-level and token-total rows aligned to fixed time buckets."""
    seconds = int(bucket_seconds or 0)
    if seconds <= 0:
        raise ValueError("bucket_seconds must be positive")
    scale = 10 ** max(0, int(token_decimals or 0))
    pool_rows = list(verified_pools or [])
    pools, aliases, pairs = _pool_registry(pool_rows)
    flows: dict[tuple[int, Optional[str]], dict[str, Any]] = defaultdict(_new_flow)
    observed_pools: set[str] = set()
    all_buckets: set[int] = set()

    for row in swaps or []:
        if str(row.get("event_type") or "").upper() != "SWAP":
            continue
        meta = _resolve_pool(row, pools, aliases, pairs)
        bucket = _bucket(row.get("block_timestamp"), seconds)
        if not bucket:
            continue
        amount = _target_amount(row, meta, target_token, scale)
        if amount is None:
            continue
        all_buckets.add(bucket)
        _update_swap_flow(
            flows[(bucket, None)], row, amount, meta, target_token
        )
        if meta is not None:
            observed_pools.add(meta.identifier)
            _update_swap_flow(
                flows[(bucket, meta.identifier)], row, amount, meta, target_token
            )

    for row in liquidity_events or []:
        event_type = str(row.get("event_type") or "").upper()
        if event_type not in {"LIQUIDITY_ADD", "LIQUIDITY_REMOVE"}:
            continue
        meta = _resolve_pool(row, pools, aliases, pairs)
        if meta is None:
            continue
        bucket = _bucket(row.get("block_timestamp"), seconds)
        if not bucket:
            continue
        amount = _target_amount(row, meta, target_token, scale)
        observed_pools.add(meta.identifier)
        all_buckets.add(bucket)
        _update_liquidity_flow(flows[(bucket, meta.identifier)], row, amount)
        _update_liquidity_flow(flows[(bucket, None)], row, amount)

    latest_tvl: dict[tuple[int, str], tuple[tuple[int, int, int], dict[str, Any]]] = {}
    for row in tvl_timeline or []:
        meta = _resolve_pool(row, pools, aliases, pairs)
        if meta is None:
            continue
        bucket = _bucket(row.get("block_timestamp"), seconds)
        if not bucket:
            continue
        order = _event_order(row)
        key = (bucket, meta.identifier)
        previous = latest_tvl.get(key)
        if previous is None or order >= previous[0]:
            latest_tvl[key] = (order, dict(row))
        observed_pools.add(meta.identifier)
        all_buckets.add(bucket)

    if not all_buckets:
        return []
    bucket_list = list(
        range(min(all_buckets), max(all_buckets) + seconds, seconds)
    )
    current_tvl: dict[
        str, tuple[int, Optional[float], Optional[float], Optional[int]]
    ] = {}
    last_price: dict[Optional[str], tuple[float, int, str, str]] = {}
    rows: list[dict[str, Any]] = []

    for bucket in bucket_list:
        for identifier in observed_pools:
            state = latest_tvl.get((bucket, identifier))
            if state is not None:
                state_row = state[1]
                raw_tvl = _float(state_row.get("tvl_in_token"))
                tvl_token = raw_tvl / scale if raw_tvl is not None else None
                current_tvl[identifier] = (
                    bucket,
                    tvl_token,
                    _float(state_row.get("tvl_usd")),
                    _int(state_row.get("snapshot_block")) or None,
                )

        pool_output: list[dict[str, Any]] = []
        for identifier in sorted(observed_pools):
            flow = _finish_flow(flows.get((bucket, identifier)))
            if not lp_identity_available:
                flow["active_lp_count"] = None
                flow["lp_identity_coverage"] = None
            state = current_tvl.get(identifier)
            has_activity = bool(
                flow["swap_count"]
                or flow["lp_add_event_count"]
                or flow["lp_remove_event_count"]
            )
            if state is None and not has_activity:
                continue
            meta = pools[identifier]
            output = _base_row(
                chain_id=chain_id,
                target_token=target_token,
                token_symbol=token_symbol,
                scope="pool",
                meta=meta,
                bucket=bucket,
                bucket_seconds=seconds,
                flow=flow,
                state=state,
                tvl_source=tvl_source,
                last_price=last_price,
            )
            pool_output.append(output)
            rows.append(output)

        total_state: Optional[
            tuple[int, Optional[float], Optional[float], Optional[int]]
        ] = None
        measured_states = [current_tvl[p] for p in observed_pools if p in current_tvl]
        if measured_states:
            token_values = [state[1] for state in measured_states]
            usd_values = [state[2] for state in measured_states]
            total_state = (
                min(state[0] for state in measured_states),
                sum(value for value in token_values if value is not None)
                if token_values and all(value is not None for value in token_values)
                else None,
                sum(value for value in usd_values if value is not None)
                if usd_values and all(value is not None for value in usd_values)
                else None,
                max(
                    (state[3] for state in measured_states if state[3] is not None),
                    default=None,
                ),
            )
        total_flow = _finish_flow(flows.get((bucket, None)))
        if not lp_identity_available:
            total_flow["active_lp_count"] = None
            total_flow["lp_identity_coverage"] = None
        if pool_output or total_state is not None or total_flow["swap_count"]:
            total = _base_row(
                chain_id=chain_id,
                target_token=target_token,
                token_symbol=token_symbol,
                scope="token_total",
                meta=None,
                bucket=bucket,
                bucket_seconds=seconds,
                flow=total_flow,
                state=total_state,
                tvl_source=tvl_source,
                last_price=last_price,
            )
            total["measured_pool_count"] = len(measured_states)
            total["verified_pool_count"] = len(pools)
            rows.append(total)

    _add_derived_features(rows)
    return sorted(
        rows,
        key=lambda row: (
            _int(row.get("bucket_start")),
            1 if row.get("scope") == "token_total" else 0,
            str(row.get("pool_identifier") or ""),
        ),
    )


def _base_row(
    *,
    chain_id: int,
    target_token: str,
    token_symbol: str,
    scope: str,
    meta: Optional[_PoolMeta],
    bucket: int,
    bucket_seconds: int,
    flow: dict[str, Any],
    state: Optional[
        tuple[int, Optional[float], Optional[float], Optional[int]]
    ],
    tvl_source: str,
    last_price: dict[Optional[str], tuple[float, int, str, str]],
) -> dict[str, Any]:
    key = meta.identifier if meta else None
    observed_close = flow.get("price_close")
    price_is_carried = False
    if observed_close is not None:
        last_price[key] = (
            float(observed_close),
            int(flow["_price_close_ts"] or bucket),
            str(flow.get("price_unit") or ""),
            str(flow.get("price_source") or ""),
        )
    elif key in last_price:
        flow["price_close"] = last_price[key][0]
        price_is_carried = True
    close_info = last_price.get(key)
    state_bucket = state[0] if state else None
    tvl_is_carried = bool(state is not None and state_bucket != bucket)
    price_status = (
        "observed" if observed_close is not None else (
            "carried" if close_info else "missing"
        )
    )
    tvl_status = (
        "carried" if tvl_is_carried else ("observed" if state else "missing")
    )
    lp_events = flow["lp_add_event_count"] + flow["lp_remove_event_count"]
    add_coverage = (
        1.0 if not flow["lp_add_event_count"] else (
            float(flow["liquidity_add_amount_coverage"] or 0)
        )
    )
    remove_coverage = (
        1.0 if not flow["lp_remove_event_count"] else (
            float(flow["withdrawal_amount_coverage"] or 0)
        )
    )
    lp_status = "none" if not lp_events else (
        "quantified" if add_coverage == 1.0 and remove_coverage == 1.0 else "partial"
    )
    return {
        "chain_id": int(chain_id),
        "token_address": _lower(target_token),
        "token_symbol": str(token_symbol or ""),
        "scope": scope,
        "pool_identifier": meta.identifier if meta else None,
        "custody_address": meta.custody_address if meta else None,
        "protocol": meta.protocol if meta else None,
        "version": meta.version if meta else None,
        "bucket_start": bucket,
        "bucket_end": bucket + bucket_seconds,
        "bucket_seconds": bucket_seconds,
        "price_open": flow["price_open"],
        "price_high": flow["price_high"],
        "price_low": flow["price_low"],
        "price_close": flow["price_close"],
        "price_vwap": flow["price_vwap"],
        "price_unit": flow.get("price_unit") or (close_info[2] if close_info else None),
        "price_source": flow.get("price_source") or (close_info[3] if close_info else None),
        "price_trade_count": flow["price_trade_count"],
        "price_staleness_seconds": (
            max(0, bucket + bucket_seconds - close_info[1]) if close_info else None
        ),
        "price_is_carried_forward": price_is_carried,
        "tvl_token_close": state[1] if state else None,
        "tvl_usd_close": state[2] if state else None,
        "tvl_source": str(tvl_source or "") or None,
        "tvl_snapshot_block": state[3] if state else None,
        "tvl_is_carried_forward": tvl_is_carried,
        "volume_token": flow["volume_token"],
        "volume_usd": flow["volume_usd"],
        "swap_count": flow["swap_count"],
        "active_trader_count": flow["active_trader_count"],
        "liquidity_added_token": flow["liquidity_added_token"],
        "liquidity_removed_token": flow["liquidity_removed_token"],
        "net_lp_flow_token": flow["net_lp_flow_token"],
        "lp_add_event_count": flow["lp_add_event_count"],
        "lp_remove_event_count": flow["lp_remove_event_count"],
        "active_lp_count": flow["active_lp_count"],
        "lp_identity_coverage": flow["lp_identity_coverage"],
        "liquidity_add_amount_coverage": flow["liquidity_add_amount_coverage"],
        "withdrawal_amount_coverage": flow["withdrawal_amount_coverage"],
        "measured_pool_count": 1 if state else 0,
        "verified_pool_count": 1 if meta else 0,
        "price_return": None,
        "tvl_change": None,
        "net_lp_flow_ratio": None,
        "withdrawal_ratio": None,
        "volume_turnover": None,
        "close_vwap_gap": (
            float(flow["price_close"]) / float(flow["price_vwap"]) - 1
            if flow["price_close"] is not None and flow["price_vwap"]
            else None
        ),
        "data_coverage": "price={};tvl={};lp_amount={}".format(
            price_status, tvl_status, lp_status
        ),
        "is_imputed": price_is_carried or tvl_is_carried,
    }


def _add_derived_features(rows: list[dict[str, Any]]) -> None:
    previous: dict[tuple[str, str], dict[str, Any]] = {}
    for row in sorted(
        rows,
        key=lambda value: (
            value.get("scope") or "",
            value.get("pool_identifier") or "",
            _int(value.get("bucket_start")),
        ),
    ):
        key = (str(row.get("scope") or ""), str(row.get("pool_identifier") or ""))
        prior = previous.get(key)
        if prior:
            price = _float(row.get("price_close"))
            prior_price = _float(prior.get("price_close"))
            if price and prior_price and price > 0 and prior_price > 0:
                row["price_return"] = math.log(price / prior_price)
            tvl = _float(row.get("tvl_token_close"))
            prior_tvl = _float(prior.get("tvl_token_close"))
            if tvl and prior_tvl and tvl > 0 and prior_tvl > 0:
                row["tvl_change"] = math.log(tvl / prior_tvl)
            if prior_tvl and prior_tvl > 0:
                net = _float(row.get("net_lp_flow_token"))
                removed = _float(row.get("liquidity_removed_token"))
                row["net_lp_flow_ratio"] = net / prior_tvl if net is not None else None
                row["withdrawal_ratio"] = (
                    removed / prior_tvl if removed is not None else None
                )
                row["volume_turnover"] = float(row.get("volume_token") or 0) / prior_tvl
        previous[key] = row


_PREVIEW_COLUMNS = (
    "bucket_start",
    "price_open",
    "price_high",
    "price_low",
    "price_close",
    "price_vwap",
    "price_unit",
    "price_source",
    "price_trade_count",
    "price_staleness_seconds",
    "tvl_token_close",
    "tvl_usd_close",
    "tvl_snapshot_block",
    "volume_token",
    "volume_usd",
    "swap_count",
    "active_trader_count",
    "liquidity_added_token",
    "liquidity_removed_token",
    "net_lp_flow_token",
    "lp_add_event_count",
    "lp_remove_event_count",
    "active_lp_count",
    "lp_identity_coverage",
    "withdrawal_amount_coverage",
    "price_return",
    "tvl_change",
    "net_lp_flow_ratio",
    "withdrawal_ratio",
    "volume_turnover",
    "close_vwap_gap",
    "measured_pool_count",
    "verified_pool_count",
    "data_coverage",
    "is_imputed",
)


def _iso_utc(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    timestamp = _int(value)
    if timestamp <= 0:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def write_analysis_series_human_outputs(
    rows: Iterable[dict[str, Any]],
    output_dir: str | Path,
    *,
    liquidity_event_coverage: str = "collected",
) -> dict[str, Any]:
    """Write a token-total CSV preview and a coverage-focused Markdown summary."""
    materialized = list(rows or [])
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    token_rows = sorted(
        (row for row in materialized if row.get("scope") == "token_total"),
        key=lambda row: _int(row.get("bucket_start")),
    )
    csv_path = out / "analysis_series_preview.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(_PREVIEW_COLUMNS),
            lineterminator="\n",
        )
        writer.writeheader()
        for row in token_rows:
            preview = {key: row.get(key) for key in _PREVIEW_COLUMNS}
            preview["bucket_start"] = _iso_utc(row.get("bucket_start"))
            writer.writerow(preview)

    pool_rows = [row for row in materialized if row.get("scope") == "pool"]
    pools = sorted({
        str(row.get("pool_identifier"))
        for row in pool_rows
        if row.get("pool_identifier")
    })
    source_counts: dict[str, int] = defaultdict(int)
    for row in token_rows:
        source_counts[str(row.get("tvl_source") or "missing")] += 1
    vwap_rows = sum(row.get("price_vwap") is not None for row in pool_rows)
    tvl_rows = sum(row.get("tvl_token_close") is not None for row in pool_rows)
    measured_pool_max = max(
        (int(row.get("measured_pool_count") or 0) for row in token_rows),
        default=0,
    )
    verified_pool_max = max(
        (int(row.get("verified_pool_count") or 0) for row in token_rows),
        default=0,
    )
    unknown_removals = sum(
        int(row.get("lp_remove_event_count") or 0) > 0
        and row.get("liquidity_removed_token") is None
        for row in pool_rows
    )
    full_lp_identity = sum(
        int(row.get("lp_add_event_count") or 0)
        + int(row.get("lp_remove_event_count") or 0) > 0
        and row.get("active_lp_count") is not None
        for row in pool_rows
    )
    symbol = next(
        (str(row.get("token_symbol") or "") for row in materialized if row.get("token_symbol")),
        "TOKEN",
    )
    token_address = next(
        (str(row.get("token_address") or "") for row in materialized if row.get("token_address")),
        "",
    )
    bucket_seconds = next(
        (int(row.get("bucket_seconds") or 0) for row in materialized if row.get("bucket_seconds")),
        0,
    )
    first_bucket = _iso_utc(token_rows[0]["bucket_start"]) if token_rows else "—"
    last_bucket = _iso_utc(token_rows[-1]["bucket_start"]) if token_rows else "—"
    source_text = ", ".join(
        "{} ({})".format(source, count)
        for source, count in sorted(source_counts.items())
    ) or "missing"
    price_units = sorted({
        str(row.get("price_unit") or "")
        for row in token_rows
        if row.get("price_unit")
    })
    price_unit_text = ", ".join(price_units) or "missing"
    warnings = []
    if any("event_accumulate" in source for source in source_counts):
        warnings.append(
            "TVL uses an event-reconstructed proxy; do not use TVL correlations as formal findings."
        )
    if any("rpc_target_balance" in source for source in source_counts):
        warnings.append(
            "RPC TVL is target-token-side attributable reserve, not full two-sided TVL."
        )
    if verified_pool_max and measured_pool_max < verified_pool_max:
        warnings.append(
            "Token-total TVL covers at most {} of {} verified pools; market-wide volume/price versus this partial TVL is not approved as a formal market-wide finding.".format(
                measured_pool_max, verified_pool_max
            )
        )
    if liquidity_event_coverage != "collected":
        warnings.append(
            "Liquidity events were not collected in this run; zero LP event counts mean unavailable coverage, not observed absence."
        )
    if price_units and price_units != ["USD"]:
        warnings.append(
            "Price is quoted in {}; returns are usable within this pool, but absolute values are not USD prices.".format(
                price_unit_text
            )
        )
    if unknown_removals:
        warnings.append(
            "{} pool×bucket rows contain removal activity without quantified token amounts.".format(
                unknown_removals
            )
        )
    if full_lp_identity == 0 and any(
        int(row.get("lp_add_event_count") or 0)
        + int(row.get("lp_remove_event_count") or 0) > 0
        for row in pool_rows
    ):
        warnings.append(
            "No active pool×bucket has complete LP identity coverage; active_lp_count is not approved for correlation."
        )
    warning_lines = "\n".join("- {}".format(item) for item in warnings) or "- None"
    summary_path = out / "analysis_series_summary.md"
    summary_path.write_text(
        """# Analysis Series Summary

## Dataset

| Field | Value |
|---|---:|
| Token | {symbol} `{token_address}` |
| All rows | {all_rows} |
| Pool rows | {pool_rows} |
| Token-total buckets | {token_rows} |
| Observed pools | {pool_count} |
| Bucket seconds | {bucket_seconds} |
| First bucket (UTC) | {first_bucket} |
| Last bucket (UTC) | {last_bucket} |
| TVL source | {source_text} |
| Price unit | {price_unit_text} |
| Liquidity event coverage | {liquidity_event_coverage} |

## Coverage

| Check | Rows |
|---|---:|
| Pool rows with VWAP | {vwap_rows} |
| Pool rows with TVL state | {tvl_rows} |
| Max TVL-measured pools per bucket | {measured_pool_max} / {verified_pool_max} |
| Removal activity with unknown amount | {unknown_removals} |
| Active LP rows with full identity coverage | {full_lp_identity} |

## Interpretation warnings

{warning_lines}

## Human-readable preview

`analysis_series_preview.csv` contains only `scope=token_total` rows. The full pool-level and token-total dataset remains in `tables/analysis_series.parquet`.
""".format(
            symbol=symbol,
            token_address=token_address,
            all_rows=len(materialized),
            pool_rows=len(pool_rows),
            token_rows=len(token_rows),
            pool_count=len(pools),
            bucket_seconds=bucket_seconds,
            first_bucket=first_bucket,
            last_bucket=last_bucket,
            source_text=source_text,
            price_unit_text=price_unit_text,
            liquidity_event_coverage=liquidity_event_coverage,
            vwap_rows=vwap_rows,
            tvl_rows=tvl_rows,
            measured_pool_max=measured_pool_max,
            verified_pool_max=verified_pool_max,
            unknown_removals=unknown_removals,
            full_lp_identity=full_lp_identity,
            warning_lines=warning_lines,
        ),
        encoding="utf-8",
    )
    return {
        "csv_preview": str(csv_path),
        "summary_md": str(summary_path),
        "preview_rows": len(token_rows),
    }
