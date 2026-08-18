#!/usr/bin/env python3
"""Exploratory correlation and lead/lag analysis for analysis_series.parquet.

This intentionally reads the research feature contract instead of rebuilding
TVL from events. Positive lag means X[t] is compared with Y[t + lag], so X is
treated as leading Y by that many buckets. Results remain exploratory: a short
series and lag search do not establish causality.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.artifacts import read_table


DEFAULT_FEATURES = (
    "price_return",
    "tvl_change",
    "log1p_volume_token",
)


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _timestamp(value: Any) -> int:
    if isinstance(value, datetime):
        return int(value.timestamp())
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _feature(row: dict[str, Any], name: str) -> Optional[float]:
    if name.startswith("log1p_"):
        raw = _number(row.get(name[len("log1p_"):]))
        return math.log1p(raw) if raw is not None and raw >= 0 else None
    return _number(row.get(name))


def pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    x_var = sum((x - x_mean) ** 2 for x in xs)
    y_var = sum((y - y_mean) ** 2 for y in ys)
    denominator = math.sqrt(x_var * y_var)
    return numerator / denominator if denominator else None


def _ranks(values: list[float]) -> list[float]:
    """Average ranks for ties, using 1-based ranks."""
    order = sorted(range(len(values)), key=lambda idx: values[idx])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[order[position]] = rank
        start = end
    return ranks


def spearman(xs: list[float], ys: list[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    return pearson(_ranks(xs), _ranks(ys))


def _aligned(
    rows: list[dict[str, Any]], x_name: str, y_name: str, lag: int
) -> tuple[list[float], list[float]]:
    if lag >= 0:
        pairs = zip(rows[: len(rows) - lag or None], rows[lag:])
    else:
        pairs = zip(rows[-lag:], rows[: len(rows) + lag])
    xs: list[float] = []
    ys: list[float] = []
    for x_row, y_row in pairs:
        x = _feature(x_row, x_name)
        y = _feature(y_row, y_name)
        if x is None or y is None:
            continue
        xs.append(x)
        ys.append(y)
    return xs, ys


def analyze(
    rows: list[dict[str, Any]],
    features: tuple[str, ...],
    max_lag: int,
    min_pairs: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    correlations: list[dict[str, Any]] = []
    lead_lag: list[dict[str, Any]] = []
    methods: tuple[tuple[str, Callable[[list[float], list[float]], Optional[float]]], ...] = (
        ("pearson", pearson),
        ("spearman", spearman),
    )
    for i, x_name in enumerate(features):
        for y_name in features[i + 1:]:
            xs, ys = _aligned(rows, x_name, y_name, 0)
            for method_name, method in methods:
                value = method(xs, ys) if len(xs) >= min_pairs else None
                correlations.append({
                    "x": x_name,
                    "y": y_name,
                    "method": method_name,
                    "lag": 0,
                    "correlation": value,
                    "n": len(xs),
                })

                candidates: list[dict[str, Any]] = []
                for lag in range(-max_lag, max_lag + 1):
                    lag_xs, lag_ys = _aligned(rows, x_name, y_name, lag)
                    corr = method(lag_xs, lag_ys) if len(lag_xs) >= min_pairs else None
                    if corr is not None:
                        candidates.append({
                            "x": x_name,
                            "y": y_name,
                            "method": method_name,
                            "lag": lag,
                            "correlation": corr,
                            "n": len(lag_xs),
                        })
                if candidates:
                    best = max(candidates, key=lambda item: abs(item["correlation"]))
                    zero = next((item for item in candidates if item["lag"] == 0), None)
                    best["zero_lag_correlation"] = (
                        zero["correlation"] if zero else None
                    )
                    best["absolute_improvement"] = (
                        abs(best["correlation"]) - abs(zero["correlation"])
                        if zero else None
                    )
                    lead_lag.append(best)
    return correlations, lead_lag


def _format(value: Any) -> str:
    return "—" if value is None else "{:.4f}".format(float(value))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Correlation/lead-lag analysis from analysis_series.parquet"
    )
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--scope", choices=("pool", "token_total"), default="pool")
    parser.add_argument("--pool", default="", help="Required for --scope pool")
    parser.add_argument("--max-lag", type=int, default=6)
    parser.add_argument("--min-pairs", type=int, default=8)
    parser.add_argument(
        "--features", default=",".join(DEFAULT_FEATURES),
        help="Comma-separated analysis_series fields; log1p_<field> is supported",
    )
    parser.add_argument("--out-dir", default="output/research-correlation")
    args = parser.parse_args()

    if args.scope == "pool" and not args.pool:
        parser.error("--pool is required when --scope pool")
    if args.max_lag < 0:
        parser.error("--max-lag must be non-negative")
    if args.min_pairs < 3:
        parser.error("--min-pairs must be at least 3")

    source = Path(args.output_dir)
    rows = read_table("analysis_series", source, prefer="parquet", legacy_rows=False)
    pool = args.pool.lower()
    selected = [
        row for row in rows
        if row.get("scope") == args.scope
        and (args.scope != "pool" or str(row.get("pool_identifier") or "").lower() == pool)
    ]
    selected.sort(key=lambda row: _timestamp(row.get("bucket_start")))
    if not selected:
        parser.error("no analysis-series rows matched the requested scope/pool")

    bucket_seconds = int(selected[0].get("bucket_seconds") or 0)
    for previous, current in zip(selected, selected[1:]):
        gap = _timestamp(current.get("bucket_start")) - _timestamp(
            previous.get("bucket_start")
        )
        if bucket_seconds and gap != bucket_seconds:
            parser.error("selected rows are not a contiguous fixed-bucket series")

    features = tuple(item.strip() for item in args.features.split(",") if item.strip())
    correlations, lead_lag = analyze(
        selected, features, args.max_lag, args.min_pairs
    )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "correlations.csv", correlations)
    _write_csv(out / "lead_lag.csv", lead_lag)

    strongest_zero = sorted(
        (row for row in correlations if row["correlation"] is not None),
        key=lambda row: -abs(row["correlation"]),
    )[:10]
    strongest_lag = sorted(
        lead_lag, key=lambda row: -abs(row["correlation"])
    )[:10]
    scope_label = pool if args.scope == "pool" else "token_total"
    warning = (
        "Only {} buckets are available; treat every coefficient as exploratory, not as a formal finding."
        .format(len(selected))
        if len(selected) < 30 else
        "Correlation and lag selection remain exploratory and do not establish causality."
    )
    markdown = [
        "# Time-series Correlation — Exploratory",
        "",
        "- Scope: `{}`".format(scope_label),
        "- Buckets: `{}`".format(len(selected)),
        "- Bucket seconds: `{}`".format(bucket_seconds),
        "- Lag convention: positive lag means X leads Y.",
        "- Warning: {}".format(warning),
        "",
        "## Strongest contemporaneous correlations",
        "",
        "| X | Y | Method | Correlation | N |",
        "|---|---|---|---:|---:|",
    ]
    markdown.extend(
        "| {x} | {y} | {method} | {corr} | {n} |".format(
            x=row["x"], y=row["y"], method=row["method"],
            corr=_format(row["correlation"]), n=row["n"],
        )
        for row in strongest_zero
    )
    markdown.extend([
        "",
        "## Strongest lag-selected correlations",
        "",
        "| X | Y | Method | Lag | Best | Lag 0 | Improvement | N |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ])
    markdown.extend(
        "| {x} | {y} | {method} | {lag} | {best} | {zero} | {improvement} | {n} |".format(
            x=row["x"], y=row["y"], method=row["method"], lag=row["lag"],
            best=_format(row["correlation"]), zero=_format(row.get("zero_lag_correlation")),
            improvement=_format(row.get("absolute_improvement")), n=row["n"],
        )
        for row in strongest_lag
    )
    (out / "summary.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    (out / "results.json").write_text(json.dumps({
        "scope": args.scope,
        "pool": pool or None,
        "bucket_count": len(selected),
        "bucket_seconds": bucket_seconds,
        "features": features,
        "max_lag": args.max_lag,
        "min_pairs": args.min_pairs,
        "correlations": correlations,
        "lead_lag": lead_lag,
        "warning": warning,
    }, indent=2), encoding="utf-8")
    print("Analyzed {} buckets for {}".format(len(selected), scope_label))
    print("Saved:", out / "summary.md")
    print("Saved:", out / "correlations.csv")
    print("Saved:", out / "lead_lag.csv")


if __name__ == "__main__":
    main()
