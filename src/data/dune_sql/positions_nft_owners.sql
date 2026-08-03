-- Latest ERC-721 owners for a tokenId list at or before to_block.
SELECT
  CAST(tokenId AS varchar) AS nft_token_id,
  CAST(owner AS varchar) AS owner
FROM (
  SELECT
    tokenId,
    "to" AS owner,
    ROW_NUMBER() OVER (
      PARTITION BY tokenId
      ORDER BY evt_block_number DESC, evt_index DESC
    ) AS rn
  FROM erc721_ethereum.evt_Transfer
  WHERE contract_address = {{npm}}
    AND evt_block_number <= {{to_block}}
    AND tokenId IN ({{token_id_list}})
) t
WHERE rn = 1
  AND owner <> {{zero_address}}
