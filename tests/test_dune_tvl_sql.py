"""TVL snapshot SQL must use Dune's current curated balance namespace."""
from __future__ import annotations

import unittest

from src.data.dune import _load_sections


class TvlSnapshotSqlTest(unittest.TestCase):
    def test_pool_balance_timeline_uses_current_curated_table(self):
        sql = _load_sections()["pool_balance_timeline"].lower()

        self.assertIn("from balances.erc20_daily", sql)
        self.assertIn("b.token_address = {{token}}", sql)
        self.assertIn("b.address in ({{pool_list}})", sql)
        self.assertNotIn("balances_ethereum.daily_updates", sql)


if __name__ == "__main__":
    unittest.main()
