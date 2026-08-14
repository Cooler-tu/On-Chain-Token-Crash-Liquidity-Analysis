# Dune SQL 与 CLI Pipeline

本文说明 `src/cli.py` 中 `analyze` pipeline 的每个步骤如何获取数据，以及这些步骤如何通过 `src/data/dune.py` 执行 `src/data/dune_sql/queries.sql`。

## 1. 总体调用关系

`src/cli.py` 通常不直接请求 Dune，而是调用 discovery、holdings、positions、indexer、metrics 等业务模块。这些模块统一调用：

```python
query("sql_section_name", **params)
```

总体关系：

```text
src/cli.py
  ↓
业务模块
  ├── discovery/engine.py
  ├── analysis/holdings.py
  ├── analysis/positions.py
  ├── indexer/dune_index.py
  └── analysis/metrics.py
       ↓
src/data/dune.py::query()
       ↓
src/data/dune_sql/queries.sql
       ↓
Dune SQL API
```

真正通过 `src/data/dune.py` 获取 Dune 数据的是：

```text
Step 2  Pool Discovery
Step 4  Holdings
Step 5  LP Positions
Step 6  Event Indexing
Step 8  Metrics
```

其他步骤主要使用 RPC，或消费前面已经获取的数据。

---

## 2. `src/data/dune.py` 的职责

### 2.1 加载 named SQL section

所有 SQL 模板集中在：

```text
src/data/dune_sql/queries.sql
```

每个模板使用 marker 分隔：

```sql
-- === name: holders ===
SELECT ...
```

`_load_sections()` 读取整个文件，并建立：

```python
{
    "pools": "...",
    "pools_v4": "...",
    "holders": "...",
    ...
}
```

业务代码调用：

```python
query("holders", token=..., from_block=..., to_block=...)
```

即可执行 `holders` section。

### 2.2 参数准备

`_prep()` 负责：

- 设置默认 chain、bucket 和空 SQL fragment。
- 把 token、pool、NPM 等转成 Ethereum address。
- 把 `pool_list`、`address_list` 转成 SQL `IN (...)` 内容。
- 把 V4 `pool_id_list` 当作 bytes32，而不是普通地址。
- 格式化交易哈希列表和 NFT token ID 列表。
- 把区块参数转成整数。

普通 Ethereum address 与 V4 poolId 必须分开：

```text
20-byte address → _addr / _addr_list
32-byte poolId  → _hex32 / _hex32_list
```

### 2.3 SQL 渲染

`_render()`：

1. 根据 section name 找到 SQL。
2. 检查所有 `{{parameter}}` 是否存在。
3. 替换模板参数。
4. 返回最终 Dune SQL。

例如：

```sql
WHERE token_address = {{token}}
  AND evt_block_number BETWEEN {{from_block}} AND {{to_block}}
```

会被渲染成实际 token 和区块范围。

### 2.4 缓存

缓存键由以下内容共同决定：

```text
SQL section 名称
+ 渲染后的 SQL
+ 所有参数
```

缓存位于调用者指定的 `dune_cache` 目录。

执行时：

```text
有缓存 → 直接读取 rows
无缓存 → 请求 Dune → 保存 rows
```

SQL 内容或参数变化后，cache key 会变化，不会误用旧查询结果。

### 2.5 Dune API 请求

远程查询流程：

```text
POST /api/v1/sql/execute
  ↓
获取 execution_id
  ↓
轮询 /execution/{id}/status
  ↓
GET /execution/{id}/results
  ↓
返回 list[dict]
```

网络超时、HTTP 429 和部分 5xx 会自动重试，最多七次。

429 使用更长的退避时间，避免轮询继续触发限流。

### 2.6 Block 分块

`query()` 默认规则：

```text
窗口 ≤ 3000 blocks → 单次查询
窗口 > 3000 blocks → 默认每 2000 blocks 一段
```

也可以显式设置：

```python
chunk_blocks=0       # 禁止分块
chunk_blocks=2000    # 固定每段 2000 blocks
```

分块查询内部是串行的：

```text
chunk 1 → chunk 2 → chunk 3 → 合并 rows
```

如果某段仍然超过 quota，会继续二分，最小到 200 blocks。

### 2.7 并行查询

`query_parallel()` 同时运行多个互相独立的 `query()`：

```python
query_parallel(
    [
        ("pools", params),
        ("pools_v4", params),
    ],
    max_workers=2,
)
```

需要区分：

```text
业务 SQL 之间：可以并行
单个 SQL 的 block chunks：目前串行
```

---

## 3. `analyze` Pipeline

实际执行顺序：

```text
1.  Token Profile
2.  Pool Discovery
3.  Pool Verification
4.  Holdings / Leaderboard
5.  LP Positions
6.  Event Indexing
7.  Address Labels
8.  Metrics
9.  Timeline
10. Risk
11. Report
    Holdings Refresh
12. Dashboard
```

`cli.py` 函数顶部的 docstring 仍保留旧顺序；应以函数正文为准。

---

## 4. Step 1 — Token Profile

入口：

```python
profile = profile_token(w3, token_address, chain_id_val)
```

数据来源：

```text
Ethereum RPC
```

主要获取：

- token address
- symbol
- decimals
- decimals source

此步骤不调用 `src/data/dune.py`。

输出：

```text
token_profile.json
```

---

## 5. Step 2 — Pool Discovery

入口：

```python
result = discover_pools(
    w3,
    token_address,
    from_block,
    to_block,
    chain_id_val,
    cache_dir=out / "dune_cache",
    rpc_mode=discovery_rpc,
)
```

`discover_pools()` 通过 `query_parallel()` 同时执行：

```text
pools
pools_v4
```

### 5.1 `pools`

数据源：

```text
dex.trades
```

筛选顺序：

```text
block_number 范围
→ blockchain
→ token_bought_address 或 token_sold_address 是目标 token
→ project 属于 Uniswap / Balancer / Curve
→ 按 project、version、pool_address 分组
```

输出：

```text
project
version
pool_address
token_hint
token_hint2
```

这里发现的是分析窗口内实际交易过目标 token 的 pools，不是目标 token 历史上的全部 pools。

### 5.2 `pools_v4`

数据源：

```text
uniswap_v4_ethereum.PoolManager_evt_Swap
JOIN
uniswap_v4_ethereum.PoolManager_evt_Initialize
```

通过 Swap 的 `id` 回连 Initialize，取得：

```text
pool_id
currency0
currency1
fee
hooks
```

V4 使用 bytes32 poolId，不能把 PoolManager 地址当成具体 pool。

### 5.3 合并与 RPC fallback

两条查询返回后，discovery 模块：

1. 标准化 protocol/version。
2. 处理 Balancer poolId。
3. 合并普通 pools 和 V4 poolIds。
4. 根据 `--discovery-rpc` 决定是否额外执行 RPC discovery。

默认：

```text
--discovery-rpc off
```

输出：

```text
pool_candidates.json
```

---

## 6. Step 3 — Pool Verification

入口：

```python
verified_pools = verify_pools(...)
```

此步骤不新增 Dune 查询。

输入是 Step 2 的 pool candidates，然后通过 RPC 检查：

- bytecode
- token0/token1
- protocol/version
- custody address
- pool verification confidence

输出：

```text
verified_pools.json
```

如果 verified pool 数量为零，pipeline 停止。

---

## 7. Step 4 — Holdings / Leaderboard

入口：

```python
holdings_result = analyze_holdings(
    w3,
    target_token,
    token_decimals,
    [],                  # 第一次调用还没有 indexed transfers
    verified_pools,
    from_block,
    to_block,
    source="auto",
)
```

因为第一次调用传入空 transfer list，`source=auto` 且配置了 Dune API key 时，会走 Dune holder discovery。

### 7.1 Holder 地址查询

顺序为：

```text
query("holders")
  ↓ 失败
query("holders_from_transfers")
  ↓ 失败
query("transfer_addresses")
```

#### `holders`

数据源：

```text
ethereum.blocks
balances_ethereum.daily_updates
```

先将起止区块转换成日期，然后筛选：

```text
token_address = target token
token_standard = erc20
valid_from <= window_end
valid_to > window_start
balance_raw > 0
```

`daily_updates` 是稀疏有效区间：

```text
[valid_from, valid_to)
```

不是每个地址每天一行。

该查询表示：

> 地址在分析日期窗口中的某个有效区间内持有正余额。

它会漏掉同一天买入并在当天卖光的地址。

#### `holders_from_transfers`

数据源：

```text
erc20_ethereum.evt_Transfer
```

将窗口内目标 token 的：

```text
from
to
```

合并后去重，并排除零地址。

#### `transfer_addresses`

同样使用 Transfer，但额外计算：

```text
address
tx_count
```

这是最后一级 Dune holder 地址回退。

### 7.2 Holder 当前余额

获取地址后调用：

```python
query(
    "balances",
    token=token_address,
    address_list=top_addresses,
)
```

数据源：

```text
balances_ethereum.latest
```

输出：

```text
address
balance_raw
```

失败后使用 RPC：

```text
ERC20 balanceOf(address, to_block)
```

### 7.3 第二套历史余额路径

`holdings.py` 还会调用：

```text
src/data/dune_holdings.py
```

该模块没有通过 `src/data/dune.py::query()`，而是自己调用 Dune API，并查询：

```text
tokens_ethereum.balances
```

用于获取部分地址在：

```text
from_block
to_block
```

的双时间点历史余额。

所以 Holdings 当前实际存在两套 Dune 访问方式：

```text
queries.sql + src/data/dune.py
src/data/dune_holdings.py 内联 SQL
```

### 7.4 Leaderboard 传给 LP

Holdings 完成后：

```python
leaderboard = [
    holder
    for holder in holdings
    if not holder["is_pool"]
]

owner_allowlist = leaderboard[:100]
```

Step 5 只检查这些排名靠前的地址是否持有 LP。

主要输出：

```text
holdings.json
holdings_table.csv
pool_identification_table.csv
tables/holdings.parquet        # --artifact-format both
```

---

## 8. Step 5 — LP Positions

入口：

```python
positions, pos_summary = analyze_positions(
    w3,
    verified_pools,
    [],
    target_token,
    from_block,
    to_block,
    owner_allowlist=owner_allowlist,
)
```

这里同样尚未完成 Step 6 event indexing，所以传入的 indexed events 为空。

### 8.1 V3 主查询

优先调用：

```text
query("positions_uniswap_v3_snapshot")
```

该 SQL 将以下逻辑放在一个查询中：

```text
V3 Pair Mint
→ 通过同 tx 的 ERC721 mint Transfer 找 NPM tokenId
→ 得到 pool、tickLower、tickUpper
→ SUM IncreaseLiquidity
→ SUM DecreaseLiquidity
→ net liquidity = increase - decrease
→ 找 to_block 前最后 NFT owner
→ 只保留 net liquidity > 0
→ owner 必须在 owner_allowlist
```

输出：

```text
nft_token_id
pool_address
tick_lower
tick_upper
liquidity
owner
```

### 8.2 V3 staged fallback

如果完整 snapshot 查询失败：

```text
positions_uniswap_v3_base
→ positions_uniswap_v3_liquidity
→ positions_nft_owners
```

第一步获取 tokenId、pool、ticks。

第二步按最多 400 个 tokenId 一批计算净 liquidity。

第三步只为 open positions 查询最新 owner。

### 8.3 V3 价格与 tick 估值

调用：

```text
query("pool_sqrt_price_v3")
```

取得每个 V3 pool 在 `to_block` 之前最后一笔 Swap 的：

```text
sqrtPriceX96
```

本地使用：

```text
sqrtPriceX96
tickLower
tickUpper
liquidity
```

计算 position 的 token0/token1 数量和 share。

如果 SQL 失败，使用 RPC pool `slot0`。

### 8.4 V3 RPC fallback

如果 Dune snapshot 和 staged 都没有有效结果，转 RPC position reconstruction。

由于 Step 5 发生在 event indexing 前，RPC fallback 无法复用 indexed NFT events。

必要时会调用：

```text
query("liquidity_uniswap_v3_npm_token_ids")
```

通过 Pair Mint 与 NPM ERC721 mint Transfer 恢复 tokenId。

### 8.5 V4 Positions

调用：

```text
query("positions_uniswap_v4_liquidity")
```

按：

```text
poolId
salt
```

汇总 `liquidityDelta`，只保留净正仓位。

再调用：

```text
query("positions_nft_owners")
```

获取对应 NFT 最新 owner。

V4 slot0、active liquidity 等状态仍通过 RPC StateView 获取。

主要输出：

```text
positions.json
position_summary.json
tables/positions.parquet        # --artifact-format both
```

---

## 9. Step 6 — Event Indexing

Step 6 仍索引 raw swaps 和（非 fast mode）raw token transfers，但 LP 流动性事件已经改为：

```text
按 pool + block 聚合
```

它不再下载每个 LP actor、recipient、tx hash、tick 或 NFT salt。Step 5 负责排行榜地址的 LP position；Step 6 只保留池级流动性流入/流出，供撤池风险和时间线使用。

入口：

```python
indexed = index_events(
    w3,
    verified_pools,
    target_token,
    from_block,
    to_block,
    index_token_transfer=not fast_mode,
    source=index_source,
)
```

`index_events()` 根据：

```text
--index-source auto|dune|rpc
```

选择 Dune 或 RPC。

### 9.1 并行 Dune jobs

Dune 路径会建立：

```text
swaps
liquidity_uniswap_v2_mint
liquidity_uniswap_v2_burn
liquidity_uniswap_v3_mint
liquidity_uniswap_v3_burn
liquidity_uniswap_v4_modify
transfers
```

这些 job 使用 `ThreadPoolExecutor` 并行，最大 worker 数为 6。

每个查询强制：

```python
chunk_blocks=2000
min_chunk_blocks=200
```

因此结构是：

```text
不同 SQL jobs：并行
单个 SQL 的 block chunks：串行
```

### 9.2 `swaps`

数据源：

```text
dex.trades
```

筛选：

```text
区块范围
目标 token 在 bought/sold 任一侧
```

主 index 传入：

```text
pool_filter=""
```

所以这里拉的是目标 token 在所有 DEX 的 raw trades，不仅是 verified pools。

输出包括：

```text
block/time/tx/log
protocol/version/pool
actor/tx_from
token bought/sold
raw amounts
amount_usd
```

### 9.3 V2/V3 Liquidity（pool/block aggregate）

调用：

```text
liquidity_uniswap_v2_mint
liquidity_uniswap_v2_burn
liquidity_uniswap_v3_mint
liquidity_uniswap_v3_burn
```

只查询前 40 个普通 pool addresses。Dune SQL 现在按：

```text
evt_block_number
contract_address
```

分组，然后计算：

```text
SUM(amount0)
SUM(amount1)
COUNT(*) AS event_count
aggregation_scope = pool_block
```

不再返回：

```text
sender / owner
recipient
transaction_hash
单笔 log_index
```

Python 根据 SQL section 将聚合行 normalize 成：

```text
LIQUIDITY_ADD
LIQUIDITY_REMOVE
```

其中 `event_count` 保存该 pool/block 聚合行代表的原始事件数量，因此 withdrawal count 不会因为聚合而变小。

### 9.4 V4 Liquidity（pool/block/sign aggregate）

调用：

```text
liquidity_uniswap_v4_modify
```

只处理前 40 个 V4 poolIds，每 8 个 poolId 一批。

Dune SQL 按：

```text
evt_block_number
poolId
liquidityDelta 正负
```

分组。正负必须分开，避免同一个 block 内 add 与 remove 互相抵消：

```text
SUM(liquidityDelta)
COUNT(*) AS event_count
aggregation_scope = pool_block
```

通过聚合后 `liquidityDelta` 的正负判断添加或移除。

不再下载每个 V4 LP 的：

```text
sender
tickLower / tickUpper
salt
transaction_hash
```

这些 position-level 信息属于 Step 5，不属于 Step 6。

### 9.5 Transfers

非 `fast_mode` 时调用：

```text
query("transfers")
```

拉取目标 token 在窗口内全部 raw Transfer：

```text
from
to
amount_raw
tx_hash
block/time/log
```

### 9.6 错误处理

Indexer 内部：

```text
swaps 失败       → Dune index 失败，外层可回退 RPC
liquidity 失败   → 跳过该 liquidity job
transfers 失败   → 跳过 Transfer
HTTP 429         → dune.py 重试和退避
quota/result size→ dune.py 缩小 block chunk
```

输出：

```text
swaps.json
liquidity_events.json
transfers.json
events_all.json
index_source.json
tables/swaps.parquet              # --artifact-format both
tables/liquidity_events.parquet   # --artifact-format both
tables/transfers.parquet          # --artifact-format both
tables/positions.parquet          # --artifact-format both (written in Step 5)
```

---

## 10. Step 7 — Address Labels

入口：

```python
labels = analyze_labels(
    target_token,
    verified_pools,
    positions,
    swaps,
    liquidity_events,
    transfers,
)
```

此步骤不新增 Dune 查询。

它消费 Step 5 和 Step 6 已经获得的数据：

- LP owners
- swaps
- pool/block liquidity aggregates
- token transfers

Deployer lookup 使用 RPC。由于 Step 6 聚合行不包含 LP actor，labels 不再从这些聚合行给每个 LP 地址添加协议标签；LP owner 标签来自 Step 5 positions。

---

## 11. Step 8 — Metrics

入口：

```python
metrics = calculate_all_metrics(...)
```

这是 pipeline 中第二个主要 Dune 查询阶段。

### 11.1 Chart span

根据分析窗口决定 bucket：

```text
month → day
week  → hour
day   → hour
```

该设置覆盖完整 `from_block` 到 `to_block`，不是 dashboard UI toggle。

### 11.2 TVL：balance 与 price 并行

同时执行：

```text
query("pool_balance_timeline")
query("price_timeline")
```

worker 数为 2。

#### `pool_balance_timeline`

数据源：

```text
ethereum.blocks
utils.days
balances_ethereum.daily_updates
```

处理：

```text
block window → date window
→ 把 daily_updates 的 [valid_from, valid_to) 区间展开
→ 每日、每个 pool/custody 输出 balance_raw
```

V4 使用 custody/PoolManager 的 20-byte address，而不是 bytes32 poolId。

#### `price_timeline`

数据源：

```text
dex.trades
```

处理：

```text
目标 token + block window
→ 按 pool + hour/day 分组
→ amount_usd / target token amount
→ MAX_BY(price, block_time)
```

当前语义是桶内最后一笔成交价，不是严格的整点 as-of price。

#### 本地合并

Python 按 pool/time 合并：

```text
balance_raw / 10^decimals × price_usd
= pool TVL
```

再按时间点汇总所有 pools。

如果 snapshot 路径失败：

```text
events_all
→ 本地累加 swaps 与 pool/block Mint/Burn aggregates
→ event_accumulate_fallback
```

聚合后的 amount 总和仍可用于 fallback，但无法恢复单个 LP 的身份或单笔交易。

### 11.3 Volume

TVL 查询完成后，再调用：

```text
query("volume_timeline")
```

数据源：

```text
dex.trades
```

Dune 内完成：

```text
block filter
→ token filter
→ hour/day bucket
→ pool group
→ SUM target-token volume
→ SUM USD volume
```

如果查询失败或结果为空，则使用 Step 6 的 raw swaps 在 Python 本地聚合。

主要输出：

```text
metrics.json
tvl_timeline.json
volume_timeline.json
tables/tvl_timeline.parquet       # --artifact-format both
tables/volume_timeline.parquet    # --artifact-format both; one bucket/pool per row
```

在 `both` 模式下，`metrics.json` 只保留 concentration、withdrawal、wallet activity 和
timeline 元数据；完整 TVL/volume 图表行从 Parquet 读取。独立运行 `dashboard` 时优先
读取 Parquet，旧输出则回退到原有 JSON。Volume 行会重新组合为前端现有的 bucket→pool
结构，因此图表接口不变。

---

## 12. Step 9 — Timeline

入口：

```python
timeline = analyze_timeline(
    events_all,
    swaps,
    liquidity_events,
    transfers,
    ...
)
```

此步骤不新增 Dune 查询。

使用 Step 6 已获取的 raw events，生成：

- 时间顺序
- incident 前后变化
- liquidity migration
- 事件统计

---

## 13. Step 10 — Risk

入口：

```python
risk = compute_risk(...)
```

此步骤不新增 Dune 查询。

输入：

- pool concentration
- LP concentration
- withdrawal severity
- TVL timeline
- labels
- deployer
- liquidity migration

---

## 14. Step 11 — Report

入口：

```python
report = generate_report(...)
```

此步骤不新增 Dune 查询。

它将 profile、pools、events、positions、labels、metrics、timeline 和 risk 写入：

```text
report.md
```

---

## 15. Post-Step 11 — Holdings Refresh

如果 Step 6 成功获取 transfers，且没有使用 `fast_mode`：

```python
holdings_result = analyze_holdings(
    ...,
    transfers,
    source=holdings_source,
)
```

第二次调用已经有 indexed transfers。

在 `source=auto` 下：

```text
直接复用 transfers 找地址
```

不会再次执行 `holders` 地址发现查询。

但仍可能：

- 通过 `dune_holdings.py` 获取历史双点余额。
- 调用 `query("balances")` 补余额。
- 使用 RPC `balanceOf` 补剩余地址。

该步骤会覆盖第一次生成的 holdings artifacts。

需要注意：

```text
第一次 holdings 排名 → 决定 Step 5 的 LP owner_allowlist
第二次 holdings refresh → 更新最终 holdings
positions 不会根据新排名重新计算
```

---

## 16. Step 12 — Dashboard

入口：

```python
dashboard_path = generate_dashboard(output_dir=output_dir)
```

此步骤不访问 Dune。

它读取 output 目录中的本地 artifacts：

```text
token_profile.json
verified_pools.json
holdings.json
positions.json
metrics.json
timeline JSON
risk JSON
```

然后生成：

```text
dashboard.html
timing.json
```

---

## 17. Pipeline 与 Dune 查询对应图

```text
CLI analyze
│
├─ Step 1 Profile ───────────── RPC
│
├─ Step 2 Discovery
│    └─ query_parallel()
│         ├─ query("pools")
│         └─ query("pools_v4")
│
├─ Step 3 Verification ──────── RPC
│
├─ Step 4 Holdings
│    ├─ query("holders")
│    ├─ fallback query("holders_from_transfers")
│    ├─ fallback query("transfer_addresses")
│    ├─ query("balances")
│    ├─ dune_holdings.py inline Dune SQL
│    └─ RPC balanceOf
│
├─ Step 5 Positions
│    ├─ query("positions_uniswap_v3_snapshot")
│    ├─ query("pool_sqrt_price_v3")
│    ├─ staged V3 query fallbacks
│    ├─ query("positions_uniswap_v4_liquidity")
│    ├─ query("positions_nft_owners")
│    └─ RPC slot0 / StateView / NFT position calls
│
├─ Step 6 Event Index ───────── up to 6 workers
│    ├─ query("swaps")
│    ├─ query("liquidity_uniswap_v2_mint")  ┐
│    ├─ query("liquidity_uniswap_v2_burn")  │ pool + block aggregate
│    ├─ query("liquidity_uniswap_v3_mint")  │ no individual LP actor
│    ├─ query("liquidity_uniswap_v3_burn")  ┘
│    ├─ query("liquidity_uniswap_v4_modify")  pool + block + delta sign
│    └─ query("transfers")
│
├─ Step 7 Labels ────────────── reuse positions/events
│
├─ Step 8 Metrics
│    ├─ query("pool_balance_timeline")
│    │        ∥
│    ├─ query("price_timeline")
│    └─ query("volume_timeline")
│
├─ Step 9 Timeline ──────────── reuse indexed events
├─ Step 10 Risk ─────────────── reuse metrics/timeline/labels
├─ Step 11 Report ───────────── reuse all artifacts
├─ Holdings Refresh ─────────── indexed transfers + balance filling
└─ Step 12 Dashboard ────────── local files only
```

---

## 18. 其他 CLI 子命令

### `discover-only`

```text
Profile
→ Dune pools + pools_v4
→ RPC verify
```

### `holdings`

该子命令与完整 `analyze` 的顺序不同：

```text
Profile
→ Discover/Verify
→ 先 Index Transfers
→ analyze_holdings
```

因此它通常可以直接复用 indexed transfers。

### `dashboard`

不访问 Dune，只从 output 目录重新生成 dashboard。

### `dune pools`

直接调用：

```text
query("pools")
```

注意：这个独立命令目前不调用 `pools_v4`。

### `dune swaps`

直接调用：

```text
query("swaps")
```

并通过 `pool_filter` 限制到指定 pool。

### `dune tvl`

直接调用：

```text
query("pool_tvl")
```

数据源是 `dex.pool_tvl`。这只是 CLI helper，不是 dashboard 的 product TVL 路径。

---

## 19. 当前实现中的重要限制

### 19.1 小时 TVL 不是真正小时余额

`pool_balance_timeline` 使用：

```text
balances_ethereum.daily_updates
```

只能提供每日余额。

当 chart span 为 week/day 时：

```text
price = hourly
balance = daily，并在本地向小时点延续
```

因此当前小时 TVL 实际是：

```text
当日余额 × 每小时价格
```

如果要求每小时直接读取真实余额，需要使用：

```text
balances_ethereum.updates
```

或其他支持 block/hour snapshot 的数据源。

### 19.2 Price 不是严格整点价格

`price_timeline` 使用：

```sql
MAX_BY(price, block_time)
```

这表示 bucket 内最后一笔成交，不是离整点最近的 as-of price。

### 19.3 Pool discovery 依赖窗口内成交

没有在分析窗口内产生 Swap 的池不会被 `pools` 或 `pools_v4` 找到。

默认 `discovery_rpc=off` 时，也不会额外通过 RPC 补齐静默池。

### 19.4 Liquidity 已聚合，但 raw swaps/transfers 仍然很大

Step 6 的 V2/V3/V4 liquidity 已经在 Dune 按 pool/block 聚合，不再下载每个 LP actor。图表也优先使用聚合 SQL。

目前仍可能产生大量数据的是：

- movers
- labels
- timeline
- local metrics fallback

对应的 raw 数据源是：

```text
swaps
transfers
```

其中主 index 的 `swaps` 没有限制 verified pools。

### 19.5 聚合后不再做 LP actor migration attribution

旧的 liquidity migration 逻辑通过同一 actor 在相邻区块中：

```text
pool A remove
→ pool B add
```

判断可能的迁移。

现在 Step 6 不下载个人 LP actor，因此该 attribution 无法执行。Timeline 会返回：

```text
actor_attribution_available = false
migration_detected = false
note = not evaluated from pool/block aggregates
```

这不会影响按池统计的：

```text
removed amount
withdrawal count
withdrawal severity
TVL fallback
```

### 19.6 Wallet clustering 不在 `analyze`

以下 SQL 不属于完整 analyze pipeline：

```text
cluster_transfers
cluster_gas_payers
cluster_traces
```

它们由 `analysis/wallet_clustering.py` 的独立命令使用。

目前 `cluster_traces` 虽然会被抓取，但尚未进入 edge/signals 计算。

### 19.7 部分 SQL 已定义但未接入

当前没有主调用者：

```text
pool_token_balances
token_meta
```

`pool_tvl` 只用于 `cli dune tvl`。

### 19.8 Dune 权限

以下表可能受 Dune plan 权限影响：

```text
balances_ethereum.latest
balances_ethereum.daily_updates
balances_ethereum.updates
```

如果 API 返回 private / missing，holders 和 metrics 会进入各自 fallback。
