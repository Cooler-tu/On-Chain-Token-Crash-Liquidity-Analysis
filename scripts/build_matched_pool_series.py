#!/usr/bin/env python3
"""Build an RPC-only research series for one already verified direct pool."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from src.analysis.metrics import (
    build_tvl_timeline_rpc_snapshots,
    calculate_price_timeline_from_swaps,
)
from src.analysis.series import (
    build_analysis_series,
    write_analysis_series_human_outputs,
)
from src.client import get_web3
from src.data.artifacts import write_summary, write_table
from src.indexer.indexer import index_events
from src.models import VerifiedPool, to_dict


def _load_json(path: Path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a matched-pool analysis_series using historical RPC"
    )
    parser.add_argument("--source-output", default="output")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--pool", required=True)
    parser.add_argument("--from-block", type=int, required=True)
    parser.add_argument("--to-block", type=int, required=True)
    parser.add_argument("--bucket-seconds", type=int, default=3600)
    parser.add_argument("--rpc-url", default="")
    args = parser.parse_args()

    if args.from_block <= 0 or args.to_block < args.from_block:
        parser.error("invalid block window")
    if args.bucket_seconds <= 0:
        parser.error("--bucket-seconds must be positive")

    source = Path(args.source_output)
    destination = Path(args.output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    profile = _load_json(source / "token_profile.json")
    candidates = [
        VerifiedPool(**row) for row in _load_json(source / "verified_pools.json")
    ]
    pool_address = args.pool.lower()
    pool = next(
        (
            candidate for candidate in candidates
            if candidate.verified
            and candidate.pool_address.lower() == pool_address
        ),
        None,
    )
    if pool is None:
        parser.error("requested pool is not present as a verified pool")
    if pool.version not in {"v2", "v3"}:
        parser.error("RPC matched-pool builder currently supports direct V2/V3 pools")

    # PositionManager streams are not needed for pool price/reserve research.
    pool = replace(pool, position_manager_address=None)
    token_address = str(profile.get("address") or "")
    token_decimals = int(profile.get("decimals") or 18)
    rpc_url = args.rpc_url or os.environ.get("ETH_RPC_URL") or os.environ.get("RPC_URL")
    w3 = get_web3(rpc_url)

    write_summary("token_profile", profile, destination)
    write_summary("verified_pools", [to_dict(pool)], destination)
    indexed = index_events(
        w3,
        [pool],
        token_address,
        args.from_block,
        args.to_block,
        output_dir=destination,
        index_token_transfer=False,
        source="rpc",
        artifact_format="both",
        pool_event_types={"SWAP"},
    )
    swaps = indexed.get("swaps") or []
    liquidity = indexed.get("liquidity_events") or []
    if not swaps:
        raise RuntimeError("RPC indexing returned no swaps for the selected pool/window")

    prices = calculate_price_timeline_from_swaps(
        swaps,
        [pool],
        token_address,
        token_decimals,
        bucket_seconds=args.bucket_seconds,
    )
    if not prices:
        raise RuntimeError(
            "Swaps were indexed but no price could be derived from the quote token"
        )
    tvl = build_tvl_timeline_rpc_snapshots(
        w3,
        [pool],
        token_address,
        token_decimals,
        args.from_block,
        args.to_block,
        chart_span="week",
        bucket_seconds=args.bucket_seconds,
        price_rows=prices,
        reference_events=list(swaps) + list(liquidity),
    )
    if not tvl:
        raise RuntimeError("historical RPC returned no reserve snapshots")
    tvl_artifact = write_table(
        "tvl_timeline", tvl, destination, artifact_format="both"
    )

    rows = build_analysis_series(
        swaps,
        liquidity,
        tvl,
        [pool],
        token_address,
        token_decimals,
        token_symbol=str(profile.get("symbol") or ""),
        chain_id=int(profile.get("chain_id") or 1),
        bucket_seconds=args.bucket_seconds,
        tvl_source="rpc_target_balance_local_quote_price",
    )
    series_artifact = write_table(
        "analysis_series", rows, destination, artifact_format="parquet"
    )
    human = write_analysis_series_human_outputs(
        rows,
        destination,
        liquidity_event_coverage="not_collected_in_swaps_only_run",
    )
    series_artifact["paths"].update(human)
    units = sorted({
        str(row.get("price_unit") or "")
        for row in rows
        if row.get("price_unit")
    })
    run = {
        "mode": "matched_pool_rpc",
        "token": token_address,
        "pool": pool.pool_address,
        "from_block": args.from_block,
        "to_block": args.to_block,
        "bucket_seconds": args.bucket_seconds,
        "swaps": len(swaps),
        "liquidity_events": len(liquidity),
        "liquidity_event_coverage": "not_collected_in_swaps_only_run",
        "tvl_rows": len(tvl),
        "analysis_series_rows": len(rows),
        "price_units": units,
        "tvl_source": "rpc_target_balance_local_quote_price",
        "artifacts": {
            "tvl_timeline": tvl_artifact,
            "analysis_series": series_artifact,
        },
        "interpretation": (
            "Price is the pool quote-token execution price, not USD. "
            "TVL is target-token-side attributable reserve, not full two-sided TVL."
        ),
    }
    write_summary("research_run", run, destination)
    print(json.dumps(run, indent=2))


if __name__ == "__main__":
    main()
