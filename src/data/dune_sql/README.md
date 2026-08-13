# Dune SQL templates

All query templates live in **one file**: [`queries.sql`](./queries.sql).

Each section is marked as:

```sql
-- === name: pools ===
SELECT ...
```

Call from Python (unchanged API):

```python
from src.data.dune import configured, query, list_sql_sections

if configured():
    rows = query("pools", token="0x…", from_block=N, to_block=M, cache_dir="output/dune_cache")
    print(list_sql_sections())
```

Design notes: see [`structure.md`](./structure.md).

| Section | Step / use |
|---------|------------|
| `pools` / `pools_v4` | Discovery |
| `holders` | Historical holders via `balances_ethereum.daily_updates` |
| `holders_from_transfers` | Backup holders (same-day in/out); Python fallback only |
| `transfer_addresses` / `balances` | Holdings last-resort / balance fill |
| `swaps` | Index raw trades; volume/price charts reuse these rows locally |
| `volume_timeline` / `price_timeline` | Chart aggregates (fallback only if swaps were not indexed) |
| `pool_token_balances` / `pool_balance_timeline` | Pool balances (latest + daily history) |
| `pool_tvl` | CLI helper only |
| `transfers` | Index transfers (clustering uses filtered cluster_*) |
| `cluster_transfers` / `cluster_gas_payers` / `cluster_traces` | Wallet clustering |
| `token_meta` | Symbol / decimals |
| `liquidity_uniswap_*` | Index LP events |
| `positions_uniswap_v3_snapshot` | Primary V3 LP |
| `positions_*_base` / `_liquidity` / `positions_nft_owners` | Staged V3 fallback |
| `positions_uniswap_v4_liquidity` | V4 LP |
| `pool_sqrt_price_v3` | V3 LP tick valuation |
