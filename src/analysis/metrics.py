"""Liquidity metrics — TVL, pool concentration, LP concentration, withdrawal severity, and price estimation."""
from __future__ import annotations

import bisect
import json
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from web3 import Web3

from ..client import get_contract
from ..data.artifacts import (
    flatten_volume_timeline,
    validate_artifact_environment,
    write_table,
)
from ..models import NormalizedEvent, Position, VerifiedPool

_ZERO_ADDR = "0x0000000000000000000000000000000000000000"
# structure.md: month → daily 00:00; week/day → hourly.
# ~7.2k blocks/day; ≥ ~25 days treated as month-scale when chart_span=auto.
_MONTH_MIN_BLOCKS = 180_000
_WEEK_MIN_BLOCKS = 45_000  # ~6–7 days
_SPAN_BUCKET = {"month": "day", "week": "hour", "day": "hour"}
_SPAN_BUCKET_SECONDS = {"month": 86_400, "week": 3_600, "day": 3_600}
_SPAN_WINDOW_SECONDS = {
    "month": 30 * 86_400,
    "week": 7 * 86_400,
    "day": 86_400,
}


def resolve_chart_span(
    from_block: int = 0,
    to_block: int = 0,
    chart_span: str = "auto",
) -> str:
    """Return ``month`` | ``week`` | ``day`` (structure.md chart intervals)."""
    raw = (chart_span or "auto").strip().lower()
    if raw in _SPAN_BUCKET:
        return raw
    span = max(0, int(to_block) - int(from_block))
    if span >= _MONTH_MIN_BLOCKS:
        return "month"
    if span >= _WEEK_MIN_BLOCKS:
        return "week"
    return "day"


def chart_bucket(chart_span: str) -> str:
    """Dune ``date_trunc`` unit for price_timeline."""
    return _SPAN_BUCKET.get(chart_span, "hour")


def chart_bucket_seconds(chart_span: str) -> int:
    """Local volume aggregation bucket size matching structure.md."""
    return int(_SPAN_BUCKET_SECONDS.get(chart_span, 3_600))


def _choose_tvl_bucket(
    from_block: int,
    to_block: int,
    chart_span: str = "auto",
) -> str:
    return chart_bucket(resolve_chart_span(from_block, to_block, chart_span))


def _parse_bucket_ts(value: Any) -> int:
    """Parse Dune bucket/day timestamp → unix seconds (UTC)."""
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        v = int(value)
        return v // 1000 if v > 10_000_000_000 else v
    s = str(value).strip()
    if s.endswith(" UTC"):
        s = s[:-4]
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Normalize "YYYY-MM-DD HH:MM:SS[.fff]" → ISO
    if "T" not in s and " " in s:
        s = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        pass
    for fmt, n in (("%Y-%m-%d %H:%M:%S.%f", 26), ("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            dt = datetime.strptime(str(value).strip()[:n], fmt)
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    return 0


def _day_start_ts(ts: int) -> int:
    if ts <= 0:
        return 0
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return int(dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


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


def _verified_pool_by_key(
    verified_pools: Optional[list[VerifiedPool]],
) -> dict[str, VerifiedPool]:
    """Map every address that can identify a pool to its VerifiedPool."""
    by_key: dict[str, VerifiedPool] = {}
    for pool in verified_pools or []:
        if not pool.verified:
            continue
        for raw in (pool.pool_address, pool.pool_id, pool.custody_address):
            if raw:
                by_key.setdefault(str(raw).lower(), pool)
    return by_key


def _swap_pool_meta(
    verified_pools: Optional[list[VerifiedPool]],
) -> dict[str, dict[str, str]]:
    """Build per-pool token metadata for swap event attribution."""
    meta: dict[str, dict[str, str]] = {}
    for pool in verified_pools or []:
        if not pool.verified:
            continue
        addr = (pool.pool_address or "").lower()
        if not addr:
            continue
        meta[addr] = {
            "protocol": pool.protocol,
            "version": pool.version,
            "token0": Web3.to_checksum_address(pool.token0).lower(),
            "token1": Web3.to_checksum_address(pool.token1).lower(),
        }
    return meta


def _build_pool_price_series(
    timeline: Optional[list[dict]],
) -> dict[str, tuple[list[int], list[float]]]:
    """Build block-sorted ``price_usd`` series per pool for time-aware lookups."""
    by_pool: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for entry in timeline or []:
        pa = (entry.get("pool_address") or "").lower()
        price = float(entry.get("price_usd") or 0)
        if pa and price > 0:
            by_pool[pa].append((int(entry.get("block_number") or 0), price))
    series: dict[str, tuple[list[int], list[float]]] = {}
    for pa, points in by_pool.items():
        points.sort(key=lambda x: x[0])
        series[pa] = ([p[0] for p in points], [p[1] for p in points])
    return series


def _price_at_or_before(
    series: dict[str, tuple[list[int], list[float]]],
    pool: str,
    block,
) -> Optional[float]:
    """Return the last known pool USD price at or before ``block``."""
    pair = series.get((pool or "").lower())
    if not pair:
        return None
    blocks, prices = pair
    idx = bisect.bisect_right(blocks, int(block or 0)) - 1
    return prices[idx] if idx >= 0 else None


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


def _eth_address(value: Any) -> Optional[str]:
    """Return lowercase 20-byte address, or None for poolIds / junk."""
    s = str(value or "").strip()
    if not s.startswith("0x") or len(s) != 42:
        return None
    try:
        return Web3.to_checksum_address(s).lower()
    except Exception:
        return None


def _pool_balance_key(pool: VerifiedPool) -> Optional[str]:
    """Address that holds the target token for this pool (custody for V4)."""
    for cand in (pool.custody_address, pool.pool_address):
        addr = _eth_address(cand)
        if addr:
            return addr
    return None


def build_tvl_timeline_snapshots(
    verified_pools: list[VerifiedPool],
    target_token: str,
    token_decimals: int,
    from_block: int,
    to_block: int,
    output_dir: str | Path = "output",
    chart_span: str = "auto",
    price_rows: Optional[list[dict]] = None,
) -> list[dict]:
    """TVL at fixed buckets: direct pool balance × price (no event accumulation).

    - month → daily 00:00 UTC (``price_timeline`` + ``pool_balance_timeline``)
    - week/day → hourly price; balance still from ledger rows, joined by day

    When ``price_rows`` is already computed from indexed swaps, skip the extra
    ``dex.trades`` ``price_timeline`` query.
    """
    from ..data.dune import configured, query

    if not configured():
        raise RuntimeError("DUNE_API_KEY is not set")

    pools = [p for p in verified_pools if p.verified and p.pool_address]
    # Balance ledger is address-keyed — never pass V4 bytes32 poolIds.
    bal_addrs: list[str] = []
    bal_key_by_pool: dict[str, str] = {}
    for p in pools:
        key = _pool_balance_key(p)
        if not key:
            continue
        bal_key_by_pool[p.pool_address.lower()] = key
        if key not in bal_addrs:
            bal_addrs.append(key)
    if not pools or from_block <= 0 or to_block < from_block:
        return []

    meta = {p.pool_address.lower(): p for p in pools}
    span = resolve_chart_span(from_block, to_block, chart_span)
    bucket = chart_bucket(span)
    cache = Path(output_dir) / "dune_cache" / "metrics"
    common = dict(
        token=target_token,
        from_block=int(from_block),
        to_block=int(to_block),
        cache_dir=cache,
        chunk_blocks=0,
    )
    decimals = max(0, int(token_decimals or 18))
    scale = 10 ** decimals

    def _balances():
        if not bal_addrs:
            return []
        return query(
            "pool_balance_timeline",
            pool_list=bal_addrs,
            **common,
        )

    def _prices():
        return query(
            "price_timeline",
            bucket=bucket,
            pool_filter="",
            **common,
        )

    local_prices = list(price_rows or [])
    if local_prices:
        bal_rows = _balances()
        price_rows = local_prices
    else:
        with ThreadPoolExecutor(max_workers=2) as ex:
            fut_b = ex.submit(_balances)
            fut_p = ex.submit(_prices)
            bal_rows = fut_b.result()
            price_rows = fut_p.result()

    # Balance rows: either block-keyed ledger, or constant 'latest' balances.
    bal_by_block: dict[int, dict[str, int]] = defaultdict(dict)
    constant_bal: dict[str, int] = {}
    for row in bal_rows or []:
        raw_ts = row.get("bucket_ts")
        pa = _eth_address(row.get("pool_address"))
        if not pa:
            continue
        try:
            raw_bal = int(row.get("balance_raw") or 0)
        except (TypeError, ValueError):
            continue
        if str(raw_ts).lower() == "latest" or raw_ts in (None, ""):
            constant_bal[pa] = raw_bal
            continue
        try:
            bn = int(raw_ts)
        except (TypeError, ValueError):
            bn = _parse_bucket_ts(raw_ts)
        if not bn:
            constant_bal[pa] = raw_bal
            continue
        bal_by_block[bn][pa] = raw_bal

    known_blocks = sorted(bal_by_block)
    last_bal: dict[str, int] = dict(constant_bal)
    bal_asof_block: dict[int, dict[str, int]] = {}
    for bn in known_blocks:
        last_bal = {**last_bal, **bal_by_block[bn]}
        bal_asof_block[bn] = dict(last_bal)

    price_ts_list = [
        _parse_bucket_ts(r.get("bucket_ts")) for r in (price_rows or [])
    ]
    price_ts_list = [t for t in price_ts_list if t > 0]
    t_lo = min(price_ts_list) if price_ts_list else 0
    t_hi = max(price_ts_list) if price_ts_list else 0

    def _block_to_ts(bn: int) -> int:
        if t_hi > t_lo and to_block > from_block:
            return int(
                t_lo
                + (bn - from_block) / (to_block - from_block) * (t_hi - t_lo)
            )
        return bn

    bal_asof_ts: dict[int, dict[str, int]] = {}
    for bn in known_blocks:
        bal_asof_ts[_block_to_ts(bn)] = bal_asof_block[bn]
    known_ts = sorted(bal_asof_ts)

    def _balance_for_addr(ts: int, addr: str) -> int:
        if not addr:
            return 0
        if constant_bal and addr in constant_bal and not known_ts:
            return int(constant_bal.get(addr, 0) or 0)
        if not known_ts:
            return int(constant_bal.get(addr, 0) or 0)
        earlier = [t for t in known_ts if t <= ts]
        if not earlier:
            base = bal_asof_ts[known_ts[0]]
            return int(base.get(addr, constant_bal.get(addr, 0)) or 0)
        return int(
            bal_asof_ts[earlier[-1]].get(addr, constant_bal.get(addr, 0)) or 0
        )

    timeline: list[dict] = []
    for row in price_rows or []:
        ts = _parse_bucket_ts(row.get("bucket_ts"))
        pa = str(row.get("pool_address") or "").lower()
        if not ts or not pa:
            continue
        pool = meta.get(pa)
        # dex.trades project_contract may be custody for V4 — match via bal key too
        if pool is None:
            for p in pools:
                if _pool_balance_key(p) == pa:
                    pool = p
                    pa = p.pool_address.lower()
                    break
        try:
            price_usd = float(row.get("price_usd") or 0)
        except (TypeError, ValueError):
            price_usd = 0.0
        if price_usd <= 0:
            continue
        bal_key = bal_key_by_pool.get(pa) or _eth_address(pa)
        bal_raw = _balance_for_addr(ts, bal_key) if bal_key else 0
        if bal_raw <= 0:
            continue
        bal_dec = bal_raw / scale
        tvl_usd = bal_dec * price_usd
        timeline.append({
            "block_number": ts,
            "block_timestamp": ts,
            "bucket": bucket,
            "chart_span": span,
            "pool_address": pool.pool_address if pool else pa,
            "protocol": (pool.protocol if pool else "") or "",
            "version": (pool.version if pool else "") or "",
            "event_type": "SNAPSHOT",
            "source_event": "balance_x_price",
            "balance_raw": str(bal_raw),
            "tvl_in_token": str(bal_raw),
            "tvl_usd": round(tvl_usd, 6),
            "price": round(price_usd, 18),
            "price_usd": round(price_usd, 6),
            "quote_symbol": "USD",
        })

    timeline.sort(key=lambda e: (e["block_number"], str(e.get("pool_address") or "")))
    return timeline


def build_tvl_timeline(
    verified_pools: list[VerifiedPool],
    events_all: list[dict],
    target_token: str,
    token_decimals: int,
) -> list[dict]:
    """Legacy: TVL/price reconstructed by accumulating swap/LP events.

    Prefer ``build_tvl_timeline_snapshots`` (structure.md §6). Kept only as
    emergency fallback when Dune snapshots are unavailable.
    """
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


def calculate_price_timeline_from_swaps(
    events_all: list[dict],
    verified_pools: list[VerifiedPool],
    target_token: str,
    token_decimals: int,
    bucket_seconds: int = 3600,
) -> list[dict[str, Any]]:
    """Last swap-implied USD price per pool per bucket (same as ``price_timeline`` SQL).

    ``price_usd = amount_usd / target_token_amount``; bucket value is the last
    swap in that bucket (``MAX_BY`` equivalent).
    """
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

    last: dict[tuple[int, str], dict[str, Any]] = {}
    for evt in events_all or []:
        if (evt.get("event_type") or "").upper() != "SWAP":
            continue
        pa = (evt.get("pool_address") or "").lower()
        evt_has_tokens = bool(evt.get("token0_address") and evt.get("token1_address"))
        meta = None
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
        if not meta or not pa:
            continue
        amount_usd = float(evt.get("amount_usd") or 0)
        if amount_usd <= 0:
            continue
        side_info = _resolve_target_side(
            evt, meta["token0"], meta["token1"], target_token, token_decimals
        )
        if side_info is None:
            continue
        try:
            a0 = abs(int(evt.get("token0_amount", "0") or "0"))
            a1 = abs(int(evt.get("token1_amount", "0") or "0"))
        except (TypeError, ValueError):
            continue
        target_raw = a0 if side_info[0] == "0" else a1
        if target_raw <= 0:
            continue
        token_amount = target_raw / (10 ** max(0, int(token_decimals or 18)))
        if token_amount <= 0:
            continue
        try:
            ts = int(evt.get("block_timestamp") or 0)
        except (TypeError, ValueError):
            ts = 0
        if ts <= 0:
            continue
        bucket_ts = (ts // bucket_seconds) * bucket_seconds
        price_usd = amount_usd / token_amount
        try:
            bn = int(evt.get("block_number") or 0)
        except (TypeError, ValueError):
            bn = 0
        try:
            log_index = int(evt.get("log_index") or 0)
        except (TypeError, ValueError):
            log_index = 0
        key = (bucket_ts, pa)
        prev = last.get(key)
        if prev and (bn, log_index, ts) < (
            int(prev.get("_bn") or 0),
            int(prev.get("_log") or 0),
            int(prev.get("_ts") or 0),
        ):
            continue
        last[key] = {
            "bucket_ts": bucket_ts,
            "pool_address": pa,
            "protocol": meta.get("protocol") or evt.get("protocol") or "",
            "version": meta.get("version") or evt.get("version") or "",
            "price_usd": price_usd,
            "_bn": bn,
            "_log": log_index,
            "_ts": ts,
        }

    out = []
    for row in sorted(last.values(), key=lambda r: (r["bucket_ts"], r["pool_address"])):
        out.append({
            "bucket_ts": row["bucket_ts"],
            "pool_address": row["pool_address"],
            "protocol": row["protocol"],
            "version": row["version"],
            "price_usd": row["price_usd"],
        })
    return out


def fetch_volume_timeline_from_dune(
    verified_pools: list[VerifiedPool],
    target_token: str,
    from_block: int,
    to_block: int,
    *,
    chart_span: str = "auto",
    output_dir: str | Path = "output",
) -> dict[str, Any]:
    """Volume charts via SQL aggregate. Used only when raw swaps were not indexed."""
    from ..data.dune import configured, query

    if not configured():
        raise RuntimeError("DUNE_API_KEY is not set")
    if from_block <= 0 or to_block < from_block:
        return {}

    span = resolve_chart_span(from_block, to_block, chart_span)
    bucket = chart_bucket(span)
    bucket_seconds = chart_bucket_seconds(span)
    cache = Path(output_dir) / "dune_cache" / "metrics"
    rows = query(
        "volume_timeline",
        token=target_token,
        from_block=int(from_block),
        to_block=int(to_block),
        bucket=bucket,
        pool_filter="",
        cache_dir=cache,
        chunk_blocks=0,
    )

    pool_meta: dict[str, dict[str, Any]] = {}
    for pool in verified_pools:
        if not pool.verified or not pool.pool_address:
            continue
        pool_meta[pool.pool_address.lower()] = {
            "protocol": pool.protocol,
            "version": pool.version,
        }

    volume_by_pool: dict[str, float] = defaultdict(float)
    usd_by_pool: dict[str, float] = defaultdict(float)
    buckets: dict[int, dict[str, dict[str, Any]]] = defaultdict(
        lambda: defaultdict(lambda: {"volume_in_token": 0.0, "volume_usd": 0.0})
    )
    for row in rows or []:
        pa = str(row.get("pool_address") or "").lower()
        if not pa:
            continue
        ts = _parse_bucket_ts(row.get("bucket_ts"))
        try:
            vol = float(row.get("volume_in_token") or 0)
        except (TypeError, ValueError):
            vol = 0.0
        try:
            usd = float(row.get("volume_usd") or 0)
        except (TypeError, ValueError):
            usd = 0.0
        if vol <= 0 and usd <= 0:
            continue
        volume_by_pool[pa] += vol
        if usd > 0:
            usd_by_pool[pa] += usd
        if ts > 0:
            buckets[ts][pa]["volume_in_token"] += vol
            if usd > 0:
                buckets[ts][pa]["volume_usd"] += usd
        meta = pool_meta.setdefault(
            pa,
            {
                "protocol": str(row.get("protocol") or ""),
                "version": str(row.get("version") or ""),
            },
        )
        if row.get("protocol"):
            meta["protocol"] = str(row.get("protocol") or meta["protocol"])
        if row.get("version"):
            meta["version"] = str(row.get("version") or meta["version"])

    total_volume = sum(volume_by_pool.values())
    main_volume_pool = ""
    main_volume_share = 0.0
    if volume_by_pool:
        main_volume_pool = max(volume_by_pool, key=volume_by_pool.get)
        main_volume_share = (
            volume_by_pool[main_volume_pool] / total_volume if total_volume else 0.0
        )

    volume_by_pool_out = {}
    for pa, vol in volume_by_pool.items():
        meta = pool_meta.get(pa, {})
        volume_by_pool_out[pa] = {
            "protocol": meta.get("protocol", ""),
            "version": meta.get("version", ""),
            "volume_in_token": round(vol, 6),
            "volume_usd": round(usd_by_pool[pa], 2) if usd_by_pool.get(pa) else None,
            "share": round(vol / total_volume, 6) if total_volume else 0.0,
            "quote_symbol": "",
        }

    volume_timeline = [
        {
            "bucket_ts": bts,
            "total_volume_in_token": round(
                sum(p["volume_in_token"] for p in pools.values()), 6
            ),
            "pools": {
                pa: dict(p)
                for pa, p in sorted(
                    pools.items(), key=lambda x: -x[1]["volume_in_token"]
                )
            },
        }
        for bts, pools in sorted(buckets.items())
    ]

    return {
        "total_volume_in_token": round(total_volume, 6),
        "main_volume_pool": main_volume_pool,
        "main_volume_share": round(main_volume_share, 6),
        "volume_by_pool": volume_by_pool_out,
        "volume_timeline": volume_timeline,
        "bucket_seconds": bucket_seconds,
        "chart_span": span,
        "bucket": bucket,
        "source": "dune_volume_timeline",
        "note": (
            "Aggregated in Dune (date_trunc + sum); raw swaps are not required "
            "for volume charts."
        ),
    }


def _has_swap_events(events_all: list[dict] | None) -> bool:
    return any(
        (evt.get("event_type") or "").upper() == "SWAP" for evt in (events_all or [])
    )


def calculate_volume_metrics(
    events_all: list[dict],
    verified_pools: list[VerifiedPool],
    target_token: str,
    token_decimals: int,
    bucket_seconds: int = 3600,
) -> dict[str, Any]:
    """Aggregate swap volume by pool and by time bucket from indexed swaps.

    Primary path when ``swaps.json`` / ``events_all`` already exists so
    ``dex.trades`` is not queried again for charts. Dune ``volume_timeline``
    remains the fallback when raw swaps were not indexed.
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
    verified_pools: Optional[list[VerifiedPool]] = None,
    target_token: str = "",
    token_decimals: int = 18,
    tvl_by_pool: Optional[dict[str, int]] = None,
    timeline: Optional[list[dict]] = None,
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

    pool_by_key = _verified_pool_by_key(verified_pools)
    price_series = _build_pool_price_series(timeline)
    pool_tvl = {
        str(k).lower(): int(v)
        for k, v in (tvl_by_pool or {}).items()
        if int(v or 0) > 0
    }
    target_lower = (target_token or "").lower()
    scale = 10 ** max(0, int(token_decimals or 18))

    def _find_pool(evt: dict) -> Optional[VerifiedPool]:
        pa = (evt.get("pool_address") or "").lower()
        if pa and pa in pool_by_key:
            return pool_by_key[pa]
        t0 = (evt.get("token0_address") or "").lower()
        t1 = (evt.get("token1_address") or "").lower()
        if not t0 or not t1:
            return None
        for pool in verified_pools or []:
            if pool.verified and _event_matches_pool(evt, pool.token0, pool.token1):
                return pool
        return None

    def _normalize_removal(
        evt: dict, pool: Optional[VerifiedPool]
    ) -> tuple[int, int, str, int]:
        """Return (removed_target_raw, quote_raw, quote_addr_lower, quote_decimals)."""
        try:
            a0 = abs(int(evt.get("token0_amount", "0") or "0"))
            a1 = abs(int(evt.get("token1_amount", "0") or "0"))
        except (TypeError, ValueError):
            return 0, 0, "", 18
        if pool is None:
            return 0, 0, "", 18
        side_info = _resolve_target_side(
            evt, pool.token0, pool.token1, target_token, token_decimals
        )
        if side_info:
            side, quote_addr, quote_dec = side_info
            return (a0 if side == "0" else a1,
                    a1 if side == "0" else a0,
                    quote_addr,
                    quote_dec)
        pt0 = (pool.token0 or "").lower()
        pt1 = (pool.token1 or "").lower()
        if target_lower == pt0:
            return a0, a1, pt1, _known_decimals(pt1)
        if target_lower == pt1:
            return a1, a0, pt0, _known_decimals(pt0)
        return 0, 0, "", 18

    def _quantification_status(
        evt: dict, pool: Optional[VerifiedPool]
    ) -> str:
        """Distinguish measured zero from an event whose amount is unavailable."""
        if pool is None:
            return "unmapped"
        explicit = str(evt.get("quantification_status") or "").lower()
        if explicit in {"quantified", "liquidity_delta_only", "unmapped"}:
            return explicit
        try:
            delta_nonzero = int(evt.get("liquidity_delta") or 0) != 0
            amounts_zero = (
                int(evt.get("token0_amount") or 0) == 0
                and int(evt.get("token1_amount") or 0) == 0
            )
        except (TypeError, ValueError):
            delta_nonzero = False
            amounts_zero = False
        amounts_available = evt.get("amounts_available")
        if amounts_available is False:
            return "liquidity_delta_only" if delta_nonzero else "unmapped"
        version = str(evt.get("version") or pool.version or "").lower()
        source_event = str(evt.get("source_event") or "").lower()
        if (
            version in ("v4", "4")
            and source_event == "modifyliquidity"
            and delta_nonzero
            and amounts_zero
        ):
            return "liquidity_delta_only"
        return "quantified"

    normalized: list[dict] = []
    per_pool: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "num_withdrawals": 0,
            "removed_target_raw": 0,
            "removed_target_decimal": 0.0,
            "removed_usd": 0.0,
            "pool_tvl_raw": 0,
        }
    )
    legacy_total = 0
    total_target_raw = 0
    total_usd = 0.0
    attributed_events = 0
    withdrawal_event_count = 0
    quantification_counts = {
        "quantified": 0,
        "liquidity_delta_only": 0,
        "unmapped": 0,
    }

    for evt in pre_crash_removals:
        event_count = max(1, int(evt.get("event_count") or 1))
        withdrawal_event_count += event_count
        try:
            legacy_total += abs(int(evt.get("token0_amount", "0") or "0")) + abs(
                int(evt.get("token1_amount", "0") or "0")
            )
        except (TypeError, ValueError):
            pass
        pool = _find_pool(evt)
        quantification_status = _quantification_status(evt, pool)
        quantification_counts[quantification_status] += event_count
        removed_raw, quote_raw, quote_addr, quote_dec = _normalize_removal(evt, pool)
        protocol = pool.protocol if pool else str(evt.get("protocol") or "")
        version = pool.version if pool else str(evt.get("version") or "")
        resolved_pool_address = (
            pool.pool_address if pool else str(evt.get("pool_address") or "")
        )
        pool_label = "{} {}".format(protocol, version).strip()
        if quantification_status != "quantified" or removed_raw <= 0:
            normalized.append({
                "block_number": evt.get("block_number", 0),
                "block": evt.get("block_number", 0),
                "ts": evt.get("block_timestamp", 0),
                "pool": resolved_pool_address,
                "pool_address": resolved_pool_address,
                "actor": evt.get("actor", ""),
                "amount0": evt.get("token0_amount", "0"),
                "amount1": evt.get("token1_amount", "0"),
                "token0_amount": evt.get("token0_amount", "0"),
                "token1_amount": evt.get("token1_amount", "0"),
                "liquidity_delta": str(evt.get("liquidity_delta") or "0"),
                "pool_label": pool_label,
                "protocol": protocol,
                "version": version,
                "removed_target_raw": 0 if quantification_status == "quantified" else None,
                "removed_target_decimal": (
                    0.0 if quantification_status == "quantified" else None
                ),
                "removed_usd": None,
                "pool_tvl_share": None,
                "usd_source": "",
                "event_count": event_count,
                "aggregation_scope": evt.get("aggregation_scope", ""),
                "amounts_available": quantification_status == "quantified",
                "quantification_status": quantification_status,
            })
            continue

        attributed_events += event_count
        removed_decimal = removed_raw / scale
        pool_key = (pool.pool_address or evt.get("pool_address") or "").lower()
        pool_tvl_raw = pool_tvl.get(pool_key, 0)
        pool_share = (
            removed_raw / pool_tvl_raw
            if pool_tvl_raw > 0 and removed_raw > 0
            else None
        )
        amount_usd = float(evt.get("amount_usd") or 0)
        usd = None
        usd_source = ""
        if amount_usd > 0:
            usd = amount_usd
            usd_source = "event_amount_usd"
        elif quote_addr in _STABLE_QUOTES and quote_raw > 0:
            usd = quote_raw / (10 ** quote_dec)
            usd_source = "stable_quote"
        elif removed_decimal > 0:
            price = _price_at_or_before(
                price_series, pool_key, evt.get("block_number") or 0
            )
            if price:
                usd = removed_decimal * price
                usd_source = "target_x_pool_price"

        total_target_raw += removed_raw
        if usd is not None:
            total_usd += usd

        meta = {"protocol": pool.protocol, "version": pool.version}
        pool_label = "{} {}".format(meta["protocol"], meta["version"]).strip()
        normalized.append({
            "block_number": evt.get("block_number", 0),
            "block": evt.get("block_number", 0),
            "ts": evt.get("block_timestamp", 0),
            "pool": pool.pool_address or evt.get("pool_address", ""),
            "pool_address": pool.pool_address or evt.get("pool_address", ""),
            "amount0": evt.get("token0_amount", "0"),
            "amount1": evt.get("token1_amount", "0"),
            "token0_amount": evt.get("token0_amount", "0"),
            "token1_amount": evt.get("token1_amount", "0"),
            "liquidity_delta": str(evt.get("liquidity_delta") or "0"),
            "actor": evt.get("actor", ""),
            "pool_label": pool_label,
            "protocol": meta.get("protocol", ""),
            "version": meta.get("version", ""),
            "removed_target_raw": removed_raw,
            "removed_target_decimal": round(removed_decimal, 8),
            "removed_usd": round(usd, 2) if usd is not None else None,
            "pool_tvl_raw": pool_tvl_raw or None,
            "pool_tvl_share": round(pool_share, 8) if pool_share is not None else None,
            "usd_source": usd_source,
            "event_count": event_count,
            "aggregation_scope": evt.get("aggregation_scope", ""),
            "amounts_available": True,
            "quantification_status": "quantified",
        })

        agg = per_pool[pool_key]
        agg["num_withdrawals"] += event_count
        agg["removed_target_raw"] += removed_raw
        agg["removed_target_decimal"] += removed_decimal
        agg["removed_usd"] += usd or 0.0
        agg["pool_tvl_raw"] = pool_tvl_raw
        agg["pool_address"] = pool.pool_address or evt.get("pool_address", "")
        agg["protocol"] = meta.get("protocol", "")
        agg["version"] = meta.get("version", "")

    severity = (
        total_target_raw / pre_event_tvl
        if pre_event_tvl > 0 and total_target_raw > 0
        else 0.0
    )
    severity = min(severity, 1.0)

    per_pool_rows = []
    for pa, agg in per_pool.items():
        share = (
            agg["removed_target_raw"] / agg["pool_tvl_raw"]
            if agg["pool_tvl_raw"] > 0 and agg["removed_target_raw"] > 0
            else None
        )
        per_pool_rows.append({
            "pool_address": agg.get("pool_address", pa),
            "protocol": agg.get("protocol", ""),
            "version": agg.get("version", ""),
            "num_withdrawals": agg["num_withdrawals"],
            "removed_target_raw": agg["removed_target_raw"],
            "removed_target_decimal": round(agg["removed_target_decimal"], 8),
            "removed_usd": round(agg["removed_usd"], 2) if agg["removed_usd"] else None,
            "pool_tvl_raw": agg["pool_tvl_raw"] or None,
            "pool_tvl_share": round(share, 8) if share is not None else None,
        })
    per_pool_rows.sort(
        key=lambda r: (
            float(r.get("removed_usd") or 0),
            float(r.get("removed_target_decimal") or 0),
        ),
        reverse=True,
    )

    return {
        "num_withdrawals": withdrawal_event_count,
        "attributed_withdrawals": attributed_events,
        "quantified_withdrawals": quantification_counts["quantified"],
        "liquidity_delta_only_withdrawals": quantification_counts[
            "liquidity_delta_only"
        ],
        "unmapped_withdrawals": quantification_counts["unmapped"],
        "total_removed_token0": legacy_total,
        "legacy_total_removed_token0": legacy_total,
        "total_removed_target_raw": total_target_raw,
        "total_removed_target_decimal": round(total_target_raw / scale, 8),
        "total_removed_usd": round(total_usd, 2) if total_usd else None,
        "pre_event_tvl": pre_event_tvl,
        "withdrawal_severity": round(severity, 6),
        "per_pool_removals": per_pool_rows,
        "normalization_note": (
            "Removed target-token amount is normalized to the pool side holding "
            "the target token (no token0 + token1 double counting). USD prefers "
            "event amount_usd, then stablecoin quote, then target amount x pool "
            "price_usd at or before the event block. Quantified zero is kept as "
            "zero; V4 ModifyLiquidity rows without token amounts are classified "
            "as liquidity_delta_only rather than treated as zero."
        ),
        "withdrawal_events": sorted(
            normalized, key=lambda e: -int(e.get("block_number") or 0)
        ),
    }


def _exclusive_percentile(values: list[float], percentile: float) -> float:
    """Return an exclusive percentile suitable for outlier cutoffs.

    The ``(n + 1) * p`` position keeps a P99 cutoff near the largest values
    for smaller samples instead of collapsing to the modal value (especially
    important for integer swap counts with many ties).
    """
    ordered = sorted(float(v) for v in values if math.isfinite(float(v)))
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    q = min(1.0, max(0.0, float(percentile)))
    position = q * (len(ordered) + 1) - 1
    if position <= 0:
        return ordered[0]
    if position >= len(ordered) - 1:
        return ordered[-1]
    lower = int(math.floor(position))
    fraction = position - lower
    return ordered[lower] + (ordered[lower + 1] - ordered[lower]) * fraction


def _percentile_rank(value: float, ordered: list[float]) -> float:
    if not ordered:
        return 0.0
    return 100.0 * bisect.bisect_right(ordered, float(value)) / len(ordered)


def calculate_wallet_activity(
    events_all: list[dict],
    verified_pools: list[VerifiedPool],
    target_token: str,
    token_decimals: int,
    timeline: Optional[list[dict]] = None,
    min_large_trade_usd: Optional[float] = None,
    mover_net_usd: Optional[float] = None,
    min_activity_trades: Optional[int] = None,
    volume_ratio: Optional[float] = None,
    adaptive_percentile: float = 0.99,
    top_n: int = 200,
) -> dict[str, Any]:
    """Aggregate USD-valued swaps and select statistically unusual wallets.

    By default each flag uses the within-window ``adaptive_percentile`` of its
    metric, so the cutoff scales with token size and window activity.  Passing
    an explicit threshold keeps the former fixed-threshold behaviour for that
    metric.  ``volume_ratio`` similarly overrides the adaptive cumulative-
    volume cutoff when supplied.
    """
    target = Web3.to_checksum_address(target_token).lower()
    pool_meta = _swap_pool_meta(verified_pools)
    price_series = _build_pool_price_series(timeline)
    infra_addr_set = set()
    for p in verified_pools or []:
        for raw in (
            p.pool_address,
            p.pool_id,
            p.custody_address,
            p.position_manager_address,
            p.hooks_address,
        ):
            if raw:
                infra_addr_set.add(str(raw).lower())
        for raw in list(p.router_addresses or []) + list(p.gauge_addresses or []):
            if raw:
                infra_addr_set.add(str(raw).lower())
    scale = 10 ** max(0, int(token_decimals or 18))
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "swap_count": 0,
            "bought_usd": 0.0,
            "sold_usd": 0.0,
            "net_usd": 0.0,
            "total_usd": 0.0,
            "max_single_usd": 0.0,
            "bought_token": 0.0,
            "sold_token": 0.0,
        }
    )
    total_usd = 0.0
    no_usd_swaps = 0

    for evt in events_all or []:
        if (evt.get("event_type") or "").upper() != "SWAP":
            continue
        pa = (evt.get("pool_address") or "").lower()
        evt_has_tokens = bool(evt.get("token0_address") and evt.get("token1_address"))
        meta = None
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
            continue
        target_side, quote_addr, quote_dec = side_info
        target_raw = a0 if target_side == "0" else a1
        quote_raw = a1 if target_side == "0" else a0
        target_decimal = target_raw / scale
        amount_usd = float(evt.get("amount_usd") or 0)
        usd = 0.0
        if amount_usd > 0:
            usd = amount_usd
        elif quote_addr in _STABLE_QUOTES and quote_raw > 0:
            usd = quote_raw / (10 ** quote_dec)
        elif target_decimal > 0:
            price = _price_at_or_before(
                price_series, pa, evt.get("block_number") or 0
            )
            if price:
                usd = target_decimal * price
        if usd <= 0:
            no_usd_swaps += 1
            continue
        total_usd += usd

        addr = (evt.get("actor") or evt.get("recipient") or "").lower()
        if not addr or addr in infra_addr_set:
            continue
        t0 = (evt.get("token0_address") or "").lower()
        t1 = (evt.get("token1_address") or "").lower()
        if t0 and t1 and target in (t0, t1):
            sign = -1.0 if target == t0 else 1.0
        else:
            sign = -1.0 if target_side == "0" else 1.0

        s = stats[addr]
        s["swap_count"] += 1
        s["total_usd"] += usd
        s["max_single_usd"] = max(s["max_single_usd"], usd)
        if sign > 0:
            s["bought_usd"] += usd
            s["bought_token"] += target_decimal
        else:
            s["sold_usd"] += usd
            s["sold_token"] += target_decimal
        s["net_usd"] += sign * usd

    raw_rows: list[tuple[str, dict[str, Any]]] = list(stats.items())
    max_single_values = [float(s["max_single_usd"]) for _, s in raw_rows]
    net_values = [abs(float(s["net_usd"])) for _, s in raw_rows]
    activity_values = [float(s["swap_count"]) for _, s in raw_rows]
    total_values = [float(s["total_usd"]) for _, s in raw_rows]

    adaptive_q = min(0.9999, max(0.50, float(adaptive_percentile)))
    trade_mode = "fixed" if min_large_trade_usd is not None else "percentile"
    mover_mode = "fixed" if mover_net_usd is not None else "percentile"
    activity_mode = "fixed" if min_activity_trades is not None else "percentile"
    volume_mode = "fixed_ratio" if volume_ratio is not None else "percentile"

    trade_threshold = (
        float(min_large_trade_usd)
        if min_large_trade_usd is not None
        else _exclusive_percentile(max_single_values, adaptive_q)
    )
    mover_threshold = (
        float(mover_net_usd)
        if mover_net_usd is not None
        else _exclusive_percentile(net_values, adaptive_q)
    )
    activity_threshold = (
        int(min_activity_trades)
        if min_activity_trades is not None
        else int(math.ceil(_exclusive_percentile(activity_values, adaptive_q)))
    )
    volume_threshold_usd = (
        total_usd * float(volume_ratio)
        if volume_ratio is not None
        else _exclusive_percentile(total_values, adaptive_q)
    )
    effective_volume_ratio = (
        volume_threshold_usd / total_usd if total_usd > 0 else 0.0
    )

    modes = {trade_mode, mover_mode, activity_mode, volume_mode}
    if modes <= {"percentile"}:
        selection_mode = "adaptive_percentile"
    elif modes <= {"fixed", "fixed_ratio"}:
        selection_mode = "fixed"
    else:
        selection_mode = "hybrid"

    ordered_max = sorted(max_single_values)
    ordered_net = sorted(net_values)
    ordered_activity = sorted(activity_values)
    ordered_total = sorted(total_values)
    variable = {
        "trade": len(set(max_single_values)) > 1,
        "mover": len(set(net_values)) > 1,
        "activity": len(set(activity_values)) > 1,
        "volume": len(set(total_values)) > 1,
    }

    rows = []
    for addr, s in raw_rows:
        total = s["total_usd"]
        max_single = float(s["max_single_usd"])
        abs_net = abs(float(s["net_usd"]))
        swap_count = int(s["swap_count"])
        large_trade = max_single >= trade_threshold and (
            trade_mode == "fixed" or variable["trade"]
        )
        large_mover = abs_net >= mover_threshold and (
            mover_mode == "fixed" or variable["mover"]
        )
        high_activity = swap_count >= activity_threshold and (
            activity_mode == "fixed" or variable["activity"]
        )
        market_share = total >= volume_threshold_usd and (
            (volume_mode == "fixed_ratio" and float(volume_ratio or 0) > 0)
            or (volume_mode == "percentile" and variable["volume"])
        )
        trade_pct = _percentile_rank(max_single, ordered_max)
        mover_pct = _percentile_rank(abs_net, ordered_net)
        activity_pct = _percentile_rank(swap_count, ordered_activity)
        volume_pct = _percentile_rank(total, ordered_total)
        # Legacy fixed-ratio ``Share`` remains informational.  The adaptive
        # cumulative-volume outlier is a true selection signal.
        notable = bool(
            large_trade
            or large_mover
            or high_activity
            or (market_share and volume_mode == "percentile")
        )
        rows.append({
            "address": addr,
            "swap_count": s["swap_count"],
            "bought_usd": round(s["bought_usd"], 2),
            "sold_usd": round(s["sold_usd"], 2),
            "net_usd": round(s["net_usd"], 2),
            "total_usd": round(total, 2),
            "max_single_usd": round(s["max_single_usd"], 2),
            "bought_token": round(s["bought_token"], 6),
            "sold_token": round(s["sold_token"], 6),
            "volume_share_pct": round(
                (total / total_usd * 100.0) if total_usd > 0 else 0.0, 6
            ),
            "net_direction_pct": round(
                (abs_net / total * 100.0) if total > 0 else 0.0, 4
            ),
            "trade_percentile": round(trade_pct, 4),
            "mover_percentile": round(mover_pct, 4),
            "activity_percentile": round(activity_pct, 4),
            "volume_percentile": round(volume_pct, 4),
            "notability_score": round(
                max(trade_pct, mover_pct, activity_pct, volume_pct), 4
            ),
            "large_trade": bool(large_trade),
            "large_mover": bool(large_mover),
            "high_activity": bool(high_activity),
            "market_share": bool(market_share),
            "large": bool(large_trade or large_mover),
            "notable": notable,
            "flag_count": sum(
                bool(flag)
                for flag in (large_trade, large_mover, high_activity, market_share)
            ),
        })
    rows.sort(
        key=lambda r: (
            -int(r["flag_count"]),
            -float(r["notability_score"]),
            -abs(float(r["net_usd"])),
            -float(r["total_usd"]),
        )
    )
    notable_rows = [r for r in rows if r["notable"]]
    top_rows = [r for r in rows if not r["notable"]][:top_n]
    out_rows = notable_rows + top_rows
    seen: set[str] = set()
    out_rows = [
        r for r in out_rows
        if not (r["address"] in seen or seen.add(r["address"]))
    ]

    return {
        "selection_mode": selection_mode,
        "adaptive_percentile": round(adaptive_q, 6),
        "adaptive_percentile_label": "P{:g}".format(adaptive_q * 100),
        "threshold_modes": {
            "trade": trade_mode,
            "mover": mover_mode,
            "activity": activity_mode,
            "volume": volume_mode,
        },
        "large_trade_threshold_usd": round(trade_threshold, 2),
        "mover_net_usd_threshold": round(mover_threshold, 2),
        "activity_trade_threshold": activity_threshold,
        "volume_ratio": round(effective_volume_ratio, 8),
        "total_swap_volume_usd": round(total_usd, 2),
        "ratio_threshold_usd": round(volume_threshold_usd, 2),
        "num_large_trade_wallets": sum(1 for r in rows if r["large_trade"]),
        "num_large_mover_wallets": sum(1 for r in rows if r["large_mover"]),
        "num_high_activity_wallets": sum(1 for r in rows if r["high_activity"]),
        "num_notable_wallets": len(notable_rows),
        "wallets_considered": len(stats),
        "swaps_without_usd": no_usd_swaps,
        "wallets": out_rows,
        "note": (
            "USD per swap prefers Dune amount_usd, then stablecoin quote, then "
            "target amount x pool price_usd at or before the swap block. By "
            "default, Trade, Mover, Volume, and Activity use within-window "
            "percentile cutoffs; explicit arguments retain fixed thresholds."
        ),
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
    from_block: int = 0,
    to_block: int = 0,
    chart_span: str = "auto",
    artifact_format: str = "json",
) -> dict[str, Any]:
    """Main entry point: compute all liquidity and risk metrics."""
    artifact_mode = validate_artifact_environment(artifact_format)
    if artifact_mode == "parquet":
        raise ValueError(
            "metrics still requires artifact_format='both' so legacy JSON "
            "dashboard readers keep working"
        )
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    span = resolve_chart_span(from_block, to_block, chart_span)
    bucket = chart_bucket(span)
    bucket_seconds = chart_bucket_seconds(span)

    # structure.md §6: fixed-time balance × price snapshots (not event accumulation).
    # Price/volume reuse indexed swaps so dex.trades is not scanned again.
    local_prices = calculate_price_timeline_from_swaps(
        events_all,
        verified_pools,
        target_token,
        token_decimals,
        bucket_seconds=bucket_seconds,
    )
    timeline: list[dict] = []
    tvl_source = "none"
    if from_block > 0 and to_block >= from_block:
        try:
            timeline = build_tvl_timeline_snapshots(
                verified_pools,
                target_token,
                token_decimals,
                from_block=from_block,
                to_block=to_block,
                output_dir=out,
                chart_span=span,
                price_rows=local_prices or None,
            )
            if local_prices and timeline:
                tvl_source = "dune_balance_local_price"
            elif timeline:
                tvl_source = "dune_snapshot"
            else:
                tvl_source = "dune_snapshot_empty"
        except Exception as exc:
            print(f"  [metrics] snapshot TVL failed ({exc}); falling back to event timeline")
            timeline = build_tvl_timeline(
                verified_pools, events_all, target_token, token_decimals
            )
            tvl_source = "event_accumulate_fallback"
    else:
        timeline = build_tvl_timeline(
            verified_pools, events_all, target_token, token_decimals
        )
        tvl_source = "event_accumulate"
    tvl_artifact = write_table(
        "tvl_timeline", timeline, out, artifact_format=artifact_mode
    )

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
        events_liquidity,
        pre_event_tvl,
        incident_block,
        verified_pools=verified_pools,
        target_token=target_token,
        token_decimals=token_decimals,
        tvl_by_pool=pool_conc.get("per_pool_tvl"),
        timeline=timeline,
    )

    volume: dict[str, Any] = {}
    if _has_swap_events(events_all):
        volume = calculate_volume_metrics(
            events_all,
            verified_pools,
            target_token,
            token_decimals,
            bucket_seconds=bucket_seconds,
        )
        volume["chart_span"] = span
        volume["bucket"] = bucket
        volume["source"] = "local_swaps"
        if volume.get("volume_timeline") and local_prices:
            print(
                "  [metrics] volume + price from indexed swaps "
                "(skip extra dex.trades queries)"
            )
    if (
        not volume.get("volume_timeline")
        and from_block > 0
        and to_block >= from_block
    ):
        try:
            volume = fetch_volume_timeline_from_dune(
                verified_pools,
                target_token,
                from_block=from_block,
                to_block=to_block,
                chart_span=span,
                output_dir=out,
            )
        except Exception as exc:
            print(f"  [metrics] Dune volume aggregate failed ({exc}); using local swaps")
            volume = {}
    if not volume.get("volume_timeline"):
        volume = calculate_volume_metrics(
            events_all,
            verified_pools,
            target_token,
            token_decimals,
            bucket_seconds=bucket_seconds,
        )
        volume["chart_span"] = span
        volume["bucket"] = bucket
        volume["source"] = volume.get("source") or "local_swaps_fallback"
    volume_artifact = _write_volume_timeline_artifacts(
        out, volume, artifact_mode
    )

    wallet_activity = calculate_wallet_activity(
        events_all,
        verified_pools,
        target_token,
        token_decimals,
        timeline=timeline,
    )

    metrics = {
        "pool_concentration": pool_conc,
        "lp_concentration": lp_conc,
        "withdrawal_severity": withdrawal_sev,
        "volume": volume,
        "wallet_activity": wallet_activity,
        "tvl_timeline_length": len(timeline),
        "tvl_timeline": timeline,
        "tvl_timeline_source": tvl_source,
        "chart_span": span,
        "chart_bucket": bucket,
        "chart_bucket_seconds": bucket_seconds,
        "artifact_format": artifact_mode,
        "artifacts": {
            "tvl_timeline": tvl_artifact,
            "volume_timeline": volume_artifact,
        },
    }
    metrics_document = metrics
    if artifact_mode == "both":
        metrics_document = dict(metrics)
        metrics_document["tvl_timeline"] = []
        volume_document = dict(volume)
        volume_document["volume_timeline"] = []
        metrics_document["volume"] = volume_document
    _write_json(out / "metrics.json", metrics_document)

    return metrics


def _write_volume_timeline_artifacts(
    out: Path,
    volume: dict[str, Any],
    artifact_mode: str,
) -> dict[str, Any]:
    """Preserve nested volume JSON and optionally add its flat Parquet table."""
    rows = flatten_volume_timeline(volume)
    artifact: dict[str, Any] = {
        "name": "volume_timeline",
        "format": artifact_mode,
        "rows": len(rows),
        "paths": {"json": str(out / "volume_timeline.json")},
    }
    if artifact_mode == "both":
        parquet_artifact = write_table(
            "volume_timeline", rows, out, artifact_format="parquet"
        )
        artifact["paths"].update(parquet_artifact["paths"])
    volume["artifact_format"] = artifact_mode
    volume["artifacts"] = {"volume_timeline": artifact}
    _write_json(out / "volume_timeline.json", volume)
    return artifact


def _write_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
