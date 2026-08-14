# Artifact Storage Design

> Status: Phase 2 partially implemented (2026-08-13)
> Scope: local analysis artifacts produced by `python3 -m src.cli analyze`
> Non-goal: this document does not change metric definitions, risk logic, or dashboard presentation.

## 1. Problem

The pipeline currently uses JSON for both small summaries and large tabular datasets.
This is convenient, but it creates four problems as analysis windows grow:

1. Large event arrays are difficult to inspect as tables.
2. `json.load()` parses the complete file even when a caller needs only a few columns or rows.
3. Field names are repeated for every row, increasing file size and Git diff noise.
4. `events_all.json` duplicates swaps, liquidity events, and transfers that already exist separately.

The current sample is still small enough that JSON parsing is fast. The purpose of this
change is therefore scalability, reviewability, and a clearer data contract—not a claim
that JSON is already the main runtime bottleneck.

## 2. Decision

Use a layered artifact model:

| Responsibility | Format | Examples |
|---|---|---|
| Large tabular analysis data | Parquet | swaps, transfers, liquidity events, holdings, positions, timelines |
| Local analytical queries | DuckDB | filtering, joins, aggregation, and logical views over Parquet |
| Small nested summaries and run metadata | JSON | token profile, metrics summary, risk assessment, manifest |
| Human review and spreadsheet export | CSV / Markdown | pool summary, Top Holders, Top Movers, withdrawals, report |
| Static presentation | HTML + compact embedded JSON | dashboard and public site |

Parquet is the canonical format for large tables. DuckDB is the query layer and does not
need to become a committed database file. JSON remains valid for small nested objects.

## 3. Goals and non-goals

### Goals

- Preserve all existing calculations and dashboard output.
- Read only required columns and rows for analytical tasks.
- Reduce duplicate artifacts and large Git diffs.
- Define stable field names, types, nullability, and provenance.
- Keep analysis runs reproducible from token, block window, SQL, and code revision.
- Provide CSV or Markdown views that a person can inspect without opening raw data.
- Migrate incrementally with JSON/Parquet parity checks.

### Non-goals

- Do not introduce a database server.
- Do not change risk thresholds or metric definitions.
- Do not replace Dune or RPC as upstream data sources.
- Do not put Parquet or DuckDB binaries into Git history by default.
- Do not remove JSON compatibility until parity has been demonstrated.

## 4. Proposed output layout

```text
output-<purpose>/
├── manifest.json
├── summaries/
│   ├── token_profile.json
│   ├── metrics.json
│   ├── risk_assessment.json
│   ├── position_summary.json
│   └── index_source.json
├── tables/
│   ├── pool_candidates.parquet
│   ├── verified_pools.parquet
│   ├── swaps.parquet
│   ├── liquidity_events.parquet
│   ├── transfers.parquet
│   ├── holdings.parquet
│   ├── positions.parquet
│   ├── tvl_timeline.parquet
│   ├── volume_timeline.parquet
│   └── address_clusters.parquet
├── exports/
│   ├── pool_summary.csv
│   ├── top_holders.csv
│   ├── top_movers.csv
│   └── withdrawals.csv
├── cache/
│   └── dune/
├── report.md
└── dashboard.html
```

During migration, legacy JSON files may remain at the output root. The final directory
layout should only be adopted after all current readers use the artifact access layer.

## 5. Artifact classification

### 5.1 Keep as JSON

These artifacts are small, nested, and commonly consumed as complete objects:

- `token_profile.json`
- `metrics.json` after large timeline arrays are moved to Parquet
- `risk_assessment.json`
- `position_summary.json`
- `index_source.json`
- `manifest.json`
- resumable checkpoint files

### 5.2 Move to Parquet

These artifacts are row-oriented tables that benefit from typed columns and selective reads:

- `pool_candidates.json`
- `verified_pools.json`
- `swaps.json`
- `liquidity_events.json`
- `transfers.json`
- `holdings.json` → separate run summary from holder rows
- `positions.json`
- `tvl_timeline.json`
- `volume_timeline.json`
- wallet-clustering nodes, edges, evidence, and cluster membership

Small pool lists may technically remain JSON, but using the table interface consistently
avoids special cases in downstream joins.

### 5.3 Remove as a physical artifact

`events_all.json` should not exist in the final format. It duplicates the three event tables.
Where a combined stream is needed, create a DuckDB view or query the tables independently.

Example logical view:

```sql
CREATE VIEW events_all AS
SELECT 'swap' AS event_type, block_number, block_time, transaction_hash,
       log_index, pool_address, actor
FROM read_parquet('tables/swaps.parquet')
UNION ALL BY NAME
SELECT 'liquidity' AS event_type, block_number, block_time, transaction_hash,
       log_index, pool_address, actor
FROM read_parquet('tables/liquidity_events.parquet')
UNION ALL BY NAME
SELECT 'transfer' AS event_type, block_number, block_time, transaction_hash,
       log_index, NULL AS pool_address, actor
FROM read_parquet('tables/transfers.parquet');
```

Callers that require event-specific fields should query the original table rather than the
combined view.

## 6. Common schema rules

All Parquet tables must follow these conventions:

| Field category | Storage rule |
|---|---|
| Ethereum address | lowercase `0x` string; nullable only when the source permits it |
| Transaction hash / pool ID | lowercase `0x` string |
| `block_number` | signed INT64 |
| `log_index` / event index | INT32 when present |
| `block_time` | UTC timestamp, timezone recorded as UTC |
| protocol / version / symbol | UTF-8 string |
| boolean flags | BOOLEAN, not `0`/`1` strings |
| unavailable values | NULL, not empty string, zero, or `"unknown"` |
| USD estimates | DOUBLE initially; document approximation and source |
| normalized token amounts | DOUBLE initially for chart/summary calculations |
| raw ERC-20 amounts | decimal string unless a tested 256-bit representation is available |

Ethereum `uint256` values can exceed common DECIMAL precision. Do not coerce `amount_raw`,
`balance_raw`, or `total_supply_raw` to float. Store them as canonical base-10 strings and
derive display amounts using token decimals.

Every table should include provenance columns when meaningful:

- `source`: for example `dune.dex.trades`, `dune.daily_updates`, or `rpc`.
- `source_query`: named SQL section such as `swaps` or `pool_balance_timeline`.
- `is_estimate`: whether a value is derived or approximate.
- `run_id`: identifier linking the row to `manifest.json` when tables are combined later.

## 7. Minimum table contracts

This section defines the minimum stable columns. Additional protocol-specific columns may be
added as nullable fields.

### 7.1 `swaps`

```text
block_number: int64
block_time: timestamp UTC
transaction_hash: string
log_index: int32 nullable
protocol: string
version: string nullable
pool_address: string
actor: string nullable
tx_from: string nullable
token_bought: string
token_sold: string
token_bought_amount_raw: string
token_sold_amount_raw: string
amount_usd: double nullable
source: string
```

Primary uniqueness key when available:

```text
(transaction_hash, log_index, pool_address)
```

### 7.2 `transfers`

```text
block_number: int64
block_time: timestamp UTC
transaction_hash: string
log_index: int32
token_address: string
from_address: string
to_address: string
amount_raw: string
source: string
```

Primary uniqueness key:

```text
(transaction_hash, log_index, token_address)
```

### 7.3 `liquidity_events`

```text
block_number: int64
block_time: timestamp UTC
transaction_hash: string nullable
log_index: int32 nullable
protocol: string
version: string nullable
pool_address: string
event_type: string
actor: string nullable
target_amount_raw: string nullable
target_amount_decimal: double nullable
amount_usd: double nullable
source: string
is_aggregated: boolean
```

The Dune path may return pool-level aggregated rows without LP actor identity. Such rows must
set `is_aggregated=true` and leave unavailable identity fields NULL.

### 7.4 `holdings`

```text
address: string
node_type: string
is_pool: boolean
balance_start_raw: string nullable
balance_end_raw: string nullable
peak_balance_raw: string nullable
net_change_raw: string nullable
balance_start_decimal: double nullable
balance_end_decimal: double nullable
peak_balance_decimal: double nullable
net_change_decimal: double nullable
balance_start_block: int64 nullable
balance_end_block: int64 nullable
balance_source: string
```

Run-level fields such as total candidate addresses, zero-fill count, and snapshot coverage
belong in `manifest.json` or a small holdings summary JSON, not repeated on every row.

### 7.5 Timeline tables

All price, volume, balance, and TVL timelines should share:

```text
bucket_time: timestamp UTC
bucket_size: string  # hour or day
pool_address: string
token_address: string
```

Metric-specific fields include `price_usd`, `volume_in_token`, `volume_usd`,
`balance_raw`, `tvl_in_token`, and `tvl_usd`. Values derived from different temporal
resolutions must record the source resolution and must not be described as exact hourly
snapshots.

## 8. Manifest contract

Each analysis run must write `manifest.json` before publication. Minimum structure:

```json
{
  "schema_version": "2.0.0",
  "run_id": "ethereum-0xabc-25000000-25010000",
  "chain_id": 1,
  "token_address": "0xabc...",
  "from_block": 25000000,
  "to_block": 25010000,
  "created_at": "2026-08-13T18:00:00Z",
  "git_commit": "<commit>",
  "chart_span": "week",
  "tables": {
    "swaps": {
      "path": "tables/swaps.parquet",
      "rows": 14066,
      "source": "dune.dex.trades",
      "query_name": "swaps",
      "schema_version": "1.0.0"
    }
  },
  "summaries": {
    "metrics": "summaries/metrics.json",
    "risk": "summaries/risk_assessment.json"
  }
}
```

Recommended additions are file checksums, SQL-template hashes, Dune execution IDs, RPC chain
ID confirmation, cache hit status, warnings, row counts, and coverage statistics.

## 9. Artifact access layer

Introduce one module, provisionally `src/data/artifacts.py`, as the only supported interface
for pipeline artifacts:

```python
write_table(name, rows, output_dir, artifact_format="json")
read_table(name, output_dir, columns=None, filters=None)
query_tables(sql, output_dir, params=None)
write_summary(name, value, output_dir)
read_summary(name, output_dir)
```

Business logic in metrics, timeline, holdings, clustering, and dashboard should not call
`json.load()` or a Parquet library directly. The access layer owns:

- file naming and directory layout;
- atomic writes;
- schema validation;
- JSON fallback during migration;
- Parquet and DuckDB dependency errors;
- manifest updates;
- row-count and checksum verification.

## 10. Dashboard contract

The dashboard should remain a static artifact and should not query Dune at render time.

The generation path should be:

```text
Parquet tables
  → DuckDB/local metric queries
  → compact summary objects and chart series
  → dashboard.html
```

Only aggregated chart series, Top-N tables, selected withdrawal rows, and cluster summaries
should be embedded in HTML. Raw swaps and transfers must not be embedded in the dashboard.

Visual presentation and metric definitions must remain unchanged during the storage migration.

## 11. Human-readable exports

CSV and Markdown are presentation exports, not canonical storage. Generate only useful review
surfaces:

- verified pool summary;
- Top Holders and balance changes;
- Top Movers and wallet-activity flags;
- material liquidity withdrawals;
- cluster-pair evidence summary;
- run warnings and data-source coverage.

Avoid exporting full raw transfer history to CSV by default. A user can request a filtered
CSV through DuckDB when investigation requires it.

## 12. Git and publication policy

Default policy:

- Do not commit Parquet files, DuckDB databases, or raw Dune cache files.
- Keep large canonical tables in ignored local output directories.
- Commit small manifests, summaries, human-readable reports, and generated site files.
- If a full dataset must be shared, use a release artifact or external object storage and
  record its checksum and URL in the manifest.
- Preserve the SQL templates and run parameters needed to reproduce the data.

The repository currently commits some named example output directories. Changing that policy
requires an explicit update to `AGENTS.md` and agreement on how example datasets will be
distributed. This design does not change that rule by itself.

## 13. Migration plan

### Phase 0 — contract and benchmark

- Approve this document.
- Record current file size, load time, peak memory, row counts, and metric outputs.
- Add schema fixtures for representative V2, V3, V4, Curve, and Balancer rows.

### Phase 1 — storage abstraction and swaps dual-write

- [x] Add `src/data/artifacts.py`.
- [x] Add `--artifact-format json|both`; default remains `json` initially.
- [x] Dual-write `swaps.json` and `tables/swaps.parquet`.
- [x] Verify row-level and downstream price/volume metric parity.

Parquet-only output is intentionally rejected during Phase 1 because dashboard and legacy
standalone commands still read JSON. It will be enabled after those readers use the artifact
access layer.

### Phase 2 — remaining large tables

- [x] Migrate transfers and liquidity events.
- [x] Migrate holdings rows while preserving the nested `holdings.json` summary.
- [ ] Migrate positions and timelines.
- [x] Separate the holdings run summary from its canonical Parquet row table.

### Phase 3 — readers and combined-event removal

- Move metrics, timeline, labels, clustering, and dashboard to the artifact access layer.
- Replace `events_all.json` with a logical query/view.
- Keep legacy JSON fallback for old committed demos.

### Phase 4 — switch default and publication cleanup

- Make Parquet the default canonical table format after parity tests pass.
- Stop generating large JSON tables unless explicitly requested.
- Update README, DATA_FLOW, DUNE_CLI_PIPELINE, AGENTS, and site publication logic.

## 14. Validation and acceptance criteria

Storage migration is complete only when:

1. JSON and Parquet runs contain the same logical rows after normalization.
2. Existing metrics and risk scores are identical within documented floating-point tolerance.
3. Dashboard content and visual behavior are unchanged.
4. Schema tests reject unexpected type or nullability regressions.
5. Duplicate event rows are detected by documented uniqueness keys.
6. A large-window benchmark shows lower peak memory and faster selective reads.
7. `events_all.json` is no longer required by any production path.
8. Generated Git diffs no longer contain full raw event histories.
9. Old JSON-only example outputs still render through the compatibility reader.

Suggested performance benchmark queries:

- all swaps for one pool;
- total USD volume grouped by pool;
- transfers involving one candidate wallet;
- TVL series for a selected time range;
- Top 20 holders by end balance.

## 15. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Silent type coercion changes amounts | Keep raw uint256 values as strings; add schema and parity tests |
| JSON and Parquet diverge during dual-write | Write both from one normalized in-memory table and compare row counts/checksums |
| Old dashboards cannot open new outputs | Artifact reader falls back to legacy JSON |
| Optional dependencies are unavailable | Report a clear error or retain JSON mode until dependencies are installed |
| Binary files accidentally enter Git | Add explicit ignore rules only when implementation begins and explain the change |
| Migration changes business logic | Separate storage commits from metric/dashboard changes |

## 16. Open decisions before implementation

The following must be decided during Phase 0/1:

1. Use PyArrow directly or a DataFrame library to write Parquet.
2. Whether DuckDB remains an in-process query dependency only or optionally persists a local
   catalog file.
3. Exact floating-point tolerance for normalized token and USD values.
4. Whether small pool lists remain JSON or use Parquet for interface consistency.
5. Where shared full datasets live when a result must be publicly reproducible.
6. How long legacy JSON output remains supported.

The recommended starting decision is PyArrow-compatible Parquet, in-process DuckDB without a
persisted database, JSON compatibility for existing demos, and no committed binary artifacts.
