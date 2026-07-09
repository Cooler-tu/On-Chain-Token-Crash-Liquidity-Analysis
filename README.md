# On-Chain Token Crash & Liquidity Analysis (Task 1–4)

[English](#english) | [中文](#中文)

---

<a name="english"></a>

# English

## Overview

On-chain token liquidity analysis system.

**Current progress:** Tasks 1–4 are complete. Given an ERC-20 token address, the system automatically runs **protocol registry → token profiling → pool discovery → pool verification** and outputs structured JSON.

**Scope:** Ethereum Mainnet + Uniswap V2/V3.

---

## Quick Start

### 1. Install Dependencies

```bash
cd on-chain-token-crash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure RPC

```bash
export ETH_RPC_URL="https://eth-mainnet.g.alchemy.com/v2/YOUR_API_KEY"
```

> **Note:** Exhaustive event scanning (`eth_getLogs`) requires an RPC with a large block-range limit. Alchemy Free tier allows at most **10 blocks per `eth_getLogs` request**, which causes exhaustive mode to fail. See [Known Limitations](#known-limitations).

### 3. Run Analysis

```bash
python3 -m src.cli 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  --from-block 10000000 \
  --to-block $(cast block-number --rpc-url "$ETH_RPC_URL")
```

**CLI Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `TOKEN_ADDRESS` | Target token contract address (positional) | required |
| `--from-block` | Start block for scanning | `19000000` |
| `--to-block` | End block (integer only, no `latest`) | `19100000` |
| `--rpc-url` | RPC URL, or set `ETH_RPC_URL` | — |
| `--output-dir` | Output directory | `output` |

> There is only one CLI command — do **not** pass an `analyze` subcommand.

### 4. Check Output

```text
output/
├── token_profile.json      # Task 2: token profile
├── pool_candidates.json    # Task 3: pool candidates
└── verified_pools.json     # Task 4: verified pools
```

---

## Implemented Features (Task 1–4)

### Task 1 — Protocol Registry

Maintains a whitelist of trusted DEX protocol deployments for discovery and verification.

| File | Description |
|------|-------------|
| `config/protocols.ethereum.yaml` | Protocol config (Factory, Router, PositionManager, quote assets, fee tiers) |
| `src/registry/loader.py` | YAML loader and query API |
| `abis/` | Uniswap V2/V3 and ERC-20 ABIs |

**Whitelisted Factories:**

| Protocol | Factory |
|----------|---------|
| Uniswap V2 | `0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f` |
| Uniswap V3 | `0x1F98431c8aD98523631AE4a59f267346ea31F984` |

**Key APIs:**

- `load_registry()` — load YAML config
- `get_enabled_protocols()` — list enabled protocol deployments
- `is_trusted_factory(addr)` — check if Factory is whitelisted
- `get_quote_assets()` — quote assets (WETH/USDC/USDT/DAI)
- `get_v3_fees()` — V3 fee tier list

### Task 2 — Token Profiler

Validates the target token on-chain and reads ERC-20 metadata.

| File | Description |
|------|-------------|
| `src/token/profiler.py` | Profiling logic |
| Output | `token_profile.json` |

**Checks:**

- Contract bytecode exists
- ERC-20 metadata: `name`, `symbol`, `decimals`, `totalSupply`
- Proxy detection (EIP-1967 / EIP-1822)
- Behavior flags: `minting`, `pausing`, `blacklisting`, `fee_on_transfer`, `rebasing`
- Graceful fallback for non-standard ERC-20

### Task 3 — Pool Discovery

Discovers all Uniswap V2/V3 liquidity pools containing the target token.

| File | Description |
|------|-------------|
| `src/discovery/engine.py` | Orchestration engine |
| `src/discovery/uniswap_v2.py` | V2 discovery adapter |
| `src/discovery/uniswap_v3.py` | V3 discovery adapter |
| `src/discovery/log_utils.py` | Chunked `eth_getLogs` + deduplication |
| `src/discovery/base.py` | Adapter base class |
| Output | `pool_candidates.json` |

**Discovery Modes:**

| Mode | V2 | V3 | RPC Method |
|------|----|----|------------|
| **Fast** | `factory.getPair(token, quote)` | `factory.getPool(token, quote, fee)` | `eth_call` |
| **Exhaustive** | Index `PairCreated` events | Index `PoolCreated` events | `eth_getLogs` |

Fast mode locates main pools via quote assets (WETH/USDC/USDT/DAI). Exhaustive mode scans historical events and can find pools paired with obscure tokens.

### Task 4 — Pool Verification

Cross-validates each candidate pool on-chain to confirm it is an official Uniswap deployment.

| File | Description |
|------|-------------|
| `src/verification/verifier.py` | Verification logic |
| Output | `verified_pools.json` |

**Verification Steps:**

1. Factory must be whitelisted
2. Pool address has bytecode
3. On-chain `factory()` matches whitelist
4. `token0()` / `token1()` correct; target token present
5. **V2:** `getPair` cross-check + `getReserves()`
6. **V3:** `fee()`, `tickSpacing()`, `getPool()`, `slot0()`, `liquidity()`
7. Factory creation event provenance (`PairCreated` / `PoolCreated`)
8. Custody model resolution (V2: Pair; V3: Pool + PositionManager)

**Confidence score:** `passed_checks / total_checks`; `verified=true` when ≥ 0.3.

---

## Project Structure

```text
on-chain-token-crash/
├── README.md
├── requirements.txt
├── config/
│   └── protocols.ethereum.yaml       # Task 1
├── abis/                             # Task 1
├── src/
│   ├── cli.py                        # CLI entry (Tasks 2–4)
│   ├── client.py                     # Web3 + ABI loader
│   ├── models.py                     # Shared data models
│   ├── registry/loader.py            # Task 1
│   ├── token/profiler.py             # Task 2
│   ├── discovery/                    # Task 3
│   ├── verification/verifier.py      # Task 4
│   ├── indexer/                      # Task 5 (not implemented)
│   ├── analysis/                     # Task 6–7 (not implemented)
│   └── report/                       # Task 8 (not implemented)
└── output/
```

---

## End-to-End Pipeline

```text
Token Address
    │
    ▼
Task 2: profile_token()          → token_profile.json
    │
    ▼
Task 3: discover_pools()         → pool_candidates.json
    │   ├── UniswapV2Adapter (fast + exhaustive)
    │   └── UniswapV3Adapter (fast + exhaustive)
    │
    ▼
Task 4: verify_pools()           → verified_pools.json
    │   ├── Factory whitelist check
    │   ├── On-chain cross-validation
    │   └── Confidence scoring
    │
    ▼
Done
```

---

## Example: USDC/WETH

Use USDC as a known mainnet token to validate Milestone 1 pool discovery.

### Manual Fast-Path Check with cast

```bash
# V2 USDC/WETH Pair
cast call 0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f \
  "getPair(address,address)(address)" \
  0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  --rpc-url "$ETH_RPC_URL"
# Expected: 0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc

# V3 USDC/WETH 0.05% Pool
cast call 0x1F98431c8aD98523631AE4a59f267346ea31F984 \
  "getPool(address,address,uint24)(address)" \
  0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  500 \
  --rpc-url "$ETH_RPC_URL"
# Expected: 0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640

# V3 USDC/WETH 0.30% Pool
cast call 0x1F98431c8aD98523631AE4a59f267346ea31F984 \
  "getPool(address,address,uint24)(address)" \
  0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  3000 \
  --rpc-url "$ETH_RPC_URL"
# Expected: 0x8ad599c3A0ff1De082011EFDDc58f1908eb6e6D8
```

### Full CLI Run

```bash
python3 -m src.cli 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  --from-block 10000000 \
  --to-block 13000000
```

**Expected output:**

```text
Profiling token 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 ...
  Symbol: USDC, Decimals: 6
Discovering pools ...
  Found N candidate(s)
Verifying pools ...
  OK  0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc
  OK  0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640
  OK  0x8ad599c3A0ff1De082011EFDDc58f1908eb6e6D8
  ...
Done. Output written to .../output
```

---

## Output Format

### token_profile.json

```json
{
  "chain_id": 1,
  "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
  "symbol": "USDC",
  "name": "USD Coin",
  "decimals": 6,
  "is_contract": true,
  "proxy_address": null,
  "implementation_address": null,
  "behavior_flags": [],
  "total_supply": 50458942596192931
}
```

### pool_candidates.json

```json
{
  "pools": [ { "pool_address": "0x...", "protocol": "uniswap", "version": "v2", "verified": false } ],
  "protocols_used": ["uniswap_v2", "uniswap_v3"],
  "errors": []
}
```

### verified_pools.json

```json
[
  {
    "pool_address": "0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc",
    "protocol": "uniswap",
    "version": "v2",
    "token0": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "token1": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "custody_address": "0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc",
    "verified": true,
    "verification_confidence": 0.9091
  }
]
```

---

<a name="known-limitations"></a>

## Known Limitations

| Limitation | Details |
|------------|---------|
| **Alchemy Free `eth_getLogs`** | Max 10 blocks per request; code uses 2000-block chunks, min retry 500 → exhaustive mode fails with 400 errors |
| **No automated tests** | Validation must be run manually |

---

<a name="中文"></a>

# 中文

## 概述
链上代币流动性分析系统

目前进度: task1~4，已完成给定一个 ERC-20 代币地址，自动完成**协议注册 → 代币画像 → 池子发现 → 池子验证**，并输出结构化 JSON。

**当前范围：** 以太坊主网 + Uniswap V2/V3。

---

## 快速开始

### 1. 安装依赖

```bash
cd on-chain-token-crash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置 RPC

```bash
export ETH_RPC_URL="https://eth-mainnet.g.alchemy.com/v2/YOUR_API_KEY"
```

> **注意：** Exhaustive 事件扫描（`eth_getLogs`）需要 RPC 支持较大的 block range。Alchemy 免费档每次 `eth_getLogs` 最多 **10 个区块**，会导致 exhaustive 模式失败。详见 [已知限制](#已知限制)。

### 3. 运行分析

```bash
python3 -m src.cli 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  --from-block 10000000 \
  --to-block $(cast block-number --rpc-url "$ETH_RPC_URL")
```

**参数说明：**

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `TOKEN_ADDRESS` | 目标代币合约地址（positional） | 必填 |
| `--from-block` | 扫描起始区块 | `19000000` |
| `--to-block` | 扫描结束区块（必须是整数，不支持 `latest`） | `19100000` |
| `--rpc-url` | RPC URL，也可通过环境变量 `ETH_RPC_URL` 设置 | — |
| `--output-dir` | 输出目录 | `output` |

> CLI 只有一个命令，**不要**写 `analyze` 子命令。

### 4. 查看输出

```text
output/
├── token_profile.json      # Task 2：代币画像
├── pool_candidates.json    # Task 3：候选池列表
└── verified_pools.json     # Task 4：验证后的池列表
```

---

## 已实现功能（Task 1–4）

### Task 1 — 协议注册表

维护可信 DEX 协议部署的白名单，供发现和验证阶段使用。

| 文件 | 说明 |
|------|------|
| `config/protocols.ethereum.yaml` | 协议配置（Factory、Router、PositionManager、quote 资产、fee tiers） |
| `src/registry/loader.py` | YAML 加载与查询 API |
| `abis/` | Uniswap V2/V3 及 ERC-20 合约 ABI |

**当前白名单 Factory：**

| 协议 | Factory |
|------|---------|
| Uniswap V2 | `0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f` |
| Uniswap V3 | `0x1F98431c8aD98523631AE4a59f267346ea31F984` |

**核心 API：**

- `load_registry()` — 加载 YAML 配置
- `get_enabled_protocols()` — 返回已启用的协议部署
- `is_trusted_factory(addr)` — 判断 Factory 是否在白名单
- `get_quote_assets()` — 返回 quote 资产列表（WETH/USDC/USDT/DAI）
- `get_v3_fees()` — 返回 V3 fee tier 列表

### Task 2 — 代币画像

对目标代币做链上校验与元数据读取。

| 文件 | 说明 |
|------|------|
| `src/token/profiler.py` | 代币画像逻辑 |
| 输出 | `token_profile.json` |

**检查项：**

- 地址是否有合约 bytecode
- ERC-20 元数据：`name`、`symbol`、`decimals`、`totalSupply`
- 代理合约检测（EIP-1967 / EIP-1822）
- 异常行为标记：`minting`、`pausing`、`blacklisting`、`fee_on_transfer`、`rebasing`
- 非标准 ERC-20 字段读取失败时不会崩溃

### Task 3 — 池子发现

在 Uniswap V2/V3 中发现包含目标代币的所有流动性池。

| 文件 | 说明 |
|------|------|
| `src/discovery/engine.py` | 编排引擎，调度各协议 adapter |
| `src/discovery/uniswap_v2.py` | V2 发现 adapter |
| `src/discovery/uniswap_v3.py` | V3 发现 adapter |
| `src/discovery/log_utils.py` | 分块拉取 `eth_getLogs`、池子去重 |
| `src/discovery/base.py` | Adapter 基类接口 |
| 输出 | `pool_candidates.json` |

**两种发现模式：**

| 模式 | V2 | V3 | RPC 方法 |
|------|----|----|----------|
| **Fast** | `factory.getPair(token, quote)` | `factory.getPool(token, quote, fee)` | `eth_call` |
| **Exhaustive** | 索引 `PairCreated` 事件 | 索引 `PoolCreated` 事件 | `eth_getLogs` |

Fast 模式通过 quote 资产（WETH/USDC/USDT/DAI）快速定位主池；Exhaustive 模式扫描历史事件，能发现与冷门代币配对的池。

### Task 4 — 池子验证

对候选池做链上交叉验证，确认其为官方 Uniswap 部署。

| 文件 | 说明 |
|------|------|
| `src/verification/verifier.py` | 验证逻辑 |
| 输出 | `verified_pools.json` |

**验证步骤：**

1. Factory 必须在白名单内
2. 池地址有 bytecode
3. 链上 `factory()` 与白名单 Factory 一致
4. `token0()` / `token1()` 正确，且包含目标代币
5. **V2**：`getPair` 交叉验证 + `getReserves()`
6. **V3**：`fee()`、`tickSpacing()`、`getPool()`、`slot0()`、`liquidity()`
7. Factory 创建事件 provenance（`PairCreated` / `PoolCreated`）
8. 托管模型解析（V2 custody = Pair；V3 custody = Pool + PositionManager）

**置信度评分：** `通过检查数 / 总检查数`，≥ 0.3 标记为 `verified=true`。

---

## 项目结构

```text
on-chain-token-crash/
├── README.md
├── requirements.txt
├── config/
│   └── protocols.ethereum.yaml       # Task 1
├── abis/                             # Task 1
├── src/
│   ├── cli.py                        # CLI 入口（串联 Task 2–4）
│   ├── client.py                     # Web3 连接与 ABI 加载
│   ├── models.py                     # 共享数据模型
│   ├── registry/loader.py            # Task 1
│   ├── token/profiler.py             # Task 2
│   ├── discovery/                    # Task 3
│   ├── verification/verifier.py      # Task 4
│   ├── indexer/                      # Task 5（未实现）
│   ├── analysis/                     # Task 6–7（未实现）
│   └── report/                       # Task 8（未实现）
└── output/
```

---

## 端到端流程

```text
Token Address
    │
    ▼
Task 2: profile_token()          → token_profile.json
    │
    ▼
Task 3: discover_pools()         → pool_candidates.json
    │   ├── UniswapV2Adapter (fast + exhaustive)
    │   └── UniswapV3Adapter (fast + exhaustive)
    │
    ▼
Task 4: verify_pools()           → verified_pools.json
    │   ├── Factory 白名单检查
    │   ├── 链上交叉验证
    │   └── 置信度评分
    │
    ▼
Done
```

---

## 验证示例：USDC/WETH

以 USDC 为主网已知代币，验证 Milestone 1 的池发现能力。

### 用 cast 手动验证 Fast 路径

```bash
# V2 USDC/WETH Pair
cast call 0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f \
  "getPair(address,address)(address)" \
  0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  --rpc-url "$ETH_RPC_URL"
# 期望: 0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc

# V3 USDC/WETH 0.05% Pool
cast call 0x1F98431c8aD98523631AE4a59f267346ea31F984 \
  "getPool(address,address,uint24)(address)" \
  0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  500 \
  --rpc-url "$ETH_RPC_URL"
# 期望: 0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640

# V3 USDC/WETH 0.30% Pool
cast call 0x1F98431c8aD98523631AE4a59f267346ea31F984 \
  "getPool(address,address,uint24)(address)" \
  0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 \
  3000 \
  --rpc-url "$ETH_RPC_URL"
# 期望: 0x8ad599c3A0ff1De082011EFDDc58f1908eb6e6D8
```

### 用 CLI 跑完整流程

```bash
python3 -m src.cli 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 \
  --from-block 10000000 \
  --to-block 13000000
```

**期望终端输出：**

```text
Profiling token 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 ...
  Symbol: USDC, Decimals: 6
Discovering pools ...
  Found N candidate(s)
Verifying pools ...
  OK  0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc
  OK  0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640
  OK  0x8ad599c3A0ff1De082011EFDDc58f1908eb6e6D8
  ...
Done. Output written to .../output
```

---

## 输出格式

### token_profile.json

```json
{
  "chain_id": 1,
  "address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
  "symbol": "USDC",
  "name": "USD Coin",
  "decimals": 6,
  "is_contract": true,
  "proxy_address": null,
  "implementation_address": null,
  "behavior_flags": [],
  "total_supply": 50458942596192931
}
```

### pool_candidates.json

```json
{
  "pools": [ { "pool_address": "0x...", "protocol": "uniswap", "version": "v2", "verified": false } ],
  "protocols_used": ["uniswap_v2", "uniswap_v3"],
  "errors": []
}
```

### verified_pools.json

```json
[
  {
    "pool_address": "0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc",
    "protocol": "uniswap",
    "version": "v2",
    "token0": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "token1": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "custody_address": "0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc",
    "verified": true,
    "verification_confidence": 0.9091
  }
]
```

---

<a name="已知限制"></a>

## 已知限制

| 限制 | 说明 |
|------|------|
| **Alchemy 免费档 `eth_getLogs`** | 每次最多 10 个区块；代码默认 chunk 2000，最小只减到 500 → exhaustive 模式会 400 报错失败 |
| **无自动化测试** | 验收需手动运行 |
