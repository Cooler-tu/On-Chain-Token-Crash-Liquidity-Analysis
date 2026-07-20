# On-Chain Token Crash Analysis — 数据口径文档

本文档定义了系统所有产出数据的来源、计算方式、假设条件和已知限制。

---

## 1. 输出文件总表

token_profile.json - 代币元数据
pool_candidates.json - 候选池列表
verified_pools.json - 验证通过的池
swaps.json - Swap 事件
liquidity_events.json - 流动性事件
transfers.json - Transfer 事件
events_all.json - 合并事件流
holdings.json - 持仓持有人列表
metrics.json - TVL/集中度指标
risk_assessment.json - 风险评分
report.md - 报告
dashboard.html - HTML 可视化

---

## 2. 持有者相关指标

### Unique Addresses (from transfers)
数据源: holdings.json -> total_unique_addresses
计算方式: 在指定区块窗口内统计 Transfer 事件的 from/to 地址并去重
口径方向: "窗口中活跃地址数"，非 "总持币人数"

### Holders with Balance
数据源: holdings.json -> holdings_count
计算方式: 对每个 unique address 调用 balanceOf()，余额 > 0 的计数
限制: 只查询窗口中活跃的地址

### Holder Balance
数据源: holdings.json -> holdings[].balance_decimal
计算方式: int(balance_raw) / (10 ** token_decimals)
精度: 6 位小数

---

## 3. 池相关指标

### Verified Pools
数据源: verified_pools.json
发现方式: Factory.getPair/getPool(快速) + PairCreated事件(穷举)
验证条件: bytecode存在 + factory()匹配 + token0/token1一致 + 反向确认
置信度线: >= 0.3

### TVL
V2: reserve0 * 2(当target=token0) 或 reserve1 * 2
V3: balanceOf(target) * 2(近似值，会高估)
单位: 目标token raw unit，非USD
限制: V3 TVL用balanceOf*2是高估，准确值需基于tick计算

### Main Pool Share
计算: 最大池TVL / 所有池TVL总和
示例: 0.9753 = 主池占97.53%

---

## 4. LP 持仓相关指标

### LP Concentration
数据源: metrics.json -> lp_concentration
V2: 从LP Token Transfer事件重建余额
V3: 扫描PositionManager事件，按tokenId映射
已知问题: 短窗口几乎永远得到0个position -> top_lp_share=0

---

## 5. 撤池相关指标

### Withdrawal Severity
数据源: metrics.json -> withdrawal_severity
计算: sum(removed_token0+token1) / pre_event_tvl
上限: 1.0(100%)
筛选: 只统计有pool_address的撤池事件

---

## 6. 风险评分口径

### 公式
raw_score = 0.15*pool_concentration + 0.15*lp_concentration
          + 0.20*withdrawal_severity + 0.15*temporal_proximity
          + 0.15*role_sensitivity + 0.15*market_impact
          + 0.05*combined_activity

final_score = clamp(raw_score - migration_adjustment, 0, 1) * evidence_confidence

### 特征权重表

特征: Pool Concentration, 权重0.15
  输入: main_pool_share(0-1), 直接使用

特征: LP Concentration, 权重0.15
  输入: top_lp_share(0-100), 除以100

特征: Withdrawal Severity, 权重0.20
  输入: withdrawal_severity(0-1), 直接使用

特征: Temporal Proximity, 权重0.15
  输入: 撤池距crash时间: <1h=1.0, <6h=0.8, <24h=0.5, <7d=0.3

特征: Role Sensitivity, 权重0.15
  输入: deployer参与池子: 直接=0.8, 关联=0.6

特征: Market Impact, 权重0.15
  输入: 价格跌幅, min(price_drop, 1.0)

特征: Combined Activity, 权重0.05
  输入: 撤池数+大额卖盘组合

特征: Evidence Confidence, 调节因子
  输入: 非零特征计数, min(0.55+count*0.09, 1.0)

### 等级划分
>= 0.7: HIGH
0.4-0.7: MEDIUM
< 0.4: LOW

### 使用限制
1. 无incident-block时 temporal proximity和market impact为0
2. LP Concentration常缺，15%权重不参与
3. 分数代表相关性非因果性

---

## 7. 当前已知限制

V3 TVL用balanceOf*2近似 -> TVL高估
LP Concentration短窗口不可用 -> 风险分缺失15%权重
Unique Addresses非全量持有人 -> 持有者统计偏低
仅支持Ethereum+Uniswap V2/V3 -> 其他链不可用
事件索引受RPC限制 -> 大窗口慢(已实现断点续扫)

---

> 总结: 系统强项在池发现/验证和持仓结构分析。风险评分需理解特征覆盖限制，避免将单一数字作为决策依据。
