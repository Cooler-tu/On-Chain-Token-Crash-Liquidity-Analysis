# Plan — On-Chain Token Crash & Liquidity Analysis

---

## ✅ Completed

- **Core analysis pipeline** — resolve → profile → discover → verify → index → positions → labels → metrics → timeline → risk → report → holdings → dashboard
- **Uniswap V1–V4** — discovery, verification, indexing, positions (V4 StateView + tick share)
- **Curve + Balancer V2** — enabled in `config/protocols.ethereum.yaml`
- **Holdings** — pool tagging; optional Dune address discovery + RPC balances
- **EOA vs contract badges** — bytecode surface label on dashboard
- **Dashboard portfolio drill-down** — click holder → LP positions (`portfolios.json`)
- **DEX venue tags on holders** — Uniswap / Curve / Balancer from LP, swaps, pool transfers, same-tx linkage (`address_dex.json`)
- **Public site + GitHub Pages** — `scripts/publish_site.py`, `.github/workflows/deploy-pages.yml`
- **AGENTS.md / plan.md**
- **uPEG analysis** (`output/`) — blocks 25003546–25004000, 10 Uni pools (V2/V3/V4), 36 positions, risk ~0.44 MEDIUM, DEX tags on dashboard (2026-07-28)
- **SPX6900 demo** (`output-spx-demo/`) — earlier demo data
- **USDC test** (`output-test/`) — minimal window smoke test

---

## 🎯 Current

- **Dune unified query layer + Curve/Balancer integration** — 本周任务（[`NEXT_WEEK.md`](NEXT_WEEK.md)）
  - ✅ `src/data/dune_client.py`（SQL/轮询/缓存 + pools/swaps/tvl）
  - ✅ CLI `dune pools|swaps|tvl|data-map`
  - ✅ Dune-first pool discovery（engine 合并）
  - ✅ Curve/Balancer 持仓重建（positions.py）
  - ✅ Curve/Balancer TVL 估算（metrics.py）
  - ✅ docs/DUNE_DATA_MAP.md + research-notes/curve-balancer-vs-uniswap.md
  - ⏳ 端到端验证：需要 `DUNE_API_KEY`（用户侧）或真实 RPC 跑 CRV/BAL
  - 📋 Next week ref: pull analysis data primarily via Dune; onboard typical non-Uniswap MM pools for contrast

---

## 📋 Backlog (ordered by priority)

1. **Real token crash analysis** — known drain / rug windows with `--incident-block`
2. **Mass-scan utility** — batch tokens → comparison table
3. **Historical crash pattern research** — common LP-withdrawal signatures
4. **Deep holder unwrap** — routers / aggregators / beneficial owners beyond surface EOA label
5. **Multi-chain** — Arbitrum, Base, Polygon
6. **TVL timeline in USD** — needs price oracle (related to next-week TVL ranking, but full USD oracle is later)
7. **Real-time monitoring** — alert on sudden liquidity changes

---

## 🚀 Final Goal

A public, self-serve on-chain analysis dashboard: look up any ERC-20 for liquidity health, holder mix, and crash risk; browse historical crash patterns; shareable links. Exhaustive in evidence, neutral in judgment.
