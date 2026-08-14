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
- **Dashboard metrics layer** (2026-08-07) — V3/V4 price + per-pool TVL timeline + per-pool volume; dashboard multi-line TVL / price / volume, Top Movers, withdrawals; `docs/HOLDER_BALANCE_DESIGN.md`, `docs/LP_CORRELATION_DESIGN.md`, `docs/ADDRESS_ASSOCIATION_DESIGN.md`, LP correlation + fund flow prototypes
- **Dune historical balance snapshot** (2026-08-08) — `tokens_ethereum.balances` 稀疏余额账本按 `block_number` 取期初/期末/窗口轨迹；uPEG 12 个抽样地址与 RPC `balanceOf` 精确一致；新增 `src/data/dune_holdings.py` 历史快照与轨迹查询函数
- **Dashboard holder snapshot columns** (2026-08-08) — Top Holders 增加期初/期末/净变动/峰值列并标注快照块与来源；Top Movers 切换为持仓净变动优先、排除池地址、swap 仅作上下文
- **Withdrawal USD normalization** (2026-08-08) — 撤回事件按池、按目标 token 侧归一，输出 `per_pool_removals`、USD 估算和占池 TVL 比例；不再 token0 + token1 直接相加
- **Wallet activity flags** (2026-08-08) — `wallet_activity` 按钱包聚合 USD 买卖并输出 Trade / Mover / Frequent 独立标签，dashboard 新增 Notable Wallets 表
- **Pool-level liquidity event aggregation** (2026-08-11) — Dune V2/V3 Mint/Burn 按 pool+block 聚合，V4 ModifyLiquidity 按 pool+block+delta sign 聚合；保留 withdrawal 数量/金额并停止下载每个 LP actor
- **Data-lineage defense audit** (2026-08-12) — 审计 `structure.md → queries.sql → Python → dashboard`，新增 `docs/METHODOLOGY_DEFENSE.md`、`docs/ADVISOR_QA.md` 与可视化 Canvas；标记 holdings 时间混用、TVL 单边/2×、Risk 时间字段等答辩风险
- **Reuse indexed swaps for volume/price** (2026-08-13) — charts no longer re-query `dex.trades`; Dune `volume_timeline` / `price_timeline` are fallbacks only. Holdings start/end/peak/moved from one `tokens_ethereum.balances` window query.
- **Artifact storage Phase 1** (2026-08-13) — `docs/ARTIFACT_STORAGE_DESIGN.md` + `src/data/artifacts.py`; JSON compatibility default, optional `--artifact-format both` dual-writes typed `tables/swaps.parquet`, DuckDB local query helper, parity/dependency tests, and binary-artifact Git guardrails. Remaining tables/readers are later phases.

---

## 🎯 Current

- **Dune SQL → pipeline wiring (dashboard features)** — parallel discovery (`pools`+`pools_v4`), parallel index (swaps/liq/transfers), snapshot TVL via `pool_balance_timeline` × local swap prices; dashboard Month/Week/Day chart toggles (`--chart-span`)
- Still **not** on dashboard path: `holders` primary discovery, wallet clustering UI, Sim balance timeline

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
