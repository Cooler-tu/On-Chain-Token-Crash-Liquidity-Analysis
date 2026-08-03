-- Swaps for one pool contract (CLI / debugging)
SELECT
  block_number,
  CAST(block_time AS varchar) AS block_time,
  CAST(tx_hash AS varchar) AS tx_hash,
  evt_index AS log_index,
  project,
  version,
  CAST(project_contract_address AS varchar) AS pool_address,
  CAST(taker AS varchar) AS taker,
  CAST(token_bought_address AS varchar) AS token_bought_address,
  CAST(token_sold_address AS varchar) AS token_sold_address,
  CAST(token_bought_amount_raw AS varchar) AS amount_bought_raw,
  CAST(token_sold_amount_raw AS varchar) AS amount_sold_raw,
  amount_usd
FROM dex.trades
WHERE blockchain = '{{chain}}'
  AND project_contract_address = {{pool}}
  AND block_number BETWEEN {{from_block}} AND {{to_block}}
ORDER BY block_number, evt_index
LIMIT {{limit}}
