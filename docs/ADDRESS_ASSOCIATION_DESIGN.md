# Address Association Design（钱包聚类 + 资金流）

> 状态：可行性评估（2026-08-07）
> 结论：可以做，但只能输出「疑似关联 + 置信度」，不能证明同一真人身份。

## 1. 要解决的问题

两个目标：

1. **钱包聚类**：判断多个地址是否可能属于同一个主体。
2. **资金流图**：展示代币在地址之间的流动路径，定位资金从哪里来、到哪里去。

## 2. 关联信号

按证据强度排序：

| 强度 | 信号 | 数据来源 |
|---|---|---|
| 强 | 同一合约的 `owner()` / 控制器 | RPC `eth_call` |
| 强 | 合约创建者关系 | Dune `ethereum.creation_traces` / 创建交易 `from` |
| 中 | 同一个 CEX 入金 / 提币地址 | Dune / 外部标签 |
| 中 | 同一 EOA 为多个地址支付 gas | 交易 `from` |
| 中 | 同一时间窗口内批量 / 链式转账 | `evt_Transfer` |
| 弱 | 相近时间、相同方向的相同行为 | 行为指纹 |

## 3. Dune 可用性

已确认可用的数据：

- `erc20_ethereum.evt_Transfer`：token 转账。
- `dex.trades`：包含 `taker`、`tx_from`、token 买卖地址。
- 合约创建：Dune 的 `ethereum.creation_traces` / 交易 `from` 可追踪 EOA → 合约。

这些数据足够做第一版关联图和资金流图。

## 4. 输出形态

### 4.1 钱包聚类

```json
{
  "cluster_id": "c-001",
  "addresses": ["0xA", "0xB"],
  "confidence": 0.82,
  "signals": [
    {"type": "same_gas_payer", "strength": "medium"},
    {"type": "same_owner_contract", "strength": "strong"}
  ]
}
```

聚类结果一律带：

- 置信度。
- 证据列表。
- `reason`（为什么判定为疑似关联）。

### 4.2 资金流图

```text
节点 = 地址
边 = 聚合后的 token 转账
边的属性 = 金额、时间、方向、是否经过 DEX
```

节点必须分类：`EOA`、`contract`、`pool`、`router`、`CEX`、`burn`。

## 5. 必须先做的节点归一

不做归一会导致错误结论：

- 用户 → router → pool 的 swap，不能看成“用户给 router 转钱”。
- pool 收到大量 token 是流动性，不一定是某个人的余额。
- 合约内部转账不能直接归因给外部 EOA。

第一版只聚合“直接转账”，并标注经过的中间节点；第二版再做 router 穿透。

## 6. 资金流图 MVP

1. 读取 `transfers.json`。
2. 聚合 `(from, to)` 对，统计金额、次数、时间范围。
3. 按节点类型着色。
4. 只高亮大额边（例如占总流量前 20%）。
5. 输出 `fund_flow.json` 和静态图。

## 7. 风险与边界

- 同一个地址背后可能是多个人（共用钱包 / 多签）。
- 一个主体可能用不同链、不同合约，纯 Ethereum 单链数据会漏。
- 外部标签（CEX 等）需要 API 或维护名单，不能保证完整。
- 结论应写为「疑似关联」，不能用于确定性指控。

## 8. 验收标准

- [ ] `fund_flow.json` 可生成，节点类型齐全。
- [ ] 聚类结果包含置信度和证据列表。
- [ ] dashboard 能展示资金流图，并标注中间节点。
- [ ] README 说明「关联 ≠ 身份确认」。
