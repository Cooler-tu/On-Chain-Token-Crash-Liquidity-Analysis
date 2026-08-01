# Curve / Balancer 与 Uniswap 做市差异（对风险解读的影响）

## 为什么要看非 Uniswap 的池

Uniswap V2/V3/V4 的池子以 **常数积（x·y=k）或集中流动性** 为主。Curve 与
Balancer 用了不同的做市公式 / 池结构，同样的「撤池」「池子集中度」在解读上
有本质差异：

| 维度 | Uniswap | Curve | Balancer |
|------|---------|-------|----------|
| 做市公式 | x·y=k（V2）；集中流动性（V3/V4） | StableSwap x³y+y³x=k / CryptoSwap | 加权：任意权重，最多 8 币 |
| 目标资产 | 任意 ERC-20 | 同类资产 / 稳定币 | 任意多资产组合 |
| 池子结构 | 单对（V2）/ 单对多费率（V3/V4） | 单池多币（通常 2-8 币） | 单池多币（2-8 币）+ 权重 |
| 滑点特性 | 中等（50/50） | 稳定币区间极低滑点 | 取决于权重，非对称 |
| TVL 近似 | 目标币余额 × 2 | 目标币余额 × 币数 | Vault getPoolTokens 余额 × 币数 |
| 撤池语义 | Burn / DecreaseLiquidity | RemoveLiquidity* | PoolBalanceChanged（deltas） |

## 对集中度 / 撤池 / 风险解读的影响

1. **池子集中度**：Uniswap 的「主池占比」通常是同代币多个交易对中的最大
   V2 池或 V3 主费率池。Curve 的池子可能同时含 3-4 个币，一个 Curve 池
   对某个稳定币来说就是几乎全部流动性；Balancer 80/20 池中，代币只占池子
   价值一部分，「主池占比」不能直接与 Uniswap 对比，需要看权重。

2. **撤池**：Uniswap 撤池 = LP 退出交易对；Curve 的 RemoveLiquidity /
   RemoveLiquidityOne 可只撤单个币，若大量单边撤出会直接改变池子币种比例；
   Balancer 的 PoolBalanceChanged 通过 deltas 描述多币增减，撤池更精细，
   但也更容易被「按目标币余额 × 2」的近似低估。

3. **风险解读**：稳定币 / 锚定类（Curve）的崩盘更多是**脱锚**（价格离开
   1:1），而不是流动性突然消失；Balancer 加权池的风险取决于权重和重平衡
   机制，撤池影响与权重成正比。

## 实现现状

- 池发现：Curve Registry / Balancer Vault Swap 事件 + Dune `dex.trades` 兜底
- 事件索引：`curve:` / `balancer:` 前缀流（TokenExchange / PoolBalanceChanged）
- 持仓重建：Curve LP token 与 Balancer BPT 的 balanceOf/totalSupply 快照
- TVL：Curve `coins/balances` × 币数；Balancer `getPoolTokens` × 币数

## 已知近似

- Curve/Balancer TVL 均用「目标币余额 × 币数」近似，假定池内币种价值接近
  平衡；80/20 池会低估目标币侧真实权重，3pool 类稳定池较准。
- Balancer poolId 使用 `pool_address + 0x00…`（标准 V2 格式），非标准
  nonce 的池需通过 Vault Swap 事件还原完整 poolId。
