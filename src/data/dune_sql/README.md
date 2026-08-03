# Dune SQL templates

Call from Python:

```python
from src.data.dune import configured, query

if configured():
    rows = query("pools", token="0x…", from_block=N, to_block=M, cache_dir="output/dune_cache")
```

| Template | Step |
|----------|------|
| `pools.sql` | Discovery (non-V4) |
| `pools_v4.sql` | Discovery — real V4 bytes32 poolIds |
| `swaps.sql` | Index swaps |
| `liquidity_uniswap_v2_*.sql` / `v3_*.sql` | Index V2/V3 LP |
| `liquidity_uniswap_v4_modify.sql` | Index V4 LP by poolId |
| `liquidity_uniswap_v3_npm_token_ids.sql` | Positions RPC-fallback tokenIds |
| `positions_uniswap_v3_snapshot.sql` | Positions — V3 owner+L+ticks at to_block |
| `positions_uniswap_v3_base.sql` | Positions — V3 mint→tokenId (staged) |
| `positions_uniswap_v3_liquidity.sql` | Positions — V3 net L for tokenId list |
| `positions_uniswap_v4_liquidity.sql` | Positions — V4 net L by poolId+salt |
| `positions_nft_owners.sql` | Positions — ERC721 owners for tokenId list |
| `pool_sqrt_price_v3.sql` | Positions — last V3 sqrtPriceX96 |
| `transfers.sql` | Index ERC20 transfers |
| `transfer_addresses.sql` / `balances.sql` | Holdings (optional) |
| `swaps_by_pool.sql` / `pool_tvl.sql` | CLI helpers |
| `token_meta.sql` | Optional metadata |
