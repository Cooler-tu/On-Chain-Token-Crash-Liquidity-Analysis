import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

from src.analysis.series import (
    build_analysis_series,
    write_analysis_series_human_outputs,
)
from src.data.artifacts import read_table, write_table
from src.models import VerifiedPool


HAS_PYARROW = importlib.util.find_spec("pyarrow") is not None
TARGET = "0x00000000000000000000000000000000000000aa"
QUOTE = "0x00000000000000000000000000000000000000bb"
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
POOL_A = "0x0000000000000000000000000000000000000101"
POOL_B = "0x0000000000000000000000000000000000000202"
BASE = (1_700_000_000 // 3_600) * 3_600


def _pool(address: str) -> VerifiedPool:
    return VerifiedPool(
        chain_id=1,
        protocol="uniswap",
        version="v3",
        architecture="direct_pool",
        factory_address="0x0000000000000000000000000000000000000000",
        pool_address=address,
        custody_address=address,
        token0=TARGET,
        token1=QUOTE,
        verified=True,
    )


def _swap(
    pool: str,
    *,
    timestamp: int,
    block: int,
    target_amount: int,
    amount_usd: float,
    actor: str = "0x0000000000000000000000000000000000000abc",
) -> dict:
    return {
        "event_type": "SWAP",
        "block_number": block,
        "log_index": block,
        "block_timestamp": timestamp,
        "pool_address": pool,
        "token0_address": TARGET,
        "token1_address": QUOTE,
        "token0_amount": str(target_amount),
        "token1_amount": "0",
        "amount_usd": amount_usd,
        "actor": actor,
    }


def _tvl(pool: str, *, timestamp: int, block: int, amount: int) -> dict:
    return {
        "block_timestamp": timestamp,
        "block_number": block,
        "log_index": block,
        "pool_address": pool,
        "tvl_in_token": str(amount),
        "tvl_usd": float(amount) * 2,
        "snapshot_block": block,
    }


def _rows(**kwargs):
    return build_analysis_series(
        kwargs.get("swaps", []),
        kwargs.get("liquidity", []),
        kwargs.get("tvl", []),
        kwargs.get("pools", [_pool(POOL_A)]),
        TARGET,
        0,
        token_symbol="TEST",
        bucket_seconds=3_600,
        tvl_source="snapshot_test",
    )


def _one(rows, *, scope: str, bucket: int, pool: str | None = None):
    matches = [
        row for row in rows
        if row["scope"] == scope
        and row["bucket_start"] == bucket
        and (pool is None or row["pool_identifier"] == pool.lower())
    ]
    if len(matches) != 1:
        raise AssertionError("expected one row, got {}".format(matches))
    return matches[0]


class AnalysisSeriesTest(unittest.TestCase):
    def test_price_ohlc_and_vwap_use_target_token_volume(self):
        swaps = [
            _swap(POOL_A, timestamp=BASE + 10, block=1, target_amount=10, amount_usd=10),
            _swap(POOL_A, timestamp=BASE + 20, block=2, target_amount=10, amount_usd=20),
            _swap(POOL_A, timestamp=BASE + 30, block=3, target_amount=80, amount_usd=240),
        ]
        rows = _rows(swaps=swaps, tvl=[_tvl(POOL_A, timestamp=BASE + 5, block=1, amount=100)])
        row = _one(rows, scope="pool", bucket=BASE, pool=POOL_A)

        self.assertEqual(row["price_open"], 1.0)
        self.assertEqual(row["price_high"], 3.0)
        self.assertEqual(row["price_low"], 1.0)
        self.assertEqual(row["price_close"], 3.0)
        self.assertAlmostEqual(row["price_vwap"], 2.7)
        self.assertEqual(row["volume_token"], 100.0)
        self.assertEqual(row["volume_usd"], 270.0)
        self.assertEqual(row["swap_count"], 3)

    def test_tvl_uses_last_pool_observation_not_sum(self):
        pools = [_pool(POOL_A), _pool(POOL_B)]
        tvl = [
            _tvl(POOL_A, timestamp=BASE + 5, block=1, amount=100),
            _tvl(POOL_A, timestamp=BASE + 25, block=3, amount=150),
            _tvl(POOL_B, timestamp=BASE + 15, block=2, amount=200),
        ]
        rows = _rows(tvl=tvl, pools=pools)

        pool_a = _one(rows, scope="pool", bucket=BASE, pool=POOL_A)
        total = _one(rows, scope="token_total", bucket=BASE)
        self.assertEqual(pool_a["tvl_token_close"], 150.0)
        self.assertEqual(pool_a["tvl_snapshot_block"], 3)
        self.assertEqual(total["tvl_token_close"], 350.0)
        self.assertEqual(total["tvl_snapshot_block"], 3)
        self.assertEqual(total["measured_pool_count"], 2)

    def test_swap_without_usd_does_not_create_price_or_vwap(self):
        swap = _swap(
            POOL_A,
            timestamp=BASE + 10,
            block=1,
            target_amount=10,
            amount_usd=0,
        )
        rows = _rows(swaps=[swap])
        row = _one(rows, scope="pool", bucket=BASE, pool=POOL_A)

        self.assertEqual(row["swap_count"], 1)
        self.assertEqual(row["volume_token"], 10.0)
        self.assertIsNone(row["volume_usd"])
        self.assertEqual(row["price_trade_count"], 0)
        self.assertIsNone(row["price_close"])
        self.assertIsNone(row["price_vwap"])

    def test_rpc_swap_uses_known_quote_ratio_when_usd_is_missing(self):
        pool = _pool(POOL_A)
        pool.token1 = WETH
        swap = _swap(
            POOL_A,
            timestamp=BASE + 10,
            block=1,
            target_amount=1,
            amount_usd=0,
        )
        swap["token1_address"] = WETH
        swap["token1_amount"] = str(2 * 10**18)

        rows = _rows(swaps=[swap], pools=[pool])
        row = _one(rows, scope="pool", bucket=BASE, pool=POOL_A)

        self.assertEqual(row["price_close"], 2.0)
        self.assertEqual(row["price_vwap"], 2.0)
        self.assertEqual(row["price_unit"], "WETH")
        self.assertEqual(row["price_source"], "pool_swap_ratio")
        self.assertIsNone(row["volume_usd"])

    def test_ambiguous_pool_swap_still_contributes_to_token_total(self):
        pool_a = _pool(POOL_A)
        pool_b = _pool(POOL_B)
        shared_custody = "0x0000000000000000000000000000000000000999"
        pool_a.custody_address = shared_custody
        pool_b.custody_address = shared_custody
        swap = _swap(
            shared_custody,
            timestamp=BASE + 10,
            block=1,
            target_amount=10,
            amount_usd=20,
        )

        rows = _rows(swaps=[swap], pools=[pool_a, pool_b])
        total = _one(rows, scope="token_total", bucket=BASE)

        self.assertEqual(total["volume_token"], 10.0)
        self.assertEqual(total["price_close"], 2.0)
        self.assertEqual(total["swap_count"], 1)
        self.assertFalse(any(row["scope"] == "pool" for row in rows))

    def test_empty_trade_bucket_carries_close_but_not_vwap(self):
        swaps = [
            _swap(POOL_A, timestamp=BASE + 10, block=1, target_amount=10, amount_usd=20),
        ]
        tvl = [
            _tvl(POOL_A, timestamp=BASE + 5, block=1, amount=100),
            _tvl(POOL_A, timestamp=BASE + 3_605, block=2, amount=110),
        ]
        rows = _rows(swaps=swaps, tvl=tvl)
        second = _one(rows, scope="pool", bucket=BASE + 3_600, pool=POOL_A)

        self.assertEqual(second["price_close"], 2.0)
        self.assertIsNone(second["price_vwap"])
        self.assertEqual(second["price_trade_count"], 0)
        self.assertTrue(second["price_is_carried_forward"])
        self.assertTrue(second["is_imputed"])
        self.assertGreater(second["price_staleness_seconds"], 3_600)

    def test_unknown_v4_style_removal_amount_stays_missing(self):
        liquidity = [{
            "event_type": "LIQUIDITY_REMOVE",
            "block_timestamp": BASE + 50,
            "block_number": 4,
            "pool_address": POOL_A,
            "token0_amount": "0",
            "token1_amount": "0",
            "liquidity_delta": "-100",
            "source_event": "ModifyLiquidity",
            "version": "v4",
            "amounts_available": False,
            "quantification_status": "liquidity_delta_only",
            "event_count": 2,
        }]
        rows = _rows(liquidity=liquidity)
        row = _one(rows, scope="pool", bucket=BASE, pool=POOL_A)

        self.assertEqual(row["lp_remove_event_count"], 2)
        self.assertIsNone(row["liquidity_removed_token"])
        self.assertIsNone(row["net_lp_flow_token"])
        self.assertEqual(row["withdrawal_amount_coverage"], 0.0)
        self.assertIsNone(row["active_lp_count"])

    def test_derived_features_use_prior_bucket_state(self):
        swaps = [
            _swap(POOL_A, timestamp=BASE + 10, block=1, target_amount=10, amount_usd=20),
            _swap(POOL_A, timestamp=BASE + 3_610, block=2, target_amount=20, amount_usd=60),
        ]
        tvl = [
            _tvl(POOL_A, timestamp=BASE + 5, block=1, amount=100),
            _tvl(POOL_A, timestamp=BASE + 3_605, block=2, amount=110),
        ]
        rows = _rows(swaps=swaps, tvl=tvl)
        second = _one(rows, scope="pool", bucket=BASE + 3_600, pool=POOL_A)

        self.assertAlmostEqual(second["price_return"], math.log(3 / 2))
        self.assertAlmostEqual(second["tvl_change"], math.log(110 / 100))
        self.assertAlmostEqual(second["volume_turnover"], 0.2)

    def test_human_outputs_preview_token_total_and_warn_on_proxy_tvl(self):
        rows = _rows(
            swaps=[_swap(POOL_A, timestamp=BASE + 10, block=1, target_amount=10, amount_usd=20)],
            tvl=[_tvl(POOL_A, timestamp=BASE + 5, block=1, amount=100)],
        )
        for row in rows:
            row["tvl_source"] = "event_accumulate_fallback"
        with tempfile.TemporaryDirectory() as tmp:
            outputs = write_analysis_series_human_outputs(rows, tmp)
            csv_text = Path(outputs["csv_preview"]).read_text()
            summary = Path(outputs["summary_md"]).read_text()

            self.assertEqual(outputs["preview_rows"], 1)
            self.assertEqual(len(csv_text.strip().splitlines()), 2)
            self.assertIn("price_vwap", csv_text.splitlines()[0])
            self.assertIn("event-reconstructed proxy", summary)
            self.assertIn("Token-total buckets | 1", summary)

    @unittest.skipUnless(HAS_PYARROW, "PyArrow is optional")
    def test_analysis_series_parquet_round_trip(self):
        rows = _rows(
            swaps=[_swap(POOL_A, timestamp=BASE + 10, block=1, target_amount=10, amount_usd=20)],
            tvl=[_tvl(POOL_A, timestamp=BASE + 5, block=1, amount=100)],
        )
        with tempfile.TemporaryDirectory() as tmp:
            meta = write_table("analysis_series", rows, tmp, "parquet")
            self.assertTrue(Path(meta["paths"]["parquet"]).exists())
            loaded = read_table("analysis_series", tmp, legacy_rows=True)
            self.assertEqual(len(loaded), len(rows))
            self.assertEqual(loaded[0]["bucket_start"], rows[0]["bucket_start"])
            self.assertEqual(loaded[0]["price_vwap"], rows[0]["price_vwap"])


if __name__ == "__main__":
    unittest.main()
