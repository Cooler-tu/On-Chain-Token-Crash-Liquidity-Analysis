# Plan — On-Chain Token Crash & Liquidity Analysis

---

## ✅ Completed

- **Core analysis pipeline** — 12-step pipeline: token resolve → profile → discover pools → verify → index → positions → labels → metrics → timeline → risk → report → dashboard
- **Uniswap V2/V3 discovery** — pool detection via factory events + position manager
- **Uniswap V4 discovery** — exists but needs validation
- **Event indexer** — checkpointed, resumable, covers Swap / Mint / Burn / Transfer / PM liquidity
- **Risk scoring** — concentration, withdrawal pattern, market impact, holder distribution
- **Dashboard generation** — professional dark-mode, Chart.js, responsive, public-facing
- **Public site generator** — `scripts/publish_site.py` scans all outputs, creates landing page + per-token dashboards
- **GitHub Pages deployment** — `.github/workflows/deploy-pages.yml` auto-deploys on push
- **AGENTS.md** — agent self-discipline document
- **plan.md** — this file
- **SPX6900 analysis** (`output/`) — 8 verified pools, 3 holders, LOW risk (0.1944)
- **SPX6900 demo** (`output-spx-demo/`) — partial demo data
- **USDC test** (`output-test/`) — basic test with minimal block window

---

## 🎯 Current

- _(nothing in progress)_

---

## 📋 Backlog (ordered by priority)

1. **Real token crash analysis** — analyze tokens with known crash events; use `--incident-block` to capture temporal risk
   - Need to find: recent pump-and-dump tokens, rug pulls, or liquidity drain events on Ethereum
   - Suggested: look at on-chain fraud databases, Twitter/Telegram reports, or historical token death lists
2. **Mass-scan utility** — script to analyze many tokens in batch, output a comparison table
3. **Historical crash pattern research** — analyze multiple crash events, look for common signatures (coordinated LP withdrawal, frontrunning, sandwich attacks)
4. **Multi-chain support** — expand beyond Ethereum mainnet (Arbitrum, Base, Polygon)
5. **V4 pool discovery hardening** — currently experimental; needs more validation and edge case handling
6. **Real-time monitoring** — optional: watch for new pools on a token and alert on sudden liquidity changes
7. **LP position tracking** — best-effort only; needs improvement for complex positions
8. **TVL timeline accuracy** — current TVL graph is incomplete (no USD price oracle)

---

## 🚀 Final Goal

A public, self-serve on-chain analysis dashboard where anyone can:
- Look up any ERC-20 token and see its liquidity health, holder distribution, and crash risk
- Browse historical crash patterns to understand common failure modes
- Get alerts when a token they care about shows unusual liquidity changes
- Click a link and share the analysis with others

The tool should be **exhaustive in evidence, neutral in judgment** — it surfaces the data and the risk signals, not conclusions.
