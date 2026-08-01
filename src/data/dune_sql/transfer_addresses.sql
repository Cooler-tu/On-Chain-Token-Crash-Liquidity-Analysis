-- Unique Transfer counterparties in the window
SELECT
  address,
  COUNT(*) AS tx_count,
  MIN(block_number) AS first_seen_block,
  MAX(block_number) AS last_seen_block
FROM (
  SELECT "from" AS address, evt_block_number AS block_number
  FROM erc20_ethereum.evt_Transfer
  WHERE contract_address = {{token}}
    AND evt_block_number BETWEEN {{from_block}} AND {{to_block}}
  UNION ALL
  SELECT "to" AS address, evt_block_number AS block_number
  FROM erc20_ethereum.evt_Transfer
  WHERE contract_address = {{token}}
    AND evt_block_number BETWEEN {{from_block}} AND {{to_block}}
) t
WHERE address <> {{zero_address}}
GROUP BY 1
ORDER BY tx_count DESC
