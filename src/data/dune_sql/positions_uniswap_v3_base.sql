-- First Mint → NPM tokenId mapping for pools (ticks fixed at mint).
-- Lighter than full snapshot; pair with liquidity + owners queries.
SELECT
  CAST(token_id AS varchar) AS nft_token_id,
  CAST(pool_address AS varchar) AS pool_address,
  CAST(tick_lower AS varchar) AS tick_lower,
  CAST(tick_upper AS varchar) AS tick_upper
FROM (
  SELECT
    trn.tokenId AS token_id,
    mint.contract_address AS pool_address,
    mint.tickLower AS tick_lower,
    mint.tickUpper AS tick_upper,
    ROW_NUMBER() OVER (
      PARTITION BY trn.tokenId
      ORDER BY mint.evt_block_number ASC, mint.evt_index ASC
    ) AS rn
  FROM uniswap_v3_ethereum.Pair_evt_Mint AS mint
  INNER JOIN erc721_ethereum.evt_Transfer AS trn
    ON trn.evt_tx_hash = mint.evt_tx_hash
   AND trn.contract_address = {{npm}}
   AND trn."from" = {{zero_address}}
  WHERE mint.contract_address IN ({{pool_list}})
    AND mint.evt_block_number <= {{to_block}}
) t
WHERE rn = 1
