-- Uniswap V4 pools that traded the token in-window (real bytes32 poolId).
-- dex.trades only exposes PoolManager; here we join Swap → Initialize.
SELECT
  CAST(i.id AS varchar) AS pool_id,
  CAST(i.currency0 AS varchar) AS token0,
  CAST(i.currency1 AS varchar) AS token1,
  CAST(i.fee AS varchar) AS fee,
  CAST(i.tickSpacing AS varchar) AS tick_spacing,
  CAST(i.hooks AS varchar) AS hooks,
  COUNT(*) AS trade_count,
  MIN(s.evt_block_number) AS first_block,
  MAX(s.evt_block_number) AS last_block
FROM uniswap_v4_ethereum.PoolManager_evt_Swap AS s
INNER JOIN uniswap_v4_ethereum.PoolManager_evt_Initialize AS i
  ON i.id = s.id
WHERE s.evt_block_number BETWEEN {{from_block}} AND {{to_block}}
  AND (
    i.currency0 = {{token}}
    OR i.currency1 = {{token}}
  )
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY trade_count DESC
