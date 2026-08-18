# 会后工作交接（HandOver）

> 最新研究阶段交接（2026-08-18）见
> `docs/TEAMMATE_UPDATE_2026-08-18.md`。本文保留 2026-08-14 Dashboard
> 口径修复阶段的详细背景。

> 更新时间：2026-08-14
>
> 交接范围：本次导师会议结束后至当前版本
>
> 当前主提交：`d2be0a0 feat: clarify dashboard analysis semantics`
>
> 远程状态：该提交已推送到 `origin/main`

## 1. 这段时间完成了什么

这轮工作的重点不是增加新的链上数据源，而是修正 Dashboard 中容易被误解的指标口径，让用户能够分清“真实数值”“部分覆盖”和“数据不可得”。

### 1.1 Notable Wallets 改为自适应筛选

原来的固定标准是 `$10,000`、`50 swaps`、`0.1% volume share`，对不同规模的 token 和不同长度的分析窗口不够稳健。

现在默认在当前分析窗口的钱包样本内部计算 P99，分别考察：

- 最大单笔成交额（Trade）；
- 买卖净流量绝对值（Mover）；
- 累计成交额（Volume）；
- swap 次数（Activity）。

任一指标进入窗口内 P99，即可成为 Notable Wallet。显式传入旧阈值时仍支持固定阈值模式。

当前 uPEG 输出中的实际结果：

| 项目 | 当前值 |
|---|---:|
| 参与比较的钱包 | 683 |
| Notable Wallets | 13 |
| Trade P99 | $5,670.04 |
| Mover P99 | $34,990.42 |
| Activity P99 | 61 swaps |
| Volume P99 | $47,464.40 |

主要实现：

- `src/analysis/metrics.py`：计算 P99、percentile rank、notability score 和自适应标签；
- `src/analysis/dashboard.py`：显示本次实际阈值、Volume Share 和入选原因；
- `src/cli.py`：支持从本地 swap artifacts 刷新钱包指标，不重新请求 Dune/RPC。

### 1.2 多池曲线增加视觉区分

TVL、Price 等多池曲线原来只有少量颜色，池数量增加后会出现重复。

现在采用更大的深色主题调色板，并叠加实线、长虚线、短虚线等线型。即使颜色接近，也能通过线型继续区分。

### 1.3 DEX custody reserve 改为饼图并增加限制说明

原来的 `DEX Pool Contracts` 表容易把 V2/V3 pool contract、V4 poolId 和 V4 共享 PoolManager 混为一谈。

现在该区域使用饼图展示“已识别 DEX 托管地址持有的目标 token 余额分布”，并明确：

- 它不是 LP 数量；
- 它不是完整的双边 USD TVL；
- V4 PoolManager 是共享托管，一个扇区可能对应多个 V4 poolId。

这个区域仍在待办中：导师如果更关注池身份而不是托管余额，下一步应移除或弱化饼图，并将 `Pool Address` 拆成 `Pool Identifier`、`Contract Address` 和 `V4 Pool ID`。

### 1.4 Pool TVL Share 改为“已测池范围内的份额”

Dashboard 不再把缺少 per-pool TVL 的池显示为 `0%`。

当前页面明确显示：

- 14 个 verified pools 中只有 3 个成功测量；
- 覆盖率为 21.4%；
- 份额分母只包含这 3 个 measured pools；
- 11 个未可靠拆分的 V4 pools 显示 `Not measured`；
- `99.41%` 只能解释为“占 3 个已测池总量的 99.41%”，不能解释为占全部 14 个池。

当前 TVL timeline 来源为 `event_accumulate_fallback`，因此图表会标注为 event-reconstructed proxy，而不是精确链上余额快照。

### 1.5 Non-Pool Holders 排名语义明确化

Dashboard 现在明确执行以下规则：

1. 排除 pool/custody 地址；
2. 排除 `zero_fill` 和非正期末余额；
3. 按 end balance 从高到低排序；
4. 图表最多显示 Top 10，表格最多显示 Top 20。

当前 uPEG 数据覆盖情况：

| 项目 | 当前值 |
|---|---:|
| Transfer 中出现的地址 | 1,134 |
| 成功取得余额的地址 | 80 |
| 未覆盖、以 zero-fill 占位的地址 | 1,054 |
| 正余额 Non-Pool Holders | 38 |
| 正余额 Pool/Custody 地址 | 4 |

因此 Top 20 只是“余额查询已覆盖地址中的 Top 20”，不是全量持有人排行榜。EOA 和普通合约都可能出现在 Non-Pool 列表中。

### 1.6 Liquidity Withdrawals 区分真实 0 与金额缺失

本轮最重要的语义修复之一，是不再把 V4 `ModifyLiquidity` 中 token0/token1 的零占位解释为真实撤出 0。

数据层现在使用三种状态：

- `quantified`：token amount 已知，可以计算 token、USD 和 TVL share；
- `liquidity_delta_only`：负 liquidity delta 已确认撤池动作，但没有 token amount；
- `unmapped`：事件无法可靠映射到目标 token 一侧。

当前 uPEG 看板显示：

| 项目 | 当前值 |
|---|---:|
| Removal actions detected | 114 |
| Amount known | 0 |
| Amount missing | 114 |
| Pool mapping failed | 0 |

页面中的表达已经改为：

- `Raw Liquidity Change`：保留原始负 liquidity delta；
- `Token amount not returned`：查询没有返回 token0/token1 amount；
- `Cannot calculate`：因此不能计算 USD 和 TVL share；
- 真正经过量化的 0 仍然显示为 0。

需要特别注意：这 114 次操作证明发生了 removal activity，但不能说明“撤出了 0 uPEG”，也不能仅凭 liquidity delta 换算出 token 或 USD 数量。

为了兼容旧分析目录，Dashboard 重建时会从 canonical `liquidity_events` 在内存中重新计算上述三态。当前旧 run 的 `output/metrics.json` 不一定包含新增的三态计数字段；直接研究该 JSON 时不要把缺失字段或零占位当结论。新跑的完整 pipeline 会写入新字段。

## 2. 关键文件及职责

| 文件 | 本轮相关职责 |
|---|---|
| `src/analysis/metrics.py` | 自适应钱包阈值；withdrawal 三态、金额归一和覆盖计数 |
| `src/analysis/dashboard.py` | 看板文案、表格、饼图、Holder 排名、曲线颜色/线型、本地兼容刷新 |
| `src/indexer/dune_index.py` | 标记 liquidity event 是否具备 token amounts |
| `src/data/artifacts.py` | Parquet liquidity schema 增加 `amounts_available` 和 `quantification_status` |
| `src/cli.py` | 本地刷新 adaptive wallet activity 的 CLI 参数 |
| `tests/test_metrics.py` | P99 钱包筛选和 withdrawal 真 0/未知值回归测试 |
| `tests/test_dashboard.py` | Holder、TVL coverage、withdrawal 文案与多池曲线测试 |
| `tests/test_artifacts.py` | liquidity Parquet 新字段与原始大整数保存测试 |
| `docs/DATA_FLOW.md` | 当前 pipeline 和 Dashboard 口径 |
| `docs/METHODOLOGY_DEFENSE.md` | 方法、公式、限制和答辩边界 |
| `plan.md` | 已完成事项与优先级 backlog |

## 3. 本地验收方式

进入项目：

```bash
cd /Users/jelly/Desktop/On-Chain-Token-Crash-Liquidity-Analysis-main
```

只使用已有数据重建 Dashboard，不会请求 Dune/RPC：

```bash
python3 -m src.cli dashboard --output-dir output
open output/dashboard.html
```

如果页面已经打开，重建后按 `⌘R` 刷新。

从本地 artifacts 重新计算 adaptive Notable Wallets：

```bash
python3 -m src.cli dashboard \
  --output-dir output \
  --refresh-wallet-activity
```

运行回归测试：

```bash
python3 -m unittest discover -s tests -q
```

当前测试结果：73 项通过，1 项因当前环境已安装/未安装的可选依赖按设计跳过。

如果需要把最新版同步到 public site：

```bash
python3 scripts/publish_site.py
```

然后检查 `site/` 首页和 token 页面，再单独提交。当前会后提交主要更新了本地 `output/dashboard.html`；不要默认认为 GitHub Pages 已自动获得完全相同的页面内容。

## 4. API Key 与安全

Dune API Key 只应放在本地环境变量或 `.env` 中，不能提交到 GitHub。

```bash
export DUNE_API_KEY="YOUR_DUNE_API_KEY"
```

当前主提交已检查，没有上传真实 Key。完整分析前还要确认 `ETH_RPC_URL` 已配置。

## 5. 汇报时不要混淆的结论

| 不准确说法 | 应该怎么说 |
|---|---|
| “我们已经做了完整的钱包聚类” | 已有 `wallet_clustering.py` 原型，但尚未接入主 Dashboard；当前完成的是按钱包聚合 swap activity 与自适应筛选 |
| “Top 20 是全量 Holder 排名” | 是余额查询已覆盖地址中的正余额 Non-Pool Top 20；当前覆盖 80/1,134 |
| “99.41% 表示占全部池 TVL” | 只表示占 3 个 measured pools 总量的 99.41%；verified pools 共 14 个 |
| “114 次撤池金额都是 0” | 检测到 114 次动作，但 114 次都缺少 token amount，因此金额未知 |
| “Raw Liquidity Change 可以直接换算 uPEG” | 不可以；V4 liquidity delta 与 amount0/amount1 不是同一单位 |
| “DEX custody 饼图代表每个 V4 池 TVL” | 不代表；V4 PoolManager 是多个 poolId 的共享托管地址 |
| “TVL timeline 是精确余额快照” | 当前是 `event_accumulate_fallback`，应称为 activity-based reconstructed proxy |

## 6. 下一步建议（按优先级）

1. **Pool identity / custody cleanup**：决定是否从主流程移除 custody reserve 饼图；把 Contract Address、Pool Identifier、V4 Pool ID 和共享 PoolManager 关系讲清楚。
2. **选择一个真实 crash/rug 窗口分析**：使用明确的 `--incident-block`，验证撤池、价格和大钱包流向之间的时间关系。
3. **再考虑 wallet clustering UI**：原型已有，但在证据阈值和误聚类风险明确前，不建议直接作为确定性标签放进 Dashboard。
4. **提高关键案例的 holder/TVL coverage**：仅在真实 crash 案例需要时启用，避免无意义消耗 Dune/RPC quota。
5. **后续研究方向**：批量扫描、历史 crash pattern、beneficial owner 深度解析、多链和实时告警。

## 7. Git 交接状态

- 分支：`main`
- 功能提交：`d2be0a0 feat: clarify dashboard analysis semantics`
- 远程：`origin/main`
- 该功能提交包含 Dashboard、metrics、artifact schema、测试、README、方法文档和当前示例输出。
- `HANDOVER.md` 是在上述提交之后更新的，提交前请先检查 `git status`。
