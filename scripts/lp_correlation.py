#!/usr/bin/env python3
"""LP correlation and lead-lag prototype.

Builds hourly series for TVL, swap volume, LP activity, and holder activity,
then computes Pearson correlations and finds the time shift (lead/lag) that
maximizes correlation between series.

Usage:
    python3 scripts/lp_correlation.py --output-dir output \
        --out-dir output-lp-correlation-demo
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.artifacts import (
    ArtifactError,
    inflate_volume_timeline,
    read_table,
)


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _read_rows(out: Path, name: str, fallback: list[dict]) -> list[dict]:
    parquet_path = out / "tables" / "{}.parquet".format(name)
    if not parquet_path.exists():
        return list(fallback or [])
    try:
        return read_table(name, out, prefer="parquet", legacy_rows=True)
    except (ArtifactError, FileNotFoundError, ImportError, OSError, ValueError):
        return list(fallback or [])


def _load_analysis_inputs(
    out: Path,
) -> tuple[dict[str, Any], list[dict], list[dict]]:
    """Load correlation inputs from Parquet with legacy JSON fallback."""
    metrics = dict(_load_json(out / "metrics.json", {}) or {})
    tvl_fallback = metrics.get("tvl_timeline") or _load_json(
        out / "tvl_timeline.json", []
    )
    metrics["tvl_timeline"] = _read_rows(
        out, "tvl_timeline", tvl_fallback
    )

    volume_summary = dict(metrics.get("volume") or {})
    volume_document = _load_json(out / "volume_timeline.json", {}) or {}
    volume_rows = _read_rows(out, "volume_timeline", [])
    if volume_rows:
        volume_summary = inflate_volume_timeline(volume_rows, volume_summary)
    elif not volume_summary.get("volume_timeline"):
        volume_summary["volume_timeline"] = volume_document.get(
            "volume_timeline", []
        )
    metrics["volume"] = volume_summary

    liquidity_fallback = _load_json(out / "liquidity_events.json", []) or []
    transfer_fallback = _load_json(out / "transfers.json", []) or []
    liquidity_events = _read_rows(
        out, "liquidity_events", liquidity_fallback
    )
    transfers = _read_rows(out, "transfers", transfer_fallback)
    return metrics, liquidity_events, transfers


def _bucket(ts: int, bucket_seconds: int) -> int:
    return (int(ts or 0) // bucket_seconds) * bucket_seconds if ts else 0


def pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 3 or len(y) != n:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    num = 0.0
    dx = 0.0
    dy = 0.0
    for xi, yi in zip(x, y):
        xd = xi - mx
        yd = yi - my
        num += xd * yd
        dx += xd * xd
        dy += yd * yd
    denom = math.sqrt(dx * dy)
    if denom == 0.0:
        return 0.0
    return round(num / denom, 6)


def _to_series(values: dict[int, float], buckets: list[int]) -> list[float]:
    return [float(values.get(b, 0.0)) for b in buckets]


def build_series(
    metrics: dict,
    liquidity_events: list[dict],
    transfers: list[dict],
    token_decimals: int,
    bucket_seconds: int,
) -> tuple[list[int], dict[str, list[float]]]:
    timeline = metrics.get("tvl_timeline", []) or []
    volume_timeline = (metrics.get("volume") or {}).get("volume_timeline", []) or []
    scale = 10 ** max(0, int(token_decimals or 18))

    min_ts = max_ts = 0
    for t in timeline:
        ts = int(t.get("block_timestamp") or 0)
        if ts:
            min_ts = min(min_ts, ts) if min_ts else ts
            max_ts = max(max_ts, ts)
    for evt in liquidity_events:
        ts = int(evt.get("block_timestamp") or 0)
        if ts:
            min_ts = min(min_ts, ts) if min_ts else ts
            max_ts = max(max_ts, ts)
    for evt in transfers:
        ts = int(evt.get("block_timestamp") or 0)
        if ts:
            min_ts = min(min_ts, ts) if min_ts else ts
            max_ts = max(max_ts, ts)
    if min_ts == max_ts == 0:
        return [], {}

    buckets = list(range(
        _bucket(min_ts, bucket_seconds),
        _bucket(max_ts, bucket_seconds) + bucket_seconds,
        bucket_seconds,
    ))

    tvl = defaultdict(float)
    for t in timeline:
        try:
            raw = float(t.get("tvl_in_token", t.get("tvl", 0)) or 0) / scale
        except (TypeError, ValueError):
            raw = 0.0
        tvl[_bucket(t.get("block_timestamp", 0), bucket_seconds)] += raw

    volume = defaultdict(float)
    for bucket in volume_timeline:
        volume[int(bucket.get("bucket_ts") or 0)] += float(
            bucket.get("total_volume_in_token", 0) or 0
        )

    lp_active: dict[int, set[str]] = defaultdict(set)
    lp_events = defaultdict(int)
    for evt in liquidity_events:
        if evt.get("event_type") not in ("LIQUIDITY_ADD", "LIQUIDITY_REMOVE"):
            continue
        b = _bucket(evt.get("block_timestamp", 0), bucket_seconds)
        lp_events[b] += 1
        actor = (evt.get("actor") or evt.get("recipient") or "").lower()
        if actor:
            lp_active[b].add(actor)

    holders = defaultdict(set)
    for evt in transfers:
        b = _bucket(evt.get("block_timestamp", 0), bucket_seconds)
        for key in ("actor", "recipient"):
            addr = (evt.get(key) or "").lower()
            if addr:
                holders[b].add(addr)

    series = {
        "tvl_in_token": _to_series(tvl, buckets),
        "volume_in_token": _to_series(volume, buckets),
        "active_lp_count": [float(len(lp_active.get(b, set()))) for b in buckets],
        "lp_event_count": _to_series(lp_events, buckets),
        "holder_count": [float(len(holders.get(b, set()))) for b in buckets],
    }
    return buckets, series


def correlation_matrix(series: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    names = sorted(series)
    out = {}
    for a in names:
        out[a] = {}
        for b in names:
            out[a][b] = pearson(series[a], series[b]) if a != b else 1.0
    return out


def lead_lag(
    series: dict[str, list[float]],
    max_lag: int,
) -> list[dict[str, Any]]:
    names = sorted(series)
    results = []
    for a in names:
        for b in names:
            if a == b:
                continue
            best = {"lag": 0, "correlation": 0.0, "n": 0}
            n = len(series[a])
            for lag in range(-max_lag, max_lag + 1):
                if lag >= 0:
                    # X[t] vs Y[t+lag]: X leads Y by lag buckets.
                    xs = series[a][: n - lag]
                    ys = series[b][lag:]
                else:
                    # X[t] vs Y[t+lag] with negative lag: X trails Y.
                    xs = series[a][-lag:]
                    ys = series[b][: n + lag]
                if len(xs) < 3:
                    continue
                corr = pearson(xs, ys)
                if abs(corr) > abs(best["correlation"]):
                    best = {
                        "lag": lag,
                        "correlation": corr,
                        "n": len(xs),
                    }
            results.append({
                "x": a,
                "y": b,
                **best,
                "note": (
                    "positive lag means X is shifted later (X leads Y); "
                    "negative lag means X trails Y"
                ),
            })
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="LP correlation prototype")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--out-dir", default="output-lp-correlation-demo")
    parser.add_argument("--bucket-seconds", type=int, default=3600)
    parser.add_argument("--max-lag", type=int, default=6)
    args = parser.parse_args()

    out = Path(args.output_dir)
    metrics, liquidity_events, transfers = _load_analysis_inputs(out)
    profile = _load_json(out / "token_profile.json", {})

    buckets, series = build_series(
        metrics,
        liquidity_events,
        transfers,
        int(profile.get("decimals", 18) or 18),
        args.bucket_seconds,
    )
    if not buckets:
        print("No timestamped events to correlate.")
        return

    matrix = correlation_matrix(series)
    lags = lead_lag(series, args.max_lag)
    result = {
        "bucket_seconds": args.bucket_seconds,
        "max_lag": args.max_lag,
        "buckets": buckets,
        "series": series,
        "correlation_matrix": matrix,
        "lead_lag": lags,
        "caveat": (
            "Correlation and lead/lag are exploratory signals only. "
            "They do not prove causation; combine with Mint/Burn/Collect events."
        ),
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "lp_correlation.json", "w") as f:
        json.dump(result, f, indent=2, default=str)

    print("Buckets: {} - {}".format(buckets[0], buckets[-1]))
    print("Series lengths: {}".format({k: len(v) for k, v in series.items()}))
    print("Correlation matrix:")
    names = sorted(series)
    print("{:<18}".format("") + "".join("{:>18}".format(n) for n in names))
    for a in names:
        print(
            "{:<18}".format(a)
            + "".join("{:>18.4f}".format(matrix[a][b]) for b in names)
        )
    print("Top lead-lag pairs:")
    for row in sorted(lags, key=lambda r: -abs(r["correlation"]))[:8]:
        print(
            "  {} vs {} lag={} corr={} n={}".format(
                row["x"], row["y"], row["lag"], row["correlation"], row["n"]
            )
        )
    print("Saved:", out_dir / "lp_correlation.json")


if __name__ == "__main__":
    main()
