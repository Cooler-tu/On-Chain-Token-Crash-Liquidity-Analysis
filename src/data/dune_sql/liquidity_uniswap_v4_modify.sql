-- Uniswap V4 liquidity changes for known poolIds
SELECT
  evt_block_number AS block_number,
  CAST(evt_block_time AS varchar) AS block_time,
  CAST(evt_tx_hash AS varchar) AS transaction_hash,
  evt_index AS log_index,
  'uniswap' AS protocol,
  'v4' AS version,
  CAST(id AS varchar) AS pool_address,
  CAST(id AS varchar) AS pool_id,
  CAST(sender AS varchar) AS actor,
  CAST(sender AS varchar) AS recipient,
  CAST(liquidityDelta AS varchar) AS liquidity_delta,
  CAST(tickLower AS varchar) AS tick_lower,
  CAST(tickUpper AS varchar) AS tick_upper,
  CAST(salt AS varchar) AS salt,
  'ModifyLiquidity' AS source_event
FROM uniswap_v4_ethereum.PoolManager_evt_ModifyLiquidity
WHERE evt_block_number BETWEEN {{from_block}} AND {{to_block}}
  AND id IN ({{pool_id_list}})
ORDER BY evt_block_number, evt_index
