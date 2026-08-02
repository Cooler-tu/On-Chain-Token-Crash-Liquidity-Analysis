-- Map in-window Uniswap V3 pool Mint events → NPM NFT tokenIds.
-- Pool Mint.owner is usually the NPM; the NFT Transfer from 0x0 in the same
-- tx carries the real tokenId (and often the recipient owner).
SELECT DISTINCT
  CAST(trn.tokenId AS varchar) AS nft_token_id,
  CAST(mint.contract_address AS varchar) AS pool_address,
  CAST(trn."to" AS varchar) AS owner
FROM uniswap_v3_ethereum.Pair_evt_Mint AS mint
INNER JOIN erc721_ethereum.evt_Transfer AS trn
  ON trn.evt_tx_hash = mint.evt_tx_hash
 AND trn.contract_address = {{npm}}
 AND trn."from" = {{zero_address}}
WHERE mint.contract_address IN ({{pool_list}})
  AND mint.evt_block_number BETWEEN {{from_block}} AND {{to_block}}
