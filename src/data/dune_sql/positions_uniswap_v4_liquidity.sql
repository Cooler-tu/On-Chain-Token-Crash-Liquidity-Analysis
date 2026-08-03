-- V4 LP net liquidity by (poolId, salt) at to_block.
-- salt is typically bytes32(tokenId) from the Position Manager.
SELECT
  CAST(id AS varchar) AS pool_id,
  CAST(salt AS varchar) AS salt,
  MIN(tickLower) AS tick_lower,
  MIN(tickUpper) AS tick_upper,
  CAST(SUM(CAST(liquidityDelta AS decimal(38, 0))) AS varchar) AS liquidity
FROM uniswap_v4_ethereum.PoolManager_evt_ModifyLiquidity
WHERE evt_block_number <= {{to_block}}
  AND id IN ({{pool_id_list}})
GROUP BY 1, 2
HAVING SUM(CAST(liquidityDelta AS decimal(38, 0))) > 0
