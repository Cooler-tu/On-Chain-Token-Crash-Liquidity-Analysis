-- Pools that traded the token in the block window (one row per project/version/pool)
SELECT
  project,
  version,
  CAST(project_contract_address AS varchar) AS pool_address,
  COUNT(*) AS trade_count,
  COALESCE(SUM(amount_usd), 0) AS volume_usd,
  MIN(block_number) AS first_block,
  MAX(block_number) AS last_block,
  MAX(CAST(token_bought_address AS varchar)) AS token_hint,
  MAX(CAST(token_sold_address AS varchar)) AS token_hint2
FROM dex.trades
WHERE blockchain = '{{chain}}'
  AND block_number BETWEEN {{from_block}} AND {{to_block}}
  AND (
    token_bought_address = {{token}}
    OR token_sold_address = {{token}}
  )
GROUP BY 1, 2, 3
ORDER BY trade_count DESC
