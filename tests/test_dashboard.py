"""Focused tests for TVL chart click-detail data."""
from __future__ import annotations

import unittest

from src.analysis.dashboard import (
    _build_tvl_chart_js,
    _build_tvl_details_data,
    _find_volume_bucket,
)


class TvlClickDetailsTest(unittest.TestCase):
    def setUp(self):
        self.tvl = [
            {
                "block_number": 100,
                "block_timestamp": 1000000000,
                "pool_address": "0xAa",
                "protocol": "uniswap",
                "version": "v4",
                "tvl_in_token": "1000000000000000000",
                "price_usd": 1.5,
            },
            {
                "block_number": 100,
                "block_timestamp": 1000000005,
                "pool_address": "0xAa",
                "protocol": "uniswap",
                "version": "v4",
                "tvl_in_token": "2000000000000000000",
                "price_usd": 1.6,
            },
            {
                "block_number": 100,
                "block_timestamp": 1000000001,
                "pool_address": "0xBb",
                "protocol": "uniswap",
                "version": "v3",
                "tvl_in_token": "3000000000000000000",
                "price_usd": 0.9,
            },
            {
                "block_number": 101,
                "block_timestamp": 1000003600,
                "pool_address": "0xAa",
                "protocol": "uniswap",
                "version": "v4",
                "tvl_in_token": "4000000000000000000",
                "price_usd": 1.7,
            },
        ]
        self.volume = {
            "bucket_seconds": 3600,
            "volume_timeline": [
                {
                    "bucket_ts": 1000000000,
                    "pools": {
                        "0xaa": {"volume_in_token": 5.0, "volume_usd": 8.0},
                        "0xbb": {"volume_in_token": 2.0, "volume_usd": 1.8},
                    },
                },
                {
                    "bucket_ts": 1000003600,
                    "pools": {"0xaa": {"volume_in_token": 7.0, "volume_usd": 11.9}},
                },
            ],
        }

    def test_details_use_last_tvl_per_pool_per_block(self):
        details = _build_tvl_details_data(self.tvl, self.volume, token_decimals=18)
        self.assertEqual(len(details), 2)

        block_100 = details[0]
        by_pool = {p["address"]: p for p in block_100["pools"]}
        self.assertEqual(by_pool["0xAa"]["tvl"], 2.0)
        self.assertEqual(by_pool["0xBb"]["tvl"], 3.0)
        self.assertEqual(block_100["total_tvl"], 5.0)
        self.assertEqual(by_pool["0xAa"]["share_pct"], 40.0)
        self.assertEqual(by_pool["0xBb"]["share_pct"], 60.0)
        self.assertEqual(by_pool["0xAa"]["volume_token"], 5.0)
        self.assertEqual(by_pool["0xAa"]["volume_usd"], 8.0)

    def test_volume_bucket_matches_block_timestamp(self):
        details = _build_tvl_details_data(self.tvl, self.volume, token_decimals=18)
        self.assertEqual(details[0]["volume_bucket_label"], "2001-09-09 01:46 UTC")
        self.assertEqual(details[1]["volume_bucket_label"], "2001-09-09 02:46 UTC")
        self.assertEqual(details[1]["pools"][0]["volume_token"], 7.0)

    def test_find_volume_bucket_falls_back_to_nearest_earlier(self):
        bucket = _find_volume_bucket(self.volume["volume_timeline"], 3600, 1000003700)
        self.assertEqual(bucket["bucket_ts"], 1000003600)

    def test_chart_js_wires_click_handler(self):
        js = _build_tvl_chart_js(self.tvl, token_decimals=18, symbol="TST")
        self.assertIn("getElementsAtEventForMode", js)
        self.assertIn("renderTvlDetails(active[0].index)", js)


if __name__ == "__main__":
    unittest.main()
