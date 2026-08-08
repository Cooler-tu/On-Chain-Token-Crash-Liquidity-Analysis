-- V3 LP snapshot at to_block: tokenId, pool, ticks, net liquidity, owner.
-- One query replaces per-NFT positions()/ownerOf RPC.
WITH minted AS (
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
),
base AS (
  SELECT token_id, pool_address, tick_lower, tick_upper
  FROM minted
  WHERE rn = 1
),
inc AS (
  SELECT
    tokenId AS token_id,
    SUM(CAST(liquidity AS decimal(38, 0))) AS liq_inc
  FROM uniswap_v3_ethereum.NonfungiblePositionManager_evt_IncreaseLiquidity
  WHERE evt_block_number <= {{to_block}}
    AND tokenId IN (SELECT token_id FROM base)
  GROUP BY 1
),
dec AS (
  SELECT
    tokenId AS token_id,
    SUM(CAST(liquidity AS decimal(38, 0))) AS liq_dec
  FROM uniswap_v3_ethereum.NonfungiblePositionManager_evt_DecreaseLiquidity
  WHERE evt_block_number <= {{to_block}}
    AND tokenId IN (SELECT token_id FROM base)
  GROUP BY 1
),
own AS (
  SELECT
    tokenId AS token_id,
    "to" AS owner,
    ROW_NUMBER() OVER (
      PARTITION BY tokenId
      ORDER BY evt_block_number DESC, evt_index DESC
    ) AS rn
  FROM erc721_ethereum.evt_Transfer
  WHERE contract_address = {{npm}}
    AND evt_block_number <= {{to_block}}
    AND tokenId IN (SELECT token_id FROM base)
)
SELECT
  CAST(b.token_id AS varchar) AS nft_token_id,
  CAST(b.pool_address AS varchar) AS pool_address,
  CAST(b.tick_lower AS varchar) AS tick_lower,
  CAST(b.tick_upper AS varchar) AS tick_upper,
  CAST(COALESCE(i.liq_inc, 0) - COALESCE(d.liq_dec, 0) AS varchar) AS liquidity,
  CAST(o.owner AS varchar) AS owner
FROM base AS b
LEFT JOIN inc AS i ON i.token_id = b.token_id
LEFT JOIN dec AS d ON d.token_id = b.token_id
LEFT JOIN own AS o ON o.token_id = b.token_id AND o.rn = 1
WHERE COALESCE(i.liq_inc, 0) - COALESCE(d.liq_dec, 0) > 0
  AND o.owner IS NOT NULL
  AND o.owner <> {{zero_address}}
