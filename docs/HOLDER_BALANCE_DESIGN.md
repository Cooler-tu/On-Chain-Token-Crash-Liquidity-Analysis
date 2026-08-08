# Holder Balance Design

> 状态：数据源已验证（2026-08-08），字段实现待做
> 目标：回答“holder 的金额随时间变化，到底应该按什么口径统计和排序”。

## 1. 现状

当前 `src/analysis/holdings.py` 的实现：

1. 从分析窗口 `[from_block, to_block]` 的 Transfer 事件中收集所有出现过的地址，并加入已验证池地址。
2. 对每个地址查一次 `balanceOf`，默认查 `to_block` 时刻，历史 RPC 失败时退回最新块。
3. 按该单点余额从大到小排序，输出 Top Holders。

因此当前“Top Holders”的真实含义是：

> 窗口内出现过、且在期末区块仍有余额的地址，按期末余额排序。

它不是“谁在窗口内买卖过多少”，也不是完整持有人排名。

## 2. 现状的数据限制

### 2.1 地址发现不完整

- 地址池来自 Transfer 事件，窗口内完全没交易的持有者不会出现。
- 未来需要 Dune 全量持有人表（如 `tokens_ethereum.balances`）才能覆盖“只持有不动”的地址。

### 2.2 余额查询被截断

- `max_rpc_balances` 默认 80，Dune 也只覆盖排前 50-80 的地址。
- 以 uPEG `output/` 为例：3075 个唯一地址，只有约 80 个真正查了余额，其余 2995 个被直接填 0。
- 所以现在的 Top Holders 是“采样子集里的 Top”，不是全量 Top。

### 2.3 Dune 历史快照已验证

- `tokens_ethereum.balances` 是稀疏余额账本：每个地址在「余额发生变化的区块」有一行，带
  `block_number` / `block_time`，可以用 `block_number <= 目标块` + 每地址最新一行取任意历史快照。
- 2026-08-08 用 uPEG 验证：12 个抽样地址（2 池 + EOA + 合约）的期初 / 期末余额与 RPC
  `balanceOf` 全部精确一致；期末有余额的地址 4,640 个，大于窗口内转账地址 3,075 个，
  说明能覆盖「只持有不动」的持有人。
- 旧的 `balances_ethereum.latest` 查询保留为兜底，不再作为历史快照主路径。

## 3. 口径定义

建议 dashboard 把三个概念分开：

| 名称 | 定义 |
|---|---|
| Unique Transfer Addresses | 窗口内 Transfer 事件中出现过的唯一地址数 |
| Holders at Block X | 在指定快照块余额 > 0 的地址数 |
| Active Holders | 在快照块余额 > 0，且在窗口内至少有过一次交易 |

Top Holders 必须带快照块信息，例如 `Top Holders (Block 25012000)`。

## 4. 方案对比

### A. 双时间点快照（from + to）

```text
balance_start = balanceOf(from_block)
balance_end   = balanceOf(to_block)
net_change    = balance_end - balance_start
```

优点：

- 实现简单，Dune `tokens_ethereum.balances` 已支持历史区块快照，不需要 2N 次 RPC。
- 能直接回答“谁在增持 / 减持”。

缺点：

- 拿不到峰值和轨迹。
- Dune 侧约 2 次 SQL（期初 + 期末）；RPC 只在抽样校验时使用。

### B. 事件流重建

```text
期初快照 balanceOf(from_block)
按 Transfer 事件顺序累加 / 累减
得到 balance(t) 曲线
```

优点：

- 一次期初快照后，直接复用已索引的 Transfer 事件。
- Dune 余额账本的窗口内行可以替代原始 Transfer 回放，天然避免 pool / router 内部转账重复计算。
- 能算峰值、净变动、持仓时间、holder 数量变化。
- 不需要每个区块都调用 `balanceOf`。

缺点：

- 依赖期初快照和完整 Transfer 事件。
- 合约 / router / 池的内部转账需要归一，否则会重复计算。
- 只覆盖被发现的地址，纯持币不动的地址仍依赖全量持有人表。

### C. 时间桶快照（每小时 / 每天）

```text
for each bucket:
    balanceOf(block_at_bucket)
```

优点：

- 直观，适合画持有人数量变化。

缺点：

- 成本约 N × M 次查询，最贵。
- 只适合对少量重点地址做，不适合全量。

### D. 推荐：混合方案

```text
全量地址：双时间点快照（from + to），算 net_change
Top Movers / 重点大户：事件流重建，算 peak_balance 和余额轨迹
```

理由：

- 全量双时间点解决“谁在净买入 / 净卖出”。
- 事件流重建只花少量额外成本，解决“谁曾经大量持有但已经跑了”。
- dashboard 的两个视图互不冲突：`Top Holders` 看期末，`Top Movers` 看窗口内动作。

## 5. 成本模型

设：

- N = 需要查询的地址数
- M = 时间桶数
- C = RPC 单次 `balanceOf` 成本
- E = 窗口内 Transfer 事件条数

| 方案 | 查询成本 | 额外计算 |
|---|---|---|
| 双时间点快照 | 2N × C | O(N) |
| 事件流重建 | N × C + 1 次全量 Transfer 拉取 | O(E) |
| 时间桶快照 | N × M × C | O(N × M) |
| 混合方案 | 全量 2N × C + 重点地址事件流 | O(E) |

验证后的真实建议：

1. 用 Dune `tokens_ethereum.balances` 做全量双时间点快照，避免 2N 次 RPC。
2. 用同一张表的窗口内行做事件流重建，只对 Top Movers 或期末 Top 20 执行，算峰值和轨迹。
3. RPC `balanceOf` 只用于抽样交叉验证或 Dune 失败兜底。

## 6. 输出字段

`holdings.json` 建议新增 / 标准化：

```json
{
  "address": "0x...",
  "balance_start": "123",
  "balance_end": "456",
  "net_change": "333",
  "peak_balance": "789",
  "moved_in": "1000",
  "moved_out": "667",
  "tx_count": 42,
  "first_seen_block": 25008000,
  "last_seen_block": 25012000
}
```

说明：

- `moved_in` / `moved_out` 只在事件流重建时可靠。
- 没有事件流数据时，`peak_balance` 可以留空并标注 `source: "two_point_snapshot"`。

## 7. 排序口径

| 想回答的问题 | 排序字段 |
|---|---|
| 现在谁控制筹码 | 期末余额 |
| 谁在窗口内大量买入 / 卖出 | 净变动、moved_in、moved_out |
| 谁曾经是巨鲸但已经离场 | 峰值余额 |
| 谁最活跃，可能在洗盘 | 交易次数、moved_in + moved_out |

## 8. 验收标准

- [x] Dune 历史余额快照已验证（`tokens_ethereum.balances`，uPEG 12/12 与 RPC 一致）。
- [x] `holdings.json` 已输出 `balance_start` / `balance_end` / `net_change` / `peak_balance`；长尾地址标记 `zero_fill` 并注明来源。
- [x] Top Holders / Top Movers 已接入期初 / 期末 / 净变动 / 峰值，并标注快照块与数据来源。
- [ ] dashboard 区分 `Unique Transfer Addresses`、`Holders at Block X`、`Active Holders`。
- [x] Top Holders 表带快照块说明（起止块 + Dune/RPC 来源）。
- [ ] 文档记录真实 token 的 N、E、RPC 调用数和耗时对比。
- [ ] 方案选定后，README / plan 同步更新。
