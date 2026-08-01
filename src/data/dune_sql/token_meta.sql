-- Token metadata
SELECT
  contract_address AS address,
  symbol,
  name,
  decimals
FROM tokens.erc20
WHERE contract_address = {{token}}
  AND blockchain = '{{chain}}'
LIMIT 1
