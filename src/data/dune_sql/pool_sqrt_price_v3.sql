-- Last V3 pool sqrtPriceX96 at or before to_block (replaces slot0 RPC).
SELECT
  CAST(contract_address AS varchar) AS pool_address,
  CAST(sqrtPriceX96 AS varchar) AS sqrt_price_x96
FROM (
  SELECT
    contract_address,
    sqrtPriceX96,
    ROW_NUMBER() OVER (
      PARTITION BY contract_address
      ORDER BY evt_block_number DESC, evt_index DESC
    ) AS rn
  FROM uniswap_v3_ethereum.Pair_evt_Swap
  WHERE contract_address IN ({{pool_list}})
    AND evt_block_number <= {{to_block}}
) t
WHERE rn = 1
