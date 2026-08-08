-- Latest USD TVL row for a pool
SELECT
  day,
  pool AS pool_address,
  tvl_usd,
  token_count
FROM dex.pool_tvl
WHERE blockchain = '{{chain}}'
  AND pool = {{pool}}
  {{block_filter}}
ORDER BY day DESC
LIMIT 1
