# Supported Protocols & DeFi Integrations

> 本文件记录当前系统已支持的 DeFi 协议及其版本、合约地址、支持状态。
> 目标是持续扩展支持的协议数量，量变达到质变。

---

## Supported Protocols Overview

| # | Protocol | Version | Architecture | Status | Notes |
|---|----------|---------|-------------|--------|-------|
| 1 | Uniswap | V2 | Direct Pair | ✅ 完整支持 | Factory: `0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f` |
| 2 | Uniswap | V3 | Concentrated Pool | ✅ 完整支持 | Factory: `0x1F98431c8aD98523631AE4a59f267346ea31F984` |
| 3 | Uniswap | V4 | Singleton | ✅ 完整支持 | PoolManager + StateView + PositionManager + 5k块穷举扫描 |
| 4 | Uniswap | V1 | ETH-ERC20 Exchange | ✅ 完整支持 | `getExchange` 发现 + LP 份额快照 + 事件索引 |
| 5 | Curve | V1/V2 | StableSwap/CryptoSwap | ✅ 完整支持 | Registry-based发现; x³y+y³x=k / crypto invariant |
| 6 | Balancer | V2 | Weighted Pool | ✅ 完整支持 | Vault架构; 多代币加权池; Vault Swap事件发现 |

## Uniswap V2

- **状态**: ✅ 完整支持
- **Factory**: `0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f`
- **Router**: `0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D`
- **部署区块**: 10000835
- **池子识别**: `getPair()` 快速发现 + `PairCreated` 事件穷举发现
- **事件索引**: Swap, Mint, Burn

## Uniswap V3

- **状态**: ✅ 完整支持
- **Factory**: `0x1F98431c8aD98523631AE4a59f267346ea31F984`
- **Router**: `0xE592427A0AEce92De3Edee1F18E0157C05861564`
- **Position Manager**: `0xC36442b4a4522E871399CD717aBDD847Ab11FE88`
- **部署区块**: 12369621
- **池子识别**: `getPool()` 快速发现 + `PoolCreated` 事件穷举发现
- **事件索引**: Swap, Mint, Burn, Collect
- **支持费率**: 100, 500, 3000, 10000

## Uniswap V4

- **状态**: ✅ 完整支持
- **PoolManager**: `0x000000000004444c5dc75cB358380D2e3dE08A90`
- **PositionManager**: `0xbD216513d74C8cf14cf4747E6AaA6420FF64ee9e`
- **StateView**: `0x7ffe42c4a5deea5b0fec41c94c136cf115597227`
- **部署区块**: 21688329
- **架构**: Singleton；池子由 `PoolId = keccak256(abi.encode(PoolKey))` 标识
- **池子识别**:
  - 快速：已知 quote（含 native ETH `0x0`）× fee/tick × hooks=0 → `StateView.getSlot0`
  - 穷举（窗口 ≤1000 块）：PoolManager `Initialize` 日志（可捕获非零 hooks）
  - 窗口内 PositionManager `Transfer` → `getPoolAndPositionInfo`（捕获动态费率 / hooks 活跃池）
- **事件索引**: PoolManager `Swap` / `ModifyLiquidity`；PositionManager `Transfer` / `ModifyLiquidity`
- **仓位份额**: tick → amount0/amount1；`share_pct` = 区间内仓位 `L / StateView.getLiquidity(poolId)`（活跃流动性占比，链上可对；区间外为 0）

## Uniswap V1

- **状态**: 🔧 薄支持
- **Factory**: `0xc0a47dFe034B400B47bDaD5FecDa2621de6c4d95`
- **部署区块**: 6627917
- **池子识别**: `factory.getExchange(token)`
- **仓位**: exchange LP `balanceOf` / `totalSupply` 在 `to_block` 快照
- **说明**: 协议已基本无流动性；不做完整事件时间线

## 未来计划 (TODO)

| 协议 | 版本 | 优先度 | 说明 |
|------|------|--------|------|
| Sushiswap | V2/V3 | ⭐⭐⭐ | 与 Uniswap 兼容的 Factory |
| Curve | StableSwap | ⭐⭐⭐ | 稳定币兑换协议 |
| PancakeSwap | V2/V3 | ⭐⭐ | BSC 链上的 Uniswap 分叉 |
| Balancer | V2 | ⭐⭐ | 多代币池 |
| Trader Joe | V2.1 | ⭐ | Avalanche 链 |

## 如何添加新协议

1. 在 `config/protocols.ethereum.yaml` 中添加协议配置
2. 在 `src/discovery/` 下创建适配器 (继承 `PoolDiscoveryAdapter`)
3. 在 `src/discovery/engine.py` 的 `_ADAPTER_MAP` 中注册
4. 在 `abis/` 下添加必要的 ABI 文件
5. 在本文件 `SUPPORTED_PROTOCOLS.md` 中更新记录
