#!/usr/bin/env python3
"""
Publish site generator — scans all analysis outputs and builds a public-facing site.

Usage:
    python3 scripts/publish_site.py                  # builds site/ from all output dirs
    python3 scripts/publish_site.py --serve          # builds site/ and starts a dev server

Output:
    site/
    ├── index.html          # Landing page with all tokens
    ├── assets/
    │   └── style.css       # Shared styles
    ├── {token}/
    │   └── dashboard.html  # Per-token dashboard
    └── ...
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import re
import shutil
import socketserver
import sys
from pathlib import Path
from typing import Any

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.dashboard import generate_dashboard  # noqa: E402


SITE_DIR = PROJECT_ROOT / "site"
ASSETS_DIR = SITE_DIR / "assets"


def discover_outputs() -> list[dict[str, Any]]:
    """Scan project for output directories containing analysis data."""
    outputs = []
    seen_tokens = set()

    # Look for output/ and output-*/
    candidates = sorted(PROJECT_ROOT.glob("output*"))
    for out_dir in candidates:
        if not out_dir.is_dir():
            continue

        token_profile = _load_json(out_dir / "token_profile.json")
        holdings = _load_json(out_dir / "holdings.json", {})
        risk = _load_json(out_dir / "risk_assessment.json", {})
        metrics = _load_json(out_dir / "metrics.json", {})
        incident = _load_json(out_dir / "incident_timeline.json", {})
        verified_pools = _load_json(out_dir / "verified_pools.json", [])

        symbol = token_profile.get("symbol", "")
        if not symbol:
            continue

        # Deduplicate (keep first occurrence)
        key = symbol.lower()
        if key in seen_tokens:
            continue
        seen_tokens.add(key)

        risk_score = risk.get("final_score", 0)
        risk_level = risk.get("risk_level", "N/A")

        outputs.append({
            "dir": out_dir,
            "symbol": symbol,
            "name": token_profile.get("name", symbol),
            "address": token_profile.get("address", ""),
            "chain_id": token_profile.get("chain_id", 1),
            "decimals": token_profile.get("decimals", 18),
            "total_supply": token_profile.get("total_supply_decimal", 0) or 0,
            "holdings_count": holdings.get("holdings_count", 0),
            "total_addresses": holdings.get("total_unique_addresses", 0),
            "num_pools": len(verified_pools),
            "risk_score": risk_score,
            "risk_level": risk_level,
            "pool_concentration": metrics.get("pool_concentration", {}).get("main_pool_share", 0) * 100,
            "incident_block": incident.get("incident_block", 0),
            "query_time": holdings.get("query_time_human", ""),
        })

    return outputs


def generate_dashboard_for(output: dict[str, Any]) -> str:
    """Generate a dashboard from an output directory, return the path."""
    out_dir = output["dir"]
    try:
        return generate_dashboard(str(out_dir))
    except Exception as e:
        print(f"  ⚠️  Dashboard generation failed for {out_dir.name}: {e}")
        # Fall back to existing dashboard.html
        existing = out_dir / "dashboard.html"
        if existing.exists():
            return str(existing)
        raise


def build_landing_page(outputs: list[dict[str, Any]]) -> str:
    """Build the landing page HTML."""
    cards = _build_cards(outputs)
    total_tokens = len(outputs)
    total_pools = sum(o["num_pools"] for o in outputs)
    avg_risk = sum(o["risk_score"] for o in outputs) / max(total_tokens, 1)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>On-Chain Token Crash &amp; Liquidity Analysis</title>
<meta name="description" content="Public dashboards for on-chain token crash and liquidity analysis on Ethereum mainnet.">
<meta property="og:title" content="On-Chain Token Crash Analysis">
<meta property="og:description" content="Public dashboards analyzing on-chain liquidity, holdings, and crash risk for Ethereum tokens.">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box}}
:root{{--bg:#0f172a;--card:#1e293b;--border:#334155;--text:#f1f5f9;--text-muted:#94a3b8;--text-dim:#64748b;--accent:#3b82f6;--accent-light:#60a5fa;--green:#4ade80;--yellow:#facc15;--red:#f87171;--radius:10px;--shadow:0 4px 24px rgba(0,0,0,0.25)}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);padding:20px;min-height:100vh;display:flex;flex-direction:column}}
.container{{max-width:1200px;margin:0 auto;width:100%;flex:1}}
.hero{{text-align:center;padding:48px 0 32px}}
.hero h1{{font-size:36px;font-weight:700;letter-spacing:-0.5px}}
.hero .accent{{color:var(--accent)}}
.hero p{{color:var(--text-muted);font-size:15px;margin-top:8px;max-width:600px;margin-left:auto;margin-right:auto}}
.hero .badge-row{{display:flex;justify-content:center;gap:24px;margin-top:20px;flex-wrap:wrap}}
.hero .badge-item{{text-align:center;padding:12px 20px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius)}}
.hero .badge-value{{font-size:22px;font-weight:700;color:var(--text)}}
.hero .badge-label{{font-size:12px;color:var(--text-dim)}}
.search-bar{{max-width:400px;margin:24px auto;padding:10px 16px;background:var(--card);border:1px solid var(--border);border-radius:8px;display:flex;align-items:center;gap:8px}}
.search-bar input{{flex:1;background:none;border:none;color:var(--text);font-size:14px;outline:none}}
.search-bar input::placeholder{{color:var(--text-dim)}}
.token-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px;margin-top:8px;padding-bottom:32px}}
.token-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px;cursor:pointer;transition:all 0.2s;text-decoration:none;color:inherit;display:block}}
.token-card:hover{{border-color:var(--accent);box-shadow:0 0 20px rgba(59,130,246,0.12);transform:translateY(-2px)}}
.token-card .header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}}
.token-card .symbol{{font-size:20px;font-weight:700}}
.token-card .name{{font-size:13px;color:var(--text-muted);margin-top:2px}}
.token-card .risk-badge{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:600}}
.token-card .risk-low{{background:rgba(34,197,94,0.12);color:var(--green)}}
.token-card .risk-medium{{background:rgba(250,204,21,0.12);color:var(--yellow)}}
.token-card .risk-high{{background:rgba(239,68,68,0.12);color:var(--red)}}
.token-card .risk-na{{background:rgba(100,116,139,0.12);color:var(--text-muted)}}
.token-card .stats{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px;padding-top:12px;border-top:1px solid var(--border)}}
.token-card .stat{{font-size:12px;color:var(--text-dim)}}
.token-card .stat span{{color:var(--text);font-weight:600}}
.token-card .address{{font-family:'SF Mono','Fira Code',monospace;font-size:11px;color:var(--text-dim);margin-top:8px;word-break:break-all}}
.nav-bar{{display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-bottom:1px solid var(--border);margin-bottom:24px}}
.nav-bar .brand{{font-size:18px;font-weight:700}}
.nav-bar .brand-accent{{color:var(--accent)}}
.nav-bar .nav-links a{{color:var(--text-dim);text-decoration:none;font-size:13px;margin-left:20px;transition:color 0.2s}}
.nav-bar .nav-links a:hover{{color:var(--accent-light)}}
.footer{{margin-top:auto;padding:20px 0;border-top:1px solid var(--border);text-align:center;font-size:12px;color:var(--text-dim)}}
.footer a{{color:var(--accent-light);text-decoration:none}}
.empty-state{{text-align:center;padding:80px 20px;color:var(--text-dim)}}
.empty-state h2{{font-size:20px;margin-bottom:8px}}
@keyframes fadeIn{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}
.token-card{{animation:fadeIn 0.3s ease-out}}
@media(max-width:640px){{.hero h1{{font-size:26px}}.token-grid{{grid-template-columns:1fr}}.nav-bar{{flex-direction:column;gap:10px;align-items:flex-start}}.nav-links a{{margin-left:0;margin-right:14px}}}}
</style>
</head>
<body>
<div class="container">
  <nav class="nav-bar">
    <div class="brand"><span class="brand-accent">On-Chain</span> Token Crash</div>
    <div class="nav-links">
      <a href="#" class="active">Home</a>
      <a href="https://github.com/Cooler-tu/On-Chain-Token-Crash-Liquidity-Analysis" target="_blank">GitHub</a>
    </div>
  </nav>

  <div class="hero">
    <h1><span class="accent">On-Chain Token Crash</span> &amp; Liquidity Analysis</h1>
    <p>End-to-end on-chain analysis tool for Ethereum — discover Uniswap pools, track holdings, and assess crash-related risk.</p>
    <div class="badge-row">
      <div class="badge-item">
        <div class="badge-value">{total_tokens}</div>
        <div class="badge-label">Tokens Analyzed</div>
      </div>
      <div class="badge-item">
        <div class="badge-value">{total_pools}</div>
        <div class="badge-label">Liquidity Pools</div>
      </div>
      <div class="badge-item">
        <div class="badge-value" style="color:{_risk_color(avg_risk)}">{avg_risk:.3f}</div>
        <div class="badge-label">Avg Risk Score</div>
      </div>
    </div>
  </div>

  <div class="search-bar">
    <span style="color:var(--text-dim)">🔍</span>
    <input type="text" id="search" placeholder="Search tokens..." oninput="filterTokens(this.value)">
  </div>

  <div id="token-grid" class="token-grid">
    {cards}
  </div>

  <div class="footer">
    Generated by <a href="https://github.com/Cooler-tu/On-Chain-Token-Crash-Liquidity-Analysis">On-Chain Token Crash &amp; Liquidity Analysis</a>
    &middot; Data sourced from Ethereum mainnet
  </div>
</div>
<script>
function filterTokens(q){{
  q = q.toLowerCase();
  document.querySelectorAll('.token-card').forEach(c=>{{
    const txt = c.textContent.toLowerCase();
    c.style.display = txt.includes(q) ? 'block' : 'none';
  }});
}}
</script>
</body>
</html>"""


def _build_cards(outputs: list[dict[str, Any]]) -> str:
    """Build token cards HTML."""
    if not outputs:
        return '<div class="empty-state"><h2>No token analyses found</h2><p>Run the analysis pipeline first with: python3 -m src.cli analyze TOKEN</p></div>'

    cards = []
    for i, o in enumerate(outputs):
        sym = o["symbol"]
        slug = _token_slug(sym)
        rl = o["risk_level"].lower() if o["risk_level"] != "N/A" else "na"
        rl_display = o["risk_level"] if o["risk_level"] != "N/A" else "N/A"
        rc = _risk_color(o["risk_score"])
        supply_str = _fmt_num(o["total_supply"]) if o["total_supply"] else "—"
        addr_short = o["address"][:18] + "..." if len(o["address"]) > 18 else o["address"] or "—"

        cards.append(f"""<a href="{slug}/dashboard.html" class="token-card" style="animation-delay:{i * 0.05}s">
    <div class="header">
      <div>
        <div class="symbol">{sym}</div>
        <div class="name">{o["name"]}</div>
      </div>
      <span class="risk-badge risk-{rl}">{rl_display}</span>
    </div>
    <div class="stats">
      <div class="stat">Holders · <span>{o["holdings_count"]}</span></div>
      <div class="stat">Pools · <span>{o["num_pools"]}</span></div>
      <div class="stat">Addresses · <span>{o["total_addresses"]}</span></div>
      <div class="stat">Score · <span style="color:{rc}">{o["risk_score"]:.4f}</span></div>
    </div>
    <div class="address">{addr_short}</div>
  </a>""")

    return "\n".join(cards)


def _token_slug(symbol: str) -> str:
    """Create a filesystem-safe slug from a token symbol."""
    s = re.sub(r'[^a-zA-Z0-9-]', '', symbol).lower()
    return s or "unknown"


def _fmt_num(n: float) -> str:
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.2f}K"
    return f"{n:.2f}"


def _risk_color(score: float) -> str:
    if score < 0.25:
        return "#4ade80"
    if score < 0.55:
        return "#facc15"
    return "#f87171"


def _load_json(path: Path, default: Any = None) -> Any:
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return default
    return default


def build_site(outputs: list[dict[str, Any]]) -> Path:
    """Build the complete site from analysis outputs."""
    print(f"🔨 Building site with {len(outputs)} token(s)...")

    # Clean site directory
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # Generate landing page
    print("  📄 Generating landing page...")
    index_html = build_landing_page(outputs)
    (SITE_DIR / "index.html").write_text(index_html)

    # Generate per-token dashboards
    for o in outputs:
        sym = o["symbol"]
        slug = _token_slug(sym)
        dash_dir = SITE_DIR / slug
        dash_dir.mkdir(parents=True, exist_ok=True)
        print(f"  📊 Generating dashboard for {sym}...")

        try:
            dashboard_path = generate_dashboard_for(o)
            # Copy dashboard
            src = Path(dashboard_path)
            if src.exists():
                dest = dash_dir / "dashboard.html"
                shutil.copy2(src, dest)
                print(f"    → {dest.relative_to(SITE_DIR)}")
            else:
                print(f"    ⚠️  No dashboard found at {src}")
        except Exception as e:
            print(f"    ⚠️  Failed: {e}")

    print(f"\n✅ Site built at: {SITE_DIR}")
    return SITE_DIR


def serve_site(port: int = 8080):
    """Start a simple HTTP server for the site."""
    os.chdir(str(SITE_DIR))

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            print(f"  [{self.address_string()}] {format % args}")

    print(f"\n🌐 Serving site at http://localhost:{port}")
    print("   Press Ctrl+C to stop")

    with socketserver.TCPServer(("", port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


def main():
    parser = argparse.ArgumentParser(description="Build and publish the token analysis site")
    parser.add_argument("--serve", action="store_true", help="Start a dev server after building")
    parser.add_argument("--port", type=int, default=8080, help="Dev server port (default: 8080)")
    args = parser.parse_args()

    outputs = discover_outputs()
    if not outputs:
        print("⚠️  No token analysis outputs found.")
        print("   Run the analysis pipeline first:")
        print("     python3 -m src.cli analyze TOKEN --output-dir output")
        sys.exit(1)

    build_site(outputs)

    if args.serve:
        serve_site(args.port)


if __name__ == "__main__":
    main()
