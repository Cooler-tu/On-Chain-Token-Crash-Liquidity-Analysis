# Time-series Correlation — Exploratory

- Scope: `0xdc893995d488e5be8ec8ca1db92cbec2a1ab0775`
- Buckets: `169`
- Bucket seconds: `3600`
- Lag convention: positive lag means X leads Y.
- Warning: Correlation and lag selection remain exploratory and do not establish causality.

## Strongest contemporaneous correlations

| X | Y | Method | Correlation | N |
|---|---|---|---:|---:|
| price_return | tvl_change | spearman | -0.7757 | 168 |
| price_return | tvl_change | pearson | -0.6841 | 168 |
| tvl_change | log1p_volume_token | spearman | -0.0600 | 168 |
| price_return | log1p_volume_token | pearson | -0.0473 | 168 |
| price_return | log1p_volume_token | spearman | -0.0123 | 168 |
| tvl_change | log1p_volume_token | pearson | 0.0037 | 168 |

## Strongest lag-selected correlations

| X | Y | Method | Lag | Best | Lag 0 | Improvement | N |
|---|---|---|---:|---:|---:|---:|---:|
| price_return | tvl_change | spearman | 0 | -0.7757 | -0.7757 | 0.0000 | 168 |
| price_return | tvl_change | pearson | 0 | -0.6841 | -0.6841 | 0.0000 | 168 |
| tvl_change | log1p_volume_token | spearman | -16 | -0.2307 | -0.0600 | 0.1706 | 153 |
| tvl_change | log1p_volume_token | pearson | -16 | -0.1758 | 0.0037 | 0.1721 | 153 |
| price_return | log1p_volume_token | spearman | 12 | 0.1455 | -0.0123 | 0.1332 | 156 |
| price_return | log1p_volume_token | pearson | 12 | 0.1455 | -0.0473 | 0.0982 | 156 |
