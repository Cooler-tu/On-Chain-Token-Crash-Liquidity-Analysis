# 本周任务计划（2026-08-06 ～ 2026-08-12）

> 整合来源：导师聊天截图（Dune SQL / 性能 / 快照要求）、队友转述（流程图、架构图、策略方向）、仓库现状（README / HANDOVER / NEXT_WEEK / plan）。

## 一、本周目标

1. 把项目的「数据流」和「整体架构」讲清楚，沉淀为手绘图 + 文档。
2. 按导师要求把 Dune 取数改成「最小字段 + 表内筛选 + join + 可并行」的 SQL，不再硬拉总表。
3. 在半年数据量级下跑 benchmark，找到瓶颈，让主流程可优化到 30 分钟内，并记录删掉/保留了哪些数据。
4. 落地基于时间点的持仓快照（小时 / 天），并输出 24h / 72h 持仓分析。
5. 收尾上一阶段遗留：Dune TVL、Dune vs RPC 对照、Curve v2 金额方向、Balancer 记录核对、代码提交。
6. 周五前准备好「项目结束后的方向」调研：选币策略 / RWA / 学术。

---

## 二、导师原话 → 落地动作

| 导师 / 队友要求 | 落地任务 | 验收标准 |
|---|---|---|
| 手写数据流流程图 + 整体项目架构图 | 先白板 / 手绘，再沉淀到 `docs/ARCHITECTURE.md`，配 Mermaid / ASCII 图 | 图覆盖 `resolve → discover → verify → index → positions → metrics → risk → report → holdings → dashboard`，并标注 Dune / RPC 数据入口 |
| 不硬抓总表，只抓用到的东西 | Dune SQL 重构：每个查询只 `SELECT` 所需字段，`WHERE` 限定代币 / 池 / 区块范围 | SQL 中没有 `SELECT *`；`docs/DUNE_DATA_MAP.md` 说明每个字段用途 |
| 筛选逻辑：表内筛选 + join，写成一个 SQL，讲清楚查询 | 新增 `docs/DUNE_SQL_DESIGN.md`，逐条 SQL 说明过滤条件、join 理由、期望返回行数 | 每条 SQL 有一句话说明 + 关键字段清单 |
| 手动判断哪些数据可并行、无依赖 | 在数据清单中标注并行组（池发现 / swaps / holdings / tvl 可并行） | 文档有并行组表格；命令可分别后台跑 |
| 一次拿一个月的数据 | 把常用窗口定为约 1 个月，做成 CLI 默认 / 示例参数 | README 示例更新；跑一次 demo 验证 |
| 不能拉总表，token 耗量大 | 增加 Dune 查询用量说明（表名、时间范围、字段数、结果行数） | 用量说明写进文档；无整表扫描 |
| 地址 + balance 按时间范围（from-to）扫当前 balance | 明确 balance 快照实现：按时间点调 Dune `balances` / RPC `balanceOf` | `holdings.json` 输出带时间戳 |
| mean burn（Mint / Burn）如何设计，写一个文档 | 新增 `docs/MINT_BURN_DESIGN.md`：事件模型、净增铸、销毁 / 撤池区分、指标口径 | 文档描述字段、SQL、指标公式 |
| 数据量查半年，找瓶颈，时间优化在 30min 内 | 用半年窗口跑 benchmark，输出各阶段耗时，定位瓶颈 | `docs/PERF_BENCHMARK.md` 记录每阶段耗时与优化后总耗时 |
| 讲清楚把什么数据剪掉、拿到了什么数据 | 性能优化记录：剪枝策略（交易量少可灵活删除、tick 只标注有流动性的价位） | 文档列出“剪掉 / 保留”清单 |
| 先跑，再用大模型分析如何优化 | 先跑一轮真实数据，把日志 / 耗时喂给模型，提出优化点 | 优化点清单 + 是否采纳原因 |
| tick 性能比较慢，每一次不用全部都处理，什么价位提供流动性进行标注 | V3/V4 tick 处理只处理有流动性变化的 tick，输出价位标注 | 索引日志显示 tick 处理量下降；positions 保留 tick 价位标注 |
| 基于时间做快照，有没有存当前小时的挂单状态 | 新增 snapshot 模式：按小时 / 天生成 positions / holdings 快照 | 输出 `snapshots/` 目录，含时间点、持仓 |
| 先做一个小时 / 一天的，需要有每个时间点的持仓情况 | timeline 输出 hourly / daily 快照点 | 每个快照文件可独立读取 |
| 分析 24 / 72 小时持仓，每个分别做 | 新增 CLI 参数或输出 24h / 72h 汇总 | 输出报告含 24h / 72h 持仓变化 |
| 先把所有池子 / 用户 balance 拿下来，再做流动性筛选、找交易、再算 | 明确 pipeline 顺序：先拉池 / 地址 / balance，再筛选流动性，再对账交易与计算 | 数据流文档体现该顺序；pipeline 与之一致 |
| 项目结束后：做项目 or 策略 / 学术 | 周五前准备策略调研：选币（预选约 100 个标的、动量、回归预测 / 大模型辅助、参数调整、风险管理）、RWA、学术 | 一页 summary 供周五讨论 |

---

## 三、结合仓库现状的落地清单

1. **Dune TVL 修复**：`src/data/dune_client.py::fetch_pool_tvl()` 目前引用不存在的 `dex.pool_tvl` 表，本周换用 Dune 当前真实存在的 TVL / 池余额表，并重新验证 `dune tvl`。
2. **Dune vs RPC 对照**：同一代币、同一区块窗口，对比 Dune pools / swaps / holdings 与纯 RPC 结果，差异写进 `docs/DUNE_DATA_MAP.md` 或报告。
3. **Curve v2 多币池金额方向**：校验 `sold_id / bought_id` 与 `token0_amount / token1_amount` 的映射，确认 TVL 和风险分使用的金额口径正确。
4. **Balancer 记录核对**：`0x2d4d246d8f46d3a2a9cf6160bcabbf164c15b36f` 是否为真实 Vault 池，决定保留或从池列表过滤。
5. **代码提交**：确认 `.env` 不入库；提交 `dune_client.py` 等本次修改；更新 `plan.md`、`README.md`。
6. **真实崩盘场景**：用已知 drain / rug 事件配合 `--incident-block` 跑一次完整验证。
7. **遵守 AGENTS.md**：新分析更新 README 分析日志、重新生成 site、更新 plan.md；不整库扫描、不随意删输出。

---

## 四、建议每日安排

- **周四 08-06**：整理聊天需求 + 现状盘点；定本周验收清单；开始画数据流 / 架构图初稿。
- **周五 08-07**：完成架构 / 数据流图与文档；参加导师讨论，确认策略方向与 RWA 调研范围；跑半年窗口 benchmark 初版。
- **周六 08-08**：Dune SQL 重构 + `MINT_BURN_DESIGN.md`；修复 Dune TVL。
- **周日 08-09**：性能优化（30min 目标）与 tick 剪枝；Dune vs RPC 对照。
- **周一 08-10**：时间快照（小时 / 天）+ 24h / 72h 持仓分析。
- **周二 08-11**：真实崩盘场景端到端验证；整理文档 / README / plan；代码提交。
- **周三 08-12**：策略方向总结（选币 / RWA / 学术），准备下次讨论；留 buffer 处理突发问题。

---

## 五、风险与依赖

- **Dune API key**：`.env` 已有 key；若无 key 或 key 失效，回退 RPC 并在文档中标注。
- **免费 RPC 性能**：Curve / Balancer 发现可能慢，必要时用 `--pools-file` 或 Dune 缓存。
- **半年数据量大**：先跑小窗口验证 SQL，再逐步放大到月 / 半年，避免一开始就全量。
- **队友分工**：明确谁负责 Dune SQL、性能、快照、策略调研，避免重复劳动；周五同步一次。
