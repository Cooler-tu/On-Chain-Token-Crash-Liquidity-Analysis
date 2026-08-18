"""Tests for research-table correlation and lag alignment."""
from __future__ import annotations

import unittest

from scripts.time_series_correlation import analyze, pearson, spearman


class TimeSeriesCorrelationTest(unittest.TestCase):
    def test_pearson_and_spearman(self):
        self.assertAlmostEqual(pearson([1, 2, 3], [2, 4, 6]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3], [9, 5, 1]), -1.0)

    def test_positive_lag_means_x_leads_y(self):
        rows = []
        xs = [0, 1, 4, 2, 8, 3, 7, 5, 9, 6]
        ys = [99] + xs[:-1]
        for x, y in zip(xs, ys):
            rows.append({"x": x, "y": y})

        _, lag_rows = analyze(rows, ("x", "y"), max_lag=2, min_pairs=5)
        pearson_row = next(row for row in lag_rows if row["method"] == "pearson")

        self.assertEqual(pearson_row["lag"], 1)
        self.assertAlmostEqual(pearson_row["correlation"], 1.0)


if __name__ == "__main__":
    unittest.main()
