-- Latest non-zero ERC-20 balances (curated table)
-- Docs: balances_ethereum.latest  (columns: address, token_address, balance_raw)
SELECT
  CAST(address AS varchar) AS address,
  CAST(balance_raw AS varchar) AS balance_raw
FROM balances_ethereum.latest
WHERE token_address = {{token}}
  AND address IN ({{address_list}})
