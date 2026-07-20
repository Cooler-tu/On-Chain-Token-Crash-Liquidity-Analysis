"""Dashboard visualization — generates a standalone HTML dashboard.

Reads analysis output files and renders an interactive dashboard using Chart.js.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_HTML_TEMPLATE: str | None = None
_JS_TEMPLATE: str | None = None


def _load_templates():
    global _HTML_TEMPLATE, _JS_TEMPLATE
    if _HTML_TEMPLATE is not None:
        return

    _JS_TEMPLATE = """const topH = {top_h_json};
const poolH = {pool_h_json};
const poolI = {pool_i_json};
const tvlD = {tvl_json};

(function(){
  function tc(id,cfg){ new Chart(document.getElementById(id),cfg); }

  tc('c1',{
    type:'doughnut',
    data:{
      labels:['Pool LP Holders','Regular Holders'],
      datasets:[{data:[{pool_count},{holder_count}],backgroundColor:['#3b82f6','#64748b'],borderWidth:0}]
    },
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom',labels:{color:'#94a3b8',padding:12,font:{size:12}}}}}
  });

  tc('c2',{
    type:'doughnut',
    data:{
      labels:['Main Pool Share','Other Pools'],
      datasets:[{data:[{pool_share},{pool_other}],backgroundColor:['#f59e0b','#1e293b'],borderWidth:0}]
    },
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom',labels:{color:'#94a3b8',padding:12,font:{size:12}}}}}
  });

  tc('c3',{
    type:'bar',
    data:{
      labels:topH.slice(0,10).map(function(d){return d.address.slice(0,8)+'...';}),
      datasets:[{label:'Balance',data:topH.slice(0,10).map(function(d){return d.balance_decimal;}),backgroundColor:'#3b82f6',borderRadius:4}]
    },
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{y:{beginAtZero:true,ticks:{color:'#64748b'},grid:{color:'#1e293b'}},x:{ticks:{color:'#64748b'},grid:{display:false}}}}
  });
  {tvl_chart}
})();
"""

    _HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{symbol} Token Dashboard</title>
<meta name="description" content="On-chain liquidity and holdings analysis for {symbol} on Ethereum mainnet.">
<meta property="og:title" content="{symbol} Token Dashboard">
<meta property="og:description" content="On-chain liquidity and holdings analysis for {symbol}.">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#0f172a;--card:#1e293b;--border:#334155;--text:#f1f5f9;--text-muted:#94a3b8;--text-dim:#64748b;--accent:#3b82f6;--accent-light:#60a5fa;--green:#4ade80;--yellow:#facc15;--red:#f87171;--radius:10px;--shadow:0 4px 24px rgba(0,0,0,0.25)}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);padding:20px;min-height:100vh}
.container{max-width:1400px;margin:0 auto}
h1{font-size:24px;font-weight:700;letter-spacing:-0.3px}
.symbol-muted{color:var(--text-muted);font-weight:400}
.subtitle{color:var(--text-muted);font-size:13px;margin-bottom:20px}
.nav-bar{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid var(--border)}
.brand{font-size:18px;font-weight:700}
.brand-accent{color:var(--accent)}
.nav-links a{color:var(--text-dim);text-decoration:none;font-size:13px;margin-left:20px;transition:color 0.2s}
.nav-links a:hover,.nav-links a.active{color:var(--accent-light)}
.nav-links a.active{font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px;box-shadow:var(--shadow)}
.card h2{font-size:12px;color:var(--text-muted);margin-bottom:14px;text-transform:uppercase;letter-spacing:0.6px;font-weight:600}
.stat-value{font-size:30px;font-weight:700;color:var(--text)}
.stat-label{font-size:12px;color:var(--text-dim);margin-top:2px}
.badge{display:inline-block;padding:3px 16px;border-radius:20px;font-weight:600;font-size:13px}
.bg-low{background:rgba(34,197,94,0.12);color:var(--green)}
.bg-medium{background:rgba(250,204,21,0.12);color:var(--yellow)}
.bg-high{background:rgba(239,68,68,0.12);color:var(--red)}
.bg-n-a{background:rgba(100,116,139,0.12);color:var(--text-muted)}
.fw{grid-column:1/-1}
.chart-box{position:relative;height:260px;width:100%}
.chart-box-sm{position:relative;height:200px;width:100%}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;padding:8px 6px;border-bottom:1px solid var(--border);color:var(--text-dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.5px}
td{padding:6px;border-bottom:1px solid #1e293b;color:#cbd5e1}
tr:hover td{background:rgba(59,130,246,0.04)}
.addr{font-family:'SF Mono','Fira Code','Cascadia Code','Courier New',monospace;font-size:11px;color:var(--accent-light);word-break:break-all}
.plabel{display:inline-block;padding:1px 8px;border-radius:4px;font-size:10px;font-weight:600;background:rgba(96,165,250,0.12);color:var(--accent-light)}
.scroll{max-height:360px;overflow-y:auto}
.scroll::-webkit-scrollbar{width:5px}
.scroll::-webkit-scrollbar-track{background:transparent}
.scroll::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.glow{box-shadow:0 0 30px rgba(59,130,246,0.06)}
.info-bar{display:flex;flex-wrap:wrap;gap:12px 24px;margin-bottom:20px;padding:12px 16px;background:var(--card);border:1px solid var(--border);border-radius:8px}
.info-item{font-size:12px;color:var(--text-muted)}
.info-item span{color:var(--text);font-weight:500}
.empty-note{padding:12px 16px;background:rgba(239,68,68,0.08);border:1px solid rgba(239,68,68,0.2);border-radius:8px;color:var(--red);font-size:13px;margin-bottom:16px}
.footer{margin-top:32px;padding:16px;border-top:1px solid var(--border);text-align:center;font-size:12px;color:var(--text-dim)}
.footer a{color:var(--accent-light);text-decoration:none}
@media(max-width:640px){.grid{grid-template-columns:1fr}.nav-bar{flex-direction:column;gap:10px;align-items:flex-start}.nav-links a{margin-left:0;margin-right:14px}.stat-value{font-size:24px}}
</style>
</head>
<body>
<div class="container">
  <nav class="nav-bar">
    <div class="brand"><span class="brand-accent">On-Chain</span> Token Crash</div>
    <div class="nav-links">
      <a href="../index.html">Home</a>
      <a href="#" class="active">Dashboard</a>
      <a href="https://github.com/Cooler-tu/On-Chain-Token-Crash-Liquidity-Analysis" target="_blank">GitHub</a>
    </div>
  </nav>

  <h1>{symbol} <span class="symbol-muted">Holdings &amp; Liquidity</span></h1>
  <p class="subtitle">Chain ID: {chain_id} &middot; Token: <span class="addr">{token_address}</span></p>
  {empty_note}

  <div class="info-bar">
    <div class="info-item">Analysis &middot; <span>{query_time}</span></div>
    <div class="info-item">Token &middot; <span>{token_name}</span></div>
    <div class="info-item">Decimals &middot; <span>{decimals}</span></div>
    {supply_info}
  </div>

  <div class="grid">
    <div class="card glow">
      <div class="stat-value">{total_addresses}</div>
      <div class="stat-label">Unique Transfer Addresses</div>
    </div>
    <div class="card glow">
      <div class="stat-value">{holdings_count}</div>
      <div class="stat-label">Active Holders</div>
    </div>
    <div class="card glow">
      <div class="stat-value">{num_pools}</div>
      <div class="stat-label">Verified Liquidity Pools</div>
    </div>
    <div class="card glow">
      <div class="stat-value"><span class="badge bg-{risk_lvl_class}">{risk_level}</span></div>
      <div class="stat-label">Risk Index &middot; Score <span style="color:{risk_color}">{risk_score}</span></div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Holder Distribution</h2>
      <div class="chart-box-sm"><canvas id="c1"></canvas></div>
    </div>
    <div class="card">
      <h2>Pool Concentration</h2>
      <div class="chart-box-sm"><canvas id="c2"></canvas></div>
    </div>
    <div class="card">
      <h2>Top Holders</h2>
      <div class="chart-box-sm"><canvas id="c3"></canvas></div>
    </div>
  </div>

  <div class="grid">
    <div class="card fw">
      <h2>All Non-Pool Holders</h2>
      <div class="scroll"><table><thead><tr><th>#</th><th>Address</th><th>Balance ({symbol})</th><th>Tx Count</th><th>Label</th></tr></thead><tbody>{table_top}</tbody></table></div>
    </div>
  </div>

  {pool_section}

  <div class="grid">
    <div class="card fw">
      <h2>Pool TVL Timeline</h2>
      <div class="chart-box"><canvas id="c4"></canvas></div>
    </div>
  </div>

  <div class="footer">
    Generated by <a href="https://github.com/Cooler-tu/On-Chain-Token-Crash-Liquidity-Analysis">On-Chain Token Crash &amp; Liquidity Analysis</a>
    &middot; Data sourced from Ethereum mainnet
  </div>
</div>
<script>
{js_script}
</script>
</body>
</html>"""


def generate_dashboard(
    output_dir: str | Path = "output",
) -> str:
    out = Path(output_dir)
    _load_templates()

    holdings = _load_json(out / "holdings.json", {})
    token_profile = _load_json(out / "token_profile.json", {})
    verified_pools = _load_json(out / "verified_pools.json", [])
    metrics = _load_json(out / "metrics.json", {})
    risk = _load_json(out / "risk_assessment.json", {})

    holdings_data = holdings.get("holdings", [])
    pool_ident = holdings.get("pool_identification", [])

    if not pool_ident and verified_pools:
        pool_ident = [
            {
                "pool_address": p.get("pool_address", ""),
                "protocol": p.get("protocol", ""),
                "version": p.get("version", ""),
                "token0": p.get("token0", ""),
                "token1": p.get("token1", ""),
                "in_holders_list": False,
            }
            for p in verified_pools if p.get("verified", True)
        ]

    top_holders = [h for h in holdings_data if not h.get("is_pool")][:20]
    pool_holders = [h for h in holdings_data if h.get("is_pool")]
    tvl_data = metrics.get("tvl_timeline", [])
    pool_conc = metrics.get("pool_concentration", {})

    risk_score = risk.get("final_score", 0)
    risk_level = risk.get("risk_level", "N/A")
    symbol = token_profile.get("symbol", "TOKEN")
    chain_id = token_profile.get("chain_id", 1)
    token_addr = token_profile.get("address", "")
    token_name = token_profile.get("name", symbol)
    decimals = token_profile.get("decimals", 18)
    total_supply = token_profile.get("total_supply_decimal", 0) or 0
    holdings_count = holdings.get("holdings_count", 0)
    total_addresses = holdings.get("total_unique_addresses", 0)
    query_time = holdings.get("query_time_human", "")
    main_pool_share = pool_conc.get("main_pool_share", 0) * 100

    risk_lvl_class = risk_level.lower() if risk_level != "N/A" else "n-a"
    risk_color = _risk_color(risk_score)

    empty_note = ""
    if holdings_count == 0 and total_addresses == 0:
        empty_note = (
            '<div class="empty-note">'
            "No transfer/holdings data in this block window — "
            "pool list and risk score below still reflect discovery results."
            "</div>"
        )

    supply_info = (
        f'<div class="info-item">Total Supply · <span>{_fmt_supply(total_supply, symbol)}</span></div>'
        if total_supply else ''
    )

    # Build tables
    table_top = _table_top_holders(top_holders, symbol)
    table_pool = _table_pool_holders(pool_holders, symbol)
    table_ident = _table_pool_ident(pool_ident)

    # Build pool section
    pool_section_parts = []
    if table_pool:
        pool_section_parts.append(f"""<div class="grid">
    <div class="card fw">
      <h2>Pool-Labeled Addresses</h2>
      <div class="scroll"><table><thead><tr><th>Pool Address</th><th>Protocol</th><th>Balance</th><th>Label</th></tr></thead><tbody>{table_pool}</tbody></table></div>
    </div>
  </div>""")
    if table_ident:
        pool_section_parts.append(f"""<div class="grid">
    <div class="card fw">
      <h2>All Verified Pools</h2>
      <div class="scroll"><table><thead><tr><th>Pool Address</th><th>Protocol / Version</th><th>Token Pair</th><th>In Holders</th></tr></thead><tbody>{table_ident}</tbody></table></div>
    </div>
  </div>""")
    pool_section = "\n".join(pool_section_parts)

    # Build TVL chart JS
    tvl_chart = _build_tvl_chart_js(tvl_data)

    # Build JS
    js_vars = {
        "top_h_json": json.dumps(top_holders, indent=2),
        "pool_h_json": json.dumps(pool_holders, indent=2),
        "pool_i_json": json.dumps(pool_ident, indent=2),
        "tvl_json": json.dumps(tvl_data, indent=2),
        "pool_count": len(pool_holders),
        "holder_count": max(0, holdings_count - len(pool_holders)),
        "pool_share": main_pool_share,
        "pool_other": max(0, 100 - main_pool_share),
        "tvl_chart": tvl_chart,
    }
    
    js_script = _JS_TEMPLATE
    for k, v in js_vars.items():
        js_script = js_script.replace("{" + k + "}", str(v))


    # Build HTML
    html_vars = {
        "symbol": symbol,
        "token_name": token_name,
        "chain_id": chain_id,
        "token_address": token_addr or "N/A",
        "query_time": query_time or "N/A",
        "decimals": decimals,
        "supply_info": supply_info,
        "empty_note": empty_note,
        "total_addresses": total_addresses,
        "holdings_count": holdings_count,
        "num_pools": len(verified_pools),
        "risk_lvl_class": risk_lvl_class,
        "risk_level": risk_level if risk_level != "N/A" else "N/A",
        "risk_color": risk_color,
        "risk_score": risk_score,
        "table_top": table_top,
        "pool_section": pool_section,
        "js_script": js_script,
    }
    html = _HTML_TEMPLATE
    for k, v in html_vars.items():
        html = html.replace("{" + k + "}", str(v))

    dashboard_path = out / "dashboard.html"
    with open(dashboard_path, "w") as f:
        f.write(html)

    return str(dashboard_path.resolve())


def _build_tvl_chart_js(tvl_data: list) -> str:
    if not tvl_data:
        return (
            "tc('c4',{type:'line',data:{labels:['No Data'],datasets:[{data:[0],"
            "backgroundColor:'#3b82f6',borderColor:'#3b82f6'}]},"
            "options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},"
            "scales:{y:{ticks:{color:'#64748b'},grid:{color:'#1e293b'}},"
            "x:{ticks:{color:'#64748b'},grid:{display:false}}}}});"
        )

    labels_json = json.dumps([t.get("block_number", i) for i, t in enumerate(tvl_data)])
    values_json = json.dumps([t.get("tvl", 0) for t in tvl_data])

    return (
        "const tvlLabels = %s;\n"
        "const tvlValues = %s;\n"
        "tc('c4',{type:'line',data:{labels:tvlLabels,datasets:[{label:'TVL (USD)',"
        "data:tvlValues,borderColor:'#3b82f6',backgroundColor:'rgba(59,130,246,0.1)',"
        "fill:true,tension:0.3,pointRadius:3}]},"
        "options:{responsive:true,maintainAspectRatio:false,"
        "plugins:{legend:{labels:{color:'#94a3b8'},position:'top'}},"
        "scales:{y:{beginAtZero:true,ticks:{color:'#64748b',"
        "callback:function(v){return '$'+v.toLocaleString();}},grid:{color:'#1e293b'}},"
        "x:{ticks:{color:'#64748b'},grid:{display:false}}}}})"
    ) % (labels_json, values_json)


def _table_top_holders(holders: list, symbol: str) -> str:
    if not holders:
        return '<tr><td colspan="5" style="text-align:center;padding:24px;color:#64748b">No holder data available</td></tr>'
    rows = []
    for i, h in enumerate(holders[:20], 1):
        lbl = ""
        if h.get("pool_label"):
            lbl = f'<span class="plabel">{h["pool_label"]}</span>'
        rows.append(
            f"<tr><td>{i}</td><td class=\"addr\">{h.get('address','')}</td>"
            f"<td>{_fmt_bal(h.get('balance_decimal',0),symbol)}</td>"
            f"<td>{h.get('tx_count',0)}</td><td>{lbl}</td></tr>"
        )
    return "\n".join(rows)


def _table_pool_holders(holders: list, symbol: str) -> str:
    rows = []
    for h in holders:
        rows.append(
            f"<tr><td class=\"addr\">{h.get('address','')}</td>"
            f"<td>{h.get('pool_label','')}</td>"
            f"<td>{_fmt_bal(h.get('balance_decimal',0),symbol)}</td>"
            f"<td><span class=\"plabel\">POOL</span></td></tr>"
        )
    return "\n".join(rows)


def _table_pool_ident(pools: list) -> str:
    rows = []
    for p in pools:
        t0 = (p.get("token0") or "")[:10] + "..."
        t1 = (p.get("token1") or "")[:10] + "..."
        in_list = "Yes" if p.get("in_holders_list") else "No"
        rows.append(
            f"<tr><td class=\"addr\">{p.get('pool_address','')}</td>"
            f"<td>{p.get('protocol','')} {p.get('version','')}</td>"
            f"<td>{t0}/{t1}</td><td>{in_list}</td></tr>"
        )
    return "\n".join(rows)


def _fmt_bal(bal: float, symbol: str) -> str:
    if bal >= 1_000_000:
        return f"{bal/1_000_000:.2f}M {symbol}"
    if bal >= 1_000:
        return f"{bal/1_000:.2f}K {symbol}"
    return f"{bal:.4f} {symbol}"


def _fmt_supply(val: float, symbol: str) -> str:
    if val >= 1_000_000_000:
        return f"{val/1_000_000_000:.2f}B {symbol}"
    if val >= 1_000_000:
        return f"{val/1_000_000:.2f}M {symbol}"
    if val >= 1_000:
        return f"{val/1_000:.2f}K {symbol}"
    return f"{val:.4f} {symbol}"


def _risk_color(score: float) -> str:
    if score < 0.25:
        return "#4ade80"
    if score < 0.55:
        return "#facc15"
    return "#f87171"


def _load_json(path: Path, default: Any) -> Any:
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return default
    return default
