# 链上流动性时间序列、相关性与异常行为研究设计

> 状态：Phase 1A 已实现（统一时间桶核心表）；Phase 1B 进行中（可靠 TVL 与 LP 身份覆盖）
> 日期：2026-08-18
> 目标：从“展示链上指标”转向“发现指标之间的领先/滞后关系，并回到具体交易解释异常行为”。

---

## 1. 研究目标

项目下一阶段不再以 Dashboard UI 优化为主，而是研究代币价格、流动性、LP 行为、交易活动和持有人活动之间的动态关系。

核心问题是：

1. LP 净流入或净流出是否领先价格、波动率或成交量变化？
2. 价格变化发生后，LP 是提前行动者还是被动反应者？
3. TVL、成交量、活跃 LP、活跃交易者和集中度之间是否存在稳定关系？
4. 指标之间出现反常背离时，背后由哪些池、交易、LP 或钱包行为驱动？
5. 这些模式能否在多个崩盘案例和正常对照窗口中重复出现？

研究链路：

```text
链上原始事件
  → 统一时间序列特征
  → 同期相关性
  → lead-lag / shift 分析
  → 异常与反常关系筛选
  → 交易级证据回溯
  → 跨案例验证
```

相关性与 shift 用于发现候选现象；具体交易行为和跨案例复现才构成研究解释。

---

## 2. 当前项目基础

项目已经具备以下原始输入：

- `tables/swaps.parquet`：逐笔交易、地址、数量、USD 成交额；
- `tables/liquidity_events.parquet`：增加/移除流动性事件；
- `tables/tvl_timeline.parquet`：分池 TVL 时间线；
- `tables/volume_timeline.parquet`：分池成交量时间线；
- `tables/positions.parquet`：可重建的 LP 仓位；
- `tables/holdings.parquet`：持仓期初、期末、峰值和净变动；
- `scripts/lp_correlation.py`：已有 Pearson 与简单 lead-lag 原型。

原型已经证明数据链路可行，但当前结果仍属于探索，不可直接作为研究结论。

### 2.1 Phase 1A 实现状态（2026-08-18）

已完成：

- 新增 `src/analysis/series.py`，独立于 Dashboard 构建研究时间序列；
- 新增 typed `tables/analysis_series.parquet` schema；
- 新增本地重建命令；默认不调用 Dune/RPC：

```bash
python3 -m src.cli research-series --output-dir output
```

- Phase 1B 增加历史 RPC 储备快照刷新：

```bash
python3 -m src.cli research-series --output-dir output --refresh-tvl
```

该模式在每个小时桶最后一个已索引区块调用目标代币
`balanceOf(custody_address, block_identifier=...)`，并记录
`tvl_snapshot_block`。它只输出能唯一归因的目标代币侧储备代理；多个 V4
Pool ID 共享同一个 PoolManager 时不会把同一余额复制到多个池。

- `analyze --artifact-format both` 会在 metrics 阶段自动生成研究表；
- 已实现 pool 与 token_total 两种 scope；
- 已实现 TVL 桶末状态、OHLC、VWAP、Volume、Swap/Trader 数、LP add/remove、覆盖率和基础派生指标；
- 已增加 TVL 不重复求和、VWAP 权重、无交易桶、未知 V4 撤池金额、派生指标和 Parquet round-trip 测试。

当前 uPEG 本地输出验收：

| 项目 | 结果 |
|---|---:|
| 输入 swaps | 3,174 |
| 输入 liquidity events | 172 |
| 输入 TVL rows | 50 |
| verified pools | 14 |
| `analysis_series` rows | 161 |
| 有观测的 pools | 12 |
| token_total 小时桶 | 25 |
| 重复主键 | 0 |
| 有 VWAP 的 pool×bucket | 27 |
| 有 TVL 状态的 pool×bucket | 50 |
| 每桶 TVL 可测池 | 2 / 14 |
| token_total 纳入的 swaps | 3,174 / 3,174 |
| 有撤池动作但金额未知的 pool×bucket | 46 |
| LP 身份完全覆盖的活动 pool×bucket | 0 |

这组覆盖诊断说明基础表和历史 RPC 路径已经可以稳定生成，当前 TVL 来源为
`rpc_target_balance_local_price`，不再使用 `event_accumulate_fallback`。但是它表示
2 个可独立归因 V2/V3 池的目标代币侧储备，不是完整双边 TVL；11 个共享
PoolManager 的 V4 池尚不能按 poolId 拆分。token_total 的成交量/价格覆盖全体
3,174 笔 swap，因此不得把全市场成交量与这个 2/14 池的部分 TVL 直接解释为
“全市场 TVL 规律”。下一步应建立 pool-matched 子样本，并补 LP 身份与 V4
流动性金额覆盖，再批准具体变量对进入正式相关性分析。

Phase 1C 已完成第一个 pool-matched 扩窗验证：`output-upeg-v3-7d/`
只选择数据可唯一归因的 uPEG/WETH V3 池，覆盖区块
`25033767–25083999`（2026-05-06 05:00 至 2026-05-13 05:00 UTC）。
RPC 共取得 4,105 笔 Swap、169 个小时价格桶和 169 个历史目标代币储备快照；
价格以 WETH 报价，不冒充 USD。168 个有效变化样本中，price return 与目标侧
reserve change 的 Pearson 为 `-0.6841`，Spearman 为 `-0.7757`，139/168 个
小时方向相反；前后半段、逐点剔除和去极值检查后关系仍保持负向。同期总成交量
相关接近 0，±24 小时 lag 的最佳绝对相关也不超过 `0.231`。这支持 AMM 库存
调整解释，但不构成 LP 撤池或因果关系证据。本次为控制公共 RPC 成本采用
swaps-only，LP event coverage 明确标记为未采集，而不是零事件。

### 2.2 当前原型的主要限制

1. uPEG 旧示例只有 15 个时间桶，相关系数不稳定。
2. 旧聚合会把同一小时、同一池的多个 TVL 观测值相加；TVL 是状态量，不应按事件求和。
3. 当前输出的 554 条 TVL 记录，在按“池 × 小时”取桶末状态后只有 96 个状态点。一次本地诊断中，旧求和口径的 TVL–Volume 相关系数约为 `0.155`，修正后约为 `0.088`，说明聚合口径会明显影响结果。
4. `active_lp_count` 依赖 liquidity event 中的 actor；当前部分数据已经按池和区块聚合，LP 身份可能缺失。
5. `holder_count` 实际表示 Transfer 中出现的活跃地址数，不等于真实持有人数量，应重命名为 `active_transfer_address_count`。
6. Phase 1B 已用历史 RPC 替换 `event_accumulate_fallback`；但当前 TVL 仍是 2/14 个可归因池的目标代币侧储备代理，不是完整双边或全市场 TVL。
7. 当前 lead-lag 只选择绝对相关系数最大的 lag，没有置信区间、多重检验修正或样本外验证。

因此，实施相关性研究前必须先统一指标定义和时间聚合语义。

---

## 3. 统一研究表：`analysis_series.parquet`

`analysis_series.parquet` 是研究特征表，Phase 1A 已实现。

它不代表新的链上数据源，而是把已有事件表按统一时间桶整理成可直接用于统计分析的宽表。

每一行表示：

```text
一个代币 × 一个分析范围 × 一个时间桶
```

分析范围包含两种：

- `scope = pool`：单个池的指标；
- `scope = token_total`：该代币所有可可靠聚合池的总体指标。

### 3.1 标识与时间字段

| 字段 | 含义 |
|---|---|
| `chain_id` | 链 ID |
| `token_address` | 目标代币地址 |
| `token_symbol` | 目标代币符号 |
| `scope` | `pool` 或 `token_total` |
| `pool_identifier` | V2/V3 合约地址或 V4 pool ID；总体行为空 |
| `custody_address` | 实际托管合约；V4 通常为共享 PoolManager |
| `protocol` / `version` | 协议和版本 |
| `bucket_start` / `bucket_end` | 时间桶起止时间 |
| `bucket_seconds` | 例如 900、3600、86400 |
| `data_coverage` | 该行关键指标的覆盖状态 |

### 3.2 价格字段

| 字段 | 含义 |
|---|---|
| `price_open` | 桶内第一笔有效交易价格 |
| `price_high` | 桶内最高有效交易价格 |
| `price_low` | 桶内最低有效交易价格 |
| `price_close` | 桶内最后一笔有效交易价格 |
| `price_vwap` | 按目标代币成交量加权的平均成交价 |
| `price_trade_count` | 参与价格计算的交易数 |
| `price_staleness_seconds` | 桶末距离最近真实成交的时间 |
| `price_source` | Dune USD、稳定币 quote、外部价格或不可得 |

### 3.3 流动性字段

| 字段 | 含义 |
|---|---|
| `tvl_token_close` | 桶末目标代币口径 TVL/储备代理值 |
| `tvl_usd_close` | 桶末 USD TVL；必须记录估值来源 |
| `tvl_snapshot_block` | 该桶状态实际读取的历史链上区块；向前填充时保留原区块 |
| `liquidity_added_token` | 桶内已量化的新增目标代币数量 |
| `liquidity_removed_token` | 桶内已量化的移除目标代币数量 |
| `net_lp_flow_token` | add − remove |
| `net_lp_flow_ratio` | 净 LP 流量 / 上一桶 TVL |
| `withdrawal_ratio` | 移除流动性 / 上一桶 TVL |
| `lp_add_event_count` | 增加流动性事件数 |
| `lp_remove_event_count` | 移除流动性事件数 |
| `active_lp_count` | 身份可用时的独立 LP 数 |
| `lp_identity_coverage` | LP 身份可识别事件比例 |

`active_lp_count` 只有在身份覆盖足够时才进入正式相关性分析；否则保留为空，不能以 0 代替未知。

### 3.4 交易与参与者字段

| 字段 | 含义 |
|---|---|
| `volume_token` | 目标代币成交数量 |
| `volume_usd` | USD 成交额 |
| `volume_turnover` | Volume / 上一桶 TVL |
| `swap_count` | Swap 数量 |
| `active_trader_count` | 独立交易地址数 |
| `large_trade_volume_share` | 大额交易占总成交额比例 |
| `buy_volume_usd` / `sell_volume_usd` | 买卖方向成交额 |
| `net_buy_flow_usd` | 买入 − 卖出 |
| `active_transfer_address_count` | Transfer 中出现的独立地址数 |

### 3.5 结构与诊断字段

| 字段 | 含义 |
|---|---|
| `main_pool_share` | 主池占已测池流动性的比例 |
| `lp_concentration` | 可测 LP 仓位集中度 |
| `holder_concentration` | 已覆盖持仓样本中的集中度 |
| `measured_pool_count` / `verified_pool_count` | 已测池和已验证池数量 |
| `tvl_source` | snapshot、event reconstruction 等 |
| `lp_identity_coverage` | LP 身份可识别事件比例 |
| `liquidity_add_amount_coverage` | 可量化加池事件比例 |
| `withdrawal_amount_coverage` | 可量化撤池事件比例 |
| `is_imputed` | 是否包含填充值 |

覆盖率字段必须与指标一起保存，避免把缺失值误解释为真实的 0。

---

## 4. 不同指标的时间聚合语义

统一时间桶不等于所有字段都使用同一种聚合函数。

| 指标类型 | 示例 | 桶内处理 | 空桶处理 |
|---|---|---|---|
| 状态量 | TVL、储备、持仓 | 每池取桶末最后状态 | 在来源允许时向前延续，并标记填充 |
| 流量 | Volume、add/remove | 求和 | 填 0 |
| 事件计数 | Swap、Mint、Burn | 计数 | 填 0 |
| 独立参与者 | trader、LP、transfer address | 地址去重计数 | 填 0；身份未知则为空 |
| 市场价格 | OHLC、VWAP | 按交易顺序和成交量计算 | VWAP 为空；close 可有限向前填充并记录 stale |
| 集中度 | pool/LP/holder share | 取桶末可用快照 | 缺失，不盲目延续 |

特别注意：

- TVL 不能把同一池在一个桶内的多次观测相加；
- 先对每个池取桶末状态，再聚合为 `token_total`；
- V4 多个 pool ID 共享 PoolManager，托管余额不能直接重复分配给每个 V4 池；
- flow 类指标的 0 表示没有观察到事件，state 类指标的 0 可能表示真实零或覆盖失败，必须区分。

---

## 5. OHLC 与 VWAP

### 5.1 VWAP 定义

VWAP 全称为 Volume-Weighted Average Price，即成交量加权平均价格。

```text
VWAP = Σ(每笔成交价格 × 每笔目标代币数量)
       ÷ Σ目标代币数量

     = 桶内总成交额 USD
       ÷ 桶内目标代币成交数量
```

示例：

| 交易 | 价格 | 数量 | 成交额 |
|---|---:|---:|---:|
| A | $1 | 10 | $10 |
| B | $2 | 10 | $20 |
| C | $3 | 80 | $240 |

普通平均价：

```text
($1 + $2 + $3) / 3 = $2
```

VWAP：

```text
($1×10 + $2×10 + $3×80) / (10+10+80) = $2.70
```

因为大部分资金在 `$3` 附近成交，`$2.70` 比简单平均的 `$2` 更能表示桶内实际资金成交水平。

### 5.2 为什么不能只保留 VWAP

VWAP 会平均整个时间桶。如果价格在桶末突然崩盘，VWAP 可能仍然较高，因此价格表必须同时保留 OHLC。

默认用途：

| 指标 | 主要用途 |
|---|---|
| `price_close` | close-to-close 收益率、崩盘时点、lead-lag |
| `price_vwap` | 桶内代表成交价、执行价格、成交成本 |
| `price_high/low` | 桶内价格范围和波动 |
| `trade_count + staleness` | 判断价格可靠性 |

例如：

```text
本小时 VWAP  = $1.20
本小时 Close = $0.70
```

这表示多数资金成交价仍较高，但桶末发生了显著下跌。`close / VWAP - 1` 本身可以作为桶末价格冲击指标。

### 5.3 无交易时间桶

- `volume` 和 `swap_count` 填 0；
- `price_vwap` 保持为空，因为没有真实成交；
- `price_close` 可以有限向前填充，但必须更新 `price_staleness_seconds` 和 `is_imputed`；
- stale 超过阈值的价格不进入高频相关性分析。

---

## 6. 用于相关性分析的转换指标

直接比较价格、TVL 等水平值容易受到趋势和规模影响。默认使用变化率或标准化比例：

```text
price_return[t]
  = log(price_close[t] / price_close[t-1])

tvl_change[t]
  = log(tvl_close[t] / tvl_close[t-1])

net_lp_flow_ratio[t]
  = net_lp_flow[t] / tvl_close[t-1]

withdrawal_ratio[t]
  = liquidity_removed[t] / tvl_close[t-1]

volume_turnover[t]
  = volume[t] / tvl_close[t-1]

close_vwap_gap[t]
  = price_close[t] / price_vwap[t] - 1
```

建议保留原始值和转换值，避免丢失解释能力。

### 6.1 需要避免的机械相关性

以下关系可能由指标定义直接产生，不能自动解释为市场规律：

- `price` 与 `TVL_USD`：TVL_USD 本身包含价格；
- `volume` 与 `swap_count`：两者来自同一批 swap；
- `active_trader_count` 与 `swap_count`：参与者数受事件数约束；
- `lp_event_count` 与 `active_lp_count`：来自同一批 liquidity events；
- `holder activity` 与 `transfer_count`：来自同一批 Transfer。

研究报告必须区分“定义上的机械关系”和“具有额外预测信息的关系”。

---

## 7. 同期相关性与 lead-lag

### 7.1 同期相关性

对转换后的指标同时计算：

- Pearson：线性相关；
- Spearman：单调但可能非线性的相关；
- 样本量 `n`；
- 置信区间和显著性；
- 原始值与去极值结果。

### 7.2 Shift 定义

统一使用：

```text
corr(X[t], Y[t+k])
```

- `k > 0`：X 领先 Y；
- `k = 0`：同期关系；
- `k < 0`：X 落后于 Y。

例如：

```text
corr(net_lp_outflow[t], price_return[t+1])
```

用于研究本小时撤池是否与下一小时收益率相关。

### 7.3 不只选择“最大相关系数”

每一组 lead-lag 结果至少报告：

- lag；
- Pearson / Spearman；
- 有效样本量；
- 置信区间或 p-value；
- 相对 lag=0 的提升；
- 多重比较修正后的显著性；
- 在其他时间粒度和样本窗口中是否稳定。

扫描大量指标和 lag 后必然会出现偶然高相关。因此不能只展示绝对值最大的结果。

### 7.4 后续检验

在样本量充足、序列平稳并处理缺失值后，可以增加：

- cross-correlation function；
- block bootstrap / 时间块置换；
- Granger predictive-causality test；
- VAR 或带控制变量的回归；
- 事件研究和匹配对照窗口。

Granger 检验只能说明 X 的历史值是否改善 Y 的预测，不能单独证明经济因果。

---

## 8. 反常模式与交易级解释

第二阶段的核心不是继续增加相关系数，而是寻找违背常见解释的组合。

### 8.1 候选反常模式

| 观测 | 初步解释 | 必须回溯的证据 |
|---|---|---|
| 大额净撤池领先负收益 | LP 可能提前退出 | Burn/ModifyLiquidity、LP 地址、后续 Swap |
| 价格先跌，LP 随后撤资 | LP 更可能是反应者 | 崩盘交易与撤池的区块顺序 |
| USD TVL 下跌但 LP 净流量接近零 | 可能只是价格估值下降 | token reserve、价格、liquidity events |
| Volume 暴涨但独立交易者不增加 | 少数地址集中驱动或循环交易 | trader、tx path、买卖往返 |
| 活跃地址增加但 Holder 集中度上升 | 表面扩散、实际集中 | 转账来源、期末余额、关联地址 |
| 桶末 Close 远低于 VWAP | 桶末发生突然抛售 | 最后若干 Swap、卖方、滑点和池深度 |
| Swap 前添加、Swap 后立即撤出 | 可能是 JIT liquidity | 同块/相邻块 Mint–Swap–Burn 顺序 |
| TVL 上升但没有 LP add | 可能是价格或 AMM 库存变化 | reserve 变化、swap 方向、价格单位 |

这些模式只是候选解释，不能在没有交易证据时直接标记为操纵、内幕或攻击。

### 8.2 异常证据包

每个高价值异常建议输出：

```text
anomaly_id
token / pool
time range / block range
triggered indicators
baseline vs observed values
best lag and correlation evidence
transaction hashes
liquidity add/remove events
large swaps and participants
before/after price, TVL and concentration
coverage and alternative explanations
```

建议产物：

- `correlation_matrix.json`；
- `lead_lag_results.json`；
- `anomalies.json`；
- `research-notes/<token>-<incident>.md`；
- 必要时生成独立研究图，而不是立即塞入主 Dashboard。

---

## 9. 样本与稳健性设计

### 9.1 单案例探索

- 使用真实事件块作为 `t=0`；
- 同时观察事件前后窗口；
- 研究窗口应明显长于最大 lag；
- 1 小时为主粒度，同时使用 15 分钟和 1 天检查方向是否稳定。

### 9.2 跨案例验证

最终不能只依赖 uPEG。建议构造：

- 多个已知 drain / rug / liquidity crash 案例；
- 每个案例对应正常时期或规模相近 token 的对照窗口；
- 区分 V2、V3、V4 和多池结构；
- 汇总哪些模式只在个案出现，哪些模式能够重复。

### 9.3 最低研究边界

- 样本桶太少时只画图，不输出“显著领先”；
- 缺失值不能统一填 0；
- 同一事件派生出的两个指标不能被描述为独立证据；
- 对所有测试记录有效样本量；
- 对 lag 搜索和多指标扫描进行多重检验控制；
- 在研究笔记中保留未支持原假设的结果，避免只挑选显著结论。

---

## 10. 实施阶段

### Phase 1 — 时间序列语义与基础表

1. 修复 TVL 的“池 × 时间桶取末值”逻辑；
2. 明确 snapshot 与 event-reconstructed TVL；
3. 生成 OHLC、VWAP、Volume、LP flow 和参与者指标；
4. 输出 `analysis_series.parquet`；
5. 增加覆盖率、缺失值和单位测试；
6. 用现有 uPEG 数据做口径验收，不把结果当跨市场结论。

### Phase 2 — 相关性与 lead-lag 引擎

1. Pearson + Spearman；
2. 原始值、差分、收益率和比例指标；
3. 多 lag 扫描；
4. 样本量、置信区间、显著性和多重检验；
5. 15 分钟、1 小时、1 天稳健性对比；
6. 输出机器可读结果和研究图。

### Phase 3 — 异常行为取证

1. 根据相关性突变、背离和 robust z-score 选择异常窗口；
2. 回溯具体 Swap、Mint/Burn/ModifyLiquidity 和地址；
3. 输出异常证据包；
4. 区分 LP 领先退出、LP 被动反应、价格估值效应、JIT 和少数地址集中交易。

### Phase 4 — 真实崩盘案例与对照研究

1. 选定多个已知事件和 incident block；
2. 为每个案例生成统一时间序列；
3. 与正常窗口或匹配 token 对照；
4. 总结可重复模式；
5. 决定哪些指标适合进入风险模型，哪些只适合研究报告。

---

## 11. Phase 1 验收标准

- 同一池同一时间桶最多一条状态行；
- `token_total` 等于可聚合池状态之和，不重复计算 V4 PoolManager；
- Volume 等流量字段按桶求和，TVL 等状态字段取桶末值；
- OHLC 和 VWAP 可从逐笔 swaps 重算并得到一致结果；
- 无交易桶的 VWAP 为缺失，而不是 0 或前值；
- `price_close` 的填充带有 staleness 和 imputation 标记；
- LP 身份未知时 `active_lp_count` 为缺失，并报告覆盖率；
- 原型不再把 `holder_count` 表述为真实 Holder 数；
- 每个派生指标能够追溯到输入表、字段、时间语义和单位；
- 旧的 uPEG `0.9608` 结果被明确标记为未验证，不继续引用为市场结论。

---

## 12. 预期研究结论的表达边界

推荐表达：

> 在该 token、该池和该窗口中，净 LP 流出领先一小时收益率的相关性高于同期相关性；结果在指定时间粒度和稳健性检验下成立，随后交易证据显示若干 LP 在价格变化前撤出流动性。

不推荐表达：

> LP 撤池导致了代币崩盘。

最终目标不是制造一个普遍因果结论，而是建立一条透明、可复现的链上证据链：

```text
统计关系 → 时间顺序 → 具体交易 → 地址行为 → 替代解释 → 跨案例复现
```
