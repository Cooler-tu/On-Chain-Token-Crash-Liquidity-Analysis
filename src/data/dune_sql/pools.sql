-- Pools that traded the token in the block window (all dex.trades projects)
SELECT
  project,
  version,
  CAST(project_contract_address AS varchar) AS pool_address,
  CAST(token_bought_address AS varchar) AS token_bought,
  CAST(token_sold_address AS varchar) AS token_sold,
  COUNT(*) AS trade_count,
  COALESCE(SUM(amount_usd), 0) AS volume_usd,
  MIN(block_number) AS first_block,
  MAX(block_number) AS last_block
FROM dex.trades
WHERE blockchain = '{{chain}}'
  AND block_number BETWEEN {{from_block}} AND {{to_block}}
  AND (
    token_bought_address = {{token}}
    OR token_sold_address = {{token}}
  )
GROUP BY 1, 2, 3, 4, 5
ORDER BY trade_count DESC
