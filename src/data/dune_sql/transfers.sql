-- ERC-20 Transfer events for the token
SELECT
  evt_block_number AS block_number,
  CAST(evt_block_time AS varchar) AS block_time,
  CAST(evt_tx_hash AS varchar) AS transaction_hash,
  evt_index AS log_index,
  CAST("from" AS varchar) AS actor,
  CAST("to" AS varchar) AS recipient,
  CAST(value AS varchar) AS amount_raw
FROM erc20_ethereum.evt_Transfer
WHERE contract_address = {{token}}
  AND evt_block_number BETWEEN {{from_block}} AND {{to_block}}
ORDER BY evt_block_number, evt_index
