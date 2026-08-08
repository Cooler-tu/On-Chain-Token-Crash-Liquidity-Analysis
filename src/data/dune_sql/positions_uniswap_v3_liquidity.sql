-- Net Uniswap V3 NPM liquidity at to_block for known tokenIds.
SELECT
  CAST(token_id AS varchar) AS nft_token_id,
  CAST(SUM(delta) AS varchar) AS liquidity
FROM (
  SELECT
    tokenId AS token_id,
    CAST(liquidity AS decimal(38, 0)) AS delta
  FROM uniswap_v3_ethereum.NonfungiblePositionManager_evt_IncreaseLiquidity
  WHERE evt_block_number <= {{to_block}}
    AND tokenId IN ({{token_id_list}})
  UNION ALL
  SELECT
    tokenId AS token_id,
    -CAST(liquidity AS decimal(38, 0)) AS delta
  FROM uniswap_v3_ethereum.NonfungiblePositionManager_evt_DecreaseLiquidity
  WHERE evt_block_number <= {{to_block}}
    AND tokenId IN ({{token_id_list}})
) t
GROUP BY 1
HAVING SUM(delta) > 0
