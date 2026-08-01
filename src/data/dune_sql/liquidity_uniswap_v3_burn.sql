SELECT
  evt_block_number AS block_number,
  CAST(evt_block_time AS varchar) AS block_time,
  CAST(evt_tx_hash AS varchar) AS transaction_hash,
  evt_index AS log_index,
  'uniswap' AS protocol,
  'v3' AS version,
  CAST(contract_address AS varchar) AS pool_address,
  'LIQUIDITY_REMOVE' AS event_type,
  CAST(owner AS varchar) AS actor,
  CAST(owner AS varchar) AS recipient,
  CAST(amount0 AS varchar) AS token0_amount,
  CAST(amount1 AS varchar) AS token1_amount,
  'Burn' AS source_event
FROM uniswap_v3_ethereum.Pool_evt_Burn
WHERE evt_block_number BETWEEN {{from_block}} AND {{to_block}}
  AND contract_address IN ({{pool_list}})
