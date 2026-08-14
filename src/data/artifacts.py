"""Typed artifact storage for large tables and small JSON summaries.

The migration keeps legacy JSON as the default and supports JSON/Parquet
dual-write for swaps, transfers, liquidity events, holdings, and positions
rows. Imports for optional analytical dependencies are lazy so existing
JSON-only runs continue to work without PyArrow or DuckDB installed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


ARTIFACT_FORMATS = ("json", "parquet", "both")


class ArtifactError(RuntimeError):
    """Base error for artifact storage operations."""


class ArtifactDependencyError(ArtifactError):
    """Raised when an explicitly requested artifact backend is unavailable."""


class ArtifactSchemaError(ArtifactError):
    """Raised when rows do not satisfy a table's storage contract."""


def normalize_artifact_format(value: str) -> str:
    """Return a validated artifact format name."""
    mode = str(value or "json").strip().lower()
    if mode not in ARTIFACT_FORMATS:
        raise ValueError(
            "artifact format must be one of: {} (got {!r})".format(
                ", ".join(ARTIFACT_FORMATS), value
            )
        )
    return mode


def _json_path(name: str, output_dir: str | Path) -> Path:
    return Path(output_dir) / "{}.json".format(name)


def _parquet_path(name: str, output_dir: str | Path) -> Path:
    return Path(output_dir) / "tables" / "{}.parquet".format(name)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, default=str)
    tmp.replace(path)


def write_summary(name: str, value: Any, output_dir: str | Path) -> Path:
    """Write a small JSON summary atomically."""
    path = _json_path(name, output_dir)
    _atomic_json(path, value)
    return path


def read_summary(
    name: str,
    output_dir: str | Path,
    default: Any = None,
) -> Any:
    """Read a small JSON summary, returning ``default`` when it is absent."""
    path = _json_path(name, output_dir)
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _pyarrow_modules():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ArtifactDependencyError(
            "Parquet output requires PyArrow. Install project dependencies "
            "with `python3 -m pip install -r requirements.txt`, or use "
            "`--artifact-format json`."
        ) from exc
    return pa, pq


def _duckdb_module():
    try:
        import duckdb
    except ImportError as exc:
        raise ArtifactDependencyError(
            "DuckDB queries require duckdb. Install project dependencies "
            "with `python3 -m pip install -r requirements.txt`."
        ) from exc
    return duckdb


def validate_artifact_environment(artifact_format: str) -> str:
    """Validate requested optional backends before a pipeline starts work."""
    mode = normalize_artifact_format(artifact_format)
    if mode in ("parquet", "both"):
        _pyarrow_modules()
    return mode


def _lower_hex(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    return text.lower() if text.startswith("0x") else text


def _raw_string(value: Any, default: str = "0") -> str:
    if value is None or value == "":
        return default
    return str(value)


def _utc_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ArtifactSchemaError(
            "block_timestamp must be a Unix timestamp or datetime, got {!r}".format(
                value
            )
        ) from exc


def _schema_metadata(name: str, schema_version: str = "1.0.0") -> dict[bytes, bytes]:
    return {
        b"artifact_name": name.encode("utf-8"),
        b"schema_version": schema_version.encode("utf-8"),
        b"raw_amount_encoding": b"base10-string",
        b"address_encoding": b"lowercase-hex",
    }


def _swap_schema(pa):
    return pa.schema(
        [
            pa.field("block_number", pa.int64(), nullable=False),
            pa.field(
                "block_timestamp",
                pa.timestamp("s", tz="UTC"),
                nullable=True,
            ),
            pa.field("transaction_hash", pa.string(), nullable=False),
            pa.field("log_index", pa.int32(), nullable=False),
            pa.field("protocol", pa.string(), nullable=False),
            pa.field("version", pa.string(), nullable=True),
            pa.field("pool_address", pa.string(), nullable=True),
            pa.field("event_type", pa.string(), nullable=False),
            pa.field("actor", pa.string(), nullable=True),
            pa.field("recipient", pa.string(), nullable=True),
            pa.field("token0_address", pa.string(), nullable=True),
            pa.field("token1_address", pa.string(), nullable=True),
            pa.field("amount_usd", pa.float64(), nullable=True),
            pa.field("token0_amount", pa.string(), nullable=False),
            pa.field("token1_amount", pa.string(), nullable=False),
            pa.field("liquidity_delta", pa.string(), nullable=False),
            pa.field("source_event", pa.string(), nullable=True),
            pa.field("verified", pa.bool_(), nullable=False),
            pa.field("nft_token_id", pa.string(), nullable=True),
        ],
        metadata=_schema_metadata("swaps"),
    )


def _normalize_swap_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ArtifactSchemaError("swaps rows must be dictionaries")
    return {
        "block_number": int(row.get("block_number") or 0),
        "block_timestamp": _utc_datetime(row.get("block_timestamp")),
        "transaction_hash": _lower_hex(row.get("transaction_hash") or "") or "",
        "log_index": int(row.get("log_index") or 0),
        "protocol": str(row.get("protocol") or "").lower(),
        "version": str(row.get("version") or "") or None,
        "pool_address": _lower_hex(row.get("pool_address")),
        "event_type": str(row.get("event_type") or "SWAP"),
        "actor": _lower_hex(row.get("actor")),
        "recipient": _lower_hex(row.get("recipient")),
        "token0_address": _lower_hex(row.get("token0_address")),
        "token1_address": _lower_hex(row.get("token1_address")),
        "amount_usd": (
            float(row["amount_usd"])
            if row.get("amount_usd") is not None
            else None
        ),
        "token0_amount": _raw_string(row.get("token0_amount")),
        "token1_amount": _raw_string(row.get("token1_amount")),
        "liquidity_delta": _raw_string(row.get("liquidity_delta")),
        "source_event": str(row.get("source_event") or "") or None,
        "verified": bool(row.get("verified", False)),
        "nft_token_id": (
            str(row["nft_token_id"])
            if row.get("nft_token_id") is not None
            else None
        ),
    }


def _event_base_fields(pa) -> list[Any]:
    return [
        pa.field("block_number", pa.int64(), nullable=False),
        pa.field("block_timestamp", pa.timestamp("s", tz="UTC"), nullable=True),
        pa.field("transaction_hash", pa.string(), nullable=False),
        pa.field("log_index", pa.int32(), nullable=False),
        pa.field("protocol", pa.string(), nullable=True),
        pa.field("version", pa.string(), nullable=True),
        pa.field("pool_address", pa.string(), nullable=True),
        pa.field("event_type", pa.string(), nullable=False),
        pa.field("actor", pa.string(), nullable=True),
        pa.field("recipient", pa.string(), nullable=True),
        pa.field("token0_amount", pa.string(), nullable=False),
        pa.field("token1_amount", pa.string(), nullable=False),
        pa.field("liquidity_delta", pa.string(), nullable=False),
        pa.field("source_event", pa.string(), nullable=True),
        pa.field("verified", pa.bool_(), nullable=False),
        pa.field("nft_token_id", pa.string(), nullable=True),
    ]


def _transfer_schema(pa):
    return pa.schema(
        _event_base_fields(pa),
        metadata=_schema_metadata("transfers"),
    )


def _normalize_transfer_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ArtifactSchemaError("transfers rows must be dictionaries")
    return {
        "block_number": int(row.get("block_number") or 0),
        "block_timestamp": _utc_datetime(row.get("block_timestamp")),
        "transaction_hash": _lower_hex(row.get("transaction_hash") or "") or "",
        "log_index": int(row.get("log_index") or 0),
        "protocol": str(row.get("protocol") or "") or None,
        "version": str(row.get("version") or "") or None,
        "pool_address": _lower_hex(row.get("pool_address")),
        "event_type": str(row.get("event_type") or "TOKEN_TRANSFER"),
        "actor": _lower_hex(row.get("actor")),
        "recipient": _lower_hex(row.get("recipient")),
        "token0_amount": _raw_string(row.get("token0_amount")),
        "token1_amount": _raw_string(row.get("token1_amount")),
        "liquidity_delta": _raw_string(row.get("liquidity_delta")),
        "source_event": str(row.get("source_event") or "") or None,
        "verified": bool(row.get("verified", False)),
        "nft_token_id": (
            str(row["nft_token_id"])
            if row.get("nft_token_id") is not None
            else None
        ),
    }


def _liquidity_schema(pa):
    return pa.schema(
        _event_base_fields(pa)
        + [
            pa.field("tick_lower", pa.int32(), nullable=True),
            pa.field("tick_upper", pa.int32(), nullable=True),
            pa.field("salt", pa.string(), nullable=True),
            pa.field("event_count", pa.int64(), nullable=False),
            pa.field("aggregation_scope", pa.string(), nullable=True),
            pa.field("amount_usd", pa.float64(), nullable=True),
        ],
        metadata=_schema_metadata("liquidity_events"),
    )


def _normalize_liquidity_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ArtifactSchemaError("liquidity_events rows must be dictionaries")
    base = _normalize_transfer_row(row)
    base["event_type"] = str(row.get("event_type") or "")
    base.update(
        {
            "tick_lower": (
                int(row["tick_lower"])
                if row.get("tick_lower") is not None
                else None
            ),
            "tick_upper": (
                int(row["tick_upper"])
                if row.get("tick_upper") is not None
                else None
            ),
            "salt": str(row["salt"]) if row.get("salt") is not None else None,
            "event_count": max(1, int(row.get("event_count") or 1)),
            "aggregation_scope": (
                str(row.get("aggregation_scope") or "") or None
            ),
            "amount_usd": (
                float(row["amount_usd"])
                if row.get("amount_usd") is not None
                else None
            ),
        }
    )
    return base


def _holdings_schema(pa):
    return pa.schema(
        [
            pa.field("address", pa.string(), nullable=False),
            pa.field("address_type", pa.string(), nullable=False),
            pa.field("is_contract", pa.bool_(), nullable=False),
            pa.field("is_pool", pa.bool_(), nullable=False),
            pa.field("pool_label", pa.string(), nullable=True),
            pa.field("resolved_owner", pa.string(), nullable=True),
            pa.field("resolution_method", pa.string(), nullable=True),
            pa.field("balance_raw", pa.string(), nullable=False),
            pa.field("balance_decimal", pa.float64(), nullable=False),
            pa.field("balance_start_raw", pa.string(), nullable=True),
            pa.field("balance_start_decimal", pa.float64(), nullable=True),
            pa.field("balance_end_raw", pa.string(), nullable=True),
            pa.field("net_change_raw", pa.string(), nullable=True),
            pa.field("net_change_decimal", pa.float64(), nullable=True),
            pa.field("peak_balance_raw", pa.string(), nullable=True),
            pa.field("peak_balance_decimal", pa.float64(), nullable=True),
            pa.field("moved_in_raw", pa.string(), nullable=True),
            pa.field("moved_out_raw", pa.string(), nullable=True),
            pa.field("balance_source", pa.string(), nullable=True),
            pa.field("trajectory_source", pa.string(), nullable=True),
            pa.field("tx_count", pa.int64(), nullable=False),
            pa.field("first_seen_block", pa.int64(), nullable=True),
            pa.field("last_seen_block", pa.int64(), nullable=True),
            pa.field("query_timestamp", pa.timestamp("s", tz="UTC"), nullable=True),
        ],
        metadata=_schema_metadata("holdings"),
    )


def _optional_raw(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return str(value)


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(value)


def _normalize_holdings_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ArtifactSchemaError("holdings rows must be dictionaries")
    return {
        "address": _lower_hex(row.get("address") or "") or "",
        "address_type": str(row.get("address_type") or "unknown").lower(),
        "is_contract": bool(row.get("is_contract", False)),
        "is_pool": bool(row.get("is_pool", False)),
        "pool_label": str(row.get("pool_label") or "") or None,
        "resolved_owner": _lower_hex(row.get("resolved_owner")),
        "resolution_method": str(row.get("resolution_method") or "") or None,
        "balance_raw": _raw_string(row.get("balance_raw")),
        "balance_decimal": float(row.get("balance_decimal") or 0),
        "balance_start_raw": _optional_raw(row.get("balance_start_raw")),
        "balance_start_decimal": _optional_float(row.get("balance_start_decimal")),
        "balance_end_raw": _optional_raw(row.get("balance_end_raw")),
        "net_change_raw": _optional_raw(row.get("net_change_raw")),
        "net_change_decimal": _optional_float(row.get("net_change_decimal")),
        "peak_balance_raw": _optional_raw(row.get("peak_balance_raw")),
        "peak_balance_decimal": _optional_float(row.get("peak_balance_decimal")),
        "moved_in_raw": _optional_raw(row.get("moved_in_raw")),
        "moved_out_raw": _optional_raw(row.get("moved_out_raw")),
        "balance_source": str(row.get("balance_source") or "") or None,
        "trajectory_source": str(row.get("trajectory_source") or "") or None,
        "tx_count": int(row.get("tx_count") or 0),
        "first_seen_block": _optional_int(row.get("first_seen_block")),
        "last_seen_block": _optional_int(row.get("last_seen_block")),
        "query_timestamp": _utc_datetime(row.get("query_timestamp")),
    }


def _positions_schema(pa):
    return pa.schema(
        [
            pa.field("pool_address", pa.string(), nullable=False),
            pa.field("owner", pa.string(), nullable=False),
            pa.field("lp_token_address", pa.string(), nullable=True),
            pa.field("nft_token_id", pa.string(), nullable=True),
            pa.field("liquidity", pa.string(), nullable=False),
            pa.field("share_pct", pa.float64(), nullable=False),
            pa.field("beneficial_owner", pa.string(), nullable=True),
            pa.field("resolution_method", pa.string(), nullable=True),
            pa.field("confidence", pa.float64(), nullable=False),
            pa.field("tick_lower", pa.int32(), nullable=True),
            pa.field("tick_upper", pa.int32(), nullable=True),
            pa.field("token0_amount", pa.string(), nullable=True),
            pa.field("token1_amount", pa.string(), nullable=True),
        ],
        metadata=_schema_metadata("positions"),
    )


def _normalize_position_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ArtifactSchemaError("positions rows must be dictionaries")
    return {
        "pool_address": _lower_hex(row.get("pool_address") or "") or "",
        "owner": _lower_hex(row.get("owner") or "") or "",
        "lp_token_address": _lower_hex(row.get("lp_token_address")),
        "nft_token_id": _optional_raw(row.get("nft_token_id")),
        "liquidity": _raw_string(row.get("liquidity")),
        "share_pct": float(row.get("share_pct") or 0),
        "beneficial_owner": _lower_hex(row.get("beneficial_owner")),
        "resolution_method": str(row.get("resolution_method") or "") or None,
        "confidence": float(row.get("confidence") or 0),
        "tick_lower": _optional_int(row.get("tick_lower")),
        "tick_upper": _optional_int(row.get("tick_upper")),
        "token0_amount": _optional_raw(row.get("token0_amount")),
        "token1_amount": _optional_raw(row.get("token1_amount")),
    }


def _table_schema(name: str, pa):
    if name == "swaps":
        return _swap_schema(pa), _normalize_swap_row
    if name == "transfers":
        return _transfer_schema(pa), _normalize_transfer_row
    if name == "liquidity_events":
        return _liquidity_schema(pa), _normalize_liquidity_row
    if name == "holdings":
        return _holdings_schema(pa), _normalize_holdings_row
    if name == "positions":
        return _positions_schema(pa), _normalize_position_row
    raise ArtifactSchemaError(
        "Parquet schema for table {!r} is not implemented yet".format(name)
    )


def _write_parquet(
    name: str,
    rows: list[dict[str, Any]],
    output_dir: str | Path,
) -> Path:
    pa, pq = _pyarrow_modules()
    schema, normalizer = _table_schema(name, pa)
    normalized = [normalizer(row) for row in rows]
    table = pa.Table.from_pylist(normalized, schema=schema)

    path = _parquet_path(name, output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, tmp, compression="zstd")
    tmp.replace(path)
    return path


def write_table(
    name: str,
    rows: Iterable[dict[str, Any]],
    output_dir: str | Path,
    artifact_format: str = "json",
) -> dict[str, Any]:
    """Write one logical table and return paths/row count metadata.

    JSON uses the legacy ``output/<name>.json`` location. Parquet uses
    ``output/tables/<name>.parquet``. Materializing ``rows`` once ensures a
    dual-write starts from exactly the same logical input.
    """
    mode = validate_artifact_environment(artifact_format)
    materialized = list(rows)
    result: dict[str, Any] = {
        "name": name,
        "format": mode,
        "rows": len(materialized),
        "paths": {},
    }
    if mode in ("json", "both"):
        json_path = _json_path(name, output_dir)
        _atomic_json(json_path, materialized)
        result["paths"]["json"] = str(json_path)
    if mode in ("parquet", "both"):
        parquet_path = _write_parquet(name, materialized, output_dir)
        result["paths"]["parquet"] = str(parquet_path)
    return result


def read_table(
    name: str,
    output_dir: str | Path,
    *,
    columns: Optional[list[str]] = None,
    filters: Any = None,
    prefer: str = "parquet",
    legacy_rows: bool = False,
) -> list[dict[str, Any]]:
    """Read a table, preferring Parquet and falling back to legacy JSON.

    ``legacy_rows=True`` converts typed Parquet timestamps back to Unix seconds
    for existing analysis functions during the incremental migration.
    """
    preference = str(prefer or "parquet").lower()
    if preference not in ("parquet", "json"):
        raise ValueError("prefer must be 'parquet' or 'json'")

    parquet_path = _parquet_path(name, output_dir)
    json_path = _json_path(name, output_dir)
    order = (
        (("parquet", parquet_path), ("json", json_path))
        if preference == "parquet"
        else (("json", json_path), ("parquet", parquet_path))
    )
    for backend, path in order:
        if not path.exists():
            continue
        if backend == "json":
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)
            if name == "holdings" and isinstance(rows, dict):
                rows = rows.get("holdings") or []
            if not isinstance(rows, list):
                raise ArtifactSchemaError(
                    "JSON artifact {!r} does not contain a row list".format(name)
                )
            if columns is not None:
                rows = [{key: row.get(key) for key in columns} for row in rows]
            return rows
        _pa, pq = _pyarrow_modules()
        rows = pq.read_table(path, columns=columns, filters=filters).to_pylist()
        if legacy_rows:
            for row in rows:
                for key in ("block_timestamp", "query_timestamp"):
                    timestamp = row.get(key)
                    if isinstance(timestamp, datetime):
                        row[key] = int(timestamp.timestamp())
        return rows
    raise FileNotFoundError(
        "No artifact found for table {!r} under {}".format(name, output_dir)
    )


def query_tables(
    sql: str,
    output_dir: str | Path,
    *,
    table_names: Optional[list[str]] = None,
    params: Optional[list[Any] | tuple[Any, ...]] = None,
) -> list[dict[str, Any]]:
    """Query local Parquet tables with an in-memory DuckDB connection.

    Each discovered table is registered as a view using its artifact name.
    No persistent DuckDB database is created.
    """
    duckdb = _duckdb_module()
    root = Path(output_dir)
    names = table_names or sorted(
        path.stem for path in (root / "tables").glob("*.parquet")
    )
    con = duckdb.connect(database=":memory:")
    try:
        for name in names:
            if not name.replace("_", "").isalnum():
                raise ArtifactError("unsafe table name {!r}".format(name))
            path = _parquet_path(name, root)
            if not path.exists():
                raise FileNotFoundError(path)
            escaped = str(path.resolve()).replace("'", "''")
            con.execute(
                'CREATE VIEW "{}" AS SELECT * FROM read_parquet(\'{}\')'.format(
                    name, escaped
                )
            )
        cursor = con.execute(sql, list(params or []))
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        con.close()
