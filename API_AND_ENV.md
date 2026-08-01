# API & Environment Setup

本文件集中说明运行本项目需要（以及可选）的环境变量 / API Key。  
所有 `export …` 都写在这里；日常用法见根目录 [README.md](../README.md)。

---

## 一键示例

在 `on-chain-token-crash/` 目录下：

```bash
# 必填：以太坊 JSON-RPC
export ETH_RPC_URL="https://eth-mainnet.g.alchemy.com/v2/DMnGXCAoKNOFCWmvxBXHi"
# 或
# export ETH_RPC_URL="https://eth-mainnet.g.alchemy.com/v2/YOUR_ALCHEMY_KEY"

# 可选：Dune（目前代码未强制依赖；接入后使用）
# export DUNE_API_KEY="YOUR_DUNE_API_KEY"

# 跑分析
python3 -m src.cli analyze USDC \
  --from-block 19000000 \
  --to-block 19000050 \
  --output-dir output
```

也可不设环境变量，在命令行传：

```bash
python3 -m src.cli analyze USDC \
  --rpc-url "https://mainnet.infura.io/v3/YOUR_INFURA_KEY" \
  --from-block 19000000 \
  --to-block 19000050
```

---

## 变量一览

| 变量 | 是否必需 | 用途 | 在哪里申请 / 说明 |
|------|----------|------|-------------------|
| `ETH_RPC_URL` | **必需** | 链上读合约、扫 `eth_getLogs`、持仓 `balanceOf` 等 | Infura / Alchemy / 自建节点 |
| `DUNE_API_KEY` | 可选 | 用 Dune SQL 拉持仓 / LP（规划接入，尚未写进主流程） | [Dune](https://dune.com) → Settings → API |
| CLI `--rpc-url` | 可选 | 覆盖 `ETH_RPC_URL` | 与上同 |

**不需要 Key 的外部服务：**

| 服务 | 用途 | 说明 |
|------|------|------|
| [DexScreener](https://docs.dexscreener.com/) | 按代币名称/符号解析合约地址 | 公开 HTTP，无 API Key |

---

## `ETH_RPC_URL`（必填）

代码读取位置：`src/client.py`、`src/cli.py`（`envvar="ETH_RPC_URL"`）。

### Infura

1. 打开 [https://infura.io](https://infura.io) 注册并创建项目  
2. 网络选 **Ethereum Mainnet**  
3. 复制 HTTPS endpoint：

```bash
export ETH_RPC_URL="https://mainnet.infura.io/v3/<PROJECT_ID>"
```

### Alchemy

1. 打开 [https://www.alchemy.com](https://www.alchemy.com) 创建 App（Ethereum Mainnet）  
2. 复制 HTTP URL：

```bash
export ETH_RPC_URL="https://eth-mainnet.g.alchemy.com/v2/<API_KEY>"
```

> **注意：** Alchemy 免费档对单次 `eth_getLogs` 区块跨度限制很紧（约 10 blocks），exhaustive / 大窗口索引会极慢或频繁缩小 chunk。完整分析更推荐 Infura 付费档或其他高限额节点。

### 自建 / 其它节点

任意兼容 `eth_call` + `eth_getLogs` 的主网 HTTPS RPC 均可，例如：

```bash
export ETH_RPC_URL="https://your-node.example/rpc"
```

### 持久化（可选）

写入 shell 配置（勿把真实 Key 提交到 git）：

```bash
# ~/.zshrc
export ETH_RPC_URL="https://mainnet.infura.io/v3/YOUR_INFURA_KEY"
```

或本地 `.env`（自行 `source`；仓库默认不应提交真实密钥）：

```bash
# on-chain-token-crash/.env  （加入 .gitignore）
ETH_RPC_URL=https://mainnet.infura.io/v3/YOUR_INFURA_KEY
# DUNE_API_KEY=YOUR_DUNE_API_KEY
```

```bash
set -a && source .env && set +a
```

---

## `DUNE_API_KEY`（可选；设置后主数据路径优先走 Dune）

[Dune Analytics](https://dune.com) 用 SQL 查已解码的链上表。本项目的统一查询层
（`src/data/dune_client.py`）在配置 key 后优先从 Dune 拉取池发现、Swap、持仓与
TVL；无 key 或查询失败时自动回退 RPC。

1. 注册 Dune → **Settings → API** → Create key  
2. 导出：

```bash
export DUNE_API_KEY="YOUR_DUNE_API_KEY"
```

3. 验证：

```bash
python3 -m src.cli dune data-map
python3 -m src.cli dune pools USDC --from-block 19000000 --to-block 19000050
```

CLI 命令：`pools`（跨 DEX 池发现）、`swaps`（单池 Swap）、`tvl`（池 USD TVL）、
`data-map`（数据清单）。缓存写入 `output/dune_cache/`。

> 不设 `DUNE_API_KEY` 时，`analyze` 全流程仍可运行（纯 RPC 路径）。
> 文档：[docs/DUNE_DATA_MAP.md](docs/DUNE_DATA_MAP.md)

---

## 安全提醒

- **不要**把 Infura / Alchemy / Dune 的真实 Key 写进 README、commit、截图或公开 Issue  
- 若 Key 已泄露：在对应控制台立刻 rotate / revoke  
- 团队分享用私密渠道或各自本地 `.env`，不要共用写死在仓库里的 URL

---

## 快速自检

```bash
# 是否已设置 RPC
echo "$ETH_RPC_URL"

# 能否连上主网（需已安装依赖）
cd on-chain-token-crash
python3 -c "from src.client import get_web3; print(get_web3().eth.block_number)"
```

能打印出当前区块高度，说明 RPC 配置可用。
