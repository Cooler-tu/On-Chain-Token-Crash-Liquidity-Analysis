# LP Correlation & Lead-Lag Design

> 状态：原型已实现（2026-08-07）
> 对应脚本：`scripts/lp_correlation.py`

## 1. 为什么不用固定涨跌阈值

固定阈值（例如“TVL 单小时跌 20% 就算剧烈”）有两个问题：

- 不同 token、不同池规模下，绝对阈值没有可比性。
- TVL 变化可能来自价格波动或 swap，不一定是 LP 进出，只看涨跌会误判。

因此先用时间序列相关性做探索，再用真实 LP 事件（Mint / Burn / Collect）做验证。

## 2. 指标定义

按时间桶（默认 1 小时）构造以下序列：

| 序列 | 定义 |
|---|---|
| `tvl_in_token` | 每桶 TVL 总和（目标 token 口径） |
| `volume_in_token` | 每桶 swap 成交量（目标 token 口径） |
| `active_lp_count` | 每桶出现 LIQUIDITY_ADD / REMOVE 的唯一 actor 数 |
| `lp_event_count` | 每桶流动性事件数量 |
| `holder_count` | 每桶 Transfer 事件中出现的唯一地址数 |

## 3. 相关性

计算 Pearson 相关系数矩阵。相关系数接近 +1 表示同涨同跌，接近 -1 表示反向。

## 4. 领先 / 滞后分析

对每一对 `(X, Y)`，把 X 平移 `lag` 个桶：

- `lag > 0`：`X[t]` 与 `Y[t+lag]` 比较，表示 X 领先 Y。
- `lag < 0`：X 落后于 Y。

取相关系数绝对值最大的 lag 作为最佳领先 / 滞后。

## 5. 当前 uPEG 结果

`output-lp-correlation-demo/lp_correlation.json`：

| X | Y | lag | corr |
|---|---|---|---|
| tvl | volume | 0 | 0.9608 |
| holder_count | volume | 0 | 0.8953 |
| holder_count | tvl | 0 | 0.8935 |
| tvl | lp_event_count | +1 | 0.7587 |
| lp_event_count | tvl | -1 | 0.7587 |

解读（探索性，非结论）：

- TVL 和成交量高度同步，说明价格波动与交易活跃同时发生。
- TVL 领先 LP 事件约 1 小时，可能是“价格先动，LP 后调整”，值得用真实 Burn/Mint 事件进一步验证。

## 6. 使用

```bash
python3 scripts/lp_correlation.py \
  --output-dir output \
  --out-dir output-lp-correlation-demo \
  --bucket-seconds 3600 \
  --max-lag 6
```

## 7. 已知限制

- 时间桶太少时相关系数不稳定（uPEG 示例只有 15 个桶）。
- 相关性不等于因果，必须配合具体 LP 地址和事件解释。
- `active_lp_count` 只能看到“窗口内活跃 LP”，看不到不动的 LP。
- TVL 序列是近似值，不同协议口径不完全一致。

## 8. 下一步

1. 在更多 token / 更长窗口上跑，确认「TVL 领先 LP 事件」是否稳定。
2. 对每个高相关 lag，列出对应的具体 Mint / Burn / Collect 事件作为证据。
3. 把相关性信号作为风险分的参考特征，但只在样本量足够时启用。
