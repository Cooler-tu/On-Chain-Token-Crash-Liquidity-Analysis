"""Local derivation of start / end / peak / moved from one balance window."""
from __future__ import annotations

import unittest

from src.data.dune_holdings import summarize_balance_trajectory


class SummarizeBalanceTrajectoryTest(unittest.TestCase):
    def test_start_end_peak_and_moved(self):
        rows = [
            {"block_number": 90, "balance_raw": "100"},
            {"block_number": 110, "balance_raw": "500"},
            {"block_number": 120, "balance_raw": "80"},
        ]
        out = summarize_balance_trajectory(rows, from_block=100, to_block=130)
        self.assertEqual(out["start"], "100")
        self.assertEqual(out["end"], "80")
        self.assertEqual(out["peak"], "500")
        self.assertEqual(out["moved_in"], "400")
        self.assertEqual(out["moved_out"], "420")
        self.assertEqual(out["source"], "event_rebuild")

    def test_change_at_from_block_is_start_not_a_move(self):
        rows = [
            {"block_number": 100, "balance_raw": "40"},
            {"block_number": 101, "balance_raw": "50"},
        ]
        out = summarize_balance_trajectory(rows, from_block=100, to_block=110)
        self.assertEqual(out["start"], "40")
        self.assertEqual(out["end"], "50")
        self.assertEqual(out["moved_in"], "10")
        self.assertEqual(out["moved_out"], "0")

    def test_no_window_moves_is_two_point_snapshot(self):
        rows = [{"block_number": 50, "balance_raw": "7"}]
        out = summarize_balance_trajectory(rows, from_block=100, to_block=110)
        self.assertEqual(out["start"], "7")
        self.assertEqual(out["end"], "7")
        self.assertEqual(out["peak"], "7")
        self.assertEqual(out["moved_in"], "0")
        self.assertEqual(out["moved_out"], "0")
        self.assertEqual(out["source"], "two_point_snapshot")


if __name__ == "__main__":
    unittest.main()
