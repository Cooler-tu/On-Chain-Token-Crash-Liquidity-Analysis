# Analysis Series Summary

## Dataset

| Field | Value |
|---|---:|
| Token | uPEG `0x44b28991b167582f18ba0259e0173176ca125505` |
| All rows | 338 |
| Pool rows | 169 |
| Token-total buckets | 169 |
| Observed pools | 1 |
| Bucket seconds | 3600 |
| First bucket (UTC) | 2026-05-06T05:00:00+00:00 |
| Last bucket (UTC) | 2026-05-13T05:00:00+00:00 |
| TVL source | rpc_target_balance_local_quote_price (169) |
| Price unit | WETH |
| Liquidity event coverage | not_collected_in_swaps_only_run |

## Coverage

| Check | Rows |
|---|---:|
| Pool rows with VWAP | 169 |
| Pool rows with TVL state | 169 |
| Max TVL-measured pools per bucket | 1 / 1 |
| Removal activity with unknown amount | 0 |
| Active LP rows with full identity coverage | 0 |

## Interpretation warnings

- RPC TVL is target-token-side attributable reserve, not full two-sided TVL.
- Liquidity events were not collected in this run; zero LP event counts mean unavailable coverage, not observed absence.
- Price is quoted in WETH; returns are usable within this pool, but absolute values are not USD prices.

## Human-readable preview

`analysis_series_preview.csv` contains only `scope=token_total` rows. The full pool-level and token-total dataset remains in `tables/analysis_series.parquet`.
