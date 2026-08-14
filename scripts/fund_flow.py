#!/usr/bin/env python3
"""Fund flow graph prototype.

Aggregates ERC-20 Transfer events into (from, to) edges and writes
``fund_flow.json`` plus a top-edges summary.  Node types are inferred from
the canonical holdings artifact (pool / EOA / contract) and can be extended
with CEX labels. Parquet is preferred; legacy JSON remains supported.

Usage:
    python3 scripts/fund_flow.py --output-dir output \
        --out-dir output-fund-flow-demo
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data.artifacts import ArtifactError, read_table  # noqa: E402


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _read_artifact_rows(out: Path, name: str) -> list[dict[str, Any]]:
    try:
        return read_table(name, out, prefer="parquet", legacy_rows=True)
    except (ArtifactError, FileNotFoundError, ImportError, OSError, ValueError):
        try:
            return read_table(name, out, prefer="json", legacy_rows=True)
        except (ArtifactError, FileNotFoundError, ImportError, OSError, ValueError):
            return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Fund flow prototype")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--out-dir", default="output-fund-flow-demo")
    parser.add_argument("--top-edges", type=int, default=20)
    args = parser.parse_args()

    out = Path(args.output_dir)
    transfers = _read_artifact_rows(out, "transfers")
    holdings = _read_artifact_rows(out, "holdings")
    profile = _load_json(out / "token_profile.json", {})
    scale = 10 ** max(0, int(profile.get("decimals", 18) or 18))

    node_types: dict[str, str] = {}
    for row in holdings:
        addr = str(row.get("address") or "").lower()
        if not addr:
            continue
        if row.get("is_pool"):
            node_types[addr] = "pool"
        elif row.get("address_type") == "contract":
            node_types[addr] = "contract"
        else:
            node_types.setdefault(addr, "eoa")

    edges: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "amount": 0.0,
            "tx_count": 0,
            "first_block": 0,
            "last_block": 0,
        }
    )
    for evt in transfers:
        fr = (evt.get("actor") or "").lower()
        to = (evt.get("recipient") or "").lower()
        if not fr or not to:
            continue
        try:
            amount = abs(int(evt.get("token0_amount", "0") or "0")) / scale
        except (TypeError, ValueError):
            amount = 0.0
        if amount <= 0:
            continue
        key = (fr, to)
        e = edges[key]
        e["amount"] += amount
        e["tx_count"] += 1
        bn = int(evt.get("block_number") or 0)
        e["first_block"] = min(e["first_block"], bn) if e["first_block"] else bn
        e["last_block"] = max(e["last_block"], bn)

    edge_rows = []
    for (fr, to), e in edges.items():
        edge_rows.append({
            "from": fr,
            "to": to,
            "from_type": node_types.get(fr, "unknown"),
            "to_type": node_types.get(to, "unknown"),
            **e,
        })
    edge_rows.sort(key=lambda r: -r["amount"])

    result = {
        "token": profile.get("address", ""),
        "symbol": profile.get("symbol", "TOKEN"),
        "node_count": len(set(node_types) | {fr for fr, _ in edges} | {to for _, to in edges}),
        "edge_count": len(edge_rows),
        "total_flow_in_token": round(sum(r["amount"] for r in edge_rows), 6),
        "edges": edge_rows,
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "fund_flow.json", "w") as f:
        json.dump(result, f, indent=2, default=str)

    print("Nodes:", result["node_count"], "Edges:", result["edge_count"])
    print("Top edges:")
    for r in edge_rows[: args.top_edges]:
        print(
            "  {} ({}) -> {} ({})  amount={:.4f} tx={}".format(
                r["from"][:10],
                r["from_type"],
                r["to"][:10],
                r["to_type"],
                r["amount"],
                r["tx_count"],
            )
        )
    print("Saved:", out_dir / "fund_flow.json")


if __name__ == "__main__":
    main()
