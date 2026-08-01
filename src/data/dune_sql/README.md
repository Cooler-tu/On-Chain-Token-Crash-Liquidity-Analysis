# Dune SQL templates

Edit these `.sql` files to change what we pull from Dune.
Python (`dune_collector.py`) only substitutes placeholders and runs the API.

## Placeholders

| Placeholder | Meaning | Example |
|-------------|---------|---------|
| `{{token}}` | token address (0x… lowercase) | `0xd533…` |
| `{{chain}}` | Dune blockchain name | `ethereum` |
| `{{from_block}}` / `{{to_block}}` | inclusive block window | `22000000` |
| `{{pool_list}}` | comma-separated pool addresses | `0xabc…, 0xdef…` |
| `{{pool_filter}}` | optional AND clause (may be empty) | `AND project_contract_address IN (…)` |
| `{{address_list}}` | wallet IN-list for balances | `0x…, 0x…` |
| `{{zero_address}}` | zero address literal | `0x000…000` |

## Try in Dune UI

1. Open a `.sql` file
2. Replace `{{…}}` with real values
3. Run on [dune.com](https://dune.com)
4. Paste back / commit when it works

## Run collector

```bash
python3 -m src.data.dune_collector \
  --token 0xD533a949740bb3306d119CC777fa900bA034cd52 \
  --from-block 22000000 --to-block 22005000 \
  --out-dir dune_cache/crv
```
