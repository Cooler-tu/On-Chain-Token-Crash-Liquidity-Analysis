# 本地交互首页（Studio）说明

日期：2026-08-20

## 一句话

现在可以在本机开一个网页：输入代币地址或名称、选 from block 和 7/30 天，直接排队跑完整分析并打开 dashboard。  
这是**本机服务**，不是 GitHub Pages，队友 pull 代码后要自己启动，打不开别人电脑上的 `127.0.0.1:8080`。

---

## 和公开站点的区别

| | 本地 Studio | GitHub Pages |
|--|--|--|
| 地址 | `http://127.0.0.1:8080/` | 仓库 Pages 上的静态站 |
| 能不能填表生成新 dashboard | 能 | 不能 |
| 数据从哪来 | 本机 `output*/` | CI 里扫得到的已提交 output（多数 `output-*/` 被 gitignore） |
| 需要密钥 | 本机 `.env`（`ETH_RPC_URL`、`DUNE_API_KEY`） | 不跑 pipeline |

公开站点仍然只是浏览已经发布过的结果。交互生成必须走 Studio。

---

## 怎么开

在项目根目录：

```bash
set -a && source .env && set +a
python3 -m src.cli studio
```

默认绑 `127.0.0.1:8080`。浏览器打开：

[http://127.0.0.1:8080/](http://127.0.0.1:8080/)

常用参数：

```bash
python3 -m src.cli studio --port 8080 --host 127.0.0.1 --no-open
```

不要把 `.env` 提交或发给队友。各自用自己的 Dune key 和 RPC。

---

## 页面上做什么

1. **Token address or name**：合约地址、符号或名称（和 `analyze` 一样会走 `resolve_token`）。
2. **From block**：分析窗口起点。  
   - 填了：`to_block = from_block + 天数 × 7200 - 1`（按约 12 秒一块，一天 7200 块）。  
   - 留空：用 RPC 查最新块，再往前推 7 或 30 天。RPC 不可用时必须手填。
3. **Duration**：7 天（chart-span = week）或 30 天（chart-span = month）。
4. 点 **Run analysis**：后台执行 `python3 -m src.cli analyze ...`，页面打日志，完成后给 dashboard 链接。
5. 下方 **Existing dashboards**：列出本机已经有 `dashboard.html` 的 `output*` 目录。
6. 进入某个 dashboard 后，右上角 **Home**（或点标题）回到起始页。

输出目录名大致为 `output-{slug}-{天数}d-{from_block}`，例如 `output-floki-30d-25572319`。

Studio 内部**一次只跑一条** `analyze`，后面的会排队，避免把 Dune 打到 429。  
如果你已经在终端里另开了一条 `analyze`，请不要再在网页上点 Run，两边会抢同一把 Dune key。

---

## 队友 pull 之后能不能直接用

能用功能，但**不会自动看到你本机正在跑的那些结果**。

- 代码：需要先把 `src/studio/`、`src/cli.py` 的 `studio` 命令等改动 commit / push。没推的话队友 pull 不到这个页面。
- 数据：`output/`、`output-*/` 在 `.gitignore` 里。FLOKI / TURBO 等 30 天产物默认不会进仓库。
- 密钥：队友自己配 `.env`。没有可用的 RPC / Dune，表单可以开，但生成会失败。
- 网络：`127.0.0.1` 只服务本机。要给别人远程看，需要自己做隧道（例如 Tailscale），那是另一件事。

想让队友看已经跑完的 dashboard，可以：把对应 `output-*/dashboard.html` 另发；或本地 `python3 scripts/publish_site.py` 后再走公开站点流程。不要指望 `git push` 把这些目录带过去。

---

## 当前已知问题（2026-08-20）

- 仓库 `.env` 里的 Alchemy `ETH_RPC_URL` 已出现 **月额度 429**。Studio 查「最新块」会很快失败，提示手填 from block。留空 from block 再点 Run 也会失败。
- 后台 30 天分析用的是 `https://ethereum.publicnode.com`，和网页上的 Alchemy 不是同一条 RPC。
- Free-tier Dune 不要设 `DUNE_PERFORMANCE=medium`（会被拒）。Studio 启动前建议 `unset DUNE_PERFORMANCE`。

---

## 相关代码

- 启动命令：`src/cli.py` → `studio`
- HTTP 服务 / 任务队列：`src/studio/server.py`、`src/studio/jobs.py`
- 窗口计算：`src/studio/window.py`（7 天 = 50400 块，30 天 = 216000 块）
- 首页：`src/studio/home.html`
