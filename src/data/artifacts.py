"""Typed artifact storage for large tables and small JSON summaries.

Phase 1 keeps legacy JSON as the default and supports JSON/Parquet dual-write
for the swaps table. Imports for optional analytical dependencies are lazy so
existing JSON-only runs continue to work without PyArrow or DuckDB installed.
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


def _swap_schema(pa):
    metadata = {
        b"artifact_name": b"swaps",
        b"schema_version": b"1.0.0",
        b"raw_amount_encoding": b"base10-string",
        b"address_encoding": b"lowercase-hex",
    }
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
        metadata=metadata,
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


def _table_schema(name: str, pa):
    if name == "swaps":
        return _swap_schema(pa), _normalize_swap_row
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
            if columns is not None:
                rows = [{key: row.get(key) for key in columns} for row in rows]
            return rows
        _pa, pq = _pyarrow_modules()
        rows = pq.read_table(path, columns=columns, filters=filters).to_pylist()
        if legacy_rows:
            for row in rows:
                timestamp = row.get("block_timestamp")
                if isinstance(timestamp, datetime):
                    row["block_timestamp"] = int(timestamp.timestamp())
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
