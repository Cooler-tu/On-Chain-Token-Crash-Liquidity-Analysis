# Teammate Update — Time-Series & Directional-Flow Research

Date: 2026-08-18

## 一句话说明

Dashboard 优化阶段基本结束，项目已经转入数据研究阶段。本次提交建立了统一时间序列表、
七天匹配池相关性分析和带方向的 Swap/Transfer 审计，并用一个人工核验小时完成链上余额
闭环。

## 这次新增了什么

### 1. 统一分析时间序列

`src/analysis/series.py` 将价格、目标代币侧储备、成交量和 LP 流量对齐到固定时间桶，输出：

- `tables/analysis_series.parquet`：完整 typed research table；
- `analysis_series_preview.csv`：方便人工查看；
- `analysis_series_summary.md`：字段与覆盖情况摘要。

价格字段包含 OHLC 和 VWAP。状态型指标取桶末状态，流量型指标在桶内求和。缺失 LP 金额
不会自动解释成 0。

### 2. 历史 RPC 储备快照

`research-series --refresh-tvl` 可在每个小时最后一个真实区块调用历史
`balanceOf(pool)`，记录目标代币侧储备和 `tvl_snapshot_block`。

注意：这里是目标代币侧 reserve proxy，不是完整双边 USD TVL。共享 PoolManager 的 V4
poolId 无法仅靠 ERC-20 `balanceOf` 拆分，因此会被排除，避免重复计算。

### 3. 七天匹配 V3 池面板

研究池：

```text
uPEG/WETH V3
0xdc893995d488e5be8ec8ca1db92cbec2a1ab0775
```

本地 `output-upeg-v3-7d/` 覆盖：

- blocks `25033767–25083999`；
- 4,105 个 Swap；
- 169 个小时价格桶；
- 169 个历史 uPEG reserve 快照。

初步结果：价格收益与目标代币储备变化同期强负相关（Pearson `-0.6841`、Spearman
`-0.7757`、N=168），但成交量和 ±24 小时 lag 都较弱。这个负相关很大程度上符合 AMM
机械关系，不能直接当成异常或因果结论。

### 4. 带方向资金流与余额闭环

`scripts/directional_swap_flow.py` 重新读取原始 V3 signed Swap 日志，并同时审计目标代币
ERC-20 Transfer 和历史池余额。不会修改主索引中为跨协议成交量保留的绝对值口径。

人工核验小时：

```text
UTC: 2026-05-07 12:00–12:59
Swap blocks: 25043020–25043311
Balance snapshots: 25043019 → 25043311
```

| 指标 | 结果 |
|---|---:|
| Swap events | 119 |
| Sell / Buy events | 48 / 71 |
| Gross sell | 39.535591057398224730 uPEG |
| Gross buy | 30.268476394365850053 uPEG |
| Net signed Swap flow into pool | 9.267114663032374677 uPEG |
| Actual Transfer net into pool | 10.106754360913178103 uPEG |
| Historical pool-balance delta | 10.106754360913178103 uPEG |
| Transfer minus Swap residual | 0.839639697880803426 uPEG |
| Unique `tx.from` | 99 |
| Top-five sender sell share | 56.60% |

ERC-20 Transfer 与历史池余额精确闭合，但 signed Swap 并没有完整解释实际余额变化。
这说明后续资金流研究必须保留两个层次：

1. Swap event 用于池内成交方向和执行价格；
2. Transfer event 用于实际代币现金流和余额闭环。

最大残差交易为：

```text
0x5404ec8a9f0956145eddbbcdcb55daeac8ceb34a61d1193b87e6ca1e56361c30
```

该交易先从池转出约 `0.78576988 uPEG`，随后几乎等量转回，因此不能只根据一个买入侧
Swap 判断最终资金流。当前只把它标记为待研究行为，不能直接称为税费、操纵或漏洞。

## 如何复现

先配置支持历史区块查询的 `ETH_RPC_URL`，然后：

```bash
python3 scripts/build_matched_pool_series.py \
  --source-output output \
  --output-dir output-upeg-v3-7d \
  --pool 0xdc893995d488e5be8ec8ca1db92cbec2a1ab0775 \
  --from-block 25033767 \
  --to-block 25083999

python3 scripts/time_series_correlation.py \
  --output-dir output-upeg-v3-7d \
  --scope pool \
  --pool 0xdc893995d488e5be8ec8ca1db92cbec2a1ab0775 \
  --max-lag 24 \
  --out-dir output-upeg-v3-7d/research-correlation

python3 scripts/directional_swap_flow.py \
  --output-dir output-upeg-v3-7d \
  --pool 0xdc893995d488e5be8ec8ca1db92cbec2a1ab0775 \
  --from-block 25043020 \
  --to-block 25043311 \
  --start-balance-block 25043019 \
  --out-dir output-upeg-v3-7d/research-directional-flow/2026-05-07T12
```

提交中强制保留了 `output-upeg-v3-7d/` 的 JSON/CSV/Markdown 证据，包括原始 Swap、
储备时间线、相关性输出和方向审计。Parquet 与 `indexer_cache/` 仍按项目约定排除，
需要时可用以上命令重建。

## 重点文件

| 文件 | 作用 |
|---|---|
| `docs/TIME_SERIES_CORRELATION_RESEARCH.md` | 整体研究设计与字段口径 |
| `src/analysis/series.py` | 固定时间桶研究表 |
| `scripts/build_matched_pool_series.py` | 匹配池 RPC 数据构建 |
| `scripts/time_series_correlation.py` | Pearson/Spearman/lead-lag |
| `scripts/directional_swap_flow.py` | signed Swap、Transfer、余额闭环 |
| `research-notes/upeg-directional-flow-audit.md` | 异常残差证据和解释边界 |
| `plan.md` | 当前进度与下一里程碑 |

## 验证状态

```text
python3 -m unittest discover -s tests -q
94 tests passed, 1 skipped
```

## 下一步

先给区块时间戳和交易元数据增加持久缓存，再把方向分解扩展到全部 169 个小时，生成：

- gross buy / gross sell；
- net signed Swap flow；
- actual Transfer net flow；
- Transfer-minus-Swap residual；
- `tx.from` 卖方集中度；
- price impact / flow residual。

完成全窗口方向特征后，再继续相关性、lead-lag 和异常交易取证。
