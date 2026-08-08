# 项目交接文档

生成时间：2026-08-07

> 本次交接重点：Dashboard 指标层（V3/V4 价格、分池 TVL、分池成交量、Top Movers、撤回事件表）已完成；下一步是 holder 双时间点快照 / 事件流重建。

> 2026-08-08 更新：holder 双时间点第一步已完成 —— Dune `tokens_ethereum.balances`
> 历史快照已验证（uPEG 12/12 与 RPC `balanceOf` 精确一致，期末覆盖 4,640 个有余额地址），
> `holdings.py` 已输出 `balance_start` / `balance_end` / `net_change` / `peak_balance`，
> dashboard 的 Top Holders / Top Movers 已接入这些字段（快照块 + 来源标注）。

## 项目目标

做一个公开、可自助查询的链上代币流动性 / 崩盘分析工具：

- 输入任意 ERC-20 地址 / 符号 + 区块窗口
- 输出池子、Swap、流动性事件、持仓、集中度、风险评分、Markdown 报告和本地 HTML Dashboard
- 覆盖 Ethereum 主网的 Uniswap V1-V4、Curve、Balancer V2
- 数据入口优先走 Dune，RPC 做兜底或链上校验
- 最终发布为 GitHub Pages 公共站点，支持浏览历史崩盘模式

## 当前状态速览（2026-08-07）

| 能力 | 状态 | 说明 |
|---|---|---|
| Price timeline（V3/V4） | 已完成 | `tvl_timeline.json` 新增 `price_usd`，dashboard 有分池价格图 |
| Trading volume 按池贡献 | 已完成 | `volume_timeline.json` + 堆叠柱状图 + 每池占比 |
| Holder 余额口径 | 已完成 | `balance_start / balance_end / net_change / peak_balance` 已落地（Dune 历史快照 + 重点地址事件流）；Top Holders / Top Movers 已展示 |
| Pool concentration / main pool 定义 | 已完成 | dashboard 同时展示 TVL 主池、成交量主池、每池 TVL/Volume 明细 |
| Pool TVL timeline 分池 | 已完成（交互待补） | 分池多线图 + 明细表已完成；点击数据点看各池明细尚未做 |
| Liquidity removal detection | 部分完成 | 撤回事件表已上 dashboard；按池、按 USD 归一待做 |
| Large wallet transaction tracking | 部分完成 | Top Movers 已按钱包聚合买卖；USD 阈值与池比例口径待做 |
| LP provider analysis | 已完成（探索原型） | `scripts/lp_correlation.py` + `docs/LP_CORRELATION_DESIGN.md` |
| 地址关联 / 钱包聚类 / 资金流 | 部分完成 | 可行性文档 + `fund_flow.json` 原型已完成；钱包聚类待做 |

## 本次会话完成的改动

### 数据层

- `src/indexer/dune_index.py`：Dune swap 行保留 `token0_address` / `token1_address` / `amount_usd`，是后续按池算成交量、算价格的基础。
- `src/data/dune_client.py`：池发现 SQL 改为收集全部 token 提示（`token_hints`）并加 `volume_usd`。注意：此文件在本次会话开始前已是用户侧脏改动，我们继续使用并接上新逻辑，**不要回退**。

### 指标层（核心改动，`src/analysis/metrics.py`）

- `build_tvl_timeline` 从 V2/V3 扩展到 V3/V4，并新增 `price` / `price_usd` / `quote_symbol`。
- V4 PoolManager 是单例，很多池共用同一个 `pool_address`。新增 `_event_matches_pool`，按精确 token 交易对匹配事件，避免把别的池的 swap 混进 timeline。
- 新增 `_resolve_target_side`，判断每笔 swap 中目标代币在 0/1 哪一侧；旧数据没有 token 地址时用小数位量级做兜底推断。
- 新增 `calculate_volume_metrics`：按池聚合成交量、按小时分桶，输出 `volume_by_pool`、`volume_usd_by_pool`、`volume_timeline.json`，并区分 TVL 主池和成交量主池。

### Dashboard（`src/analysis/dashboard.py`）

- 新增 Price Timeline (USD)：每个池一条价格线。
- 新增 Trading Volume by Pool：按池堆叠的每小时成交量柱状图。
- Pool TVL Timeline 改为「总 TVL + 每个池一条线」，直接回答风险来自哪个池。
- Pool Concentration 卡片增加主池说明文字：TVL 主池、成交量主池、各自占比。
- 新增 Top Movers 表：按钱包聚合的买入 / 卖出 / 净额 / 交易次数。
- 新增 Liquidity Withdrawals 表：撤回事件明细（区块、池、actor、金额）。
- All Verified Pools 表增加每池 TVL、Volume、TVL Share、Vol Share。

### 探索原型与文档

- `scripts/lp_correlation.py`：LP 相关性 / 领先滞后分析原型。
- `scripts/fund_flow.py`：资金流聚合原型（Transfer 事件 → 有向边）。
- `docs/HOLDER_BALANCE_DESIGN.md`：holder 余额口径设计（双时间点快照 vs 事件流重建）。
- `docs/LP_CORRELATION_DESIGN.md`：LP 相关性设计与结果。
- `docs/ADDRESS_ASSOCIATION_DESIGN.md`：钱包聚类 / 资金流可行性。
- `WEEK_2026-08-07.md`、`plan.md`：同步进度。

## 数据口径（新接手者必读）

1. **main pool 定义**：`main_pool` = 当前快照下 TVL 最大的池；`main_pool_share` = 该池 TVL / 所有有效池 TVL。**它不等于成交量主池**，dashboard 两者分开展示。
2. **V4 池过滤**：V4 所有池共享 PoolManager 地址，只能靠 Dune swap 里的 token 地址精确配对。没有 token 地址的历史事件无法可靠归属，会跳过或归入 ambiguous。
3. **价格口径**：`price_usd` 是 Dune `dex.trades.amount_usd` 除以目标 token 数量得到的成交均价近似值，不是预言机价格；`quote_symbol` 只做展示。
4. **成交量口径**：`volume_in_token` 永远是目标 token 一侧的绝对数量；`volume_usd` 优先用 `amount_usd`，否则只在 quote 为已知稳定币（USDC/USDT/DAI）时按金额折算，其余池报 `null`。
5. **Top Movers 当前口径**：从 swap 事件按钱包聚合「买入 / 卖出 / 净额」，是**近似值**，不是真实余额净变动；holder 双时间点快照落地后要切换。
6. **撤回事件当前口径**：`calculate_withdrawal_severity` 目前把 `token0_amount + token1_amount` 直接相加，容易高估，已知待修。

## 当前数据状态（uPEG 示例）

- 代币：uPEG `0x44b28991B167582F18BA0259e0173176ca125505`（decimals=18，total supply 10000）
- 窗口：Block 25008000 → 25011999
- 已验证池 2 个：
  - V4 `0x000000000004444c5dc75cB358380D2e3dE08A90`（uPEG/USDC，PoolManager 单例地址，按 token pair 匹配）
  - V3 `0xdc893995d488E5BE8eC8CA1Db92CBEc2a1ab0775`（uPEG/WETH）
- 数据量：`events_all.json` 34,371 条；`swaps.json` 14,066 条；`tvl_timeline.json` 5,885 点（其中 5,666 点有 `price_usd`：V4 3,374 + V3 2,292）；`volume_timeline.json` 8 个小时桶
- 指标：TVL 主池 V4（95.06%），成交量主池 V3（53.55%）；总成交量约 2,107.43 uPEG
- 原型输出：`output-lp-correlation-demo/lp_correlation.json`、`output-fund-flow-demo/fund_flow.json`
- Dashboard：`output/dashboard.html`

LP 相关性原型结果（仅探索，样本只有 15 个小时桶）：

- TVL 与成交量：lag 0 时 corr ≈ 0.96
- TVL 领先 LP 事件数约 1 小时：corr ≈ 0.76

**不能作为独立风险信号，只能提示关联方向。**

## 关键文件

| 路径 | 作用 |
|---|---|
| `src/analysis/metrics.py` | TVL timeline、价格、成交量、集中度、撤回指标 |
| `src/analysis/dashboard.py` | dashboard HTML 生成（全部新增图表和表） |
| `src/indexer/dune_index.py` | Dune swap 归一化（保留 token 地址、amount_usd） |
| `src/data/dune_client.py` | Dune API 客户端（工作区已有改动，继续使用） |
| `scripts/lp_correlation.py` | LP 相关性 / 领先滞后原型 |
| `scripts/fund_flow.py` | 资金流聚合原型 |
| `docs/HOLDER_BALANCE_DESIGN.md` | holder 余额口径设计 |
| `docs/LP_CORRELATION_DESIGN.md` | LP 相关性设计 |
| `docs/ADDRESS_ASSOCIATION_DESIGN.md` | 地址关联可行性 |
| `WEEK_2026-08-07.md` | 本周计划 + 进度 |
| `plan.md` | 总计划 |

## 复现命令

```bash
# 只重新生成 dashboard（用已有 output/）
python3 -m src.cli dashboard --output-dir output

# 全量分析 uPEG（重新拉数据）
python3 -m src.cli analyze 0x44b28991B167582F18BA0259e0173176ca125505 \
  --from-block 25008000 --to-block 25011999 --output-dir output

# LP 相关性原型
python3 scripts/lp_correlation.py --output-dir output \
  --out-dir output-lp-correlation-demo

# 资金流原型
python3 scripts/fund_flow.py --output-dir output \
  --out-dir output-fund-flow-demo

# 生成公共站点（提交后执行；不要 push 公共 fork，需用户确认）
python3 scripts/publish_site.py
```

## 已知问题 / 边界

1. V4 事件如果没有 Dune token 地址，无法可靠区分 PoolManager 下的具体池。
2. `price_usd` 是成交均价近似，不是预言机价格。
3. `holdings.json` 仍是单点快照：uPEG 的 3,075 个唯一地址中约 80 个真正查了余额（RPC 上限），其余填 0；Top Holders 是采样子集，不是全量。
4. `calculate_withdrawal_severity` 直接相加 token0 + token1，可能高估撤回金额。
5. LP 相关性样本太小，仅作探索。
6. 旧已知问题：Dune `dex.pool_tvl` 表不存在，`fetch_pool_tvl()` 仍需要换真实存在的 TVL / 池余额表。

## 待办（按顺序）

1. **Holder 双时间点快照 / 事件流重建**（下一步）：给 `holdings.json` 补 `balance_start` / `balance_end` / `net_change`，Top Movers 重点地址补 `peak_balance` 和余额轨迹；方案和成本模型见 `docs/HOLDER_BALANCE_DESIGN.md`。
2. 撤回事件按池、按目标 token / USD 归一，补每池净撤出和占池 TVL 比例。
3. 大额钱包改为 USD 阈值 / 占池成交量比例口径。
4. dashboard 点击 TVL 数据点显示该时间点各池明细（当前用明细表代替）。
5. 钱包聚类原型（gas payer / deployer / owner() 信号，Dune creation_traces）。
6. README 分析日志与功能清单同步，提交后重新生成公共站点。

## 工作区状态 / 提交注意

当前 git 工作区未提交，本次会话涉及的改动：

| 文件 | 状态 |
|---|---|
| `src/analysis/metrics.py`、`src/analysis/dashboard.py` | 已修改 |
| `src/indexer/dune_index.py` | 已修改 |
| `src/data/dune_client.py` | 已修改（**用户原有改动，勿回退**） |
| `output/`（dashboard.html、metrics.json、swaps.json 等） | 已重新生成并跟踪 |
| `WEEK_2026-08-07.md`、`WEEK_PLAN.md` | 新增 |
| `docs/HOLDER_BALANCE_DESIGN.md` 等三份文档 | 新增 |
| `scripts/lp_correlation.py`、`scripts/fund_flow.py` | 新增 |

注意：`.env` 不入 git；公共 fork 推送前必须与用户确认（AGENTS.md 第 8 条）。

## 不要重做

- 完整分析流水线（resolve → profile → discover → verify → index → positions → labels → metrics → timeline → risk → report → holdings → dashboard）
- Uniswap V1-V4、Curve、Balancer 接入与验证
- Dune 统一查询层和 CLI
- 本次的 V4 按 token pair 过滤、分池 TVL / 成交量、LP 相关性原型

## 历史交接摘要（2026-08-02，供背景）

上一轮会话完成 CRV 端到端修复：Curve v1/v2 `TokenExchange` 事件签名与 ABI 修正、web3 `anonymous` 字段兼容、Curve 池不再按 Uniswap 索引、Balancer `getPoolId()` 严格验证、Dune `dex.trades` 改用 `project_contract_address`。CRV 示例窗口 22000000-22005000，6 verified / 7 total，687 swaps，风险 0.4703 MEDIUM。
