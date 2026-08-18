# On-Chain Token Crash & Liquidity Analysis

[English](#english) | [中文](#中文)

Live site: [https://jelly577.github.io/On-Chain-Token-Crash-Liquidity-Analysis/](https://jelly577.github.io/On-Chain-Token-Crash-Liquidity-Analysis/)

---

<a name="english"></a>

# English

## Overview

End-to-end **Ethereum mainnet** tool for token liquidity / crash analysis: discover pools across major DEXes, index swaps / liquidity / transfers, estimate concentration and risk, then emit JSON, Markdown, and a local HTML dashboard.

**Input:** token address, symbol, or name + block window  
**Output:** verified pools, events, holdings, risk score, `report.md`, `dashboard.html`

**Scope today:** Ethereum (`chain_id=1`) + **Uniswap V1–V4**, **Curve**, **Balancer V2**.

---

## Analysis Log

| Token | Window | Pools | Holders | Risk | Date | Dir |
|-------|--------|-------|---------|------|------|-----|
| uPEG directional audit | 25043020–25043311 | 1 V3 | 99 tx senders | Research | 2026-08-18 | `output-upeg-v3-7d/research-directional-flow/2026-05-07T12/` |
| uPEG | 25003546–25004000 | 10 (V2/V3/V4) | ~231 EOA | 0.4364 MEDIUM | 2026-07-28 | `output/` |
| SPX | 19000022–19000022 | 8 (V2+V3) | 3 | 0.1944 LOW | 2026-07-18 | `output/` (superseded) / `output-spx-demo/` |
| USDC | 19000000–19000050 | — | — | 0.0000 LOW | — | `output-test/` |

### Recent Findings (uPEG)

- Directional audit of the verified `2026-05-07 12:00 UTC` V3 bucket found 48 sell-side and 71 buy-side Swap events: 39.5356 uPEG gross sells, 30.2685 gross buys, and 9.2671 net signed Swap flow into the pool. Actual uPEG Transfer net flow and the historical balance delta both equal 10.106754360913178103 uPEG exactly; the 0.83964 Transfer-minus-Swap residual proves that Swap amounts alone are not a complete cash-flow ledger for this token/window. Evidence and guardrails are in `research-notes/upeg-directional-flow-audit.md`.
- Window `25003546–25004000`: **10** verified Uniswap pools (1 V2 / 3 V3 / 6 V4). Curve/Balancer enabled in config; this token’s liquidity in-window was Uniswap-only.
- **36** LP positions reconstructed (V3/V4 tick math; V4 share = in-range `L / StateView.getLiquidity`).
- Holdings via Dune address discovery + RPC `balanceOf`; dashboard tags **EOA / contract / pool**.
- Dashboard **DEX column**: Uniswap / Curve / Balancer from LP, swaps, pool transfers, or same-tx linkage. Expand row → **LP portfolio only** (not the same as the DEX tag).
- Hover DEX badge for `LP` vs `Swap`. `—` = no DEX link in this window (e.g. P2P only).
- Dashboard identifiers stay compact in tables; hover or keyboard focus reveals the full value, click copies it, and valid mainnet addresses include an Etherscan link. The Top Holders chart also reveals the full address/balance on hover and copies the address on bar click. V4 bytes32 pool IDs remain copyable without a misleading address link.
- Dashboard holder cards now separate transfer-observed addresses from covered, positive-balance non-pool holders and disclose balance-query coverage. TVL captions follow `tvl_timeline_source`, so event reconstruction is no longer presented as a balance snapshot.
- Notable Wallets use within-window P99 cutoffs for max single trade, absolute net flow, cumulative volume, and swap activity instead of universal `$10k / 50 swaps` defaults. Existing outputs can refresh this metric locally without Dune/RPC calls.
- Pool timeline series use a larger dark-theme palette plus dash patterns. All Verified Pools shows token symbols in the pair column, an Observed Token Reserve column, and a small reserve-share pie beside the table; Uniswap V4 may show a shared PoolManager balance rather than per-poolId reserves.
- Pool-liquidity shares disclose their denominator and measurement coverage. The current uPEG end-block estimate covers 3 of 14 verified pools; unmeasured V4 Pool IDs show `Not measured` rather than a misleading zero, and percentages are explicitly limited to measured pools.
- Non-pool holder rankings explicitly exclude pool/custody rows and zero end balances, then sort covered addresses by end balance descending. The chart shows up to 10 and the table up to 20; EOAs and contracts can both appear, so the view is not presented as a complete holder census under partial coverage.
- Liquidity removals now distinguish `quantified`, `liquidity-delta-only`, and `unmapped` evidence. V4 `ModifyLiquidity` rows without token amounts display `Token amount not returned` instead of a false `0.0000`; dependent USD/TVL fields say `Cannot calculate`, while a measured zero remains zero.

```bash
set -a && source .env && set +a
python3 -m src.cli analyze uPEG \
  --from-block 25003546 --to-block 25004000 \
  --output-dir output
python3 -m src.cli dashboard --output-dir output
python3 -m src.cli dashboard --output-dir output --refresh-wallet-activity
```

---

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export ETH_RPC_URL="https://mainnet.infura.io/v3/YOUR_API_KEY"
# optional: DUNE_API_KEY for wider holder discovery
```

### Full pipeline

```bash
python3 -m src.cli analyze USDC \
  --from-block 19000000 \
  --to-block 19000050 \
  --output-dir output
open output/dashboard.html
```

### Other commands

| Command | Purpose |
|---------|---------|
| `analyze` | Full pipeline |
| `discover-only` | Profile + discover + verify pools |
| `holdings` | Rebuild holdings / pool-ID tables |
| `dune` | Query Dune directly: `pools` / `swaps` / `tvl` / `data-map` |
| `dashboard` | Regenerate `dashboard.html`; optionally refresh adaptive wallet selection locally |
| `research-series` | Build typed `analysis_series.parquet`; optionally refresh attributable reserve snapshots with `--refresh-tvl` |

```bash
python3 -m src.cli dashboard --output-dir output
# Recompute adaptive Notable Wallets from local swaps, then rebuild dashboard
python3 -m src.cli dashboard --output-dir output --refresh-wallet-activity
# Build the bucket-aligned OHLC/VWAP/TVL/volume/LP research feature table
python3 -m src.cli research-series --output-dir output
# Recommended before formal TVL research (requires an archive-capable RPC):
python3 -m src.cli research-series --output-dir output --refresh-tvl
python3 scripts/publish_site.py          # rebuild public site/
python3 scripts/publish_site.py --serve  # preview
```

### Important `analyze` options

| Option | Description | Default |
|--------|-------------|---------|
| `TOKEN` | Address, symbol, or name | required |
| `--from-block` / `--to-block` | Analysis window | `19000000` / `19100000` |
| `--incident-block` | Crash block for temporal / impact scoring | `0` |
| `--fast-mode` | Skip heavy exhaustive indexing | `false` |
| `--output-dir` | Artifacts directory | `output` |
| `--pools-file` | Load pool candidates from a saved Dune pools JSON (skip live discovery) | (none) |
| `--artifact-format` | `json` or `both` (JSON + Parquet event/holdings/positions/timeline tables) | `json` |

> Indexing is **resumable** via `event_indexer_checkpoint.json`. Change token/window or delete checkpoint to start clean.

The artifact-storage migration keeps JSON as the compatibility default. Use
`--artifact-format both` to additionally write typed Parquet tables for swaps, transfers,
liquidity events, PositionManager evidence, holdings, positions, TVL, and volume rows under
`tables/`. Large-table readers are now Parquet-first; Parquet-only/default switching remains
a separate compatibility milestone. Parquet and DuckDB files are local artifacts and are not
committed by default. See
[`docs/ARTIFACT_STORAGE_DESIGN.md`](docs/ARTIFACT_STORAGE_DESIGN.md).

The standalone dashboard reader is Parquet-first for holdings, positions, event rows, TVL,
and volume, with automatic compatibility fallback to old JSON-only outputs. In `both` mode,
`metrics.json` keeps compact metric summaries while its duplicated chart arrays are loaded
from the timeline tables.

### Dune (optional primary data path)

With `DUNE_API_KEY` set, pool discovery runs Dune-first (`dex.trades`, fast, cross-DEX)
then merges RPC adapter results; swaps, holdings, and TVL queries go through
`src/data/dune_client.py` with caching to `output/dune_cache/`.  Without a key,
everything falls back to RPC.

```bash
export DUNE_API_KEY="..."
python3 -m src.cli dune pools CRV --from-block 19000000 --to-block 19000050
python3 -m src.cli dune swaps 0x... --from-block 19000000 --to-block 19000050
python3 -m src.cli dune tvl 0x...
python3 -m src.cli dune data-map
```

See [docs/DUNE_DATA_MAP.md](docs/DUNE_DATA_MAP.md) for the full table.

Saved Dune pool exports can be reused without an API key by passing
`--pools-file` to `analyze` / `discover-only`. The loader accepts the CLI
`dune pools` output or a web-UI export with a `data` array, maps rows to
`VerifiedPool`, and warns if the file token differs from the requested token:

```bash
python3 -m src.cli discover-only 0xD533a949740bb3306d119CC777fa900bA034cd52 \
  --pools-file output-dune-crv-demo/pools.json \
  --from-block 22000000 --to-block 22005000
```

---

## Pipeline (`analyze`)

```text
resolve + profile
  → discover pools (Dune-first; Uni V1–V4, Curve, Balancer)
  → verify
  → index Swap / Mint|Burn / PM / V4 ModifyLiquidity / Transfers
  → LP positions
  → labels
  → metrics + timeline + risk
  → report.md
  → holdings (+ optional Dune)
  → dashboard.html  (DEX tags, EOA badges, click-to-expand LP)
```

---

## What works vs what’s incomplete

| Area | Status |
|------|--------|
| Uniswap V1 / V2 / V3 / V4 | Done (productized for this pipeline) |
| Curve + Balancer V2 | Done (discovery + indexing; may be slow on free RPC) |
| Token profile + resolve | Done |
| Event indexing with resume | Done |
| Holdings + pool account tags | Done (Dune-first when key set; RPC fallback) |
| Dune unified query layer | Done (`pools` / `swaps` / `tvl` / `data-map` + caching) |
| EOA vs contract labeling | Done (bytecode surface label) |
| Dashboard + report + public site | Done |
| DEX venue tags on holders | Done (window evidence; not beneficial-owner unwrap) |
| LP portfolio drill-down | Done |
| Deep holder / router unwrap | Not done |
| Multi-chain | Not done |
| Real-time monitoring | Not done |

---

## Main outputs

| File | Contents |
|------|----------|
| `token_profile.json` | Symbol, decimals, flags |
| `verified_pools.json` | Verified pools |
| Event tables (`swaps`, `liquidity_events`, `transfers`, `position_events`) | Indexed events as JSON and/or Parquet; combined in memory |
| `positions.json` / `portfolios.json` | LP positions / by-owner |
| `address_dex.json` | Per-address DEX protocols + LP/Swap roles |
| `holdings_summary.json` + holdings table | Compact run metadata + holder rows; old `holdings.json` remains compatible |
| `metrics.json` / `risk_assessment.json` | TVL, concentration, risk |
| `report.md` / `dashboard.html` | Report + UI |

---

## Public site

```bash
python3 scripts/publish_site.py
```

GitHub Pages: **Settings → Pages → Source = GitHub Actions**. Workflow: `.github/workflows/deploy-pages.yml`.

---

## Known limitations

| Limitation | Details |
|------------|---------|
| Free-tier RPC | Curve/Balancer discovery can stall; Uni-only windows are more practical on free plans |
| DEX tags | Evidence in **this block window** only; P2P holders stay `—` |
| Expand row | Shows **LP positions**, not swap history |
| V4 pool id | Portfolio “Pool” may be bytes32 poolId; custody is PoolManager |
| No `--incident-block` | Risk leans on concentration / withdrawals |
| No automated tests | Manual CLI validation |

See `SUPPORTED_PROTOCOLS.md` for contract addresses and notes.

---

<a name="中文"></a>

# 中文

## 概述

面向 **以太坊主网** 的代币流动性 / 崩盘分析工具：发现主流 DEX 池、索引成交与流动性、计算集中度与风险，输出 JSON、报告和本地 HTML 看板。

**当前范围：** 以太坊 + **Uniswap V1–V4**、**Curve**、**Balancer V2**。

线上站点：[https://jelly577.github.io/On-Chain-Token-Crash-Liquidity-Analysis/](https://jelly577.github.io/On-Chain-Token-Crash-Liquidity-Analysis/)

---

## 分析记录

| Token | 窗口 | 池子 | 持有者 | 风险 | 日期 | 目录 |
|-------|------|------|--------|------|------|------|
| uPEG 方向审计 | 25043020–25043311 | 1 V3 | 99 个交易发起地址 | 研究 | 2026-08-18 | `output-upeg-v3-7d/research-directional-flow/2026-05-07T12/` |
| uPEG | 25003546–25004000 | 10 (V2/V3/V4) | ~231 EOA | 0.4364 中 | 2026-07-28 | `output/` |
| SPX | 19000022–19000022 | 8 (V2+V3) | 3 | 0.1944 低 | 2026-07-18 | `output-spx-demo/` 等 |
| USDC | 19000000–19000050 | — | — | 0.0000 低 | — | `output-test/` |

### 近期发现（uPEG）

- 对已人工核验的 `2026-05-07 12:00 UTC` V3 小时桶做方向审计：48 个卖出侧、71 个买入侧 Swap，卖出总量 39.5356 uPEG、买入总量 30.2685 uPEG，带符号 Swap 净流入池 9.2671 uPEG。实际 uPEG Transfer 净流入与历史池余额增加都精确等于 10.106754360913178103 uPEG；0.83964 uPEG 的“Transfer 减 Swap”残差证明该代币/窗口不能只用 Swap 数量作为完整资金流账本。证据与解释边界见 `research-notes/upeg-directional-flow-audit.md`。
- 窗口内验证 **10** 个 Uniswap 池（1 V2 / 3 V3 / 6 V4）。配置已开 Curve/Balancer，但该代币本窗口流动性主要在 Uniswap。
- 重建 **36** 个 LP 仓位（V3/V4 tick；V4 份额 = 区间内 `L / StateView.getLiquidity`）。
- 持仓：Dune 发现地址 + RPC `balanceOf`；看板区分 **EOA / 合约 / 池账户**。
- **DEX 列**：按本窗口证据标 Uniswap / Curve / Balancer（LP、swap、与池转账、或同笔 tx 关联）。
- **点开一行**只看 LP 仓位，不等于 DEX 标签；悬停标签可见 `LP` / `Swap`。`—` = 本窗口无 DEX 关联（如纯转账）。
- 看板中的地址和 Pool ID 保持短格式；悬浮或键盘聚焦可查看全文，点击即可复制。Top Holders 图表悬浮柱子会显示完整地址与余额，点击柱子复制地址。合法主网地址提供 Etherscan 跳转，V4 bytes32 poolId 只提供查看与复制，避免错误跳转。
- 看板将“窗口内出现过的地址”与“余额已覆盖且为正的非池 Holder”分开统计，并公开余额查询覆盖率；TVL 文案按 `tvl_timeline_source` 动态显示，不再把事件累计重建误写成余额快照。
- 撤池表区分“已量化金额”“只有 liquidity delta 信号”和“无法映射”三种证据。V4 `ModifyLiquidity` 未提供 token amount 时显示 `Token amount not returned`，依赖金额的列显示 `Cannot calculate`，不再误写成 `0.0000`；真正测得的 0 仍保留为 0。

```bash
set -a && source .env && set +a
python3 -m src.cli analyze uPEG \
  --from-block 25003546 --to-block 25004000 \
  --output-dir output
python3 -m src.cli dashboard --output-dir output
```

---

## 快速开始

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ETH_RPC_URL="https://mainnet.infura.io/v3/YOUR_API_KEY"
# 可选: DUNE_API_KEY
```

| 命令 | 作用 |
|------|------|
| `analyze` | 完整流水线 |
| `discover-only` | 只发现/验证池 |
| `holdings` | 重跑持仓 |
| `dashboard` | 用已有数据重生成看板；可在本地刷新自适应钱包筛选 |
| `research-series` | 生成 typed `analysis_series.parquet`；可用 `--refresh-tvl` 刷新可归因的历史储备快照 |

```bash
python3 -m src.cli dashboard --output-dir output
# 只读本地 swaps，重算 P99 Notable Wallets，不请求 Dune/RPC
python3 -m src.cli dashboard --output-dir output --refresh-wallet-activity
# 生成按时间桶对齐的 OHLC/VWAP/TVL/成交量/LP 研究特征表
python3 -m src.cli research-series --output-dir output
# 正式研究 TVL 前建议执行（RPC 需支持历史区块）：
python3 -m src.cli research-series --output-dir output --refresh-tvl
python3 scripts/publish_site.py
```

大型事件、持仓、LP positions 和图表时间序列表正在迁移到 Parquet。默认仍生成兼容 JSON；
运行 `analyze` 时增加 `--artifact-format both`，会额外生成：

```text
tables/swaps.parquet
tables/transfers.parquet
tables/liquidity_events.parquet
tables/position_events.parquet
tables/holdings.parquet
tables/positions.parquet
tables/tvl_timeline.parquet
tables/volume_timeline.parquet
holdings_summary.json
```

独立运行 `holdings` 命令时，`both` 模式只额外生成 `tables/holdings.parquet`。

独立重建 dashboard 时会优先读取这些 Parquet 表；旧的 JSON-only 输出仍可直接使用。
在 `both` 模式下，`metrics.json` 不再重复保存完整 TVL/volume 图表数组。

这些 Parquet/DuckDB 文件只作为本地分析数据，默认不提交到 Git。

也支持直接复用已保存的 Dune 池列表，跳过在线发现（例如
`output-dune-crv-demo/pools.json`）：

```bash
python3 -m src.cli discover-only 0xD533a949740bb3306d119CC777fa900bA034cd52 \
  --pools-file output-dune-crv-demo/pools.json \
  --from-block 22000000 --to-block 22005000
```

---

## 完成度一览

| 模块 | 状态 |
|------|------|
| Uniswap V1–V4 | ✅ |
| Curve、Balancer V2 | ✅（免费 RPC 上可能很慢） |
| 事件索引续扫、持仓、风险、报告 | ✅ |
| EOA/合约标签、看板点开 LP | ✅ |
| 持有者 DEX 来源标签 | ✅（仅本窗口证据） |
| 深度穿透路由/受益人 | ❌ |
| 多链、实时监控 | ❌ |

---

## 看板怎么读（DEX vs 展开）

| 位置 | 含义 |
|------|------|
| 行上 DEX 标签 | 本窗口是否碰过该 DEX（多为 Swap） |
| 点开展开 | **仅 LP 仓位**；Pool 列为 pair/pool 地址（V4 多为 poolId） |
| `—` | 本窗口找不到 DEX 关联，不是“一定不是 Uniswap 用户” |

---

## 公开站点

`python3 scripts/publish_site.py` → `site/`。GitHub Pages 选 **GitHub Actions** 作为 Source。

---

## 已知限制

| 限制 | 说明 |
|------|------|
| 免费 RPC | Curve/Balancer 发现易卡住 |
| DEX 标签 | 只看分析窗口内证据 |
| 展开行 | 不是成交明细，只是 LP |
| 无 incident-block | 风险偏结构信号 |
| 协议细节 | 见 `SUPPORTED_PROTOCOLS.md` |
