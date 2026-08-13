# 导师追问清单与口头回答

配套阅读：[数据方法论与答辩手册](./METHODOLOGY_DEFENSE.md)。

使用方法：

- 先背每题的“短答”，控制在 20–30 秒。
- 导师继续追问时再展开“细答”。
- 当前实现有缺口时直接说明，不要把近似描述成精确值。

---

## A. Dune 抓取机制

### Q1：程序是怎么从 Dune 把数据拿下来的？

**短答**

业务模块按名字调用 `query()`，程序从 `queries.sql` 取出对应 SQL，替换 token、block window 等参数，先查本地 cache；没有缓存才调用 Dune SQL Execute API，轮询 execution id，完成后下载 rows 并缓存。

**细答**

API 顺序是：

```text
POST /api/v1/sql/execute
→ GET /execution/{id}/status
→ GET /execution/{id}/results
```

窗口大于 3000 blocks 默认每 2000 blocks 切块。遇到 quota 继续二分，最小 200 blocks。HTTP 429/5xx 等最多重试 7 次。

---

### Q2：为什么要并行？并行会不会改变结果？

**短答**

并行只用于互不依赖的数据集，例如 pools 与 pools_v4、balance 与 price。每个 SQL 的筛选和聚合不变，所以并行改变的是等待时间，不是计算口径。

**追问点**

- Discovery：2 workers
- Event index：最多 6 workers
- TVL balance/price：2 workers
- 单个 SQL 的 block chunks 仍串行

---

### Q3：缓存会不会读到旧数据？

**短答**

缓存 key 同时包含 SQL 名、渲染后的 SQL 和全部参数。token、区块窗口、bucket 或 SQL 内容变化都会生成新 key，不会直接复用旧查询。

**限制**

相同 SQL 和参数会复用历史返回值；若 Dune 底层表回补数据，需要 force refresh 才能重新抓。

---

### Q4：大窗口如何避免 Dune 免费额度或结果过大？

**短答**

默认超过 3000 blocks 时分成 2000-block chunks；某块仍超额则二分，最小到 200 blocks。各块 rows 最后按顺序拼接。

**注意**

拼接阶段不额外去重，因此 SQL 查询必须保证相邻 block 区间不重叠；当前区间使用闭区间且下一段从前段末尾加一开始。

---

### Q5：Dune 失败以后程序怎么办？

**短答**

不同步骤策略不同。Discovery 会记录错误并可继续 RPC；Index 在 auto 模式可回退 RPC；部分 liquidity/transfer job 失败会跳过并保留已有数据；TVL 失败会回退到事件累计。需要看 output 的 source 字段确认某次运行到底走了哪条路径。

---

## B. Pool

### Q6：所有池是怎么找到的？

**短答**

普通池从 `dex.trades` 找窗口内目标 token 实际成交过的 pool，按 protocol、version、pool address 分组；V4 单独用 Swap 的 pool id 回连 Initialize，得到真正 bytes32 poolId。

**不能说**

不能说这是 token 的历史全部池，只能说是分析窗口内的活跃交易池。

---

### Q7：为什么找到池以后还要 RPC 验证？

**短答**

Dune discovery 给的是候选池。RPC 再检查 bytecode、token0/token1、factory 和协议状态，防止把 router、PoolManager 或错误 contract address 当成池。

---

### Q8：V4 为什么不能像 V2/V3 一样直接用 pool address？

**短答**

V4 使用 singleton PoolManager。具体池由 bytes32 `poolId` 标识，资金托管地址是 20-byte PoolManager。查询 StateView 用 poolId，查询 ERC-20 custody balance 用 PoolManager 地址，两者不能互换。

---

### Q9：Pool discovery 为什么基于交易，而不是扫描所有 Factory？

**短答**

研究关注分析窗口内真正有市场活动的流动性场所。`dex.trades` 可以跨协议快速筛出活跃池，RPC Factory 扫描更慢，默认只作为可选补充或 fallback。

**限制**

窗口内没有成交但仍持有流动性的池可能不会被发现。

---

## C. Holder 与 Balance

### Q10：Holder 地址到底是怎么找到的？

**短答**

第一次优先查询 `balances_ethereum.daily_updates`，取余额有效区间与窗口日期重叠且 `balance_raw>0` 的 distinct address。事件索引完成后，再用窗口内 Transfer 的 from/to 地址刷新最终集合。

---

### Q11：`daily_updates` 是每天一条余额吗？

**短答**

不是。它是稀疏有效区间 `[valid_from, valid_to)`。一行表示这个余额值在一段日期内有效；holder discovery 只判断该区间是否和研究窗口重叠。

---

### Q12：同一天买入又卖光的人能抓到吗？

**短答**

只用 `daily_updates` 可能漏掉，因为日级有效区间未必留下正余额。程序准备了 Transfer from/to fallback，而且 Step 6 后的 holdings refresh 会纳入窗口 Transfer 对手方。

---

### Q13：Holder balance 是把 Transfer 一笔一笔加出来的吗？

**短答**

不是。主历史路径查询 `tokens_ethereum.balances` 稀疏余额账本，对每个地址取目标 block 之前最后一条余额记录。RPC fallback 直接调用 `balanceOf(address, block)`。

---

### Q14：End Balance 是哪个时间点？

**短答**

设计目标是 `to_block`，历史账本和 RPC 路径可以精确到 `to_block`。但当前补洞还会使用 `balances_ethereum.latest`，并且长尾可能 zero-fill，因此最终结果目前不是所有地址统一同一时间截面。

**这是必须主动承认的当前缺口。**

---

### Q15：为什么还要用 `balances_ethereum.latest`？

**短答**

它用于历史快照没覆盖到的地址快速补洞，但它代表查询时最新状态，不是历史 `to_block`。当前这样提高覆盖率，却造成时间口径混合，后续应该改成严格历史快照或把每行时间来源明确暴露。

---

### Q16：是否查询了所有地址的余额？

**短答**

候选地址可以很多，但精确历史和 RPC 查询有预算。默认历史 snapshot 大约优先 160 个地址，RPC 大约 80 个，pool 地址优先；超预算地址可能 zero-fill，所以不能把所有 0 都解释为真实零余额。

---

### Q17：Start、End、Net Change 怎么算？

**短答**

Start 是 `from_block` 前最后余额快照，End 是 `to_block` 目标快照，`Net = End - Start`。两者都是余额状态，不是把窗口 Transfer 简单求和。

---

### Q18：Peak Balance 怎么算？

**短答**

对快照预算内的地址，一次读取 `tokens_ethereum.balances` 的期初行 + 窗口变化点，取过程最大值。其他地址只有 `max(start,end)`，这只是 peak 的下界。

---

### Q19：Moved In / Moved Out 是 Transfer 金额总和吗？

**短答**

不是。它遍历相邻余额快照，用 `delta=current-previous`；正 delta 累加 moved-in，负 delta 累加 moved-out。这是余额变化，不一定能逐笔对应某个 Transfer。

---

### Q20：EOA 和合约怎么区分？

**短答**

Pool 地址直接标为 pool；部分优先地址通过 RPC `eth_getCode` 判断是否有 bytecode。为了控制 RPC 成本，只检查前一部分地址，长尾标记 unknown，不能把 unknown 当 EOA。

---

## D. Positions 与事件

### Q21：LP positions 是全量 LP 吗？

**短答**

不是。Holdings 先排出非 pool holder，Step 5 只检查前 100 个候选地址是否有 open LP。它是排行榜地址的 LP 暴露，不是全池 LP census。

---

### Q22：V3 position 怎么重建？

**短答**

先用 pool Mint 和同交易的 ERC-721 mint 找 NFT tokenId，再计算 IncreaseLiquidity 减 DecreaseLiquidity 的净 liquidity，取 `to_block` 前最后 NFT owner，只保留净 liquidity 大于 0 的 open position。

---

### Q23：V3 position 的 token 数量怎么从 liquidity 得到？

**短答**

取 position 的 tickLower、tickUpper、liquidity，再取得池在 `to_block` 附近的 `sqrtPriceX96`，按 Uniswap V3 tick math 计算 token0/token1 数量；SQL 失败时价格状态回退 RPC `slot0`。

---

### Q24：Swap 是逐笔还是聚合？

**短答**

`swaps.json` 主路径来自 `dex.trades`，一笔 trade 一行，保留 tx hash、log index、pool、actor、两侧 token amount 和 amount_usd。

---

### Q25：Liquidity event 是逐笔吗？

**短答**

Dune 主路径不是。V2/V3 按 pool+block 聚合，V4 按 poolId+block+delta 正负聚合，保留 amount SUM 和 event_count，但不保留单个 actor。RPC fallback 才是一条 log 一行。

---

### Q26：为什么要把 liquidity 聚合？

**短答**

Step 6 主要服务撤池规模和时间线，不需要下载每个 LP 的完整 position 字段。池级聚合显著降低 Dune rows 和额度压力；LP owner 的仓位信息由 Step 5 单独处理。

**代价**

无法从 Dune 聚合行直接回答“具体谁撤池”，也削弱 migration 和 deployer-role 归因。

---

### Q27：V4 同一 block 内加池和撤池会互相抵消吗？

**短答**

不会。SQL 除了按 poolId、block 分组，还按 `liquidityDelta` 正负分组，因此 add 和 remove 分开聚合。

---

### Q28：Transfers 保留到什么粒度？

**短答**

一条 ERC-20 Transfer log 一行，保留 from、to、amount_raw、tx hash、block time 和 log index。只有 fast mode 会跳过完整 Transfer 索引。

---

## E. Price、Volume 与 TVL

### Q29：价格从哪里来？

**短答**

从 `dex.trades` 的 `amount_usd / 目标 token 数量` 得到单笔隐含美元价格，再按 pool 和时间桶分组。

---

### Q30：是平均价、收盘价还是整点价格？

**短答**

当前是时间桶内最后一笔成交价，SQL 用 `MAX_BY(price, block_time)`。它近似桶末价格，但不是严格整点 as-of，也不是成交量加权平均价。

---

### Q31：没有成交的小时怎么办？

**短答**

当前该 pool 在该桶不会自然产生价格行；系统没有严格向前填充一个全局整点价格序列。这也是低流动性池时间线的限制。

---

### Q32：Volume 怎么算？

**短答**

Dune 按 pool 和 hour/day bucket，把目标 token 位于 bought 或 sold 一侧的 token amount 做 SUM，同时对 `amount_usd` 做 SUM；Python 再把各池加总，并保留 per-pool 份额。

---

### Q33：买和卖会不会把 volume 正负抵消？

**短答**

不会。Volume 使用两侧成交的绝对 token amount 语义，买入和卖出都计入成交量，不带方向相减。方向性净流量在 wallet activity 中单独计算。

---

### Q34：Pool balance timeline 是逐笔累计出来的吗？

**短答**

不是。它用 `balances_ethereum.daily_updates` 的有效区间直接展开到每天，取得每个 pool/custody 的目标 token 余额快照。

---

### Q35：TVL 的公式是什么？

**短答**

时间线主路径是：

```text
目标 token balance_raw / 10^decimals × 该池该桶 price_usd
```

然后同一时点跨池加总。

---

### Q36：这个 TVL 是完整双边 TVL 吗？

**短答**

时间线不是，它是目标 token 单边余额按目标 token 价格估值。Pool concentration 的链上快照又常用目标侧×2近似双边 TVL，因此当前两处口径并不完全一致。

---

### Q37：为什么 Pool concentration 要乘 2？

**短答**

V2 等常假设池两侧按价值接近 50/50，用目标 token 侧价值×2近似总池价值。对 V3 集中流动性和非对称池，这只是近似，不能称为精确 TVL。

---

### Q38：周/日图是小时级 TVL 吗？

**短答**

价格是小时分桶，但 pool balance 仍来自日级 ledger，所以不是真正的小时余额快照。小时内看到的 TVL 变化主要来自价格变化，不能解释为小时级真实资金流入流出。

---

## F. Withdrawal、Timeline 与 Risk

### Q39：撤池严重度是不是 token0+token1 相加？

**短答**

不是。当前已经改为只归一化目标 token 一侧，避免直接把不同币种 raw amount 相加。

---

### Q40：Withdrawal Severity 公式是什么？

**短答**

```text
min(目标 token 总撤出 raw / 参考 TVL raw, 1)
```

同时输出美元估算和每个池的撤出占比。

**限制**

当前参考 TVL 可能使用×2近似，而分子是目标 token 单边，分子分母口径仍需统一。

---

### Q41：能不能判断是谁撤了池？

**短答**

Dune 主路径的 liquidity 已按 pool+block 聚合，没有单个 actor，因此只能确定哪个池、哪个 block、撤出总量和事件数，不能直接归因到某个钱包。若必须做 actor 归因，需要 RPC 逐 log 或保留关键 Dune raw events。

---

### Q42：Liquidity migration 怎么判断？

**短答**

同一 actor 在 5 blocks 内先从一个池 remove、再向另一个池 add，会被标为迁移候选。但 Dune 聚合路径没有 actor，因此这个检测在主路径下覆盖较弱。

---

### Q43：Risk score 是机器学习概率吗？

**短答**

不是。它是规则型加权分数，由集中度、撤池严重度、时间接近性、角色、市场影响等特征组成，用于解释风险证据强弱，不是 crash probability。

---

### Q44：Risk 各特征权重是什么？

**短答**

Pool 15%、LP 15%、Withdrawal 20%、Temporal 15%、Role 15%、Market Impact 15%、Combined Activity 5%，之后减 migration adjustment，再乘 evidence confidence。

---

### Q45：Evidence confidence 是统计置信度吗？

**短答**

不是。它只是根据非零证据特征数量构造的覆盖度调节因子。多个特征还可能同源，因此不能解释成统计学 confidence interval。

---

### Q46：HIGH、MEDIUM、LOW 如何划分？

**短答**

Final score ≥0.7 为 HIGH，≥0.4 为 MEDIUM，否则 LOW。等级只总结当前规则体系下的风险信号，不证明恶意行为或因果关系。

---

### Q47：当前风险模型最需要修的是什么？

**短答**

第一是统一 block height 与 Unix timestamp；第二是让 combined activity 真正读取 sell swaps；第三是统一 TVL 和 withdrawal 的单边/双边口径；第四是明确缺失 LP/actor 数据时哪些特征不可用。

---

## G. 展示与可信度

### Q48：Dashboard 打开时还会实时请求 Dune 吗？

**短答**

不会。Dashboard 只读 output 目录已有 JSON，生成静态 HTML。数据刷新必须重新运行 analyze 或相关子命令。

---

### Q49：为什么 Dashboard 不同表里的 pool balance 看起来不一样？

**短答**

因为目前有三种口径：Holdings 表显示 pool/custody 的 token end balance；Verified Pools 表显示近似 pool TVL；时间线显示日级目标 token balance×price。它们不是同一个指标，不能直接逐值比较。

---

### Q50：你如何证明这次运行用的是 Dune 还是 RPC？

**短答**

看 `output/index_source.json`、`holdings.json` 的 `source/balance_source`、`metrics.json` 的 `tvl_timeline_source`，再结合 `dune_cache` 和 CLI 日志。不能只根据代码的默认配置判断某次运行。

---

### Q51：当前结果最可靠的部分是什么？

**短答**

Pool 候选发现后再 RPC 验证、逐笔 swaps/transfers、Dune historical balance 快照和明确公式的 SQL 聚合较容易复核。需要谨慎的是混合时间口径的 holdings、近似 TVL、非全量 LP concentration 和缺 actor 的撤池归因。

---

### Q52：如果导师指出一个口径问题，怎么回答？

建议格式：

> 对，这里当前实现是……，它与原设计的……有偏差。这样做的原因是……，代价是不能解释为……。目前结果里我把它当作近似/限制，修复方案是……。

不要回答：

> 应该是……、可能是 Dune 自动算的、代码里大概做了……

---

## 最后 60 秒总述

> 我们的主数据路径是 Dune SQL 加少量关键 RPC。Dune 负责跨协议池发现、holder 候选、逐笔 swaps/transfers、池级流动性聚合以及 balance/price/volume 时间线；RPC 负责 token 元数据、候选池验证和关键时点状态。余额不是通过 Transfer 全量重放，而是优先使用稀疏余额账本在目标 block 前的最后快照。Swaps 和 Transfers 是逐笔数据，Dune liquidity 为 pool+block 聚合。TVL 时间线用目标 token 的 pool balance 乘时间桶价格，风险分再组合集中度、撤池、时间与角色特征。当前最大的限制是 holdings 时间点混合、日级 balance 配小时 price、TVL 单边与×2近似并存，以及聚合 liquidity 缺少 actor；所以结果应解释为可追溯的风险信号，而不是精确因果结论。
