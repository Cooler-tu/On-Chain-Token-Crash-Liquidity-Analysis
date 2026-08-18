"""Tests for signed swap/transfer reconciliation helpers."""
from __future__ import annotations

import unittest

from scripts.directional_swap_flow import (
    build_address_rows,
    build_signed_swap_rows,
    build_transaction_rows,
    build_transfer_rows,
    summarize,
)
from src.models import VerifiedPool


TARGET = "0x00000000000000000000000000000000000000aa"
QUOTE = "0x00000000000000000000000000000000000000bb"
POOL = "0x0000000000000000000000000000000000000101"
USER = "0x0000000000000000000000000000000000000abc"


class _Hash(str):
    def hex(self):
        return str(self).removeprefix("0x")


def _pool() -> VerifiedPool:
    return VerifiedPool(
        chain_id=1,
        protocol="uniswap",
        version="v3",
        architecture="concentrated_pool",
        factory_address="0x0000000000000000000000000000000000000000",
        pool_address=POOL,
        custody_address=POOL,
        token0=TARGET,
        token1=QUOTE,
        verified=True,
    )


def _swap(tx: str, log_index: int, amount0: int, amount1: int):
    return {
        "args": {
            "sender": USER,
            "recipient": USER,
            "amount0": amount0,
            "amount1": amount1,
            "sqrtPriceX96": 1,
            "liquidity": 2,
            "tick": 3,
        },
        "blockNumber": 10,
        "transactionHash": _Hash(tx),
        "logIndex": log_index,
    }


def _transfer(tx: str, log_index: int, sender: str, recipient: str, value: int):
    return {
        "args": {"from": sender, "to": recipient, "value": value},
        "blockNumber": 10,
        "transactionHash": _Hash(tx),
        "logIndex": log_index,
    }


class DirectionalSwapFlowTest(unittest.TestCase):
    def test_signed_direction_and_price(self):
        rows = build_signed_swap_rows(
            [_swap("0x01", 1, 5_000_000, -10_000_000)],
            pool=_pool(),
            target_token=TARGET,
            target_symbol="TEST",
            target_decimals=6,
            quote_symbol="QUOTE",
            quote_decimals=6,
            timestamps={10: 1_700_000_000},
            tx_from={"0x01": USER},
        )
        self.assertEqual(rows[0]["direction"], "SELL_TEST")
        self.assertEqual(rows[0]["target_amount_abs"], "5")
        self.assertEqual(rows[0]["price_quote_per_target"], "2")

    def test_transfer_rows_dedupe_and_sign_from_pool_perspective(self):
        inbound = [_transfer("0x01", 2, USER, POOL, 7_000_000)]
        outbound = [_transfer("0x02", 3, POOL, USER, 2_000_000)]
        rows = build_transfer_rows(
            inbound,
            outbound,
            pool_address=POOL,
            token_symbol="TEST",
            token_decimals=6,
            timestamps={10: 1_700_000_000},
            tx_from={"0x01": USER, "0x02": USER},
            swap_hashes={"0x01"},
        )
        self.assertEqual([row["pool_delta_signed"] for row in rows], ["7", "-2"])
        self.assertTrue(rows[0]["related_to_swap_tx"])
        self.assertFalse(rows[1]["related_to_swap_tx"])

    def test_summary_separates_swap_residual_and_exact_transfer_closure(self):
        swaps = build_signed_swap_rows(
            [
                _swap("0x01", 1, 5_000_000, -10_000_000),
                _swap("0x02", 2, -2_000_000, 5_000_000),
            ],
            pool=_pool(),
            target_token=TARGET,
            target_symbol="TEST",
            target_decimals=6,
            quote_symbol="QUOTE",
            quote_decimals=6,
            timestamps={10: 1_700_000_000},
            tx_from={"0x01": USER, "0x02": USER},
        )
        transfers = build_transfer_rows(
            [_transfer("0x01", 3, USER, POOL, 6_000_000)],
            [_transfer("0x02", 4, POOL, USER, 2_000_000)],
            pool_address=POOL,
            token_symbol="TEST",
            token_decimals=6,
            timestamps={10: 1_700_000_000},
            tx_from={"0x01": USER, "0x02": USER},
            swap_hashes={"0x01", "0x02"},
        )
        transactions = build_transaction_rows(swaps, transfers, token_decimals=6)
        addresses = build_address_rows(transactions)
        summary = summarize(
            swaps,
            transfers,
            transactions,
            addresses,
            token_symbol="TEST",
            token_decimals=6,
            start_balance_raw=10_000_000,
            end_balance_raw=14_000_000,
            start_balance_block=9,
            end_balance_block=10,
        )
        self.assertEqual(summary["sell_volume"], "5")
        self.assertEqual(summary["buy_volume"], "2")
        self.assertEqual(summary["net_swap_to_pool"], "3")
        self.assertEqual(summary["actual_transfer_net_to_pool"], "4")
        self.assertEqual(summary["transfer_minus_swap"], "1")
        self.assertEqual(summary["balance_minus_transfer"], "0")
        self.assertEqual(summary["transfer_balance_reconciliation"], "exact")


if __name__ == "__main__":
    unittest.main()
