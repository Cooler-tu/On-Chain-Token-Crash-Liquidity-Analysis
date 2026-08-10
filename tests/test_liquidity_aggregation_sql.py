"""Dune liquidity indexing must not download individual LP identities."""
from __future__ import annotations

import unittest

from src.data.dune import _load_sections


class LiquidityAggregationSqlTest(unittest.TestCase):
    def test_v2_v3_sections_are_pool_block_aggregates_without_actors(self):
        sections = _load_sections()
        for name in (
            "liquidity_uniswap_v2_mint",
            "liquidity_uniswap_v2_burn",
            "liquidity_uniswap_v3_mint",
            "liquidity_uniswap_v3_burn",
        ):
            sql = sections[name].lower()
            self.assertIn("group by evt_block_number, contract_address", sql)
            self.assertIn("count(*) as event_count", sql)
            self.assertIn("'pool_block' as aggregation_scope", sql)
            self.assertNotIn(" as actor", sql)
            self.assertNotIn(" as recipient", sql)

    def test_v4_aggregates_by_pool_block_and_delta_sign(self):
        sql = _load_sections()["liquidity_uniswap_v4_modify"].lower()
        self.assertIn("sum(cast(liquiditydelta", sql)
        self.assertIn("case when liquiditydelta < 0 then -1 else 1 end", sql)
        self.assertIn("count(*) as event_count", sql)
        self.assertNotIn(" as actor", sql)
        self.assertNotIn(" as salt", sql)


if __name__ == "__main__":
    unittest.main()
