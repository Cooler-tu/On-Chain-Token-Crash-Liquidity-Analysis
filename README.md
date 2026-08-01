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
| uPEG | 25003546–25004000 | 10 (V2/V3/V4) | ~231 EOA | 0.4364 MEDIUM | 2026-07-28 | `output/` |
| SPX | 19000022–19000022 | 8 (V2+V3) | 3 | 0.1944 LOW | 2026-07-18 | `output/` (superseded) / `output-spx-demo/` |
| USDC | 19000000–19000050 | — | — | 0.0000 LOW | — | `output-test/` |

### Recent Findings (uPEG)

- Window `25003546–25004000`: **10** verified Uniswap pools (1 V2 / 3 V3 / 6 V4). Curve/Balancer enabled in config; this token’s liquidity in-window was Uniswap-only.
- **36** LP positions reconstructed (V3/V4 tick math; V4 share = in-range `L / StateView.getLiquidity`).
- Holdings via Dune address discovery + RPC `balanceOf`; dashboard tags **EOA / contract / pool**.
- Dashboard **DEX column**: Uniswap / Curve / Balancer from LP, swaps, pool transfers, or same-tx linkage. Expand row → **LP portfolio only** (not the same as the DEX tag).
- Hover DEX badge for `LP` vs `Swap`. `—` = no DEX link in this window (e.g. P2P only).

```bash
set -a && source .env && set +a
python3 -m src.cli analyze uPEG \
  --from-block 25003546 --to-block 25004000 \
  --output-dir output
python3 -m src.cli dashboard --output-dir output
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
| `dashboard` | Regenerate `dashboard.html` from existing output |

```bash
python3 -m src.cli dashboard --output-dir output
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

> Indexing is **resumable** via `event_indexer_checkpoint.json`. Change token/window or delete checkpoint to start clean.

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
| `swaps.json` / `liquidity_events.json` / `transfers.json` | Indexed events |
| `events_all.json` | Combined stream |
| `positions.json` / `portfolios.json` | LP positions / by-owner |
| `address_dex.json` | Per-address DEX protocols + LP/Swap roles |
| `holdings.json` | Holders + pool flags |
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
| uPEG | 25003546–25004000 | 10 (V2/V3/V4) | ~231 EOA | 0.4364 中 | 2026-07-28 | `output/` |
| SPX | 19000022–19000022 | 8 (V2+V3) | 3 | 0.1944 低 | 2026-07-18 | `output-spx-demo/` 等 |
| USDC | 19000000–19000050 | — | — | 0.0000 低 | — | `output-test/` |

### 近期发现（uPEG）

- 窗口内验证 **10** 个 Uniswap 池（1 V2 / 3 V3 / 6 V4）。配置已开 Curve/Balancer，但该代币本窗口流动性主要在 Uniswap。
- 重建 **36** 个 LP 仓位（V3/V4 tick；V4 份额 = 区间内 `L / StateView.getLiquidity`）。
- 持仓：Dune 发现地址 + RPC `balanceOf`；看板区分 **EOA / 合约 / 池账户**。
- **DEX 列**：按本窗口证据标 Uniswap / Curve / Balancer（LP、swap、与池转账、或同笔 tx 关联）。
- **点开一行**只看 LP 仓位，不等于 DEX 标签；悬停标签可见 `LP` / `Swap`。`—` = 本窗口无 DEX 关联（如纯转账）。

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
| `dashboard` | 用已有数据重生成看板 |

```bash
python3 -m src.cli dashboard --output-dir output
python3 scripts/publish_site.py
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
