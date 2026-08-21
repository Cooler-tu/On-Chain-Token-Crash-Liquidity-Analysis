# TURBO 30-Day Correlation Pilot / TURBO 30 天相关性试验

Date / 日期: 2026-08-21  
Output / 输出: `output-turbo-30d-25580851/`  
Window / 区块窗口: `25580851–25796850`  
Matched pool / 匹配主池: `0x7baecE5d47f1BC5E1953FBE0E9931D54DAB6D810`

## Dataset / 数据集

- 31 daily buckets from 2026-07-21 through 2026-08-20 UTC.
- 1,040 swaps; price is WETH per TURBO, not USD.
- Historical RPC `balanceOf` snapshots measure target-token reserve for 3 of 5 verified pools; the matched main-pool analysis avoids mixing unmatched pool coverage.
- Pool-level liquidity amounts are collected. Position Manager history was skipped, so LP NFT identity and `active_lp_count` are unavailable.
- 212 additions supplied 1,864.46M TURBO; 214 removals withdrew 1,865.73M TURBO; measured net LP flow is only -1.2675M TURBO.

- 共 31 个 UTC 日桶（2026-07-21 至 2026-08-20）。
- 1,040 笔 Swap；价格单位是 WETH/TURBO，不是 USD。
- 历史 RPC `balanceOf` 只覆盖 5 个已验证池中的 3 个；试验使用匹配主池，避免把未匹配的市场总量与部分储备直接混合。
- 池级流动性金额已采集；Position Manager 被跳过，因此 LP NFT 身份和 `active_lp_count` 不可用。
- 212 次添加共 1,864.46M TURBO，214 次移除共 1,865.73M TURBO，但净 LP 流量只有 -1.2675M TURBO。

## Exploratory results / 探索性结果

| Relationship | Pearson | Spearman | Lag | Interpretation |
|---|---:|---:|---:|---|
| Reserve change vs net LP-flow ratio | 0.9647 | 0.9658 | 0 | Mechanical/data-consistency check, not a new market law |
| Volume turnover vs later price return | 0.4157 | 0.4702 | volume leads by 2 days | Candidate only; moderate and short-sample |
| Volume turnover vs later gross-withdrawal ratio | 0.4094 | 0.3471 | volume leads by 3 days | Candidate for transaction forensics |
| Price return vs later gross-withdrawal ratio | 0.4116 | 0.4286 | price leads by 1–2 days | Candidate LP response pattern |

The strongest same-day result is reserve change versus net LP flow. This is expected because both describe pool balance/liquidity movement and share a prior-reserve denominator. Treat it as a pipeline sanity check.

The more interesting candidate is a 2–3 day ordering: high volume/turnover may precede later price movement and heavy LP position cycling. For example, 2026-08-05 and 2026-08-06 were the two highest-volume days; 2026-08-08 and 2026-08-09 then recorded gross-withdrawal ratios above 1.0. A manually audited pair also shows why “gross withdrawal” is activity rather than permanent exit: transaction `0x7ce77b...b182` removed about 10.8067M TURBO, and two blocks later `0xf23dc4...f665` minted a new position with about 10.7805M TURBO in the same pool and tick range.

最强的同步结果是“储备变化 vs 净 LP 流量”。两者都描述池内资金变化，并共用前一期储备作为分母，因此它主要证明数据链条自洽，不应包装成新的市场规律。

更值得调查的是 2–3 天的先后关系：高成交量/高周转可能领先后续价格变化和频繁 LP 头寸重建。2026-08-05、08-06 是成交量最高的两天，08-08、08-09 的累计撤资强度随后超过 1.0。人工核验也证明“累计撤资”更接近活动强度：`0x7ce77b...b182` 撤出约 10.8067M TURBO，仅两个区块后，`0xf23dc4...f665` 在同一池、相同 tick 区间重新铸造约 10.7805M TURBO 的新头寸。

## Guardrails / 解释边界

- 31 observations are too few for a formal lead-lag claim.
- Lag selection searches several feature pairs and lags; no confidence interval, p-value, or multiple-testing correction has been applied yet.
- Gross withdrawal ratio can exceed 1 because the same capital can be removed and re-added repeatedly. It must not be called “percent of liquidity permanently exited”.
- The price unit is WETH and the reserve series is target-token-side only.
- LP identity is unavailable, so the same beneficial owner cannot be asserted from the local panel alone.

- 31 个样本不足以支持正式的领先/滞后结论。
- 当前同时搜索了多组指标和 lag，尚未加入置信区间、显著性检验和多重检验校正。
- 同一笔资金可反复撤出并加入，所以累计撤资比率可以超过 1，不能解释为“永久退出比例”。
- 价格单位为 WETH，储备仅为目标代币一侧。
- LP 身份不可用，不能仅凭本地时间序列断言多笔交易属于同一受益所有人。

## Next evidence bundle / 下一步证据包

Focus on 2026-08-05 through 2026-08-09 and separate four ledgers:

1. Swap direction and target-token volume.
2. Actual target-token Transfer net flow into/out of the main pool.
3. Gross LP adds/removes and same-pool remove→mint cycles.
4. WETH/TURBO price returns at +1, +2, and +3 days.

The goal is to decide whether the lag candidate reflects genuine liquidity exit, routine V3 position recreation, or trading-driven pool inventory changes.

重点调查 2026-08-05 至 2026-08-09，并拆开四本账：Swap 方向、池地址实际 Transfer 净流、LP 累计增减与同池重建、以及 +1/+2/+3 天的 WETH/TURBO 收益。最终判断该 lag 是真实流动性退出、常规 V3 头寸重建，还是交易导致的池库存变化。

## Commands / 指令

```bash
python3 -m src.cli research-series \
  --output-dir output-turbo-30d-25580851

python3 scripts/time_series_correlation.py \
  --output-dir output-turbo-30d-25580851 \
  --scope pool \
  --pool 0x7baecE5d47f1BC5E1953FBE0E9931D54DAB6D810 \
  --max-lag 3 --min-pairs 24 \
  --features price_return,tvl_change,volume_turnover,net_lp_flow_ratio,withdrawal_ratio \
  --out-dir output-turbo-30d-25580851/research-correlation-main-pool-turnover
```
