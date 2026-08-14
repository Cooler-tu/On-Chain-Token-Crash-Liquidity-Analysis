"""Focused tests for TVL chart click-detail data."""
from __future__ import annotations

import unittest

import src.analysis.dashboard as dashboard
from src.analysis.dashboard import (
    _build_tvl_chart_js,
    _build_tvl_details_data,
    _find_volume_bucket,
    _holder_semantics,
    _identifier_html,
    _tvl_method_presentation,
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


class IdentifierUxTest(unittest.TestCase):
    def test_ethereum_address_is_copyable_and_links_to_etherscan(self):
        address = "0x44b28991B167582F18BA0259e0173176ca125505"
        rendered = _identifier_html(address, chain_id=1)

        self.assertIn('data-identifier="{}"'.format(address), rendered)
        self.assertIn("0x44b289...5505", rendered)
        self.assertIn("https://etherscan.io/address/{}".format(address), rendered)
        self.assertIn("copyIdentifier(event,this)", rendered)

    def test_bytes32_pool_id_is_copyable_without_address_link(self):
        pool_id = "0x" + "ab" * 32
        rendered = _identifier_html(pool_id, chain_id=1)

        self.assertIn('data-identifier="{}"'.format(pool_id), rendered)
        self.assertIn("0xababab...abab", rendered)
        self.assertNotIn("etherscan.io/address", rendered)

    def test_non_mainnet_address_does_not_get_mainnet_link(self):
        address = "0x44b28991B167582F18BA0259e0173176ca125505"
        rendered = _identifier_html(address, chain_id=8453)
        self.assertNotIn("etherscan.io/address", rendered)

    def test_dashboard_script_contains_tooltip_copy_and_fallback(self):
        dashboard._load_templates()
        script = dashboard._JS_TEMPLATE or ""

        self.assertIn("function showIdentifierTooltip", script)
        self.assertIn("async function copyIdentifier", script)
        self.assertIn("fallbackCopyIdentifier", script)
        self.assertIn("identifierHtml(p.address)", script)

    def test_top_holder_chart_reveals_and_copies_full_address(self):
        dashboard._load_templates()
        script = dashboard._JS_TEMPLATE or ""
        template = dashboard._HTML_TEMPLATE or ""

        self.assertIn("const topChartHolders = topH.slice(0, 10)", script)
        self.assertIn("return row && row.address ? row.address : '-'", script)
        self.assertIn("Click bar to copy full address", script)
        self.assertIn("copyIdentifierValue(event.native || event, row.address)", script)
        self.assertIn("event.native.target.style.cursor", script)
        self.assertIn("Hover for the full address and balance", template)


class DashboardMetricSemanticsTest(unittest.TestCase):
    def test_holder_counts_exclude_pools_zero_balances_and_zero_fill(self):
        rows = [
            {
                "balance_raw": "10",
                "balance_source": "rpc",
                "is_pool": False,
            },
            {
                "balance_raw": "0",
                "balance_source": "rpc",
                "is_pool": False,
            },
            {
                "balance_raw": "99",
                "balance_source": "zero_fill",
                "is_pool": False,
            },
            {
                "balance_raw": "5",
                "balance_source": "rpc",
                "is_pool": True,
            },
        ]

        result = _holder_semantics(rows)

        self.assertEqual(result["total_count"], 4)
        self.assertEqual(result["covered_count"], 3)
        self.assertEqual(result["zero_fill_count"], 1)
        self.assertEqual(result["positive_non_pool_count"], 1)
        self.assertEqual(result["positive_pool_count"], 1)

    def test_event_fallback_is_never_described_as_snapshot(self):
        result = _tvl_method_presentation("event_accumulate_fallback", [{}])

        self.assertEqual(result["kind"], "reconstructed")
        self.assertIn("snapshot query failed", result["note"].lower())
        self.assertIn("not an on-chain balance snapshot", result["note"])
        self.assertIn("Event reconstructed", result["badge_html"])

    def test_balance_source_gets_snapshot_description(self):
        result = _tvl_method_presentation("dune_balance_local_price", [{}])

        self.assertEqual(result["kind"], "snapshot")
        self.assertIn("pool token balance snapshots", result["note"])
        self.assertIn("local swap-derived prices", result["note"])
        self.assertIn("Balance snapshot", result["badge_html"])

    def test_legacy_rows_can_infer_balance_snapshot_lineage(self):
        result = _tvl_method_presentation(
            None, [{"source_event": "balance_x_price"}]
        )
        self.assertEqual(result["kind"], "snapshot")


if __name__ == "__main__":
    unittest.main()
