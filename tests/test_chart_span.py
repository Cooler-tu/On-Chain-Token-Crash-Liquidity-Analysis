"""Chart span helpers (structure.md: window size → bucket granularity)."""
from __future__ import annotations

import unittest

from src.analysis.metrics import (
    chart_bucket,
    chart_bucket_seconds,
    resolve_chart_span,
)


class ChartSpanResolveTest(unittest.TestCase):
    def test_explicit_and_auto(self):
        self.assertEqual(resolve_chart_span(0, 1, "month"), "month")
        self.assertEqual(resolve_chart_span(0, 1, "week"), "week")
        self.assertEqual(resolve_chart_span(0, 1, "day"), "day")
        # ~70k blocks ≈ week → hourly
        self.assertEqual(resolve_chart_span(25_000_000, 25_070_000, "auto"), "week")
        self.assertEqual(resolve_chart_span(0, 200_000, "auto"), "month")
        self.assertEqual(resolve_chart_span(0, 1_000, "auto"), "day")

    def test_bucket_mapping(self):
        self.assertEqual(chart_bucket("month"), "day")
        self.assertEqual(chart_bucket("week"), "hour")
        self.assertEqual(chart_bucket("day"), "hour")
        self.assertEqual(chart_bucket_seconds("month"), 86_400)
        self.assertEqual(chart_bucket_seconds("week"), 3_600)
        self.assertEqual(chart_bucket_seconds("day"), 3_600)


if __name__ == "__main__":
    unittest.main()
