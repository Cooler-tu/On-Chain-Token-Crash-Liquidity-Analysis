"""Wallet clustering prototype — edge signals + confidence + random baseline.

Edge-forming signals (from design / uPEG demo):
  - reciprocal_transfer
  - repeated_transfer          (same direction, count >= 3, similar amounts)
  - same_gas_payer
  - same_owner_contract        (RPC owner map; reserved if empty)

Supporting only (never forms an edge alone):
  - same_tx_cooccurrence

Dune fetch contract (see queries.sql):
  1. cluster_transfers   — one pull
  2. cluster_gas_payers  — one pull for distinct tx hashes
  owner() stays on RPC; no traces / no dex.trades for clustering.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional


# --- signal policy -----------------------------------------------------------

EDGE_SIGNALS = frozenset({
    "reciprocal_transfer",
    "repeated_transfer",
    "same_gas_payer",
    "same_owner_contract",
})
SUPPORT_SIGNALS = frozenset({"same_tx_cooccurrence"})

CLUSTER_TRANSFER_COLUMNS = (
    "from_address",
    "to_address",
    "amount_raw",
    "tx_hash",
    "block_time",
)
CLUSTER_GAS_COLUMNS = ("tx_hash", "gas_payer")

REPEATED_MIN_COUNT = 3
AMOUNT_SIM_TOL = 0.25  # relative deviation from mean
SAME_TX_SUPPORT_MIN = 3


@dataclass
class EdgeEvidence:
    a: str
    b: str
    signals: list[str] = field(default_factory=list)
    support: list[str] = field(default_factory=list)
    reason: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def pair(self) -> tuple[str, str]:
        return (self.a, self.b) if self.a < self.b else (self.b, self.a)


@dataclass
class Cluster:
    cluster_id: str
    addresses: list[str]
    confidence: float
    confidence_level: str
    signals: list[dict[str, str]]
    reason: str


def _norm(addr: Any) -> str:
    s = str(addr or "").strip().lower()
    if s.startswith("\\x"):
        s = "0x" + s[2:]
    if s and not s.startswith("0x"):
        s = "0x" + s
    return s


def _amt(raw: Any) -> float:
    try:
        return float(int(raw))
    except (TypeError, ValueError):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0


def amounts_similar(values: Iterable[float], tol: float = AMOUNT_SIM_TOL) -> bool:
    vals = [v for v in values if v > 0]
    if len(vals) < 2:
        return len(vals) == 1
    mean = sum(vals) / len(vals)
    if mean <= 0:
        return False
    return all(abs(v - mean) / mean <= tol for v in vals)


def means_similar(a: float, b: float, tol: float = AMOUNT_SIM_TOL) -> bool:
    if a <= 0 or b <= 0:
        return False
    m = max(a, b)
    return abs(a - b) / m <= tol


# --- union-find --------------------------------------------------------------

class _UF:
    def __init__(self) -> None:
        self.p: dict[str, str] = {}

    def add(self, x: str) -> None:
        self.p.setdefault(x, x)

    def find(self, x: str) -> str:
        self.add(x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


# --- signal extraction -------------------------------------------------------

def extract_transfer_edges(
    transfers: list[dict],
    *,
    repeated_min: int = REPEATED_MIN_COUNT,
    amount_tol: float = AMOUNT_SIM_TOL,
) -> dict[tuple[str, str], EdgeEvidence]:
    """Build edge-forming evidence from ``cluster_transfers`` rows only."""
    directed: dict[tuple[str, str], list[float]] = defaultdict(list)
    pair_txs: dict[tuple[str, str], set[str]] = defaultdict(set)

    for row in transfers or []:
        fr = _norm(row.get("from_address") or row.get("from") or row.get("actor"))
        to = _norm(row.get("to_address") or row.get("to") or row.get("recipient"))
        if not fr or not to or fr == to:
            continue
        amt = _amt(row.get("amount_raw") or row.get("value") or 0)
        if amt <= 0:
            continue
        directed[(fr, to)].append(amt)
        und = (fr, to) if fr < to else (to, fr)
        tx = _norm(row.get("tx_hash") or row.get("transaction_hash"))
        if tx:
            pair_txs[und].add(tx)

    edges: dict[tuple[str, str], EdgeEvidence] = {}

    def _edge(a: str, b: str) -> EdgeEvidence:
        key = (a, b) if a < b else (b, a)
        if key not in edges:
            edges[key] = EdgeEvidence(a=key[0], b=key[1])
        return edges[key]

    # reciprocal_transfer
    seen_rec: set[tuple[str, str]] = set()
    for (fr, to), amts_ab in directed.items():
        amts_ba = directed.get((to, fr))
        if not amts_ba:
            continue
        key = (fr, to) if fr < to else (to, fr)
        if key in seen_rec:
            continue
        seen_rec.add(key)
        mean_ab = sum(amts_ab) / len(amts_ab)
        mean_ba = sum(amts_ba) / len(amts_ba)
        if means_similar(mean_ab, mean_ba, amount_tol):
            e = _edge(fr, to)
            if "reciprocal_transfer" not in e.signals:
                e.signals.append("reciprocal_transfer")
            e.meta["reciprocal"] = {
                "ab_count": len(amts_ab),
                "ba_count": len(amts_ba),
                "ab_mean": mean_ab,
                "ba_mean": mean_ba,
            }

    # repeated_transfer (same direction ≥ N, similar amounts)
    for (fr, to), amts in directed.items():
        if len(amts) < repeated_min:
            continue
        if not amounts_similar(amts, amount_tol):
            continue
        e = _edge(fr, to)
        if "repeated_transfer" not in e.signals:
            e.signals.append("repeated_transfer")
        e.meta["repeated"] = {"direction": f"{fr}->{to}", "count": len(amts)}

    # same_tx_cooccurrence — supporting only
    for (a, b), txs in pair_txs.items():
        if len(txs) < SAME_TX_SUPPORT_MIN:
            continue
        e = _edge(a, b)
        if "same_tx_cooccurrence" not in e.support:
            e.support.append("same_tx_cooccurrence")
        e.meta["same_tx_count"] = len(txs)

    for e in edges.values():
        parts = []
        if "reciprocal_transfer" in e.signals:
            parts.append("bidirectional transfers with similar size")
        if "repeated_transfer" in e.signals:
            parts.append(f"≥{repeated_min} same-direction transfers, similar size")
        if e.support:
            parts.append("corroborated by repeated same-tx co-occurrence")
        e.reason = "; ".join(parts) if parts else "no edge-forming signal"

    # Drop pairs that only have support (no edge-forming signal)
    return {
        k: v for k, v in edges.items()
        if any(s in EDGE_SIGNALS for s in v.signals)
    }


def apply_gas_payer_edges(
    edges: dict[tuple[str, str], EdgeEvidence],
    transfers: list[dict],
    gas_by_tx: dict[str, str],
    candidates: set[str],
) -> dict[tuple[str, str], EdgeEvidence]:
    """Add same_gas_payer edges: gas payer ↔ other candidate in the same tx."""
    out = dict(edges)

    def _edge(a: str, b: str) -> EdgeEvidence:
        key = (a, b) if a < b else (b, a)
        if key not in out:
            out[key] = EdgeEvidence(a=key[0], b=key[1])
        return out[key]

    # tx → candidate addresses involved
    tx_addrs: dict[str, set[str]] = defaultdict(set)
    for row in transfers or []:
        tx = _norm(row.get("tx_hash") or row.get("transaction_hash"))
        if not tx:
            continue
        for key in ("from_address", "to_address", "from", "to", "actor", "recipient"):
            a = _norm(row.get(key))
            if a and a in candidates:
                tx_addrs[tx].add(a)

    for tx, addrs in tx_addrs.items():
        payer = _norm(gas_by_tx.get(tx))
        if not payer or payer not in candidates:
            continue
        for other in addrs:
            if other == payer:
                continue
            e = _edge(payer, other)
            if "same_gas_payer" not in e.signals:
                e.signals.append("same_gas_payer")
            e.meta.setdefault("gas_txs", [])
            if tx not in e.meta["gas_txs"]:
                e.meta["gas_txs"].append(tx)
            if not e.reason:
                e.reason = "shared gas payer across candidate addresses"
            elif "gas payer" not in e.reason:
                e.reason += "; shared gas payer"

    return {
        k: v for k, v in out.items()
        if any(s in EDGE_SIGNALS for s in v.signals)
    }


def apply_owner_edges(
    edges: dict[tuple[str, str], EdgeEvidence],
    owner_by_contract: dict[str, str],
    candidates: set[str],
) -> dict[tuple[str, str], EdgeEvidence]:
    """same_owner_contract: contracts sharing an owner EOA, or contract↔owner."""
    out = dict(edges)

    def _edge(a: str, b: str) -> EdgeEvidence:
        key = (a, b) if a < b else (b, a)
        if key not in out:
            out[key] = EdgeEvidence(a=key[0], b=key[1])
        return out[key]

    by_owner: dict[str, list[str]] = defaultdict(list)
    for contract, owner in (owner_by_contract or {}).items():
        c, o = _norm(contract), _norm(owner)
        if not c or not o or c not in candidates:
            continue
        by_owner[o].append(c)
        if o in candidates and o != c:
            e = _edge(c, o)
            if "same_owner_contract" not in e.signals:
                e.signals.append("same_owner_contract")
            e.reason = e.reason or "contract owner() resolves to candidate EOA"

    for owner, contracts in by_owner.items():
        uniq = sorted(set(contracts))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                e = _edge(uniq[i], uniq[j])
                if "same_owner_contract" not in e.signals:
                    e.signals.append("same_owner_contract")
                e.reason = e.reason or f"contracts share owner {owner}"

    return {
        k: v for k, v in out.items()
        if any(s in EDGE_SIGNALS for s in v.signals)
    }


def confidence_for(signals: list[str], support: list[str]) -> tuple[float, str]:
    score = 0.0
    weights = {
        "same_owner_contract": 0.45,
        "reciprocal_transfer": 0.30,
        "same_gas_payer": 0.20,
        "repeated_transfer": 0.15,
    }
    for s in signals:
        score += weights.get(s, 0.1)
    if "same_tx_cooccurrence" in support:
        score += 0.05
    score = min(0.99, score)
    if score >= 0.7:
        level = "high"
    elif score >= 0.4:
        level = "medium"
    else:
        level = "low"
    return score, level


def build_clusters(
    edges: dict[tuple[str, str], EdgeEvidence],
) -> list[Cluster]:
    uf = _UF()
    edge_signals: dict[tuple[str, str], EdgeEvidence] = {}
    for key, ev in edges.items():
        if not any(s in EDGE_SIGNALS for s in ev.signals):
            continue
        uf.union(ev.a, ev.b)
        edge_signals[key] = ev

    groups: dict[str, list[str]] = defaultdict(list)
    for node in list(uf.p):
        groups[uf.find(node)].append(node)

    clusters: list[Cluster] = []
    idx = 0
    for members in groups.values():
        members = sorted(set(members))
        if len(members) < 2:
            continue
        idx += 1
        sig_set: set[str] = set()
        support_set: set[str] = set()
        reasons: list[str] = []
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                key = (a, b) if a < b else (b, a)
                ev = edge_signals.get(key)
                if not ev:
                    continue
                sig_set.update(s for s in ev.signals if s in EDGE_SIGNALS)
                support_set.update(ev.support)
                if ev.reason:
                    reasons.append(ev.reason)
        conf, level = confidence_for(sorted(sig_set), sorted(support_set))
        clusters.append(Cluster(
            cluster_id=f"c-{idx:03d}",
            addresses=members,
            confidence=round(conf, 4),
            confidence_level=level,
            signals=[{"type": s, "strength": _strength(s)} for s in sorted(sig_set)],
            reason="; ".join(dict.fromkeys(reasons)) or "edge signals present",
        ))
    clusters.sort(key=lambda c: (-c.confidence, c.cluster_id))
    return clusters


def _strength(signal: str) -> str:
    return {
        "same_owner_contract": "strong",
        "reciprocal_transfer": "medium",
        "same_gas_payer": "medium",
        "repeated_transfer": "medium-weak",
    }.get(signal, "weak")


def random_baseline_same_tx(
    candidates: list[str],
    pair_tx_counts: dict[tuple[str, str], int],
    *,
    samples: int = 50_000,
    threshold: int = SAME_TX_SUPPORT_MIN,
    seed: int = 42,
) -> dict[str, Any]:
    """False-positive control: P(random pair has same_tx >= threshold)."""
    cand = sorted({_norm(c) for c in candidates if _norm(c)})
    if len(cand) < 2:
        return {"samples": 0, "hits": 0, "rate": 0.0, "edge_rate": 0.0, "lift": None}

    rng = random.Random(seed)
    hits = 0
    for _ in range(samples):
        a, b = rng.sample(cand, 2)
        key = (a, b) if a < b else (b, a)
        if pair_tx_counts.get(key, 0) >= threshold:
            hits += 1
    rate = hits / samples

    edge_keys = [k for k, n in pair_tx_counts.items() if n >= threshold]
    # Among clustered undirected pairs that exist in pair_tx_counts with an edge…
    # Caller should pass only clustered pairs for edge_rate; here we report raw.
    edge_rate = (
        sum(1 for k in edge_keys if k in pair_tx_counts) / max(1, len(edge_keys))
        if edge_keys else 0.0
    )
    # Better: edge_rate = fraction of provided clustered pairs meeting threshold
    lift = (edge_rate / rate) if rate > 0 else None
    return {
        "samples": samples,
        "hits": hits,
        "rate": rate,
        "threshold": threshold,
        "edge_rate": edge_rate,
        "lift": lift,
    }


def pair_tx_counts_from_transfers(transfers: list[dict]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in transfers or []:
        fr = _norm(row.get("from_address") or row.get("from") or row.get("actor"))
        to = _norm(row.get("to_address") or row.get("to") or row.get("recipient"))
        tx = _norm(row.get("tx_hash") or row.get("transaction_hash"))
        if not fr or not to or fr == to or not tx:
            continue
        key = (fr, to) if fr < to else (to, fr)
        counts[key].add(tx)
    return {k: len(v) for k, v in counts.items()}


def cluster_from_dune_rows(
    transfers: list[dict],
    gas_rows: list[dict] | None = None,
    owner_by_contract: dict[str, str] | None = None,
    candidates: Iterable[str] | None = None,
) -> dict[str, Any]:
    """End-to-end clustering from the two Dune pulls (+ optional RPC owners)."""
    cand = {_norm(c) for c in (candidates or []) if _norm(c)}
    if not cand:
        for row in transfers or []:
            for k in ("from_address", "to_address", "from", "to", "actor", "recipient"):
                a = _norm(row.get(k))
                if a:
                    cand.add(a)

    edges = extract_transfer_edges(transfers)
    gas_by_tx = {
        _norm(r.get("tx_hash")): _norm(r.get("gas_payer"))
        for r in (gas_rows or [])
        if _norm(r.get("tx_hash")) and _norm(r.get("gas_payer"))
    }
    if gas_by_tx:
        edges = apply_gas_payer_edges(edges, transfers, gas_by_tx, cand)
    if owner_by_contract:
        edges = apply_owner_edges(edges, owner_by_contract, cand)

    clusters = build_clusters(edges)
    tx_counts = pair_tx_counts_from_transfers(transfers)
    clustered_pairs = set()
    for c in clusters:
        addrs = c.addresses
        for i in range(len(addrs)):
            for j in range(i + 1, len(addrs)):
                a, b = addrs[i], addrs[j]
                clustered_pairs.add((a, b) if a < b else (b, a))

    base = random_baseline_same_tx(list(cand), tx_counts)
    if clustered_pairs:
        edge_hits = sum(
            1 for p in clustered_pairs if tx_counts.get(p, 0) >= SAME_TX_SUPPORT_MIN
        )
        edge_rate = edge_hits / len(clustered_pairs)
        base["edge_rate"] = edge_rate
        base["lift"] = (edge_rate / base["rate"]) if base["rate"] > 0 else None

    return {
        "num_candidates": len(cand),
        "num_edges": len(edges),
        "num_clusters": len(clusters),
        "clusters": [
            {
                "cluster_id": c.cluster_id,
                "addresses": c.addresses,
                "confidence": c.confidence,
                "confidence_level": c.confidence_level,
                "signals": c.signals,
                "reason": c.reason,
            }
            for c in clusters
        ],
        "edges": [
            {
                "a": e.a,
                "b": e.b,
                "signals": e.signals,
                "support": e.support,
                "reason": e.reason,
            }
            for e in edges.values()
        ],
        "random_baseline": base,
        "fetch_contract": {
            "dune_queries": [
                "cluster_transfers",
                "cluster_gas_payers",
                "cluster_traces",
            ],
            "rpc": ["owner() for contract candidates"],
            "not_used": ["dex.trades", "same_tx as sole edge"],
        },
    }


def fetch_cluster_evidence(
    token: str,
    candidates: list[str],
    from_block: int,
    to_block: int,
    *,
    cache_dir: Optional[str | Path] = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Dune pulls: transfers among candidates, gas payers, then traces for those txs."""
    from ..data.dune import configured, query

    if not configured():
        raise RuntimeError("DUNE_API_KEY is not set")
    if not candidates:
        return [], [], []

    transfers = query(
        "cluster_transfers",
        token=token,
        from_block=from_block,
        to_block=to_block,
        address_list=candidates,
        cache_dir=cache_dir,
        chunk_blocks=0,
    )
    tx_hashes = sorted({
        _norm(r.get("tx_hash"))
        for r in transfers or []
        if _norm(r.get("tx_hash"))
    })
    gas_rows: list[dict] = []
    trace_rows: list[dict] = []
    for i in range(0, len(tx_hashes), 200):
        batch = tx_hashes[i : i + 200]
        gas_rows.extend(
            query(
                "cluster_gas_payers",
                tx_hash_list=batch,
                cache_dir=cache_dir,
                chunk_blocks=0,
            )
        )
        try:
            trace_rows.extend(
                query(
                    "cluster_traces",
                    tx_hash_list=batch,
                    address_list=candidates,
                    cache_dir=cache_dir,
                    chunk_blocks=0,
                )
            )
        except Exception:
            # Traces optional — transfer-based same_tx support still works.
            pass
    return transfers or [], gas_rows or [], trace_rows or []


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Wallet clustering prototype")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--out", default="", help="Write address_clusters.json here")
    parser.add_argument("--candidates", default="", help="Comma-separated addresses")
    parser.add_argument("--from-block", type=int, default=0)
    parser.add_argument("--to-block", type=int, default=0)
    parser.add_argument("--token", default="")
    parser.add_argument("--fetch-dune", action="store_true")
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    out_path = Path(args.out) if args.out else out_dir / "address_clusters.json"

    transfers: list[dict] = []
    gas_rows: list[dict] = []
    candidates: list[str] = []

    if args.candidates:
        candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]
    else:
        holdings = {}
        hp = out_dir / "holdings.json"
        if hp.exists():
            holdings = json.loads(hp.read_text())
        for row in holdings.get("holdings") or []:
            a = row.get("address")
            if a and not row.get("is_pool"):
                candidates.append(str(a))

    if args.fetch_dune:
        profile = {}
        pp = out_dir / "token_profile.json"
        if pp.exists():
            profile = json.loads(pp.read_text())
        token = args.token or profile.get("address") or ""
        fb = args.from_block
        tb = args.to_block
        if not fb or not tb:
            raise SystemExit("--from-block/--to-block required with --fetch-dune")
        transfers, gas_rows, _traces = fetch_cluster_evidence(
            token, candidates, fb, tb, cache_dir=out_dir / "dune_cache" / "cluster"
        )
    else:
        # Offline: reuse indexed transfers.json reshaped to cluster columns
        raw = []
        tp = out_dir / "transfers.json"
        if tp.exists():
            raw = json.loads(tp.read_text())
        cand_set = {_norm(c) for c in candidates}
        for row in raw:
            fr = _norm(row.get("actor") or row.get("from"))
            to = _norm(row.get("recipient") or row.get("to"))
            if cand_set and (fr not in cand_set or to not in cand_set):
                continue
            transfers.append({
                "from_address": fr,
                "to_address": to,
                "amount_raw": row.get("amount_raw") or row.get("token0_amount") or "0",
                "tx_hash": row.get("transaction_hash") or row.get("tx_hash"),
                "block_time": row.get("block_time"),
            })

    result = cluster_from_dune_rows(transfers, gas_rows, candidates=candidates)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(f"clusters={result['num_clusters']} edges={result['num_edges']} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
