"""Focused tests for withdrawal normalization and USD wallet activity."""
from __future__ import annotations

import unittest

from src.models import VerifiedPool
from src.analysis.metrics import (
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


if __name__ == "__main__":
    unittest.main()
