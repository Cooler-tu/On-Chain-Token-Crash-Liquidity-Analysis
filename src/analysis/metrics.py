"""Liquidity metrics — TVL, pool concentration, LP concentration, withdrawal severity, and price estimation."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from web3 import Web3

from ..client import get_contract
from ..models import NormalizedEvent, Position, VerifiedPool

_ZERO_ADDR = "0x0000000000000000000000000000000000000000"


def estimate_price_v2(
    pool: VerifiedPool,
    token_address: str,
    reserve0: int,
    reserve1: int,
    decimals0: int,
    decimals1: int,
) -> tuple[float, str]:
    """Estimate token price in quote-token terms from V2 reserves.

    Returns (price, quote_symbol).
    """
    target = Web3.to_checksum_address(token_address)
    t0 = Web3.to_checksum_address(pool.token0)
    t1 = Web3.to_checksum_address(pool.token1)

    if reserve0 <= 0 or reserve1 <= 0:
        price = 0.0
    elif target == t0:
        price = (reserve1 / 10 ** decimals1) / (reserve0 / 10 ** decimals0)
    else:
        price = (reserve0 / 10 ** decimals0) / (reserve1 / 10 ** decimals1)

    # Determine quote symbol
    partner_addr = t1 if target == t0 else t0
    quote_symbol = _guess_quote_symbol(partner_addr)
    return price, quote_symbol


def estimate_price_v3(
    sqrt_price_x96: int,
    token0_decimals: int,
    token1_decimals: int,
    token0_is_target: bool,
) -> float:
    """Estimate token price from V3 sqrtPriceX96.

    sqrtPriceX96 = sqrt(amount1 / amount0) * 2^96
    price = (sqrtPriceX96 / 2^96)^2 * 10^(dec0 - dec1)
    """
    if sqrt_price_x96 == 0:
        return 0.0
    price_ratio = (sqrt_price_x96 / 2 ** 96) ** 2
    if token0_is_target:
        # price = 1 / price_ratio, adjusted for decimals
        price = (1 / price_ratio) * (10 ** (token1_decimals - token0_decimals))
    else:
        price = price_ratio * (10 ** (token0_decimals - token1_decimals))
    return price if price > 0 else 0.0


def _guess_quote_symbol(addr: str) -> str:
    addr_lower = addr.lower()
    known = {
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
        "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
        "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",
    }
    return known.get(addr_lower, "???")


def _known_decimals(addr: str) -> int:
    """Best-effort quote token decimals for known stablecoins / WETH."""
    addr_lower = addr.lower()
    known = {
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": 18,
        "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": 6,
        "0xdac17f958d2ee523a2206206994597c13d831ec7": 6,
        "0x6b175474e89094c44da98b954eedeac495271d0f": 18,
    }
    return known.get(addr_lower, 18)


_STABLE_QUOTES = {
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC
    "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
    "0x6b175474e89094c44da98b954eedeac495271d0f",  # DAI
}


def _resolve_target_side(
    evt: dict,
    pool_token0: str,
    pool_token1: str,
    target_token: str,
    target_decimals: int,
) -> Optional[tuple[str, str, int]]:
    """Return ``(target_side, quote_address_lower, quote_decimals)`` or None.

    Dune swap rows store ``token0_amount`` = sold and ``token1_amount`` =
    bought, which is not necessarily the pool token order.  New Dune events
    carry ``token0_address`` / ``token1_address``; legacy events fall back to a
    decimal-magnitude inference when target and quote decimals differ.
    """
    target = target_token.lower()
    pt0 = (pool_token0 or "").lower()
    pt1 = (pool_token1 or "").lower()

    t0 = (evt.get("token0_address") or pt0).lower()
    t1 = (evt.get("token1_address") or pt1).lower()
    if t0 and t1 and t0 != t1:
        if target == t0:
            return "0", t1, _known_decimals(t1)
        if target == t1:
            return "1", t0, _known_decimals(t0)
        return None

    source = (evt.get("source_event") or "").lower()
    if source != "dex.trades" and target == pt0:
        return "0", pt1, _known_decimals(pt1)
    if source != "dex.trades" and target == pt1:
        return "1", pt0, _known_decimals(pt0)
    if target not in (pt0, pt1):
        return None

    # Legacy Dune swap: sold = token0, bought = token1.  Use magnitudes when
    # decimal counts differ; otherwise the side is genuinely ambiguous.
    try:
        a0 = abs(int(evt.get("token0_amount", "0") or "0"))
        a1 = abs(int(evt.get("token1_amount", "0") or "0"))
    except (TypeError, ValueError):
        return None
    quote_addr = pt1 if target == pt0 else pt0
    quote_dec = _known_decimals(quote_addr)
    if target_decimals == quote_dec or a0 <= 0 or a1 <= 0:
        return None

    d0 = abs(math.log10(max(a0, 1)) - target_decimals)
    d1 = abs(math.log10(max(a1, 1)) - target_decimals)
    if d0 < d1:
        return "0", quote_addr, quote_dec
    return "1", quote_addr, quote_dec


def _event_matches_pool(evt: dict, pool_token0: str, pool_token1: str) -> bool:
    """True when a swap event belongs to the pool's exact token pair.

    V4 events all share the PoolManager contract address, so token addresses
    (when present) are required to avoid mixing pools from the same custody.
    """
    t0 = evt.get("token0_address") or ""
    t1 = evt.get("token1_address") or ""
    if not t0 or not t1:
        return True
    pair = {t0.lower(), t1.lower()}
    pool_pair = {(pool_token0 or "").lower(), (pool_token1 or "").lower()}
    return pool_pair == pair


def calculate_tvl_v2(
    pool: VerifiedPool, token_address: str, reserve0: int, reserve1: int
) -> float:
    """Calculate TVL in token terms for a V2 pool.

    Returns the value of the pool's liquidity expressed in the target token.
    """
    target = Web3.to_checksum_address(token_address)
    t0 = Web3.to_checksum_address(pool.token0)
    t1 = Web3.to_checksum_address(pool.token1)

    if target == t0:
        # TVL = token0 * 2 (because in a V2 AMM, value of both sides is equal)
        return reserve0 * 2
    else:
        return reserve1 * 2




def _snapshot_curve_tvl(
    w3, pool, target_token, block_identifier: int | str = "latest"
) -> int:
    """Approximate Curve pool TVL in target-token raw units.

    Uses ``coins(i)`` + ``balances(i)`` and assumes the pool targets a
    balanced USD value per coin (StableSwap / CryptoSwap design), so total
    TVL ≈ target balance × number of coins.  Falls back to 2× target balance.
    """
    target = Web3.to_checksum_address(target_token).lower()
    pa = Web3.to_checksum_address(pool.pool_address)
    try:
        contract = get_contract(w3, pa, "curve_pool")
    except Exception:
        return 0
    coin_addrs: list[str] = []
    for i in range(8):
        try:
            c = Web3.to_checksum_address(
                contract.functions.coins(i).call(block_identifier=block_identifier)
            )
        except Exception:
            break
        if c.lower() == _ZERO_ADDR.lower():
            break
        coin_addrs.append(c)
    if not coin_addrs:
        return 0
    target_idx = next(
        (i for i, c in enumerate(coin_addrs) if c.lower() == target), None
    )
    if target_idx is None:
        return 0
    try:
        target_bal = int(
            contract.functions.balances(target_idx).call(
                block_identifier=block_identifier
            )
        )
    except Exception:
        target_bal = 0
    if target_bal <= 0:
        return 0
    n = len(coin_addrs)
    return target_bal * n


def _snapshot_balancer_tvl(
    w3, pool, target_token, block_identifier: int | str = "latest"
) -> int:
    """Approximate Balancer V2 pool TVL in target-token raw units.

    Reads balances from the Vault via ``getPoolTokens(poolId)`` and uses
    target balance × number of tokens as an approximation (weighted pools
    are not perfectly balanced; this is an acceptable first-order estimate).
    """
    target = Web3.to_checksum_address(target_token).lower()
    vault_addr = Web3.to_checksum_address(pool.factory_address)
    try:
        vault = get_contract(w3, vault_addr, "balancer_vault")
        pool_id = pool.pool_address.lower() + "0" * 24
        tokens, balances, _ = vault.functions.getPoolTokens(pool_id).call(
            block_identifier=block_identifier
        )
    except Exception:
        return 0
    if not tokens:
        return 0
    tokens = [Web3.to_checksum_address(t) for t in tokens]
    target_idx = next(
        (i for i, t in enumerate(tokens) if t.lower() == target), None
    )
    if target_idx is None:
        return 0
    target_bal = int(balances[target_idx])
    if target_bal <= 0:
        return 0
    return target_bal * len(tokens)


def snapshot_onchain_pool_tvl(
    w3: Web3,
    verified_pools: list[VerifiedPool],
    target_token: str,
    block_identifier: int | str = "latest",
) -> dict[str, int]:
    """Read pool balances/reserves and return TVL in target-token raw units."""
    target = Web3.to_checksum_address(target_token)
    token = get_contract(w3, target, "erc20")
    tvl_by_pool: dict[str, int] = {}

    def _call_with_fallback(fn):
        try:
            return fn(block_identifier)
        except Exception:
            if block_identifier == "latest":
                raise
            return fn("latest")

    for pool in verified_pools:
        if not pool.verified:
            continue
        pa = pool.pool_address
        try:
            if pool.version == "v2":
                pair = get_contract(w3, pa, "uniswap_v2_pair")
                reserve0, reserve1, _ = _call_with_fallback(
                    lambda blk: pair.functions.getReserves().call(
                        block_identifier=blk
                    )
                )
                tvl = int(calculate_tvl_v2(pool, target, int(reserve0), int(reserve1)))
            elif pool.protocol == "curve":
                tvl = _snapshot_curve_tvl(
                    w3, pool, target, block_identifier=block_identifier
                )
                if tvl <= 0 and block_identifier != "latest":
                    tvl = _snapshot_curve_tvl(
                        w3, pool, target, block_identifier="latest"
                    )
            elif pool.protocol == "balancer":
                tvl = _snapshot_balancer_tvl(
                    w3, pool, target, block_identifier=block_identifier
                )
                if tvl <= 0 and block_identifier != "latest":
                    tvl = _snapshot_balancer_tvl(
                        w3, pool, target, block_identifier="latest"
                    )
            else:
                # V3 / others: target-token balance held by the pool contract
                bal = int(
                    _call_with_fallback(
                        lambda blk: token.functions.balanceOf(
                            Web3.to_checksum_address(pa)
                        ).call(block_identifier=blk)
                    )
                )
                # Approximate full-pool TVL as 2x the target side when target is in the pair
                t0 = Web3.to_checksum_address(pool.token0)
                t1 = Web3.to_checksum_address(pool.token1)
                if target in (t0, t1) and bal > 0:
                    tvl = bal * 2
                else:
                    tvl = bal
            if tvl > 0:
                tvl_by_pool[pa] = tvl
        except Exception:
            continue
    return tvl_by_pool


def build_tvl_timeline(
    verified_pools: list[VerifiedPool],
    events_all: list[dict],
    target_token: str,
    token_decimals: int,
) -> list[dict]:
    """Build a timeline of TVL and price estimates from events."""
    timeline: list[dict] = []
    target = Web3.to_checksum_address(target_token)

    # Group events by pool and type (normalize address case)
    pool_events: dict[str, list[dict]] = defaultdict(list)
    for evt in events_all:
        pa = (evt.get("pool_address") or "").lower()
        if pa and evt.get("event_type") in ("SWAP", "LIQUIDITY_ADD", "LIQUIDITY_REMOVE"):
            pool_events[pa].append(evt)

    for pool in verified_pools:
        if not pool.verified:
            continue
        pa = pool.pool_address.lower()
        events = [
            e for e in pool_events.get(pa, [])
            if _event_matches_pool(e, pool.token0, pool.token1)
        ]
        if not events:
            continue
        events.sort(key=lambda e: (e["block_number"], e.get("log_index", 0)))

        t0 = Web3.to_checksum_address(pool.token0)
        t1 = Web3.to_checksum_address(pool.token1)
        target_is_t0 = (target == t0)

        if pool.version == "v2":
            reserve0 = 0
            reserve1 = 0
            for evt in events:
                bn = evt["block_number"]
                ts = evt["block_timestamp"]
                a0 = int(evt.get("token0_amount", "0") or "0")
                a1 = int(evt.get("token1_amount", "0") or "0")
                etype = evt["event_type"]
                source = evt.get("source_event", "")

                if source == "Sync":
                    reserve0 = a0
                    reserve1 = a1
                elif etype == "SWAP":
                    # token*_amount already signed: positive = into pool, negative = out
                    reserve0 = max(0, reserve0 + a0)
                    reserve1 = max(0, reserve1 + a1)
                elif etype == "LIQUIDITY_ADD":
                    reserve0 += abs(a0)
                    reserve1 += abs(a1)
                elif etype == "LIQUIDITY_REMOVE":
                    reserve0 = max(0, reserve0 - abs(a0))
                    reserve1 = max(0, reserve1 - abs(a1))

                tvl_in_token = (reserve0 * 2) if target_is_t0 else (reserve1 * 2)
                price, quote = estimate_price_v2(
                    pool, target_token, reserve0, reserve1, 18, 18
                )
                timeline.append({
                    "block_number": bn,
                    "block_timestamp": ts,
                    "pool_address": pool.pool_address,
                    "protocol": pool.protocol,
                    "version": pool.version,
                    "event_type": etype,
                    "source_event": source,
                    "reserve0": str(reserve0),
                    "reserve1": str(reserve1),
                    "tvl_in_token": str(tvl_in_token),
                    "price": round(price, 18),
                    "quote_symbol": quote,
                })

        elif pool.version in ("v3", "v4"):
            cum_liquidity = 0
            for evt in events:
                bn = evt["block_number"]
                ts = evt["block_timestamp"]
                a0 = abs(int(evt.get("token0_amount", "0") or "0"))
                a1 = abs(int(evt.get("token1_amount", "0") or "0"))
                etype = evt["event_type"]

                if etype in ("LIQUIDITY_ADD", "LIQUIDITY_REMOVE"):
                    delta = int(evt.get("liquidity_delta", "0") or "0")
                    cum_liquidity += delta
                    cum_liquidity = max(0, cum_liquidity)

                # Approximate TVL in target-token units from event amounts
                tvl_approx = (a0 * 2) if target_is_t0 else (a1 * 2)
                side_info = _resolve_target_side(
                    evt, pool.token0, pool.token1, target_token, token_decimals
                )
                if etype == "SWAP":
                    if side_info:
                        tvl_approx = a0 if side_info[0] == "0" else a1
                    else:
                        tvl_approx = a0 if target_is_t0 else a1

                # Swap-derived price: quote token per target token.
                price = 0.0
                price_usd = 0.0
                quote_symbol = "N/A"
                if etype == "SWAP" and a0 > 0 and a1 > 0 and side_info:
                    target_side, quote_addr, quote_decimals = side_info
                    target_raw = a0 if target_side == "0" else a1
                    quote_raw = a1 if target_side == "0" else a0
                    quote_symbol = _guess_quote_symbol(quote_addr)
                    if target_raw > 0:
                        price = (quote_raw / (10 ** quote_decimals)) / (
                            target_raw / (10 ** token_decimals)
                        )
                    amount_usd = float(evt.get("amount_usd") or 0)
                    if amount_usd > 0 and target_raw > 0:
                        price_usd = amount_usd / (target_raw / (10 ** token_decimals))

                timeline.append({
                    "block_number": bn,
                    "block_timestamp": ts,
                    "pool_address": pool.pool_address,
                    "protocol": pool.protocol,
                    "version": pool.version,
                    "event_type": etype,
                    "source_event": evt.get("source_event", ""),
                    "liquidity": str(cum_liquidity),
                    "token0_amount": str(a0),
                    "token1_amount": str(a1),
                    "tvl_in_token": str(tvl_approx),
                    "price": round(price, 18),
                    "quote_symbol": quote_symbol,
                    "price_usd": round(price_usd, 6),
                })

    return sorted(timeline, key=lambda e: (e["block_number"], e.get("log_index", 0)))


def calculate_volume_metrics(
    events_all: list[dict],
    verified_pools: list[VerifiedPool],
    target_token: str,
    token_decimals: int,
    bucket_seconds: int = 3600,
) -> dict[str, Any]:
    """Aggregate swap volume by pool and by time bucket.

    ``volume_in_token`` is always the absolute target-token side of each swap.
    ``volume_usd`` is approximate and only populated when the quote token is a
    known stablecoin; other pools report ``None`` instead of a fake USD number.
    """
    target = Web3.to_checksum_address(target_token)
    pool_meta: dict[str, dict[str, Any]] = {}
    for pool in verified_pools:
        if not pool.verified:
            continue
        addr = (pool.pool_address or "").lower()
        if not addr:
            continue
        pool_meta[addr] = {
            "protocol": pool.protocol,
            "version": pool.version,
            "token0": Web3.to_checksum_address(pool.token0).lower(),
            "token1": Web3.to_checksum_address(pool.token1).lower(),
        }

    volume_by_pool: dict[str, float] = defaultdict(float)
    usd_by_pool: dict[str, float] = defaultdict(float)
    quote_by_pool: dict[str, str] = {}
    buckets: dict[int, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(lambda: {"volume_in_token": 0.0, "volume_usd": 0.0})
    )
    ambiguous_events = 0

    for evt in events_all or []:
        if (evt.get("event_type") or "").upper() != "SWAP":
            continue
        meta = None
        pa = (evt.get("pool_address") or "").lower()
        evt_has_tokens = bool(evt.get("token0_address") and evt.get("token1_address"))
        if evt_has_tokens:
            for candidate_pa, candidate_meta in pool_meta.items():
                if _event_matches_pool(
                    evt, candidate_meta["token0"], candidate_meta["token1"]
                ):
                    meta = candidate_meta
                    pa = candidate_pa
                    break
        else:
            meta = pool_meta.get(pa)
        if not meta:
            continue
        try:
            a0 = abs(int(evt.get("token0_amount", "0") or "0"))
            a1 = abs(int(evt.get("token1_amount", "0") or "0"))
        except (TypeError, ValueError):
            continue

        side_info = _resolve_target_side(
            evt, meta["token0"], meta["token1"], target_token, token_decimals
        )
        if side_info is None:
            ambiguous_events += 1
            continue
        target_side, quote_addr, quote_decimals = side_info
        if target_side == "0":
            token_vol = a0 / (10 ** token_decimals)
            quote_raw = a1
        else:
            token_vol = a1 / (10 ** token_decimals)
            quote_raw = a0

        volume_by_pool[pa] += token_vol
        quote_by_pool[pa] = _guess_quote_symbol(quote_addr)
        amount_usd = float(evt.get("amount_usd") or 0)
        if amount_usd > 0:
            usd_by_pool[pa] += amount_usd
        elif quote_addr in _STABLE_QUOTES:
            usd_by_pool[pa] += quote_raw / (10 ** quote_decimals)

        try:
            ts = int(evt.get("block_timestamp") or 0)
        except (TypeError, ValueError):
            ts = 0
        bucket = (ts // bucket_seconds) * bucket_seconds if ts else 0
        buckets[bucket][pa]["volume_in_token"] += token_vol
        if amount_usd > 0:
            buckets[bucket][pa]["volume_usd"] += amount_usd
        elif quote_addr in _STABLE_QUOTES:
            buckets[bucket][pa]["volume_usd"] += quote_raw / (10 ** quote_decimals)

    total_volume = sum(volume_by_pool.values())
    main_volume_pool = ""
    main_volume_share = 0.0
    if volume_by_pool:
        main_volume_pool = max(volume_by_pool, key=volume_by_pool.get)
        main_volume_share = volume_by_pool[main_volume_pool] / total_volume if total_volume else 0.0

    volume_by_pool_out = {}
    for pa, vol in volume_by_pool.items():
        volume_by_pool_out[pa] = {
            "protocol": pool_meta[pa]["protocol"],
            "version": pool_meta[pa]["version"],
            "volume_in_token": round(vol, 6),
            "volume_usd": round(usd_by_pool[pa], 2) if usd_by_pool.get(pa) else None,
            "share": round(vol / total_volume, 6) if total_volume else 0.0,
            "quote_symbol": quote_by_pool.get(pa, ""),
        }

    volume_timeline = [
        {
            "bucket_ts": bucket,
            "total_volume_in_token": round(
                sum(p["volume_in_token"] for p in pools.values()), 6
            ),
            "pools": {
                pa: dict(p) for pa, p in sorted(pools.items(), key=lambda x: -x[1]["volume_in_token"])
            },
        }
        for bucket, pools in sorted(buckets.items())
    ]

    return {
        "total_volume_in_token": round(total_volume, 6),
        "main_volume_pool": main_volume_pool,
        "main_volume_share": round(main_volume_share, 6),
        "volume_by_pool": volume_by_pool_out,
        "volume_timeline": volume_timeline,
        "bucket_seconds": bucket_seconds,
        "ambiguous_events": ambiguous_events,
        "note": (
            "Legacy Dune events without token addresses are inferred by "
            "decimal magnitude; same-decimals quote pools are skipped."
        ),
    }


def calculate_pool_concentration(
    verified_pools: list[VerifiedPool],
    timeline: list[dict],
    onchain_tvl: Optional[dict[str, int]] = None,
) -> dict[str, Any]:
    """Calculate main-pool dominance and concentration metrics.

    Prefers live on-chain TVL snapshot when available; falls back to timeline.
    """
    final_tvl: dict[str, int] = {}
    if onchain_tvl:
        final_tvl = {k: int(v) for k, v in onchain_tvl.items() if int(v) > 0}
    else:
        for entry in timeline:
            pa = entry["pool_address"]
            tvl = int(entry.get("tvl_in_token", "0") or "0")
            if tvl > 0:
                final_tvl[pa] = tvl

    if not final_tvl:
        return {
            "total_tvl": 0,
            "main_pool": "",
            "main_pool_tvl": 0,
            "main_pool_share": 0,
            "num_active_pools": 0,
            "source": "none",
        }

    total_tvl = sum(final_tvl.values())
    main_pool = max(final_tvl, key=final_tvl.get)
    main_pool_tvl = final_tvl[main_pool]
    main_pool_share = main_pool_tvl / total_tvl if total_tvl > 0 else 0

    return {
        "total_tvl": total_tvl,
        "main_pool": main_pool,
        "main_pool_tvl": main_pool_tvl,
        "main_pool_share": round(main_pool_share, 6),
        "num_active_pools": len(final_tvl),
        "per_pool_tvl": {
            k: v for k, v in sorted(final_tvl.items(), key=lambda x: -x[1])
        },
        "source": "onchain" if onchain_tvl else "timeline",
    }


def calculate_lp_concentration(
    positions: list[Position],
    top_n: int = 5,
) -> dict[str, Any]:
    """Calculate LP concentration: top LP and top-N shares.

    Computed per-pool (``share_pct`` is pool-local), then aggregated as the
    max across pools so multi-pool positions cannot sum past 100%.
    """
    if not positions:
        return {"top_lp_share": 0, "top_n_share": 0, "num_lps": 0}

    by_pool: dict[str, list[Position]] = defaultdict(list)
    for pos in positions:
        by_pool[pos.pool_address or ""].append(pos)

    pool_top_lp: list[float] = []
    pool_top_n: list[float] = []
    for pos_list in by_pool.values():
        sorted_pos = sorted(pos_list, key=lambda p: p.share_pct, reverse=True)
        if not sorted_pos:
            continue
        pool_top_lp.append(float(sorted_pos[0].share_pct or 0))
        pool_top_n.append(
            min(100.0, sum(float(p.share_pct or 0) for p in sorted_pos[:top_n]))
        )

    top_lp_share = max(pool_top_lp) if pool_top_lp else 0.0
    top_n_share = max(pool_top_n) if pool_top_n else 0.0

    return {
        "top_lp_share": round(top_lp_share, 6),
        "top_n_share": round(top_n_share, 6),
        "top_{}_share".format(top_n): round(top_n_share, 6),
        "total_lp_positions": len(positions),
        "num_lps": len(set(p.owner for p in positions)),
        "aggregation": "max_across_pools",
    }


def calculate_withdrawal_severity(
    events_liquidity: list[dict],
    pre_event_tvl: int,
    incident_block: int,
) -> dict[str, Any]:
    """Calculate the severity of liquidity withdrawals before/during the crash window.

    If ``incident_block`` is 0, use all LIQUIDITY_REMOVE events in the indexed window.
    """
    removals = [
        e for e in events_liquidity
        if e.get("event_type") == "LIQUIDITY_REMOVE"
    ]
    if incident_block and incident_block > 0:
        pre_crash_removals = [
            e for e in removals
            if e.get("block_number", 0) <= incident_block
        ]
    else:
        pre_crash_removals = removals

    # Severity ratio only from removals tied to a known pool (PM events often
    # lack pool_address and use unrelated token amounts).
    amount_events = [
        e for e in pre_crash_removals
        if (e.get("pool_address") or "").strip()
    ]
    total_removed_tokens = sum(
        abs(int(e.get("token0_amount", "0") or "0"))
        + abs(int(e.get("token1_amount", "0") or "0"))
        for e in amount_events
    )

    severity = (
        total_removed_tokens / pre_event_tvl
        if pre_event_tvl > 0 and total_removed_tokens > 0
        else 0.0
    )
    # Cap for scoring stability
    severity = min(severity, 1.0)

    return {
        "num_withdrawals": len(pre_crash_removals),
        "total_removed_token0": total_removed_tokens,
        "pre_event_tvl": pre_event_tvl,
        "withdrawal_severity": round(severity, 6),
        "withdrawal_events": [
            {
                "block_number": e["block_number"],
                "block": e["block_number"],
                "ts": e.get("block_timestamp", 0),
                "pool": e.get("pool_address", ""),
                "pool_address": e.get("pool_address", ""),
                "amount0": e.get("token0_amount", "0"),
                "amount1": e.get("token1_amount", "0"),
                "token0_amount": e.get("token0_amount", "0"),
                "token1_amount": e.get("token1_amount", "0"),
                "actor": e.get("actor", ""),
            }
            for e in pre_crash_removals
        ],
    }


def calculate_all_metrics(
    verified_pools: list[VerifiedPool],
    events_all: list[dict],
    events_liquidity: list[dict],
    positions: list[Position],
    target_token: str,
    token_decimals: int,
    incident_block: int = 0,
    output_dir: str | Path = "output",
    w3: Optional[Web3] = None,
    to_block: int = 0,
) -> dict[str, Any]:
    """Main entry point: compute all liquidity and risk metrics."""
    out = Path(output_dir)

    timeline = build_tvl_timeline(
        verified_pools, events_all, target_token, token_decimals
    )
    _write_json(out / "tvl_timeline.json", timeline)

    onchain_tvl = None
    snapshot_block: int | str = int(to_block) if to_block else "latest"
    if w3 is not None:
        try:
            onchain_tvl = snapshot_onchain_pool_tvl(
                w3, verified_pools, target_token, block_identifier=snapshot_block
            )
        except Exception:
            onchain_tvl = None

    pool_conc = calculate_pool_concentration(
        verified_pools, timeline, onchain_tvl=onchain_tvl
    )
    if onchain_tvl is not None:
        pool_conc["snapshot_block"] = snapshot_block
    lp_conc = calculate_lp_concentration(positions)

    pre_event_tvl = int(pool_conc.get("total_tvl", 0) or 0)
    withdrawal_sev = calculate_withdrawal_severity(
        events_liquidity, pre_event_tvl, incident_block
    )

    volume = calculate_volume_metrics(
        events_all, verified_pools, target_token, token_decimals
    )
    _write_json(out / "volume_timeline.json", volume)

    metrics = {
        "pool_concentration": pool_conc,
        "lp_concentration": lp_conc,
        "withdrawal_severity": withdrawal_sev,
        "volume": volume,
        "tvl_timeline_length": len(timeline),
        "tvl_timeline": timeline,
    }
    _write_json(out / "metrics.json", metrics)

    return metrics


def _write_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
