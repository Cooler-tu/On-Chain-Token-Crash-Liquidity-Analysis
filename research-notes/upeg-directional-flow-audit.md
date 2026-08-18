# uPEG Directional Flow Audit / uPEG 方向资金流审计

Date / 日期: 2026-08-18

## Scope / 范围

- Token: uPEG (`0x44b28991B167582F18BA0259e0173176ca125505`)
- Pool: Uniswap V3 uPEG/WETH (`0xdc893995d488e5be8ec8ca1db92cbec2a1ab0775`)
- Swap blocks: `25043020–25043311`
- Balance snapshots: `25043019 → 25043311`
- UTC bucket: `2026-05-07 12:00:00–12:59:59`
- Local evidence: `output-upeg-v3-7d/research-directional-flow/2026-05-07T12/`

Command:

```bash
python3 scripts/directional_swap_flow.py \
  --output-dir output-upeg-v3-7d \
  --pool 0xdc893995d488e5be8ec8ca1db92cbec2a1ab0775 \
  --from-block 25043020 \
  --to-block 25043311 \
  --start-balance-block 25043019 \
  --out-dir output-upeg-v3-7d/research-directional-flow/2026-05-07T12
```

## Findings / 发现

| Metric / 指标 | Result / 结果 |
|---|---:|
| Swap events / Swap 事件 | 119 |
| Unique Swap transactions / 唯一 Swap 交易 | 118 |
| Unique `tx.from` senders / 唯一交易发起地址 | 99 |
| Sell events into pool / 卖入池事件 | 48 |
| Buy events out of pool / 从池买入事件 | 71 |
| Gross sell volume / 卖出总量 | 39.535591057398224730 uPEG |
| Gross buy volume / 买入总量 | 30.268476394365850053 uPEG |
| Net signed Swap flow to pool / Swap 净流入池 | 9.267114663032374677 uPEG |
| Actual ERC-20 transfer net to pool / 实际转账净流入池 | 10.106754360913178103 uPEG |
| Historical pool balance delta / 历史池余额变化 | 10.106754360913178103 uPEG |
| Transfer minus Swap residual / 转账减 Swap 残差 | 0.839639697880803426 uPEG |
| Balance minus Transfer / 余额减转账 | 0 uPEG |
| Top-five `tx.from` sell share / 前五发起地址卖出占比 | 56.60% |

The target-token ERC-20 Transfer logs reconcile the historical pool balance
exactly. Raw signed Swap amounts do not: they explain a net `9.2671 uPEG`, while
the actual pool balance rises by `10.1068 uPEG`.

目标代币的 ERC-20 Transfer 日志与历史池余额精确闭合；单独使用带符号 Swap
事件只能解释 `9.2671 uPEG` 净流入，而池余额实际增加 `10.1068 uPEG`。

## Largest residual transaction / 最大残差交易

Transaction:
`0x5404ec8a9f0956145eddbbcdcb55daeac8ceb34a61d1193b87e6ca1e56361c30`

- The V3 Swap event records `-0.785769880330610865 uPEG` from the pool.
- A uPEG Transfer sends the same amount from the pool to the recipient.
- A later Transfer in the same transaction returns
  `0.785769874007828371 uPEG` to the pool.
- The transaction's actual uPEG pool delta is therefore approximately zero,
  despite one buy-side Swap event.

- V3 Swap 事件记录池流出 `0.785769880330610865 uPEG`。
- 同笔交易先发生等量 uPEG 从池转出。
- 随后又有 `0.785769874007828371 uPEG` 转回池中。
- 因此这笔交易对池的实际 uPEG 净影响接近零，不能只凭一个买入侧 Swap
  事件判断最终资金流。

## Interpretation guardrails / 解释边界

1. Positive signed target-token Swap amount means the target enters the pool
   (sell target); negative means it leaves the pool (buy target).
2. `tx.from`, Swap `sender`, and Swap `recipient` are different identities.
   Routers and contracts may appear between the end user and the pool.
3. The Transfer-minus-Swap residual must not be labelled automatically as a
   tax, fee, manipulation, or exploit. It can include same-transaction returns,
   LP-related movements, direct transfers, or token-specific transfer behavior.
4. For balance reconciliation, target-token Transfer logs are the stronger
   accounting layer. For price formation, the Swap event remains the relevant
   pool execution record.

1. 目标代币带符号 Swap 数量为正表示代币进入池（卖出目标代币），为负表示
   代币离开池（买入目标代币）。
2. `tx.from`、Swap `sender` 与 Swap `recipient` 是不同身份，路由器或合约可能
   位于终端用户和池之间。
3. 不能直接把“Transfer 减 Swap”的残差称为税费、操纵或漏洞；它可能来自同笔
   交易回转、LP 相关流动、直接转账或代币自定义转账行为。
4. 余额闭环应优先使用目标代币 Transfer 日志；价格形成仍应使用池的 Swap
   执行记录。

## Next research step / 下一步

Add persistent block/transaction metadata caching, then extend the same
decomposition to all 169 hourly buckets. Derive hourly gross buy, gross sell,
net Swap flow, actual Transfer net flow, residual, sender concentration, and
price-impact features before resuming correlation or lead-lag tests.

先增加区块与交易元数据缓存，再扩展到全部 169 个小时桶；生成小时级买入、卖出、
Swap 净流、实际 Transfer 净流、残差、地址集中度和价格冲击特征，然后再恢复相关性
和 lead-lag 分析。
