# 项目交接文档

生成时间：2026-08-02

## 项目目标

做一个公开、可自助查询的链上代币流动性 / 崩盘分析工具：

- 输入任意 ERC-20 地址 / 符号 + 区块窗口
- 输出池子、Swap、流动性事件、持仓、集中度、风险评分、Markdown 报告和本地 HTML Dashboard
- 覆盖 Ethereum 主网的 Uniswap V1-V4、Curve、Balancer V2
- 数据入口优先走 Dune，RPC 做兜底或链上校验
- 最终发布为 GitHub Pages 公共站点，支持浏览历史崩盘模式

## 当前完成情况

### 已完成的整体能力

- 完整分析流水线：resolve → profile → discover → verify → index → positions → labels → metrics → timeline → risk → report → holdings → dashboard
- Uniswap V1/V2/V3/V4 池发现、验证、索引、持仓
- Curve / Balancer V2 池接入验证
- 持仓分析、池账号标记、EOA/合约标签
- Dashboard 持仓展开、DEX venue 标签
- Dune 统一查询层和 CLI：`dune pools | swaps | tvl | data-map`
- `--pools-file` 支持从 Dune 导出的池列表进入验证
- GitHub Pages 发布脚本

### 本次会话完成的修复

CRV 端到端 0 事件问题已修复，根因和改动如下：

1. Curve v1 池 `TokenExchange` 事件签名是 `int128` 版，仓库 ABI 之前用 `uint256`，导致事件查不到。
2. Curve v2 池 `TokenExchange` 是 7 参数版本，仓库 ABI 只支持 5 参数版本。
3. Curve ABI 事件缺少 `anonymous` 字段，web3 解码 `RemoveLiquidityOne` 时抛 `KeyError`，又被索引器静默吞掉。
4. Curve 池被错误地当作 Uniswap v1/v2 池索引，浪费查询且拿不到事件。
5. Balancer poolId 解析用了错误的 topic 位置，现改为 `args.poolId` / `topics[1]`。
6. Balancer 验证过于宽松，现要求池合约必须能返回 `getPoolId()` 并通过 Vault `getPoolTokens()` 校验。
7. Dune `dex.trades` 查询使用了不存在的 `pool_id` 列，已改为 `project_contract_address`。
8. 无事件时报告窗口显示 `Block 0 to 0`，已补上请求的区块窗口。

## 已验证的 Dune 路径

### Dune pools：通过

命令：

```bash
python3 -m src.cli dune pools \
  --token 0xD533a949740bb3306d119CC777fa900bA034cd52 \
  --from-block 22000000 --to-block 22000100 \
  --output-dir output-dune-crv-e2e
```

结果：成功，`22000000-22000100` 窗口内找到 5 个池，包含 Curve、Uniswap、SushiSwap，已保存到：

```text
output-dune-crv-e2e/dune_pools.json
```

### Dune swaps：通过

命令：

```bash
python3 -m src.cli dune swaps \
  --pool 0x4ebdf703948ddcea3b11f675b4d1fba9d2414a14 \
  --from-block 22000000 --to-block 22005000 \
  --output-dir output-dune-crv-e2e
```

结果：成功，返回 580 条 Swap，与 RPC 索引结果一致，已保存到：

```text
output-dune-crv-e2e/dune_swaps.json
```

### Dune tvl：失败（已知问题，本次不继续修）

命令：

```bash
python3 -m src.cli dune tvl \
  --pool 0x4ebdf703948ddcea3b11f675b4d1fba9d2414a14 \
  --output-dir output-dune-crv-e2e
```

失败原因：

```text
Table 'delta_prod.dex.pool_tvl' does not exist
```

`src/data/dune_client.py` 的 `fetch_pool_tvl()` 仍引用不存在的 `dex.pool_tvl` 表，需要在下一步换用 Dune 当前真实存在的 TVL / 池余额表。

## 当前运行状态

### CRV 端到端 RPC 分析

输出目录：`output-dune-crv-e2e/`

运行结果：

```text
6 verified / 7 total
687 swaps
2 liquidity events
10 positions / 4 holders
TVL timeline: 587 points
Risk score: 0.4703 MEDIUM
Analysis Window: Block 22000030 to 22004983
```

Dashboard：

```text
output-dune-crv-e2e/dashboard.html
```

复现命令：

```bash
python3 -m src.cli analyze 0xD533a949740bb3306d119CC777fa900bA034cd52 \
  --from-block 22000000 --to-block 22005000 \
  --pools-file output-dune-crv-demo/pools-curve-balancer.json \
  --output-dir output-dune-crv-e2e \
  --fast-mode
```

### 当前没有未结束的长任务

当前状态是：CRV 分析已跑完，Dune pools/swaps 已验证，Dune tvl 已知失败且本次暂停。

## 遇到的问题

1. Curve v1/v2 事件签名与仓库 ABI 不一致：已修复。
2. web3 对缺少 `anonymous` 字段的 ABI 事件抛错：已修复。
3. Curve 池被按 Uniswap 索引：已修复。
4. Balancer poolId 解析错误：已修复。
5. Dune 导出的 Balancer 池 `0x2d4d246d8f46d3a2a9cf6160bcabbf164c15b36f` 链上不是 Balancer V2 Vault 池，`getPoolId()` 失败，当前被严格验证过滤。
6. Dune `dex.trades` 使用 `pool_id` 列导致 pools/swaps 查询失败：已改为 `project_contract_address`，已验证通过。
7. Dune `dex.pool_tvl` 表不存在导致 tvl 查询失败：已知问题，待下一步处理。

## 修改过的文件

### 代码 / 配置修改

| 文件 | 状态 | 说明 |
|---|---|---|
| `abis/curve_pool.json` | 已修改 | v1 `TokenExchange` 改为 `int128` 版本，补 `anonymous` 字段 |
| `abis/curve_pool_crypto.json` | 新增 | v2 7 参数 `TokenExchange` ABI |
| `src/indexer/indexer.py` | 已修改 | Curve v1/v2 分流、Uniswap 过滤、Balancer poolId 修复、事件归类修复 |
| `src/verification/verifier.py` | 已修改 | Balancer 必须通过 `getPoolId()` + Vault 校验 |
| `src/analysis/timeline.py` | 已修改 | 无事件时补分析窗口 |
| `src/cli.py` | 已修改 | 传入分析窗口；保留用户原有 holdings 字段改动 |
| `src/data/dune_client.py` | 已修改 | `dex.trades` 改为 `project_contract_address`；错误信息保留更长 |
| `docs/DUNE_DATA_MAP.md` | 已修改 | 更新 Dune 列名说明 |
| `.env` | 新增，本地 | 已配置 `DUNE_API_KEY` 和 `ETH_RPC_URL`，已 gitignore，禁止提交 |

### 生成 / 缓存文件

```text
output-dune-crv-e2e/
output-dune-crv-e2e/dune_pools.json
output-dune-crv-e2e/dune_swaps.json
```

以上属于忽略目录，可随时重新生成。

## 下一步具体任务

1. 修复 Dune TVL

   - 换用 Dune 当前真实存在的池 TVL / 池余额表
   - 更新 `src/data/dune_client.py::fetch_pool_tvl()`
   - 重新执行 `dune tvl` 并确认有返回值

2. 完成 Dune vs RPC 对照

   - 用同一代币 / 区块窗口对比 Dune pools、swaps、holdings 与纯 RPC 结果
   - 把差异写进 `docs/DUNE_DATA_MAP.md` 或报告

3. 校验 Curve v2 多币池金额方向

   - 检查 `sold_id` / `bought_id` 与 `token0_amount` / `token1_amount` 的映射
   - 确认 TVL 和风险分使用的金额口径正确

4. 核对 Dune Balancer 记录

   - 检查 `0x2d4d246d8f46d3a2a9cf6160bcabbf164c15b36f` 的 Dune `pool_address` / `pool_id` 映射
   - 决定保留或从池列表过滤

5. 提交代码

   - 确认 `.env` 不进入 git
   - 提交本次 ABI / 索引 / 验证 / Dune 修复
   - 提交前检查 `src/cli.py` 中原有 holdings 字段改动

6. 跑真实崩盘场景

   - 用已知 drain / rug 事件配合 `--incident-block` 做一次完整验证

