# 数据方法论与答辩手册

> 状态：以当前代码为准，审计日期 2026-08-14。  
> 2026-08-14 起：volume/price 主路径复用已索引 swaps，不再重查 `dex.trades`；holdings start/end/peak/moved 由一次 `tokens_ethereum.balances` 窗口查询本地推出。

---

## 3. So，程序到底怎样从 Dune 拿数据

### 3.1 调用链

```text
业务模块调用 query("SQL 名称", 参数)
  ↓
src/data/dune.py::_prep()
  规范化 token / pool / poolId / block / bucket
  ↓
_render()
  从 queries.sql 找到 named section
  替换 {{token}} / {{from_block}} / {{to_block}} 等
  ↓
_cache_get()
  命中 output/.../dune_cache 则直接返回
  ↓ 未命中
POST https://api.dune.com/api/v1/sql/execute
  ↓ execution_id
轮询 GET /execution/{id}/status
  ↓ COMPLETED
GET /execution/{id}/results
  ↓ rows
缓存 rows，返回业务模块
```



### 3.2 分块、并行和重试

- 默认窗口超过 **3000 blocks** 时，按 **2000 blocks** 分块。
- 遇到 quota / result-size 限制时继续二分，最小到 **200 blocks**。
- 分块之间默认暂停 2 秒；结果用 `extend` 合并，不额外去重。
- HTTP 429、500、502、503、504、timeout、connection error 最多重试 7 次。
- 429 退避更长，最长 45 秒；执行轮询约 10 分钟超时。

并行只并行互相独立的数据集：

- Pool discovery：`pools` ∥ `pools_v4`，2 workers。
- Event index：swaps、V2/V3 Mint/Burn、V4 Modify、transfers，最多 6 workers。
- TVL：已有 swaps 时只查 `pool_balance_timeline`（价格本地算）；否则 `pool_balance_timeline` ∥ `price_timeline`。

并行不会改变 SQL 的公式，只缩短等待时间。单个 SQL 的 block chunks 仍是串行执行。

`dex.trades` 在一次 analyze 里的实际次数：

```text
1. pools        — 发现阶段 GROUP BY 出池地址（必须早于 index，暂时无法合并）
2. swaps        — Event index，一笔一行拉回本地
3. volume/price — 不再查 Dune；用 swaps.json 本地分桶
   仅当没有 SWAP 事件时，才回退跑 volume_timeline / price_timeline
```

不要说“dex.trades 只打一次”。正确说法是：逐笔只拉一次，图表不再重扫；发现池仍有一次独立的小聚合查询。

### 3.3 缓存意味着什么

缓存键由以下内容共同决定：

```text
SQL section 名
+ 渲染后的完整 SQL
+ 全部参数
```

因此 token、block window、SQL 内容或 bucket 变化都会生成新 key。缓存保存 Dune 返回的原始 rows，不是 dashboard 最终指标。

### 3.4 两条例外路径

以下代码不走统一的 named SQL：

- `src/data/dune_holdings.py`：内联 SQL 查询 `tokens_ethereum.balances`。主函数是 `fetch_balance_window_from_dune`（一次拿期初行 + 窗口变化点）。`fetch_historical_token_balances_from_dune` / `fetch_balance_trajectory_from_dune` 仅作失败回退。
- `src/data/dune_client.py`：另一套 Dune API / cache 封装，当前 analyze 主路径未使用

---



## 4. 逐项数据卡



## 4.1 Token Profile


| 问题  | 当前答案                                                           |
| --- | -------------------------------------------------------------- |
| 定义  | 目标 ERC-20 的链上元数据                                               |
| 来源  | Ethereum RPC                                                   |
| 调用  | `symbol()`、`name()`、`decimals()`、`totalSupply()`、`eth_getCode` |
| 时间  | 运行时链上状态；不是 Dune 历史快照                                           |
| 处理  | 包成 `TokenProfile`；decimals 用于所有 raw amount 换算                  |
| 输出  | `token_profile.json`                                           |
| 限制  | 代理合约或非标准 ERC-20 可能 call 失败                                     |


口头版：

> Token 元数据不从 Dune 拿，而是直接 RPC 调 ERC-20 合约；最重要的是 decimals，后续所有 `balance_raw` 都除以 `10^decimals`。

---



## 4.2 Pool Discovery



### 普通池


| 问题     | 当前答案                                                                     |
| ------ | ------------------------------------------------------------------------ |
| Dune 表 | `dex.trades`                                                             |
| 过滤     | block window；目标 token 在 bought/sold 任一侧；project 为 Uniswap/Balancer/Curve |
| 聚合     | 按 `project, version, project_contract_address` 分组                        |
| 字段     | protocol、version、pool address、token hints                                |
| 含义     | 窗口内实际发生过目标 token 交易的活跃池                                                  |
| 不代表    | 该 token 历史上创建过的全部池                                                       |




### Uniswap V4


| 问题     | 当前答案                                                     |
| ------ | -------------------------------------------------------- |
| Dune 表 | `PoolManager_evt_Swap` JOIN `PoolManager_evt_Initialize` |
| Join   | Swap 的 `id` 回连 Initialize                                |
| 字段     | bytes32 `pool_id`、currency0/1、fee、hooks                  |
| 原因     | `dex.trades` 的 V4 contract 常是 PoolManager，不是具体 pool      |


本地合并后写入 `pool_candidates.json`。

---



## 4.3 Pool Verification


| 问题   | 当前答案                                        |
| ---- | ------------------------------------------- |
| 来源   | Ethereum RPC                                |
| 输入   | `pool_candidates.json`                      |
| 检查   | bytecode、token0/1、factory、协议版本、V4 StateView |
| 输出   | `verified_pools.json`                       |
| 停止条件 | 没有 verified pool 时 pipeline 停止              |


V4 必须区分：

```text
pool_id / pool_address = bytes32 池标识
custody_address = 20-byte PoolManager
```

V2/V3 的资金通常保存在 pool 合约；V4 的资金由 singleton PoolManager 托管。

---



## 4.4 Holder 地址发现



### 第一次 Holdings

主路径：

```sql
FROM balances_ethereum.daily_updates
WHERE token_address = target
  AND valid_from <= window_end_date
  AND valid_to > window_start_date
  AND balance_raw > 0
```

`daily_updates` 是稀疏有效区间 `[valid_from, valid_to)`，不是每天一行。


| 问题     | 当前答案               |
| ------ | ------------------ |
| 得到     | `DISTINCT address` |
| 时间精度   | 日期，不是 block        |
| 是否逐笔加减 | 否                  |
| 含义     | 窗口日期内某个有效区间曾持有正余额  |
| 缺口     | 同一天买入并卖光可能被漏掉      |


Fallback：

1. `holders_from_transfers`：`erc20_ethereum.evt_Transfer` 的 from/to 并集
2. `transfer_addresses`：同样的地址集，额外按地址 `COUNT(*)`



### 第二次 Holdings Refresh

Step 6 索引完成后直接复用 `transfers.json` 的 actor/recipient 地址，不再优先跑 `holders`。因此第一次和最终 `holdings.json` 的候选地址集合可能不同。

---



## 4.5 Holder End Balance

这是最容易答错的部分。期末余额**不是**单独再查一次 `to_block` 快照；主路径和 4.6 共用同一次窗口查询。

### 设计目标

每个候选地址在 `to_block` 的目标 token 余额。

### 当前实际路径


| 顺序  | 数据源                                | 时间语义                                      | 是否逐笔累加                |
| --- | ---------------------------------- | ----------------------------------------- | --------------------- |
| 1   | `tokens_ethereum.balances` 窗口查询    | 窗口内最后一条变化点；窗口内无变化则用 `<= from_block` 的期初行  | 否。一次 SQL，本地取最后一行当 end |
| 2   | 窗口查询失败时：两次历史快照                     | `<= to_block` 最后一行 与 `<= from_block` 最后一行 | 否                     |
| 3   | `balances_ethereum.latest`         | 查询时最新状态，**不是 to_block**                   | 否                     |
| 4   | RPC `balanceOf(address, to_block)` | 精确到 to_block；失败可退 latest                  | 否                     |
| 5   | zero fill                          | 未覆盖地址填 0                                  | 否                     |


转换：

```text
balance_decimal = int(balance_raw) / 10^token_decimals
```

预算：

- 历史 Dune 窗口查询默认覆盖约 160 个优先地址（池优先）。
- RPC end balance 默认最多 80 个地址。
- 超出预算不等于真实余额为 0，但当前可能 `zero_fill` 为 0。

必须如实说明的当前问题：

> 最终 Holdings 可能混合窗口查询推出的 `to_block` 余额、Dune latest、RPC to_block 和 zero-fill。顶层虽然标记 `balance_block=to_block`，但并非每一行都严格同一时间点。

---



## 4.6 Start / Net / Peak / Moved In-Out

主路径一次查询 `tokens_ethereum.balances`（`fetch_balance_window_from_dune`）：

```text
start 行：每个地址 block_number <= from_block 的最后一条
窗口行：from_block < block_number <= to_block 的全部变化点
```

Python 本地推出：

```text
start = 窗口前最后余额
end   = 窗口内最后余额（没有变化则等于 start）
net_change = end - start
prev = start
遍历窗口内每个余额变更点 cur
peak = max(peak, cur)
delta > 0 → moved_in += delta
delta < 0 → moved_out += -delta
```

对象：holdings 快照预算内的地址（池优先，约 160 个）。与 4.5 的 end 是同一次查询推出来的，不是再打一遍。这不是逐笔 Transfer 加减，而是对稀疏余额账本的变化点做差。间隔不规则：余额变了才有一行，不是图表用的日/小时桶。

失败时回退到期初/期末两次快照；再对尚未覆盖的 pool + top-20 非池地址补一次轨迹查询。

未做完整轨迹的地址使用：

```text
peak_lower_bound = max(start, end)
```

因此 `two_point_snapshot` 的 peak 只是下界，不是真实窗口峰值。

---



## 4.7 LP Positions

Positions 在 Event Index 之前执行，只检查 Holdings 排名前 100 个非 pool 地址。

### V2 / 同质 LP Token

```text
RPC balanceOf(owner, to_block)
÷ totalSupply(to_block)
= share_pct
```

一行表示 `(pool, owner)`。

### V3

主路径 Dune：

```text
Pool Mint
→ 同交易 ERC721 mint 找 NPM tokenId
→ SUM IncreaseLiquidity - SUM DecreaseLiquidity
→ 取 to_block 前最后 NFT owner
→ 保留 net liquidity > 0 且 owner 在 allowlist
```

一行表示一个 open NFT position，字段含 tokenId、pool、tickLower、tickUpper、liquidity、owner。

价格状态：

- Dune：池在 `to_block` 前最后 Swap 的 `sqrtPriceX96`
- 失败：RPC `slot0`

本地用 ticks、liquidity、sqrtPrice 估 token0/1 数量和 share。

### V4

```text
PoolManager ModifyLiquidity
→ 按 poolId + salt 汇总 liquidityDelta
→ 仅保留净正仓
→ salt 映射 NFT owner
→ RPC StateView 获取 active liquidity
```

当前 `positions.json` 不是全体 LP 分布，只是排行榜候选地址的 LP 快照。

---



## 4.8 Swaps


| 问题          | 当前答案                                                                 |
| ----------- | -------------------------------------------------------------------- |
| 主表          | `dex.trades`                                                         |
| 过滤          | chain、block window、目标 token 在 bought/sold 一侧                         |
| pool filter | 主 index 当前为空，因此**拉回的逐笔 swaps 不限 verified pools**                     |
| 粒度          | 一笔 trade 一行                                                          |
| 字段          | block/time/tx/log、pool、actor、bought/sold token、raw amount、amount_usd |
| 输出          | `swaps.json`，并进入 `events_all`                                        |


这是 `dex.trades` 的逐笔主拉取。下游 volume / price / wallet activity / movers / labels 都吃这份数据，不再为图表重查同一张表。

Dune `volume_timeline` / `price_timeline` 只在 `events_all` 里没有 SWAP 时才跑。

---



## 4.9 Liquidity Events

Dune 路径不是一笔 Mint/Burn 一行。


| 协议                 | 表                 | 聚合粒度                      |
| ------------------ | ----------------- | ------------------------- |
| V2 Mint/Burn       | Pair event tables | pool + block              |
| V3 Mint/Burn       | Pair event tables | pool + block              |
| V4 ModifyLiquidity | PoolManager event | poolId + block + delta 正负 |


SQL 计算：

```text
SUM(amount0)
SUM(amount1)
COUNT(*) AS event_count
aggregation_scope = "pool_block"
```

V4 要按 delta 正负分开，防止同一 block 的 add 和 remove 抵消。

结果：

- Python normalize 为 `LIQUIDITY_ADD` / `LIQUIDITY_REMOVE`
- `event_count` 保留原事件数量
- 不保留单个 actor、recipient、tick、salt、tx hash

RPC fallback 则是一条链上 log 一行，可包含 actor。两条路径的信息粒度不同。

当前 Dune liquidity 最多查询前 40 个普通池和前 40 个 V4 poolId。

---



## 4.10 ERC-20 Transfers


| 问题   | 当前答案                                            |
| ---- | ----------------------------------------------- |
| 表    | `erc20_ethereum.evt_Transfer`                   |
| 过滤   | target token + block window                     |
| 粒度   | 一条 Transfer log 一行                              |
| 字段   | from、to、amount_raw、tx hash、block/time/log index |
| 输出   | `transfers.json`                                |
| 跳过条件 | `--fast-mode`                                   |


用途：最终 holder 地址集、地址标签、timeline。Wallet Activity 指标当前实际只使用 swaps，不直接使用 transfers。

---



## 4.11 Price Timeline


| 问题       | 当前答案                                                     |
| -------- | -------------------------------------------------------- |
| 定义       | 每个时间桶、每个池，目标 token 的最后一笔成交隐含 USD 价                       |
| 主路径      | `calculate_price_timeline_from_swaps`，吃 Step 6 已索引 swaps |
| 不查       | 有 SWAP 时不再跑 Dune `price_timeline`，即不再重扫 `dex.trades`     |
| 单笔价格     | `amount_usd / target_token_amount`（目标 token 人类单位）        |
| 匹配池      | 只保留能对上 `verified_pools` 的 swap                           |
| 分组       | pool + hour/day bucket（month→day，week/day→hour）          |
| 桶内值      | 桶内最后一笔（按 block_number、log_index；等价 SQL `MAX_BY`）         |
| fallback | 无 SWAP，或本地算不出任何 `price_usd` 时，才跑 Dune `price_timeline`   |


注意：

> 当前不是严格的每日 00:00 / 每小时整点 as-of price，而是该桶内最后一笔交易价格。没有成交的桶不会自然生成价格。没有 `amount_usd` 的 swap 不算价格。

输出嵌入 `tvl_timeline.json`，`metrics.json.tvl_timeline_source` 在走主路径时为 `dune_balance_local_price`。

---



## 4.12 Volume Timeline


| 问题  | 当前答案                                          |
| --- | --------------------------------------------- |
| 定义  | 窗口内目标 token 成交量（买+卖绝对值，不轧差）                   |
| 主路径 | `calculate_volume_metrics`，吃 Step 6 已索引 swaps |
| 不查  | 有 SWAP 时不再跑 Dune `volume_timeline`            |
| 匹配池 | 只保留能对上 `verified_pools` 的 swap                |
| 分桶  | 与 price 相同：month→day，week/day→hour            |


```text
volume_in_token =
  SUM(目标 token 在 bought 侧的数量
    + 目标 token 在 sold 侧的数量)

volume_usd = SUM(amount_usd)
```

本地再汇总：

- 同一 bucket 全部池加总
- 各池份额、`main_volume_pool`、`main_volume_share`

fallback：无 SWAP 或本地结果为空 → Dune `volume_timeline`（该 SQL 的 `pool_filter` 仍为空，**不限 verified pools**）→ 再空则 `local_swaps_fallback`。

`metrics.json.volume.source` 现场取值：

- `local_swaps`：主路径
- `dune_volume_timeline`：Dune 聚合
- `local_swaps_fallback`：Dune 也失败

输出：`volume_timeline.json` 以及 `metrics.json.volume`。

---



## 4.13 Pool Balance Timeline 与 TVL



### 余额

```text
ethereum.blocks：from/to block → 日期
utils.days：生成窗口内每一天
balances_ethereum.daily_updates：
  将 [valid_from, valid_to) 展开到每日 pool/custody balance_raw
```

这是直接余额快照，不是用 Mint/Burn 一笔一笔累计。

### 价格

来自已索引 swaps 的本地分桶（无 swaps 时才用 Dune `price_timeline`）。

### 本地合并

```text
pool_target_balance = balance_raw / 10^decimals
pool_tvl_usd = pool_target_balance × price_usd
total_tvl_usd(t) = SUM(all pools at t)
```

V4 balance 使用 20-byte PoolManager custody 地址，不使用 bytes32 poolId。

`metrics.json.tvl_timeline_source`：

- `dune_balance_local_price`：余额 Dune + 价格来自本地 swaps（主路径）
- `dune_snapshot`：余额和价格都来自 Dune
- `event_accumulate` / `event_accumulate_fallback`：用 swap/LP 事件累加，口径不同

当前限制：

- month：balance 和 price 都可按日。
- week/day：price 是小时级，但 balance 仍是日级，并非严格小时快照。
- 时间线 `tvl_in_token` 是目标 token 单边余额，不代表池中两侧完整资产。
- Dune 余额失败时回退到事件累加路径，口径会发生变化。

Dashboard 中的 `DEX Custody Token Reserve Distribution` 使用 holdings 余额快照，展示已识别 DEX 池/托管地址持有的目标 token 余额占比。它不是 LP 数量，也不是池中两侧资产的完整 USD TVL。V2/V3 地址通常对应单池；V4 的 PoolManager 是共享托管地址，因此一个扇区可能汇总多个 V4 poolId 的余额。

---



## 4.14 Pool Concentration

优先使用 RPC 在 `to_block` 获取各池近似 TVL：

- V2：目标 token reserve × 2
- V3：pool 的目标 token `balanceOf` × 2
- Curve/Balancer：目标 token balance × coin 数

```text
main_pool_share = 最大池 TVL / 所有池 TVL 加总
```

这是以目标 token 计价的近似，不是严格 USD TVL。若 RPC 路径失败，可能使用 timeline 最后一条单边 `tvl_in_token`，因此存在 `2×` 与单边口径混用风险。

Dashboard 不再把缺少 per-pool 测量的池显示为 `0%`。表格使用 `Estimated Pool Liquidity (in TOKEN)` 与 `Share Among Measured Pools (measured/verified)`，并公开 snapshot block、来源和覆盖率。百分比的分母只包含 `per_pool_tvl` 中成功得到正值的池；V4 Pool ID 因共享 PoolManager、不能从合约 `balanceOf` 直接拆分时显示 `Not measured`。因此当前 uPEG 的 `99.4%` 应读作“占 3 个已测池总量的 99.4%”，而不是占全部 14 个 verified pools。

`Top Non-Pool Holders` 不是全量持有人清单：Dashboard 排除 `is_pool=true` 的池/托管地址和非正期末余额，再按 end balance 降序排列；柱状图最多 10 行，明细表最多 20 行。`Non-Pool` 仅表示未被标记为池，仍可包含 EOA、Treasury、交易所或其他合约。排名范围受 balance-query coverage 约束。

---



## 4.15 LP Concentration

输入 `positions.json` 的 `share_pct`：

```text
每个池分别计算 top1 / top5
跨多个池取最大值，而不是直接相加
```

这样避免不同池百分比相加超过 100%。

限制：Positions 只检查排行榜地址，所以该指标不是全市场 LP concentration；缺失时可能为 0。

---



## 4.16 Withdrawal Severity

输入：`liquidity_events.json` 中的 `LIQUIDITY_REMOVE`。

处理：

1. 若有 incident block，只统计 incident 之前的撤池。
2. 只归一化目标 token 一侧，不再把 token0+token1 直接相加。
3. Dune 聚合行用 `event_count` 保留原事件数量。
4. USD 优先使用事件 `amount_usd`，其次 stable quote，再次使用 timeline price。
5. 量化覆盖使用三态：`quantified` 表示 token amount 已知；`liquidity_delta_only` 表示已确认流动性减少但缺少 token amount；`unmapped` 表示无法可靠映射目标 token 侧。只有第一种状态才计算 token、USD 和 TVL share。

公式：

```text
severity =
  min(total_removed_target_raw / pre_event_tvl_raw, 1)
```

输出：检测事件数与三态覆盖计数；对已量化事件再输出总撤出、估算 USD、分池撤出、占池 TVL 比、withdrawal severity。

限制：Uniswap V4 `ModifyLiquidity` 只直接提供 `liquidityDelta`，不直接提供 amount0/amount1；这类行只能证明发生了 removal activity，不能从 delta 直接换算 token 或 USD。Dashboard 因此显示 `Token amount not returned`，相关 USD/TVL 列显示 `Cannot calculate`，不会把零占位误报为真实 0。另一个限制是分母可能来自 `2×` pool concentration，而分子是目标 token 单边，当前可能低估或高估 severity。

---



## 4.17 Wallet Activity

当前实际只遍历 SWAP 事件：

- 按 actor 聚合买入 USD、卖出 USD、净流量、交易次数
- 排除 pool/router/custody 等基础设施地址
- 标记 large trade、large mover、high activity、cumulative volume

默认不再跨 token 使用固定 `$10k / 50 swaps`。系统在每个 token、每个分析窗口内，分别计算以下指标的 **P99（exclusive percentile）**：

- `max_single_usd`：最大单笔交易
- `abs(net_usd)`：方向性净流量
- `total_usd`：累计成交额
- `swap_count`：交易活跃度

任一指标进入窗口内 P99 即成为 Notable Wallet。这样阈值随 token 规模、市场活跃度和分析窗口自动变化；Dashboard 同时显示本次实际阈值、成交量占比与 P99 标签。显式传入旧参数时仍可使用固定阈值模式，便于回归和特定研究假设。

输出：`metrics.json.wallet_activity`，Dashboard 显示 Notable Wallets。

已有输出无需重跑链上查询，可在本地刷新筛选结果：

```bash
python3 -m src.cli dashboard \
  --output-dir output \
  --refresh-wallet-activity
```

---



## 4.18 Timeline

不新增 Dune 查询，只消费 Step 6 事件：

```text
按 block_number + log_index 排序
→ incident 前后切分
→ 统计 swaps / liquidity / transfers
→ 检查 liquidity migration 和 alternative causes
```

迁移检测需要同一个 actor 在 5 blocks 内 remove 后 add。Dune 聚合 liquidity 没有 actor，因此 Dune 主路径下迁移检测能力明显受限。

输出：`incident_timeline.json`、`crash_window.json`。

---



## 4.19 Risk Score

```text
raw =
  0.15 × pool concentration
+ 0.15 × LP concentration
+ 0.20 × withdrawal severity
+ 0.15 × temporal proximity
+ 0.15 × role sensitivity
+ 0.15 × market impact
+ 0.05 × combined activity

final =
  clamp(raw - migration_adjustment, 0, 1)
  × evidence_confidence
```

等级：

- `>= 0.7`：HIGH
- `>= 0.4`：MEDIUM
- `< 0.4`：LOW

该分数是规则型、解释型风险指标，不是统计显著性、因果推断或 rug-pull 概率。

---



## 4.20 Report 与 Dashboard

Report 接受 CLI 内存中的 profile、pools、events、positions、metrics、timeline、risk，生成 `report.md`。

Dashboard 不再访问 Dune/RPC，只读取 output 目录中的 JSON：

```text
token_profile.json
verified_pools.json
holdings.json
positions.json
events_*.json
metrics.json
volume_timeline.json
tvl_timeline.json
risk_assessment.json
incident_timeline.json
```

再生成：

- `address_dex.json`
- `portfolios.json`
- `dashboard.html`

Dashboard 重建时会用 canonical `liquidity_events` 在本地重新应用当前 withdrawal 三态语义，因此旧输出无需再次访问 Dune/RPC，也能把 V4 的未知金额从真实 0 中区分出来。

---



## 5. 聚合还是逐笔：一页速查


| 数据                          | 当前粒度                       | 关键处理                                            |
| --------------------------- | -------------------------- | ----------------------------------------------- |
| Pool discovery              | Dune：pool 分组               | 窗口内有成交即可入选；仍单独打 `dex.trades`                    |
| Holder discovery            | Dune：distinct address      | 稀疏余额有效区间重叠                                      |
| Holder start/end/peak/moved | Dune 一次窗口查询 + 本地           | 期初最后一行 ∪ 窗口变化点；本地做差。失败才拆成两次快照 + 补轨迹             |
| Swaps                       | Dune：一笔 trade 一行           | 这是 `dex.trades` 的逐笔主拉取                          |
| Volume                      | **本地** pool + bucket       | 吃 swaps；`SUM` 目标 token 绝对值。无 swaps 才 Dune `SUM` |
| Price                       | **本地** pool + bucket       | 吃 swaps；桶内最后一笔。无 swaps 才 Dune `MAX_BY`          |
| V2/V3 liquidity             | Dune：pool + block          | SUM amounts + COUNT                             |
| V4 liquidity                | Dune：poolId + block + sign | SUM delta + COUNT                               |
| Transfers                   | Dune：一条 log 一行             | 不预聚合                                            |
| V3 position                 | 一个 NFT 一行                  | Inc - Dec，最后 owner                              |
| V4 position                 | poolId + salt              | SUM liquidityDelta                              |
| Pool balance timeline       | Dune：pool/custody + day    | 展开稀疏有效区间                                        |
| TVL                         | 本地合并                       | Dune 日级 balance × 本地（或 Dune）price，再跨池 SUM       |


---



## 6. 原始需求与当前实现偏差



### 高优先级：开会必须主动说明


| 原始/展示语义                            | 当前实现                                                      | 影响                       |
| ---------------------------------- | --------------------------------------------------------- | ------------------------ |
| Holdings end 应为统一 `to_block`       | 混合 historical to_block、Dune latest、RPC to_block、zero-fill | 不同 holder 可能不是同一时间截面     |
| 每小时整点 balance                      | pool balance 只有 daily ledger                              | 小时 TVL 不是严格小时快照          |
| 每日 00:00 / 每小时整点 price             | 桶内最后一笔交易价                                                 | 稀疏交易池偏离整点 as-of          |
| TVL 统一口径                           | concentration 常用 2×，timeline 用目标 token 单边                 | withdrawal 分母和图表可能不可直接比较 |
| 风险 market impact 使用 incident block | Dune timeline 某字段写 Unix timestamp                         | 区块号与时间戳可能错配              |
| combined activity = 撤池 + 大额卖出      | 当前 large-sell 判断遍历 withdrawal events                      | 特征名称和实现不一致               |




### 中优先级


| 问题                                 | 影响                                                                                             |
| ---------------------------------- | ---------------------------------------------------------------------------------------------- |
| Positions 仅 top-100 holders        | LP concentration 不是全体 LP                                                                       |
| Dune liquidity 无 actor             | 不能强回答“谁撤池”；migration/role 证据弱                                                                  |
| Dune liquidity 最多前 40 pools        | 长尾池事件可能不完整                                                                                     |
| 原始 swaps 未只限 verified pools        | index 的 `pool_filter` 为空；本地 volume/price 会再按 verified pools 匹配，Dune volume/price fallback 仍不限池 |
| V4 holdings poolId 与 custody 地址键不同 | pool identification 余额可能显示 0                                                                   |
| 历史 snapshot/RPC 有地址预算              | 长尾 zero-fill 不能解释为真实零余额                                                                        |




### 文档漂移

`DATA_DEFINITIONS.md` 是旧口径，以下内容已过时：

- 仍写 holdings 只用 Transfer + RPC。
- 仍写 withdrawal 为 token0+token1。
- 仍写仅 Uniswap V2/V3。
- 仍写 V3 TVL 一律 balance×2，未区分新 Dune timeline。

当前答辩应以本文和代码为准，不应背诵旧文档。

---



## 7. 不能说与应该说


| 不要说                                           | 应该说                                                                                    |
| --------------------------------------------- | -------------------------------------------------------------------------------------- |
| “我们抓了所有 holder”                               | “主路径抓窗口内曾持正余额地址；refresh 还纳入窗口 Transfer 对手方，仍不是历史全体 holder”                             |
| “余额都在 to_block”                               | “优先历史 to_block，但当前含 latest/RPC/zero-fill 混合，行级需看 source”                               |
| “价格是每小时整点价格”                                  | “按小时分桶，取桶内最后成交价，不是严格整点 as-of”                                                          |
| “TVL 是精确总资产”                                  | “目前是目标 token 侧余额乘目标 token 价格；部分 concentration 使用 2× 近似”                                |
| “每一笔撤池都保留了地址”                                 | “Dune 主路径按 pool+block 聚合，不保留单个 actor；RPC 路径才逐 log”                                     |
| “LP concentration 是全市场 LP”                    | “它是排行榜候选地址中可识别 open LP 的集中度信号”                                                         |
| “Risk=崩盘概率”                                   | “它是规则加权的证据强弱分数，只表示相关风险，不表示因果或概率”                                                       |
| “并行改变了计算”                                     | “并行只同时拉独立数据集，单个 SQL 与最终公式不变”                                                           |
| “dex.trades 只查一次 / volume 在 Dune 里 SUM 所以没扫表” | “逐笔 swaps 拉一次；volume/price 本地分桶，不再重查。发现池仍有一次独立 GROUP BY。Dune 内部算 SUM 仍会扫匹配行，但结果不再拉回本地” |
| “peak 是全量地址真实峰值”                              | “窗口查询覆盖约 160 个优先地址；其余只有 max(start,end) 下界”                                             |


---



## 8. 某次运行如何现场自证

建议开会前检查：

```bash
python3 -m src.cli analyze <TOKEN> \
  --from-block <FROM> \
  --to-block <TO> \
  --output-dir output-defense
```

然后准备以下证据：


| 文件                     | 回答什么                                                           |
| ---------------------- | -------------------------------------------------------------- |
| `token_profile.json`   | token 地址、decimals                                              |
| `pool_candidates.json` | Dune 发现了哪些池                                                    |
| `verified_pools.json`  | 哪些池通过链上校验                                                      |
| `index_source.json`    | 事件本次走 Dune 还是 RPC、事件数量                                         |
| `holdings.json`        | `balance_source`、行级 `balance_source` / `trajectory_source`、起止块 |
| `volume_timeline.json` | `source=local_swaps` 还是 Dune fallback                          |
| `tvl_timeline.json`    | 余额×价格点；对照 `metrics.json.tvl_timeline_source`                   |
| `positions.json`       | 实际识别到哪些 LP                                                     |
| `metrics.json`         | `tvl_timeline_source`、`volume.source`、bucket、全部指标              |
| `risk_assessment.json` | 每个特征值、权重和贡献                                                    |
| `timing.json`          | 每一步耗时                                                          |


开会时先说“这次运行实际采用的是……”，再讲通用设计。

---



## 9. 后续工程改进顺序



### P0：先修口径正确性

1. Holdings 禁止将 `balances_ethereum.latest` 冒充 `to_block`。
2. 修复 risk 中 timeline timestamp 与 incident block 的比较。
3. combined activity 真正读取大额 sell swaps。
4. 给 TVL / withdrawal 统一单边或双边定义。



### P1：提高可解释性

1. 每次生成 `run_manifest.json`，记录 query、表、参数、row count、cache/API、fallback。
2. 每个 holder 保留准确 `balance_source` 和 `balance_block`。
3. 报告与 dashboard 明示数据粒度和 fallback。
4. 更新或废弃旧 `DATA_DEFINITIONS.md`。



### P2：向原始 structure 对齐

1. 实现严格 as-of 00:00 / hour price。
2. 实现小时级 pool balance 或明确只提供日级 TVL。
3. 评估 Sim Token Holders API 是否仍是 Balance Distribution 的目标路径。
4. 若研究问题要求行为归因，保留关键撤池事件 actor，而不是全部池级聚合。

---



## 10. 最短总述

> 系统先用 Dune 发现活跃池、持有人和窗口事件，再用 RPC 做 token/pool 验证与关键时点状态。`dex.trades` 逐笔只拉一次（swaps）；volume/price 在本地按桶聚合，有 swaps 时不再重查。发现池仍有一次独立的 `pools` GROUP BY。Dune 流动性事件按 pool+block 聚合。Holdings 的 start/end/peak/moved 来自一次 `tokens_ethereum.balances` 窗口查询，本地做差，不通过 Transfer 全量重放。TVL = 日级池余额 × 桶内最后成交价。最后由本地 Python 计算集中度、撤池严重度和规则型风险分。当前仍存在 latest/to_block、日级余额/小时价格和单边/2× TVL 混用，需要在结论中明确限制。
