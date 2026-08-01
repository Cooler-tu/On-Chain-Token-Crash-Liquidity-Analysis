# Dune Data Map

统一查询层：`src/data/dune_client.py`（SQL 执行 → 轮询 → 缓存到 `output/dune_cache/`）。
有 `DUNE_API_KEY` 时优先走 Dune；失败或无 key 时自动回退 RPC。

## 数据清单

| 数据 | Dune 表 / SQL | CLI | 回退策略 |
|------|---------------|-----|----------|
| 池子列表（按代币） | `dex.trades`（project/version/pool_id 聚合） | `dune pools <TOKEN>` | RPC adapters |
| Swap 事件（单池） | `dex.trades`（按 pool_id 过滤） | `dune swaps <POOL>` | RPC indexer |
| 持仓地址 | `erc20_ethereum.evt_Transfer` | `holdings --holdings-source auto` | RPC Transfer events |
| 持仓余额 | `tokens_ethereum.balances` | 同上 | RPC `balanceOf` |
| 池 TVL（USD） | `dex.pool_tvl` | `dune tvl <POOL>` | 链上余额近似 |
| Balancer 流动性事件 | `balancer_v2_ethereum.Vault_evt_PoolBalanceChanged` | `dune data-map` | RPC Vault 扫描 |
| Curve 流动性事件 | 每池独立合约，Dune 表不统一 | — | RPC `curve_pool` 事件索引 |
| 验证（factory/bytecode） | — | — | RPC（必须） |
| 持仓重建（balanceOf/totalSupply） | — | — | RPC（必须） |

## 用法

```bash
export DUNE_API_KEY="..."

# 池发现（跨 DEX）
python3 -m src.cli dune pools CRV \
  --from-block 19000000 --to-block 19000050

# 单池 Swap
python3 -m src.cli dune swaps 0x... \
  --from-block 19000000 --to-block 19000050

# 池 TVL
python3 -m src.cli dune tvl 0x...

# 数据清单
python3 -m src.cli dune data-map
```

完整分析时，若 `DUNE_API_KEY` 已配置，`discover_pools()` 会先跑 Dune
池发现（快、跨 DEX），再与 RPC 适配器结果合并去重。

## 仍依赖 RPC 的部分

- 池验证（bytecode / factory / state 检查）
- Curve 流动性事件（Dune 无统一解码表）
- 持仓重建（balanceOf / totalSupply 快照）
- 链上余额兜底（Dune balances 缺失时）
