"""Focused tests for TVL chart click-detail data."""
from __future__ import annotations

import unittest

import src.analysis.dashboard as dashboard
from src.analysis.dashboard import (
    _build_price_chart_config,
    _build_tvl_chart_config,
    _build_tvl_chart_js,
    _build_tvl_details_data,
    _find_volume_bucket,
    _holder_semantics,
    _identifier_html,
    _pool_liquidity_presentation,
    _pool_reserve_section,
    _rank_non_pool_holders,
    _table_withdrawals,
    _table_pool_ident,
    _table_large_wallets,
    _tvl_method_presentation,
    _withdrawal_quantification_note,
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

    def test_many_pool_series_use_more_colors_and_line_patterns(self):
        timeline = []
        for index in range(10):
            timeline.append({
                "block_number": 100,
                "pool_address": "0x{:040x}".format(index + 1),
                "tvl_in_token": str((index + 1) * 10**18),
                "price_usd": 1 + index / 100,
            })

        tvl_config = _build_tvl_chart_config(timeline, token_decimals=18, symbol="TST")
        pool_series = tvl_config["data"]["datasets"][1:]
        self.assertEqual(len({d["borderColor"] for d in pool_series}), 10)
        self.assertGreater(len({tuple(d["borderDash"]) for d in pool_series}), 1)

        price_config = _build_price_chart_config(timeline, symbol="TST")
        price_series = price_config["data"]["datasets"]
        self.assertEqual(len({d["borderColor"] for d in price_series}), 10)
        self.assertGreater(len({tuple(d["borderDash"]) for d in price_series}), 1)


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
        self.assertIn("Positive end balances, ranked highest to lowest", template)
        self.assertIn("Top {top_chart_holder_count} Non-Pool Holders", template)
        self.assertIn("Top {top_table_holder_count} Non-Pool Holders by End Balance", template)

    def test_dex_custody_reserves_use_explained_pie_chart(self):
        dashboard._load_templates()
        script = dashboard._JS_TEMPLATE or ""
        section = _pool_reserve_section([{"balance_decimal": 1}], "TST")

        self.assertIn("const poolReserveRows", script)
        self.assertIn("tc('c7'", script)
        self.assertIn("type:'pie'", script)
        self.assertIn("Click slice to copy full address", script)
        self.assertIn("DEX Custody Token Reserve Distribution", section)
        self.assertIn("This is not LP count or full USD TVL", section)
        self.assertIn("V4 PoolManager address is shared custody", section)
        self.assertEqual(_pool_reserve_section([], "TST"), "")


class DashboardMetricSemanticsTest(unittest.TestCase):
    def test_withdrawal_table_distinguishes_unquantified_from_real_zero(self):
        metrics = {
            "withdrawal_severity": {
                "num_withdrawals": 6,
                "quantified_withdrawals": 1,
                "liquidity_delta_only_withdrawals": 5,
                "unmapped_withdrawals": 0,
                "withdrawal_events": [
                    {
                        "block_number": 101,
                        "pool_address": "0x" + "ab" * 32,
                        "protocol": "uniswap",
                        "version": "v4",
                        "liquidity_delta": "-779119453124748",
                        "event_count": 5,
                        "aggregation_scope": "pool_block",
                        "quantification_status": "liquidity_delta_only",
                        "removed_target_decimal": None,
                    },
                    {
                        "block_number": 100,
                        "pool_address": "0x" + "11" * 20,
                        "protocol": "uniswap",
                        "version": "v3",
                        "liquidity_delta": "0",
                        "event_count": 1,
                        "quantification_status": "quantified",
                        "removed_target_decimal": 0.0,
                    },
                ],
            }
        }

        rendered = _table_withdrawals(metrics, 18, "TST")
        note = _withdrawal_quantification_note(metrics)

        self.assertIn("Token amount not returned", rendered)
        self.assertIn("Cannot calculate", rendered)
        self.assertIn("-779,119,453,124,748", rendered)
        self.assertIn("0.0000 TST", rendered)
        self.assertIn("uniswap v4", rendered)
        self.assertIn("6 removal actions detected", note)
        self.assertIn("Amount known: 1 · Amount missing: 5", note)
        self.assertIn("missing data—not a zero withdrawal", note)

    def test_non_pool_holder_ranking_is_positive_descending_and_limited(self):
        rows = [
            {"address": "low", "balance_raw": "5", "balance_decimal": 5, "is_pool": False},
            {"address": "pool", "balance_raw": "999", "balance_decimal": 999, "is_pool": True},
            {"address": "uncovered", "balance_raw": "500", "balance_decimal": 500, "is_pool": False, "balance_source": "zero_fill"},
            {"address": "zero", "balance_raw": "0", "balance_decimal": 0, "is_pool": False},
            {"address": "high", "balance_raw": "20", "balance_decimal": 20, "is_pool": False},
            {"address": "mid", "balance_raw": "10", "balance_decimal": 10, "is_pool": False},
        ]

        ranked = _rank_non_pool_holders(rows, limit=2)

        self.assertEqual([row["address"] for row in ranked], ["high", "mid"])

    def test_pool_liquidity_share_discloses_partial_coverage(self):
        pools = [
            {
                "pool_address": "0x" + "11" * 20,
                "protocol": "uniswap",
                "version": "v3",
                "token0": "0x" + "33" * 20,
                "token1": "0x" + "44" * 20,
            },
            {
                "pool_address": "0x" + "22" * 32,
                "protocol": "uniswap",
                "version": "v4",
                "token0": "0x" + "33" * 20,
                "token1": "0x" + "44" * 20,
            },
        ]
        metrics = {
            "pool_concentration": {
                "source": "onchain",
                "snapshot_block": 123456,
                "total_tvl": 100 * 10**18,
                "per_pool_tvl": {pools[0]["pool_address"]: 100 * 10**18},
            },
            "volume": {},
        }

        presentation = _pool_liquidity_presentation(pools, metrics)
        rendered = _table_pool_ident(pools, metrics, symbol="TST")

        self.assertIn("1 of 2 verified pools measured (50.0%)", presentation["coverage_title"])
        self.assertEqual(presentation["share_header"], "Share Among Measured Pools (1/2)")
        self.assertIn("1 V4 pool is not included", presentation["comparison_note"])
        self.assertIn("Block 123,456", presentation["method_note"])
        self.assertIn("100.0%", rendered)
        self.assertIn("of measured liquidity", rendered)
        self.assertIn("Not measured", rendered)
        self.assertNotIn('<span class="measured-share">0.0%', rendered)

    def test_notable_wallet_table_uses_adaptive_labels_and_volume_share(self):
        metrics = {
            "wallet_activity": {
                "adaptive_percentile_label": "P99",
                "threshold_modes": {
                    "trade": "percentile",
                    "mover": "percentile",
                    "activity": "percentile",
                    "volume": "percentile",
                },
                "wallets": [{
                    "address": "0x44b28991b167582f18ba0259e0173176ca125505",
                    "max_single_usd": 2000,
                    "bought_usd": 3000,
                    "sold_usd": 1000,
                    "net_usd": 2000,
                    "total_usd": 4000,
                    "volume_share_pct": 1.25,
                    "swap_count": 12,
                    "large_trade": True,
                    "large_mover": True,
                    "high_activity": True,
                    "market_share": True,
                    "notable": True,
                }],
            }
        }

        rendered = _table_large_wallets(metrics, "TST")

        self.assertIn("Trade P99", rendered)
        self.assertIn("Mover P99", rendered)
        self.assertIn("Activity P99", rendered)
        self.assertIn("Volume P99", rendered)
        self.assertIn("1.250%", rendered)

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
