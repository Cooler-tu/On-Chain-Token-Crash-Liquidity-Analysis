"""Uniswap V3 math: convert position L + ticks + price → token amounts.

Uses the same relations as periphery ``LiquidityAmounts.getAmountsForLiquidity``.
Tick → sqrtPrice uses high-precision ``1.0001**tick`` (analysis-grade; not a
bit-exact TickMath port).
"""
from __future__ import annotations

from decimal import Decimal, getcontext

Q96 = 2**96
MIN_TICK = -887272
MAX_TICK = 887272

getcontext().prec = 80


def tick_to_sqrt_price_x96(tick: int) -> int:
    """sqrtPriceX96 = sqrt(1.0001**tick) * 2**96."""
    if tick < MIN_TICK or tick > MAX_TICK:
        raise ValueError("tick out of range: {}".format(tick))
    price = Decimal("1.0001") ** int(tick)
    return int(price.sqrt() * (Decimal(2) ** 96))


def get_amount0_for_liquidity(sqrt_a: int, sqrt_b: int, liquidity: int) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    if sqrt_a <= 0 or sqrt_b <= 0 or liquidity <= 0:
        return 0
    # L * (sqrt_b - sqrt_a) / (sqrt_a * sqrt_b) * 2^96
    return liquidity * (sqrt_b - sqrt_a) * Q96 // (sqrt_a * sqrt_b)


def get_amount1_for_liquidity(sqrt_a: int, sqrt_b: int, liquidity: int) -> int:
    if sqrt_a > sqrt_b:
        sqrt_a, sqrt_b = sqrt_b, sqrt_a
    if liquidity <= 0:
        return 0
    # L * (sqrt_b - sqrt_a) / 2^96
    return liquidity * (sqrt_b - sqrt_a) // Q96


def get_amounts_for_liquidity(
    sqrt_price_x96: int,
    tick_lower: int,
    tick_upper: int,
    liquidity: int,
) -> tuple[int, int]:
    """Return raw (amount0, amount1) for a position at the given pool price."""
    if liquidity <= 0 or tick_lower >= tick_upper:
        return 0, 0

    sqrt_a = tick_to_sqrt_price_x96(tick_lower)
    sqrt_b = tick_to_sqrt_price_x96(tick_upper)
    sqrt_p = int(sqrt_price_x96)

    if sqrt_p <= sqrt_a:
        return get_amount0_for_liquidity(sqrt_a, sqrt_b, liquidity), 0
    if sqrt_p < sqrt_b:
        return (
            get_amount0_for_liquidity(sqrt_p, sqrt_b, liquidity),
            get_amount1_for_liquidity(sqrt_a, sqrt_p, liquidity),
        )
    return 0, get_amount1_for_liquidity(sqrt_a, sqrt_b, liquidity)


def value_in_token1_raw(amount0: int, amount1: int, sqrt_price_x96: int) -> float:
    """Value both sides in raw token1 units (token1 per token0 from sqrtPrice)."""
    if sqrt_price_x96 <= 0:
        return float(amount1)
    price_1_per_0 = (float(sqrt_price_x96) / float(Q96)) ** 2
    return float(amount1) + float(amount0) * price_1_per_0
