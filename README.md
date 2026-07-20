# On-Chain Token Crash & Liquidity Analysis

[English](#english) | [中文](#中文)

---

<a name="english"></a>

# English

## Overview

End-to-end **Ethereum mainnet** tool for analyzing a token’s Uniswap liquidity: discover pools, index swaps / liquidity / transfers, estimate concentration and crash-related risk, then emit JSON, Markdown, and a local HTML dashboard.

**Input:** token address, symbol, or name + block window  
**Output:** verified pools, event data, holdings table, risk score, `report.md`, `dashboard.html`

**Scope today:** Ethereum (`chain_id=1`) + **Uniswap V2 / V3** (V4 discovery exists but is secondary).

---

## Quick Start

```bash
cd on-chain-token-crash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export ETH_RPC_URL="https://mainnet.infura.io/v3/YOUR_API_KEY"
# or Alchemy / other archive-capable RPC
```

### Full pipeline

```bash
python3 -m src.cli analyze USDC \
  --from-block 19000000 \
  --to-block 19000050 \
  --output-dir output
```

Address also works: `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48`.

Open the result page:

```bash
open output/dashboard.html
```

### Other commands

| Command | Purpose |
|---------|---------|
| `analyze` | Full 12-step pipeline (default entry) |
| `discover-only` | Profile + discover + verify pools only |
| `holdings` | Rebuild holdings / pool-ID tables from transfers |
| `dashboard` | Regenerate `dashboard.html` from existing `output/` |

```bash
python3 -m src.cli discover-only USDC --from-block 19000000 --to-block 19100000
python3 -m src.cli holdings USDC --from-block 19000000 --to-block 19000050
python3 -m src.cli dashboard --output-dir output
```

### Important `analyze` options

| Option | Description | Default |
|--------|-------------|---------|
| `TOKEN` | Address, symbol, or name | required |
| `--from-block` / `--to-block` | Analysis window (integers only) | `19000000` / `19100000` |
| `--incident-block` | Optional crash block for temporal / market-impact scoring | `0` |
| `--fast-mode` | Skip heavy exhaustive indexing paths | `false` |
| `--pick N` | Disambiguate name matches | `0` |
| `--rpc-url` | Override `ETH_RPC_URL` | — |
| `--output-dir` | Artifacts directory | `output` |

> Indexing is **resumable**: same `output_dir` + token + block window continues from `event_indexer_checkpoint.json` / `indexer_cache/`. Change token or window, or delete those files, to start clean.

---

## Pipeline (`analyze`)

```text
token (address | symbol | name)
    → resolve + profile
    → discover pools (fast + exhaustive)
    → verify pools
    → index Swap / Mint|Burn / PM liquidity / Transfers  (checkpointed)
    → LP positions (best-effort)
    → address labels + deployer lookup
    → metrics (on-chain TVL, concentration, withdrawals)
    → timeline
    → risk score
    → report.md
    → holdings + pool identification
    → dashboard.html
```

---

## What works vs what’s incomplete

| Area | Status |
|------|--------|
| Protocol registry (V2/V3) | Done |
| Token profile + name/symbol resolve | Done |
| Pool discovery + verification | Done |
| Event indexing with resume | Done |
| Holdings + mark pool accounts | Done (RPC) |
| Local dashboard + report | Done |
| Pool-level liquidity / TVL / risk | Done (usable) |
| **LP holder reconstruction / LP concentration** | **Partial** — often empty on short windows, especially V3 NFTs |
| Uniswap V1 / V4 / other DEXes | Not productized |
| Multi-chain | Not productized |
| Public Tailscale / hosted dashboard | Not done |
| Dune integration | Not done |

---

## Project structure

```text
On-Chain-Token-Crash-Liquidity-Analysis/
├── README.md
└── on-chain-token-crash/
    ├── requirements.txt
    ├── config/protocols.ethereum.yaml
    ├── abis/
    ├── src/
    │   ├── cli.py                 # analyze / discover-only / holdings / dashboard
    │   ├── client.py
    │   ├── models.py
    │   ├── registry/              # protocol whitelist
    │   ├── token/                 # profiler + name resolver
    │   ├── discovery/             # V2 / V3 (/ V4 adapter)
    │   ├── verification/
    │   ├── indexer/               # resumable eth_getLogs indexing
    │   ├── analysis/              # positions, labels, metrics, risk, holdings, dashboard
    │   └── report/
    └── output/                    # run artifacts (gitignored locally as needed)
```

---

## Main outputs

| File | Contents |
|------|----------|
| `token_profile.json` | Symbol, decimals, flags |
| `pool_candidates.json` / `verified_pools.json` | Discovered / verified pools |
| `swaps.json` / `liquidity_events.json` / `transfers.json` | Indexed events |
| `events_all.json` | Combined event stream |
| `positions.json` / `position_summary.json` | LP positions (may be empty) |
| `metrics.json` / `tvl_timeline.json` | TVL, concentration, withdrawals |
| `risk_assessment.json` | Explainable risk score |
| `holdings.json` / `holdings_table.csv` | Token holders |
| `pool_identification_table.csv` | Addresses tagged as pools |
| `report.md` | Narrative report |
| `dashboard.html` | Local visualization |

---

## Example (short smoke window)

```bash
python3 -m src.cli analyze USDC \
  --from-block 19000000 \
  --to-block 19000050 \
  --output-dir output
```

Expect: verified USDC pools, non-zero swaps in an active window, metrics with on-chain TVL, a non-zero risk score when concentration / withdrawals exist, and `dashboard.html`.

For crash studies, pass `--incident-block` and use a window that covers the event (not only 50 blocks).

---

## Public site

The analysis dashboard can be published as a static site (built with Chart.js, zero server backend needed).

```bash
# Build the public site from all output directories
python3 scripts/publish_site.py

# Build and preview locally
python3 scripts/publish_site.py --serve
```

The generated site lives in `site/` and is ready to deploy to [GitHub Pages](https://pages.github.com/), Vercel, Netlify, or any static host.

### GitHub Pages (one-time setup)

1. Go to your repo **Settings → Pages**
2. Under **Source**, select **GitHub Actions**
3. Push to `main` — the included `.github/workflows/deploy-pages.yml` will build and deploy automatically

Your site will be available at `https://<username>.github.io/<repo-name>/`.

---

## Known limitations

| Limitation | Details |
|------------|---------|
| **RPC `eth_getLogs` limits** | Free Alchemy (~10 blocks/request) is very slow; Infura/paid nodes work better. Chunk size adapts downward on rejection. |
| **LP positions** | V2 needs LP Transfers or `balanceOf` candidates; V3 needs PositionManager `tokenId→pool` mapping. Short windows often yield **0 positions** → `lp_concentration = 0`. |
| **PositionManager scan cost** | Global Uniswap V3 NFT manager indexing is expensive relative to pool-only logs. |
| **Risk without `--incident-block`** | Temporal / market-impact features are softened or skipped; score leans on pool concentration and withdrawal counts. |
| **No automated test suite** | Validate with manual CLI runs. |

See also `on-chain-token-crash/SUPPORTED_PROTOCOLS.md` for protocol notes.

---

<a name="中文"></a>

# 中文
### Analysis Log

| Token | Chain | Block Window | Pools | Holders | Risk Score | Level | Dir |
|-------|-------|-------------|-------|---------|-----------|-------|-----|
| SPX | Ethereum | 19000022–19000022 | 8 (V2+V3) | 3 | 0.1944 | LOW | `output/` |
| USDC | Ethereum | 19000000–19000050 | — | — | 0.0000 | LOW | `output-test/` |


## 概述

面向 **以太坊主网** 的链上代币流动性 / 崩盘分析工具：输入代币（地址 / 符号 / 名称）和区块窗口，自动发现 Uniswap 池、索引成交与流动性事件、计算集中度与风险分，并输出 JSON、Markdown 报告和本地 HTML 看板。

**当前范围：** 以太坊 + **Uniswap V2 / V3**（V1 V4还未实现）。

---

## 快速开始

```bash
cd on-chain-token-crash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export ETH_RPC_URL="https://mainnet.infura.io/v3/YOUR_API_KEY"
```

### 完整分析

```bash
python3 -m src.cli analyze USDC \
  --from-block 19000000 \
  --to-block 19000050 \
  --output-dir output

open output/dashboard.html
```

### 子命令

| 命令 | 作用 |
|------|------|
| `analyze` | 完整 12 步流水线 |
| `discover-only` | 只做画像 + 发现 + 验证池 |
| `holdings` | 单独重跑持仓 / 池账户识别 |
| `dashboard` | 根据已有 `output/` 重新生成看板 |

### 常用参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `TOKEN` | 地址 / 符号 / 名称 | 必填 |
| `--from-block` / `--to-block` | 分析窗口（整数） | `19000000` / `19100000` |
| `--incident-block` | 崩盘区块（可选，影响时间邻近与冲击特征） | `0` |
| `--fast-mode` | 跳过部分重索引 | `false` |
| `--pick N` | 名称多匹配时选第 N 个 | `0` |
| `--output-dir` | 输出目录 | `output` |

索引支持**断点续扫**：同一 `output_dir` + 同一代币 + 同一窗口会从 checkpoint / `indexer_cache/` 继续。换代币或窗口时请清理这些文件。

---

## 流水线（`analyze`）

```text
代币解析与画像
  → 池发现与验证
  → 事件索引（可续扫）
  → LP 仓位（尽力而为）
  → 地址标签 / deployer
  → 指标（链上 TVL、集中度、撤池）
  → 时间线与风险分
  → report.md
  → 持仓分析
  → dashboard.html
```

---

## 完成度一览

| 模块 | 状态 |
|------|------|
| 协议注册、代币画像、名称解析 | ✅ |
| 池发现 / 验证、事件索引续扫 | ✅ |
| 持仓表、池账户识别、本地看板与报告 | ✅ |
| **池级**流动性 / TVL / 风险 | ✅ 可用 |
| **LP 持仓重建 / LP 集中度** | ⚠️ 不完整（短窗口常为 0，V3 NFT 尤弱） |
| V1/V4、其他 DEX、多链 | ❌ |
| Tailscale 公网看板、Dune | ❌ |

---

## 主要产出

| 文件 | 内容 |
|------|------|
| `verified_pools.json` | 验证后的池 |
| `swaps.json` / `liquidity_events.json` / `transfers.json` | 事件 |
| `metrics.json` / `risk_assessment.json` | 指标与风险 |
| `holdings.json` / CSV | 持币与池识别 |
| `report.md` / `dashboard.html` | 报告与可视化 |
| `positions.json` | LP 仓位（可能为空） |

---

## 公开站点

分析看板可以发布为静态站点（基于 Chart.js，无需后端服务）。

```bash
# 从所有 output 目录构建公开站点
python3 scripts/publish_site.py

# 构建并在本地预览
python3 scripts/publish_site.py --serve
```

生成的站点在 `site/` 目录中，可直接部署到 [GitHub Pages](https://pages.github.com/)、Vercel、Netlify 或任何静态托管服务。

### GitHub Pages（一次性配置）

1. 进入仓库 **Settings → Pages**
2. 在 **Source** 中选择 **GitHub Actions**
3. 推送到 `main` 分支 —— 项目自带的 `.github/workflows/deploy-pages.yml` 会自动构建并部署

站点将可通过 `https://<用户名>.github.io/<仓库名>/` 访问。

---
### 分析记录

| Token | 链 | 区块范围 | 池子 | 持有者 | 风险值 | 等级 | 目录 |
|-------|-----|---------|------|--------|-------|------|------|
| SPX | Ethereum | 19000022–19000022 | 8 (V2+V3) | 3 | 0.1944 | 低 | `output/` |
| USDC | Ethereum | 19000000–19000050 | — | — | 0.0000 | 低 | `output-test/` |


## 已知限制

| 限制 | 说明 |
|------|------|
| RPC `eth_getLogs` | 免费 Alchemy 很慢；建议 Infura / 付费节点 |
| LP 仓位 | 短窗口或未映射的 PM 事件会导致 `positions` 为空、`lp_concentration=0` |
| 无 `--incident-block` | 风险分主要靠池集中度与撤池次数等结构信号 |
| 无自动化测试 | 需手动跑 CLI 验收 |

协议细节见 `on-chain-token-crash/SUPPORTED_PROTOCOLS.md`。
