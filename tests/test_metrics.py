"""Focused tests for withdrawal normalization and USD wallet activity."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from src.models import VerifiedPool
from src.analysis.metrics import (
    build_tvl_timeline_rpc_snapshots,
    calculate_price_timeline_from_swaps,
    calculate_volume_metrics,
    calculate_wallet_activity,
    calculate_withdrawal_severity,
)


TARGET = "0x44b28991B167582F18BA0259e0173176ca125505"
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
ROUTER = "0x66a9893cC07D91D95644CFDCE5591279A7DD6748"


def _pool() -> VerifiedPool:
    return VerifiedPool(
        chain_id=1,
        protocol="uniswap",
        version="v3",
        architecture="direct_pool",
        factory_address="0x0000000000000000000000000000000000000000",
        pool_address="0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775",
        custody_address="0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775",
        router_addresses=[ROUTER],
        token0=TARGET,
        token1=WETH,
        verified=True,
    )


def _v4_pool() -> VerifiedPool:
    return VerifiedPool(
        chain_id=1,
        protocol="uniswap",
        version="v4",
        architecture="singleton_pool_manager",
        factory_address="0x0000000000000000000000000000000000000000",
        pool_address="0x" + "ab" * 32,
        custody_address="0x000000000004444c5dc75cB358380D2e3dE08A90",
        token0=TARGET,
        token1=WETH,
        verified=True,
    )


def _second_v4_pool() -> VerifiedPool:
    pool = _v4_pool()
    pool.pool_address = "0x" + "cd" * 32
    return pool


class WithdrawalNormalizationTest(unittest.TestCase):
    def test_removed_target_is_not_token0_plus_token1(self):
        pool = _pool()
        events = [
            {
                "event_type": "LIQUIDITY_REMOVE",
                "block_number": 5,
                "block_timestamp": 100,
                "pool_address": pool.pool_address,
                "actor": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
                "token0_amount": "2000000000000000000",
                "token1_amount": "1000000000000000000",
            }
        ]
        timeline = [{
            "pool_address": pool.pool_address,
            "block_number": 5,
            "price_usd": 2.0,
        }]
        result = calculate_withdrawal_severity(
            events,
            pre_event_tvl=4000000000000000000,
            incident_block=0,
            verified_pools=[pool],
            target_token=TARGET,
            token_decimals=18,
            tvl_by_pool={pool.pool_address: 4000000000000000000},
            timeline=timeline,
        )
        self.assertEqual(result["total_removed_target_raw"], 2000000000000000000)
        self.assertEqual(result["legacy_total_removed_token0"], 3000000000000000000)
        self.assertEqual(result["total_removed_target_decimal"], 2.0)
        self.assertEqual(result["withdrawal_severity"], 0.5)
        self.assertEqual(result["per_pool_removals"][0]["removed_usd"], 4.0)

    def test_pool_block_aggregate_preserves_underlying_event_count(self):
        pool = _pool()
        events = [
            {
                "event_type": "LIQUIDITY_REMOVE",
                "block_number": 5,
                "block_timestamp": 100,
                "pool_address": pool.pool_address,
                "token0_amount": "2000000000000000000",
                "token1_amount": "1000000000000000000",
                "event_count": 3,
                "aggregation_scope": "pool_block",
            }
        ]
        result = calculate_withdrawal_severity(
            events,
            pre_event_tvl=4000000000000000000,
            incident_block=0,
            verified_pools=[pool],
            target_token=TARGET,
            token_decimals=18,
            tvl_by_pool={pool.pool_address: 4000000000000000000},
            timeline=[],
        )
        self.assertEqual(result["num_withdrawals"], 3)
        self.assertEqual(result["attributed_withdrawals"], 3)
        self.assertEqual(result["per_pool_removals"][0]["num_withdrawals"], 3)
        self.assertEqual(result["withdrawal_events"][0]["aggregation_scope"], "pool_block")

    def test_v4_liquidity_delta_is_not_misreported_as_zero_amount(self):
        pool = _v4_pool()
        events = [{
            "event_type": "LIQUIDITY_REMOVE",
            "block_number": 5,
            "block_timestamp": 100,
            "pool_address": pool.pool_address,
            "protocol": "uniswap",
            "version": "v4",
            "source_event": "ModifyLiquidity",
            "token0_amount": "0",
            "token1_amount": "0",
            "liquidity_delta": "-779119453124748",
            "event_count": 5,
            "aggregation_scope": "pool_block",
            "amounts_available": False,
            "quantification_status": "liquidity_delta_only",
        }]

        result = calculate_withdrawal_severity(
            events,
            pre_event_tvl=0,
            incident_block=0,
            verified_pools=[pool],
            target_token=TARGET,
            token_decimals=18,
        )

        self.assertEqual(result["num_withdrawals"], 5)
        self.assertEqual(result["quantified_withdrawals"], 0)
        self.assertEqual(result["liquidity_delta_only_withdrawals"], 5)
        row = result["withdrawal_events"][0]
        self.assertIsNone(row["removed_target_decimal"])
        self.assertEqual(row["liquidity_delta"], "-779119453124748")
        self.assertEqual(row["protocol"], "uniswap")
        self.assertEqual(row["version"], "v4")

    def test_quantified_zero_remains_a_real_zero(self):
        pool = _pool()
        result = calculate_withdrawal_severity(
            [{
                "event_type": "LIQUIDITY_REMOVE",
                "block_number": 5,
                "pool_address": pool.pool_address,
                "protocol": "uniswap",
                "version": "v3",
                "source_event": "Burn",
                "token0_amount": "0",
                "token1_amount": "0",
                "liquidity_delta": "0",
                "amounts_available": True,
                "quantification_status": "quantified",
            }],
            pre_event_tvl=0,
            incident_block=0,
            verified_pools=[pool],
            target_token=TARGET,
            token_decimals=18,
        )

        self.assertEqual(result["quantified_withdrawals"], 1)
        self.assertEqual(
            result["withdrawal_events"][0]["removed_target_decimal"], 0.0
        )


class WalletActivityTest(unittest.TestCase):
    def test_flags_large_wallet_and_excludes_router(self):
        pool = _pool()
        events = [
            {
                "event_type": "SWAP",
                "block_number": 10,
                "block_timestamp": 100,
                "pool_address": pool.pool_address,
                "actor": "0x4c82d1fbfe28c977cbb58d8c7ff8fcf9f70a2cca",
                "token0_address": TARGET,
                "token1_address": WETH,
                "token0_amount": "1000000000000000000",
                "token1_amount": "1000000000000000000",
                "amount_usd": 50000.0,
            },
            {
                "event_type": "SWAP",
                "block_number": 11,
                "block_timestamp": 101,
                "pool_address": pool.pool_address,
                "actor": ROUTER,
                "token0_address": TARGET,
                "token1_address": WETH,
                "token0_amount": "1000000000000000000",
                "token1_amount": "1000000000000000000",
                "amount_usd": 50000.0,
            },
        ]
        result = calculate_wallet_activity(
            events,
            [pool],
            TARGET,
            18,
            min_large_trade_usd=10000.0,
            mover_net_usd=10000.0,
            min_activity_trades=50,
            volume_ratio=0.001,
        )
        wallet_addrs = [w["address"] for w in result["wallets"]]
        self.assertNotIn(ROUTER.lower(), wallet_addrs)
        wallet = next(
            w for w in result["wallets"]
            if w["address"] == "0x4c82d1fbfe28c977cbb58d8c7ff8fcf9f70a2cca"
        )
        self.assertTrue(wallet["large_trade"])
        self.assertTrue(wallet["large_mover"])
        self.assertFalse(wallet["high_activity"])
        self.assertTrue(wallet["notable"])
        self.assertEqual(result["num_large_trade_wallets"], 1)
        self.assertEqual(result["num_large_mover_wallets"], 1)
        self.assertEqual(result["num_notable_wallets"], 1)
        self.assertEqual(result["total_swap_volume_usd"], 100000.0)

    def test_adaptive_percentiles_scale_with_market_and_window_activity(self):
        pool = _pool()

        def build(scale: float) -> dict:
            events = []
            for idx in range(100):
                events.append({
                    "event_type": "SWAP",
                    "block_number": 10 + idx,
                    "block_timestamp": 100 + idx,
                    "pool_address": pool.pool_address,
                    "actor": "0x{:040x}".format(1000 + idx),
                    "token0_address": TARGET,
                    "token1_address": WETH,
                    "token0_amount": "1000000000000000000",
                    "token1_amount": "1000000000000000000",
                    "amount_usd": (100.0 + idx) * scale,
                })
            activity_actor = "0x{:040x}".format(9999)
            for idx in range(10):
                events.append({
                    "event_type": "SWAP",
                    "block_number": 1000 + idx,
                    "block_timestamp": 1000 + idx,
                    "pool_address": pool.pool_address,
                    "actor": activity_actor,
                    "token0_address": TARGET,
                    "token1_address": WETH,
                    "token0_amount": "1000000000000000000",
                    "token1_amount": "1000000000000000000",
                    "amount_usd": 1.0 * scale,
                })
            return calculate_wallet_activity(
                events, [pool], TARGET, 18, adaptive_percentile=0.99
            )

        small = build(1.0)
        large = build(1000.0)
        self.assertEqual(small["selection_mode"], "adaptive_percentile")
        self.assertEqual(small["adaptive_percentile_label"], "P99")
        self.assertEqual(small["activity_trade_threshold"], 10)
        self.assertLess(small["large_trade_threshold_usd"], 10_000.0)
        self.assertGreater(large["large_trade_threshold_usd"], 10_000.0)
        self.assertAlmostEqual(
            large["large_trade_threshold_usd"],
            small["large_trade_threshold_usd"] * 1000.0,
            places=2,
        )
        small_notable = {
            row["address"] for row in small["wallets"] if row["notable"]
        }
        large_notable = {
            row["address"] for row in large["wallets"] if row["notable"]
        }
        self.assertEqual(small_notable, large_notable)
        activity_wallet = next(
            row for row in small["wallets"]
            if row["address"] == "0x{:040x}".format(9999)
        )
        self.assertTrue(activity_wallet["high_activity"])
        self.assertFalse(activity_wallet["large_trade"])


class LocalSwapAggregatesTest(unittest.TestCase):
    def test_volume_sums_target_token_absolute_amounts(self):
        pool = _pool()
        events = [
            {
                "event_type": "SWAP",
                "block_number": 10,
                "block_timestamp": 1_700_000_000,
                "pool_address": pool.pool_address,
                "token0_address": TARGET,
                "token1_address": WETH,
                "token0_amount": "1000000000000000000",
                "token1_amount": "2000000000000000000",
                "amount_usd": 10.0,
            },
            {
                "event_type": "SWAP",
                "block_number": 11,
                "block_timestamp": 1_700_000_100,
                "pool_address": pool.pool_address,
                "token0_address": WETH,
                "token1_address": TARGET,
                "token0_amount": "500000000000000000",
                "token1_amount": "3000000000000000000",
                "amount_usd": 30.0,
            },
        ]
        result = calculate_volume_metrics(
            events, [pool], TARGET, 18, bucket_seconds=3600
        )
        self.assertEqual(result["total_volume_in_token"], 4.0)
        self.assertEqual(len(result["volume_timeline"]), 1)
        bucket = result["volume_timeline"][0]
        self.assertEqual(bucket["total_volume_in_token"], 4.0)
        self.assertEqual(bucket["pools"][pool.pool_address.lower()]["volume_usd"], 40.0)

    def test_price_uses_last_swap_in_bucket(self):
        pool = _pool()
        events = [
            {
                "event_type": "SWAP",
                "block_number": 10,
                "log_index": 1,
                "block_timestamp": 1_700_000_000,
                "pool_address": pool.pool_address,
                "token0_address": TARGET,
                "token1_address": WETH,
                "token0_amount": "1000000000000000000",
                "token1_amount": "1",
                "amount_usd": 2.0,
            },
            {
                "event_type": "SWAP",
                "block_number": 11,
                "log_index": 2,
                "block_timestamp": 1_700_000_100,
                "pool_address": pool.pool_address,
                "token0_address": TARGET,
                "token1_address": WETH,
                "token0_amount": "2000000000000000000",
                "token1_amount": "1",
                "amount_usd": 8.0,
            },
        ]
        rows = calculate_price_timeline_from_swaps(
            events, [pool], TARGET, 18, bucket_seconds=3600
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pool_address"], pool.pool_address.lower())
        self.assertEqual(rows[0]["price_usd"], 4.0)

    def test_same_pair_v4_swap_is_not_assigned_to_arbitrary_pool(self):
        pools = [_v4_pool(), _second_v4_pool()]
        event = {
            "event_type": "SWAP",
            "block_number": 10,
            "block_timestamp": 1_700_000_000,
            "pool_address": pools[0].custody_address,
            "token0_address": TARGET,
            "token1_address": WETH,
            "token0_amount": "1000000000000000000",
            "token1_amount": "2000000000000000000",
            "amount_usd": 10.0,
        }

        prices = calculate_price_timeline_from_swaps(
            [event], pools, TARGET, 18, bucket_seconds=3600
        )
        volume = calculate_volume_metrics(
            [event], pools, TARGET, 18, bucket_seconds=3600
        )

        self.assertEqual(prices, [])
        self.assertEqual(volume["total_volume_in_token"], 0)
        self.assertEqual(volume["ambiguous_events"], 1)

    def test_exact_pool_address_wins_even_when_token_pair_is_duplicated(self):
        direct = _pool()
        event = {
            "event_type": "SWAP",
            "block_number": 10,
            "log_index": 1,
            "block_timestamp": 1_700_000_000,
            "pool_address": direct.pool_address,
            "token0_address": TARGET,
            "token1_address": WETH,
            "token0_amount": "1000000000000000000",
            "token1_amount": "2000000000000000000",
            "amount_usd": 10.0,
        }

        rows = calculate_price_timeline_from_swaps(
            [event], [direct, _v4_pool()], TARGET, 18, bucket_seconds=3600
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pool_address"], direct.pool_address.lower())
        self.assertEqual(rows[0]["block_number"], 10)
        self.assertEqual(rows[0]["block_timestamp"], 1_700_000_000)

    def test_rpc_swap_price_falls_back_to_weth_quote(self):
        direct = _pool()
        event = {
            "event_type": "SWAP",
            "block_number": 10,
            "log_index": 1,
            "block_timestamp": 1_700_000_000,
            "pool_address": direct.pool_address,
            "token0_amount": "1000000000000000000",
            "token1_amount": "2000000000000000000",
            "amount_usd": None,
        }

        rows = calculate_price_timeline_from_swaps(
            [event], [direct], TARGET, 18, bucket_seconds=3600
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price"], 2.0)
        self.assertIsNone(rows[0]["price_usd"])
        self.assertEqual(rows[0]["price_unit"], "WETH")
        self.assertEqual(rows[0]["price_source"], "pool_swap_ratio")


class HistoricalRpcTvlTest(unittest.TestCase):
    def test_uses_bucket_block_and_excludes_shared_v4_custody(self):
        direct = _pool()
        v4_a = _v4_pool()
        v4_b = _second_v4_pool()

        class Call:
            def __init__(self, address):
                self.address = address

            def call(self, *, block_identifier):
                return block_identifier * 10**18

        class Functions:
            def balanceOf(self, address):
                return Call(address)

        class Token:
            functions = Functions()

        price_rows = [
            {
                "bucket_ts": 1_700_000_000 // 3600 * 3600,
                "block_number": 11,
                "block_timestamp": 1_700_000_100,
                "pool_address": direct.pool_address,
                "price_usd": 2.0,
            },
            {
                "bucket_ts": 1_700_000_000 // 3600 * 3600,
                "block_number": 11,
                "block_timestamp": 1_700_000_100,
                "pool_address": v4_a.pool_address,
                "price_usd": 9.0,
            },
        ]
        events = [
            {
                "block_number": 11,
                "log_index": 1,
                "block_timestamp": 1_700_000_100,
            },
            {
                "block_number": 20,
                "log_index": 2,
                "block_timestamp": 1_700_003_700,
            },
        ]

        with patch("src.analysis.metrics.get_contract", return_value=Token()):
            rows = build_tvl_timeline_rpc_snapshots(
                object(),
                [direct, v4_a, v4_b],
                TARGET,
                18,
                1,
                100,
                price_rows=price_rows,
                reference_events=events,
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["pool_address"] for row in rows}, {direct.pool_address}
        )
        self.assertEqual([row["snapshot_block"] for row in rows], [11, 20])
        self.assertEqual([row["tvl_in_token"] for row in rows], [
            str(11 * 10**18), str(20 * 10**18)
        ])
        self.assertEqual([row["tvl_usd"] for row in rows], [22.0, 40.0])


if __name__ == "__main__":
    unittest.main()
