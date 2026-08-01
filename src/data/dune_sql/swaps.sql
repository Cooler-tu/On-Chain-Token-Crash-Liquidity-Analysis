-- Swap / trade rows for the token (optional pool filter injected by Python)
SELECT
  block_number,
  CAST(block_time AS varchar) AS block_time,
  CAST(tx_hash AS varchar) AS transaction_hash,
  evt_index AS log_index,
  project AS protocol,
  version,
  CAST(project_contract_address AS varchar) AS pool_address,
  CAST(taker AS varchar) AS actor,
  CAST(tx_from AS varchar) AS tx_from,
  CAST(token_bought_address AS varchar) AS token_bought,
  CAST(token_sold_address AS varchar) AS token_sold,
  CAST(token_bought_amount_raw AS varchar) AS token_bought_amount_raw,
  CAST(token_sold_amount_raw AS varchar) AS token_sold_amount_raw,
  amount_usd
FROM dex.trades
WHERE blockchain = '{{chain}}'
  AND block_number BETWEEN {{from_block}} AND {{to_block}}
  AND (
    token_bought_address = {{token}}
    OR token_sold_address = {{token}}
  )
  {{pool_filter}}
ORDER BY block_number, evt_index
