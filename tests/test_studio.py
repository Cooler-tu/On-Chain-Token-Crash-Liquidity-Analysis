"""Local analysis studio window helpers."""
from __future__ import annotations

import unittest

from src.studio.server import inject_studio_home
from src.studio.window import (
    chart_span_for_days,
    output_dir_name,
    span_blocks,
    window_ending_at,
    window_from_start,
)


class StudioWindowTest(unittest.TestCase):
    def test_span_and_chart(self):
        self.assertEqual(span_blocks(7), 50_400)
        self.assertEqual(span_blocks(30), 216_000)
        self.assertEqual(chart_span_for_days(7), "week")
        self.assertEqual(chart_span_for_days(30), "month")
        with self.assertRaises(ValueError):
            span_blocks(15)

    def test_from_block_goes_forward(self):
        start, end = window_from_start(25_572_319, 30)
        self.assertEqual(start, 25_572_319)
        self.assertEqual(end, 25_572_319 + 216_000 - 1)

    def test_blank_from_ends_at_latest(self):
        start, end = window_ending_at(25_788_319, 7)
        self.assertEqual(end, 25_788_319)
        self.assertEqual(start, 25_788_319 - 50_400 + 1)

    def test_output_dir_is_safe(self):
        name = output_dir_name("0x5026F006B85729a8b14553FAE6af249aD16c9aaB", 30, 25572319)
        self.assertEqual(name, "output-0x5026f006-30d-25572319")
        sneaky = output_dir_name("../etc/passwd", 7, 1)
        self.assertTrue(sneaky.startswith("output-"))
        self.assertNotIn("..", sneaky)
        self.assertNotIn("/", sneaky)


class StudioHomeLinkTest(unittest.TestCase):
    def test_injects_home_into_legacy_dashboard(self):
        html = (
            "<html><body>"
            '<div class="brand"><span class="brand-accent">On-Chain</span> Token Crash</div>'
            '<div class="nav-links"><a href="#" class="active">Dashboard</a></div>'
            "</body></html>"
        ).encode("utf-8")
        out = inject_studio_home(html).decode("utf-8")
        self.assertIn('id="nav-home"', out)
        self.assertIn('href="/"', out)
        self.assertIn("Home", out)

    def test_rewrites_existing_home_to_studio_root(self):
        html = (
            "<html><body>"
            '<a id="nav-home" href="../">Home</a>'
            "</body></html>"
        ).encode("utf-8")
        out = inject_studio_home(html).decode("utf-8")
        self.assertIn('id="nav-home" href="/"', out)


class StudioLatestBlockTest(unittest.TestCase):
    def test_quota_error_does_not_look_like_success(self):
        from src.studio import server as studio_server

        class _Resp:
            status_code = 429
            content = b'{"error":{"code":429,"message":"Monthly capacity limit exceeded"}}'

            def json(self):
                return {"error": {"code": 429, "message": "Monthly capacity limit exceeded"}}

        orig_post = studio_server.requests.post
        orig_url = studio_server.os.environ.get("ETH_RPC_URL")
        studio_server.os.environ["ETH_RPC_URL"] = "https://example.invalid/rpc"
        studio_server.requests.post = lambda *args, **kwargs: _Resp()
        try:
            ok, latest, err = studio_server._latest_block()
        finally:
            studio_server.requests.post = orig_post
            if orig_url is None:
                studio_server.os.environ.pop("ETH_RPC_URL", None)
            else:
                studio_server.os.environ["ETH_RPC_URL"] = orig_url
        self.assertFalse(ok)
        self.assertIsNone(latest)
        self.assertIn("429", err)


if __name__ == "__main__":
    unittest.main()
