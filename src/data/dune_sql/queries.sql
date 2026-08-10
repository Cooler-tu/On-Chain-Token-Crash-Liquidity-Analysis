-- =============================================================================
-- All Dune SQL templates (one file, named sections).
-- Loaded by src/data/dune.py via query("<section_name>", ...).
-- Markers:  -- === name: <section_name> ===
-- Params:   {{token}} {{from_block}} {{to_block}} {{chain}} …
-- Design:   see structure.md  (holders / price / volume / TVL snapshots)
-- =============================================================================


-- === name: pools ===
-- Step 1: pairs that traded the token (Uniswap / Balancer / Curve family).
-- Output contract unchanged for discovery.engine.
SELECT
  project,
  version,
  CAST(project_contract_address AS varchar) AS pool_address,
  MAX(CAST(token_bought_address AS varchar)) AS token_hint,
  MAX(CAST(token_sold_address AS varchar)) AS token_hint2
FROM dex.trades
WHERE block_number BETWEEN {{from_block}} AND {{to_block}}
  AND blockchain = '{{chain}}'
  AND (
    token_bought_address = {{token}}
    OR token_sold_address = {{token}}
  )
  AND (
    lower(project) LIKE 'uniswap%'
    OR lower(project) LIKE 'balancer%'
    OR lower(project) LIKE 'curve%'
  )
GROUP BY 1, 2, 3
ORDER BY COUNT(*) DESC


-- === name: pools_v4 ===
-- Uniswap V4 pools (real bytes32 poolId via Swap → Initialize).
SELECT
  CAST(i.id AS varchar) AS pool_id,
  CAST(i.currency0 AS varchar) AS token0,
  CAST(i.currency1 AS varchar) AS token1,
  CAST(i.fee AS varchar) AS fee,
  CAST(i.hooks AS varchar) AS hooks
FROM uniswap_v4_ethereum.PoolManager_evt_Swap AS s
INNER JOIN uniswap_v4_ethereum.PoolManager_evt_Initialize AS i
  ON i.id = s.id
WHERE s.evt_block_number BETWEEN {{from_block}} AND {{to_block}}
  AND (
    i.currency0 = {{token}}
    OR i.currency1 = {{token}}
  )
GROUP BY 1, 2, 3, 4, 5
ORDER BY COUNT(*) DESC


-- === name: holders ===
-- Primary: balances_ethereum.daily_updates (sparse [valid_from, valid_to) intervals).
-- Overlap window ⇒ held > 0 on some day in range. Misses same-day in-and-out.
-- Fallback: holders_from_transfers (Python only — not main pipeline).
WITH bounds AS (
  SELECT
    DATE((SELECT time FROM ethereum.blocks WHERE number = {{from_block}})) AS d0,
    DATE((SELECT time FROM ethereum.blocks WHERE number = {{to_block}})) AS d1
)
SELECT DISTINCT
  CAST(address AS varchar) AS address
FROM balances_ethereum.daily_updates
CROSS JOIN bounds
WHERE token_address = {{token}}
  AND token_standard = 'erc20'
  AND valid_from <= bounds.d1
  AND valid_to > bounds.d0
  AND balance_raw > 0
  AND address <> {{zero_address}}


-- === name: holders_from_transfers ===
-- Backup only: catches same-day buy-then-sell addresses missed by daily_updates.
-- Do not run in the main path unless holders fails.
SELECT DISTINCT
  CAST(address AS varchar) AS address
FROM (
  SELECT "from" AS address
  FROM erc20_ethereum.evt_Transfer
  WHERE contract_address = {{token}}
    AND evt_block_number BETWEEN {{from_block}} AND {{to_block}}
  UNION ALL
  SELECT "to" AS address
  FROM erc20_ethereum.evt_Transfer
  WHERE contract_address = {{token}}
    AND evt_block_number BETWEEN {{from_block}} AND {{to_block}}
) t
WHERE address <> {{zero_address}}


-- === name: transfer_addresses ===
-- Still used by holdings.py as last-resort counterparty list (with tx_count).
SELECT
  address,
  COUNT(*) AS tx_count
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


-- === name: balances ===
-- Latest balances for an address list (balances_ethereum.latest — stable on free/paid).
-- Dashboard Balance Distribution target = Sim Token Holders API (not this SQL).
SELECT
  CAST(address AS varchar) AS address,
  CAST(balance_raw AS varchar) AS balance_raw
FROM balances_ethereum.latest
WHERE token_address = {{token}}
  AND address IN ({{address_list}})
  AND balance_raw > 0


-- === name: swaps ===
-- KEEP while indexer / movers / labels need raw trades.
-- Charts must use volume_timeline + price_timeline (aggregated), not this.
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


-- === name: volume_timeline ===
-- Chart volume: block window → token → aggregate (do NOT pull raw swaps).
SELECT
  CAST(date_trunc('{{bucket}}', block_time) AS varchar) AS bucket_ts,
  CAST(project_contract_address AS varchar) AS pool_address,
  project AS protocol,
  version,
  SUM(
    CASE
      WHEN token_bought_address = {{token}} THEN token_bought_amount
      WHEN token_sold_address = {{token}} THEN token_sold_amount
      ELSE 0
    END
  ) AS volume_in_token,
  SUM(COALESCE(amount_usd, 0)) AS volume_usd
FROM dex.trades
WHERE blockchain = '{{chain}}'
  AND block_number BETWEEN {{from_block}} AND {{to_block}}
  AND (
    token_bought_address = {{token}}
    OR token_sold_address = {{token}}
  )
  {{pool_filter}}
GROUP BY 1, 2, 3, 4
ORDER BY 1, 2


-- === name: price_timeline ===
-- Swap-implied USD price per pool per bucket (month→day, week/day→hour).
-- Current semantics: last trade in bucket (MAX_BY). Target later: as-of 00:00 / hour.
SELECT
  CAST(date_trunc('{{bucket}}', block_time) AS varchar) AS bucket_ts,
  CAST(project_contract_address AS varchar) AS pool_address,
  MAX_BY(
    CASE
      WHEN token_bought_address = {{token}} AND token_bought_amount > 0
        THEN amount_usd / token_bought_amount
      WHEN token_sold_address = {{token}} AND token_sold_amount > 0
        THEN amount_usd / token_sold_amount
      ELSE NULL
    END,
    block_time
  ) AS price_usd
FROM dex.trades
WHERE blockchain = '{{chain}}'
  AND block_number BETWEEN {{from_block}} AND {{to_block}}
  AND (
    token_bought_address = {{token}}
    OR token_sold_address = {{token}}
  )
  AND amount_usd IS NOT NULL
  AND amount_usd > 0
  {{pool_filter}}
GROUP BY 1, 2
ORDER BY 1, 2


-- === name: pool_token_balances ===
-- Target-token balance in each pool/custody address (latest).
SELECT
  CAST(address AS varchar) AS pool_address,
  CAST(balance_raw AS varchar) AS balance_raw
FROM balances_ethereum.latest
WHERE token_address = {{token}}
  AND address IN ({{pool_list}})
  AND balance_raw > 0


-- === name: pool_balance_timeline ===
-- Historical pool/custody balances via balances_ethereum.daily_updates.
-- Sparse intervals expanded to one row per day (utils.days). Local TVL = bal × price.
WITH bounds AS (
  SELECT
    DATE((SELECT time FROM ethereum.blocks WHERE number = {{from_block}})) AS d0,
    DATE((SELECT time FROM ethereum.blocks WHERE number = {{to_block}})) AS d1
),
days AS (
  SELECT CAST(timestamp AS DATE) AS day
  FROM utils.days
  CROSS JOIN bounds
  WHERE CAST(timestamp AS DATE) BETWEEN bounds.d0 AND bounds.d1
)
SELECT
  CAST(d.day AS varchar) AS bucket_ts,
  CAST(i.address AS varchar) AS pool_address,
  CAST(i.balance_raw AS varchar) AS balance_raw
FROM balances_ethereum.daily_updates AS i
JOIN days AS d
  ON d.day >= i.valid_from
 AND d.day < i.valid_to
CROSS JOIN bounds
WHERE i.token_address = {{token}}
  AND i.token_standard = 'erc20'
  AND i.address IN ({{pool_list}})
  AND i.valid_from <= bounds.d1
  AND i.valid_to > bounds.d0
  AND i.balance_raw > 0
ORDER BY 1, 2


-- === name: pool_tvl ===
-- CLI helper only. Product TVL = pool_balance_timeline × price_timeline locally.
SELECT
  day,
  pool AS pool_address,
  tvl_usd
FROM dex.pool_tvl
WHERE blockchain = '{{chain}}'
  AND pool = {{pool}}
  {{block_filter}}
ORDER BY day DESC
LIMIT 1


-- === name: transfers ===
-- KEEP while indexer still needs raw ERC20 transfers for labels / movers.
-- Clustering uses cluster_transfers (filtered candidates), not this full dump.
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


-- === name: cluster_transfers ===
-- Wallet clustering evidence — ONE transfer pull for candidates.
-- Keep from/to in the result: WHERE filters ≠ local edge endpoints.
-- Min columns for reciprocal / repeated / same_tx support (do not over-aggregate yet).
SELECT
  CAST("from" AS varchar) AS from_address,
  CAST("to" AS varchar) AS to_address,
  CAST(value AS varchar) AS amount_raw,
  CAST(evt_tx_hash AS varchar) AS tx_hash,
  CAST(evt_block_time AS varchar) AS block_time
FROM erc20_ethereum.evt_Transfer
WHERE contract_address = {{token}}
  AND evt_block_number BETWEEN {{from_block}} AND {{to_block}}
  AND "from" IN ({{address_list}})
  AND "to" IN ({{address_list}})
  AND "from" <> "to"
  AND value > 0


-- === name: cluster_gas_payers ===
-- Wallet clustering — ONE gas-payer pull for transfer tx hashes.
SELECT
  CAST(hash AS varchar) AS tx_hash,
  CAST("from" AS varchar) AS gas_payer
FROM ethereum.transactions
WHERE hash IN ({{tx_hash_list}})


-- === name: cluster_traces ===
-- same_tx_cooccurrence: only traces for txs already seen in cluster_transfers.
-- Filter to candidate addresses — never scan all ethereum.traces.
SELECT
  CAST(tx_hash AS varchar) AS tx_hash,
  CAST("from" AS varchar) AS from_address,
  CAST("to" AS varchar) AS to_address
FROM ethereum.traces
WHERE tx_hash IN ({{tx_hash_list}})
  AND (
    "from" IN ({{address_list}})
    OR "to" IN ({{address_list}})
  )
  AND "from" IS NOT NULL
  AND "to" IS NOT NULL
  AND "from" <> "to"


-- === name: token_meta ===
SELECT
  contract_address AS address,
  symbol,
  decimals
FROM tokens.erc20
WHERE contract_address = {{token}}
  AND blockchain = '{{chain}}'
LIMIT 1


-- === name: liquidity_uniswap_v2_mint ===
-- Pool/block aggregate: preserve liquidity flow without downloading each LP actor.
-- Constants (protocol/version/event_type/source) filled in dune_index normalizer.
SELECT
  evt_block_number AS block_number,
  CAST(MAX(evt_block_time) AS varchar) AS block_time,
  '' AS transaction_hash,
  0 AS log_index,
  CAST(contract_address AS varchar) AS pool_address,
  CAST(SUM(CAST(amount0 AS DECIMAL(38, 0))) AS varchar) AS token0_amount,
  CAST(SUM(CAST(amount1 AS DECIMAL(38, 0))) AS varchar) AS token1_amount,
  COUNT(*) AS event_count,
  'pool_block' AS aggregation_scope
FROM uniswap_v2_ethereum.Pair_evt_Mint
WHERE evt_block_number BETWEEN {{from_block}} AND {{to_block}}
  AND contract_address IN ({{pool_list}})
GROUP BY evt_block_number, contract_address


-- === name: liquidity_uniswap_v2_burn ===
SELECT
  evt_block_number AS block_number,
  CAST(MAX(evt_block_time) AS varchar) AS block_time,
  '' AS transaction_hash,
  0 AS log_index,
  CAST(contract_address AS varchar) AS pool_address,
  CAST(SUM(CAST(amount0 AS DECIMAL(38, 0))) AS varchar) AS token0_amount,
  CAST(SUM(CAST(amount1 AS DECIMAL(38, 0))) AS varchar) AS token1_amount,
  COUNT(*) AS event_count,
  'pool_block' AS aggregation_scope
FROM uniswap_v2_ethereum.Pair_evt_Burn
WHERE evt_block_number BETWEEN {{from_block}} AND {{to_block}}
  AND contract_address IN ({{pool_list}})
GROUP BY evt_block_number, contract_address


-- === name: liquidity_uniswap_v3_mint ===
SELECT
  evt_block_number AS block_number,
  CAST(MAX(evt_block_time) AS varchar) AS block_time,
  '' AS transaction_hash,
  0 AS log_index,
  CAST(contract_address AS varchar) AS pool_address,
  CAST(SUM(CAST(amount0 AS DECIMAL(38, 0))) AS varchar) AS token0_amount,
  CAST(SUM(CAST(amount1 AS DECIMAL(38, 0))) AS varchar) AS token1_amount,
  COUNT(*) AS event_count,
  'pool_block' AS aggregation_scope
FROM uniswap_v3_ethereum.Pair_evt_Mint
WHERE evt_block_number BETWEEN {{from_block}} AND {{to_block}}
  AND contract_address IN ({{pool_list}})
GROUP BY evt_block_number, contract_address


-- === name: liquidity_uniswap_v3_burn ===
SELECT
  evt_block_number AS block_number,
  CAST(MAX(evt_block_time) AS varchar) AS block_time,
  '' AS transaction_hash,
  0 AS log_index,
  CAST(contract_address AS varchar) AS pool_address,
  CAST(SUM(CAST(amount0 AS DECIMAL(38, 0))) AS varchar) AS token0_amount,
  CAST(SUM(CAST(amount1 AS DECIMAL(38, 0))) AS varchar) AS token1_amount,
  COUNT(*) AS event_count,
  'pool_block' AS aggregation_scope
FROM uniswap_v3_ethereum.Pair_evt_Burn
WHERE evt_block_number BETWEEN {{from_block}} AND {{to_block}}
  AND contract_address IN ({{pool_list}})
GROUP BY evt_block_number, contract_address


-- === name: liquidity_uniswap_v4_modify ===
-- Pool/block/sign aggregate: positive and negative deltas stay separate.
SELECT
  evt_block_number AS block_number,
  CAST(MAX(evt_block_time) AS varchar) AS block_time,
  '' AS transaction_hash,
  0 AS log_index,
  CAST(id AS varchar) AS pool_id,
  CAST(SUM(CAST(liquidityDelta AS DECIMAL(38, 0))) AS varchar) AS liquidity_delta,
  COUNT(*) AS event_count,
  'pool_block' AS aggregation_scope
FROM uniswap_v4_ethereum.PoolManager_evt_ModifyLiquidity
WHERE evt_block_number BETWEEN {{from_block}} AND {{to_block}}
  AND id IN ({{pool_id_list}})
GROUP BY
  evt_block_number,
  id,
  CASE WHEN liquidityDelta < 0 THEN -1 ELSE 1 END
ORDER BY evt_block_number, id


-- === name: liquidity_uniswap_v3_npm_token_ids ===
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


-- === name: positions_uniswap_v3_snapshot ===
-- PRIMARY V3 LP path (token_id + pool + ticks + liquidity + owner in one query).
-- Do not also run base/liquidity/owners in the happy path — those are fallback only.
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
  {{owner_filter}}


-- === name: positions_uniswap_v3_base ===
-- FALLBACK staged path when positions_uniswap_v3_snapshot fails (see positions.py).
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


-- === name: positions_uniswap_v3_liquidity ===
-- FALLBACK staged path (with base + positions_nft_owners).
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


-- === name: positions_uniswap_v4_liquidity ===
SELECT
  CAST(id AS varchar) AS pool_id,
  CAST(salt AS varchar) AS salt,
  MIN(tickLower) AS tick_lower,
  MIN(tickUpper) AS tick_upper,
  CAST(SUM(CAST(liquidityDelta AS decimal(38, 0))) AS varchar) AS liquidity
FROM uniswap_v4_ethereum.PoolManager_evt_ModifyLiquidity
WHERE evt_block_number <= {{to_block}}
  AND id IN ({{pool_id_list}})
GROUP BY 1, 2
HAVING SUM(CAST(liquidityDelta AS decimal(38, 0))) > 0


-- === name: positions_nft_owners ===
-- FALLBACK staged path (with base + liquidity).
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


-- === name: pool_sqrt_price_v3 ===
-- KEEP for V3 LP tick valuation (not for dashboard price_timeline).
SELECT
  CAST(contract_address AS varchar) AS pool_address,
  CAST(sqrtPriceX96 AS varchar) AS sqrt_price_x96
FROM (
  SELECT
    contract_address,
    sqrtPriceX96,
    ROW_NUMBER() OVER (
      PARTITION BY contract_address
      ORDER BY evt_block_number DESC, evt_index DESC
    ) AS rn
  FROM uniswap_v3_ethereum.Pair_evt_Swap
  WHERE contract_address IN ({{pool_list}})
    AND evt_block_number <= {{to_block}}
) t
WHERE rn = 1
