"""CLI entry point for the on-chain token crash analysis system."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import typer

try:
    from dotenv import load_dotenv
    _dotenv_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(_dotenv_path)
    # Shells often export empty DUNE_API_KEY / ETH_RPC_URL placeholders, which
    # shadow .env; fill those blanks so the repository config still applies.
    if _dotenv_path.exists() and any(
        not (os.environ.get(key) or "").strip()
        for key in ("DUNE_API_KEY", "ETH_RPC_URL", "RPC_URL")
    ):
        load_dotenv(_dotenv_path, override=True)
except ImportError:
    pass

from .client import get_web3
from .discovery.engine import discover_pools, load_pools_file
from .models import VerifiedPool, to_dict
from .token.profiler import profile_token
from .token.resolver import TokenResolveError, format_resolve_summary, resolve_token
from .registry.loader import load_registry, get_chain_id
from .verification.verifier import verify_pools
from .indexer.indexer import index_events
from .analysis.positions import analyze_positions
from .analysis.labels import analyze_labels, find_deployer
from .analysis.metrics import calculate_all_metrics
from .analysis.timeline import analyze_timeline
from .analysis.risk import compute_risk
from .report.generator import generate_report
from .analysis.holdings import analyze_holdings
from .analysis.dashboard import generate_dashboard
from .data.artifacts import combine_event_tables

app = typer.Typer()


def _fmt_duration(seconds: float) -> str:
    """Human-readable duration for step timing lines."""
    if seconds < 60:
        return "{:.1f}s".format(seconds)
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return "{:.0f}m {:.1f}s".format(minutes, secs)
    hours, minutes = divmod(minutes, 60)
    return "{:.0f}h {:.0f}m {:.1f}s".format(hours, minutes, secs)


class _StepTimer:
    """Track per-step wall times and print a summary at the end."""

    def __init__(self) -> None:
        self.t0 = time.time()
        self.steps: list[dict] = []
        self._current: Optional[str] = None
        self._step_t0 = 0.0

    def begin(self, name: str) -> None:
        self._current = name
        self._step_t0 = time.time()

    def end(self, extra: str = "") -> float:
        elapsed = time.time() - self._step_t0
        name = self._current or "?"
        self.steps.append({"step": name, "seconds": round(elapsed, 3)})
        suffix = " — {}".format(extra) if extra else ""
        typer.echo("  time: {} done in {}{}".format(name, _fmt_duration(elapsed), suffix))
        self._current = None
        return elapsed

    def total_seconds(self) -> float:
        return time.time() - self.t0

    def summary_lines(self) -> list[str]:
        total = self.total_seconds()
        lines = ["=== Timing ==="]
        width = max((len(s["step"]) for s in self.steps), default=8)
        for s in self.steps:
            pct = (100.0 * s["seconds"] / total) if total > 0 else 0.0
            lines.append(
                "  {name:<{w}}  {dur:>12}  ({pct:5.1f}%)".format(
                    name=s["step"],
                    w=width,
                    dur=_fmt_duration(s["seconds"]),
                    pct=pct,
                )
            )
        lines.append("  {name:<{w}}  {dur:>12}".format(
            name="TOTAL", w=width, dur=_fmt_duration(total)
        ))
        return lines

    def to_dict(self) -> dict:
        return {
            "steps": self.steps,
            "total_seconds": round(self.total_seconds(), 3),
            "total_human": _fmt_duration(self.total_seconds()),
        }


def _resolve_or_exit(token_query: str, chain_id: int, pick: int) -> str:
    """Resolve address/symbol/name → checksum address, or exit with a clear error."""
    try:
        resolved = resolve_token(token_query, chain_id=chain_id, pick=pick)
    except TokenResolveError as exc:
        typer.echo("Token resolve failed: {}".format(exc), err=True)
        raise typer.Exit(1)
    typer.echo(format_resolve_summary(resolved))
    return resolved["address"]


@app.command()
def analyze(
    token: str = typer.Argument(
        ..., help="Token contract address, symbol, or name (e.g. 0x… / USDC / CREDI)"
    ),
    chain_id: int = typer.Option(1, help="Chain ID"),
    from_block: int = typer.Option(19000000, help="Start block"),
    to_block: int = typer.Option(19100000, help="End block"),
    incident_block: int = typer.Option(0, help="Block number of the crash incident (optional)"),
    rpc_url: str = typer.Option("", envvar="ETH_RPC_URL", help="RPC URL"),
    output_dir: str = typer.Option("output", help="Output directory"),
    fast_mode: bool = typer.Option(False, help="Skip exhaustive event indexing (faster, less data)"),
    pick: int = typer.Option(0, help="When name matches multiple tokens, pick candidate index"),
    holdings_source: str = typer.Option(
        "auto",
        help=(
            "Holdings source: auto (reuse indexed Transfers; fastest) | dune | rpc"
        ),
    ),
    pools_file: str = typer.Option(
        "",
        help="Load pool candidates from a saved Dune pools JSON (skip live discovery)",
    ),
    discovery_rpc: str = typer.Option(
        "off",
        help=(
            "RPC discovery after Dune: off (default, fastest) | auto | light | full"
        ),
    ),
    index_source: str = typer.Option(
        "auto",
        help="Event indexing source: auto (Dune if DUNE_API_KEY set) | dune | rpc",
    ),
    chart_span: str = typer.Option(
        "auto",
        help=(
            "Time-bucket for price/volume/TVL series from window size: "
            "auto|month|week|day (month→daily points; week/day→hourly points). "
            "Not a dashboard UI toggle — covers the full --from-block/--to-block range."
        ),
    ),
    artifact_format: str = typer.Option(
        "json",
        help=(
            "Artifact storage: json (legacy default) | both (JSON + Parquet "
            "dual-write for events, holdings, positions, and chart "
            "timelines). Parquet-only becomes available after all "
            "readers migrate."
        ),
    ),
):
    """End-to-end analysis: token → liquidity report + dashboard.

    Runs the full pipeline:
      1. Token profiling
      2. Pool discovery
      3. Pool verification
      4. Event indexing
      5. Position analysis
      6. Address labeling
      7. Metrics calculation
      8. Timeline analysis
      9. Risk assessment
      10. Report generation
      11. Holdings analysis
      12. Dashboard generation
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    timer = _StepTimer()

    from .data.artifacts import (
        ArtifactDependencyError,
        validate_artifact_environment,
    )

    try:
        artifact_mode = validate_artifact_environment(artifact_format)
    except (ValueError, ArtifactDependencyError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--artifact-format") from exc
    if artifact_mode == "parquet":
        raise typer.BadParameter(
            "Parquet-only mode is not available during Phase 1; use 'both'",
            param_hint="--artifact-format",
        )

    token_address = _resolve_or_exit(token, chain_id, pick)

    w3 = get_web3(rpc_url or None)
    registry = load_registry()
    chain_id_val = get_chain_id(registry)

    # Step 1: Token profile
    typer.echo("[1/12] Profiling token ...")
    timer.begin("[1/12] Profile token")
    profile = profile_token(w3, token_address, chain_id_val)
    _write_json(out / "token_profile.json", profile.__dict__)
    typer.echo(
        "  Symbol: {}, Decimals: {} ({})".format(
            profile.symbol, profile.decimals, profile.decimals_source
        )
    )
    target_token = profile.address
    timer.end()

    # Step 2: Discover pools (or load a saved Dune pools file)
    typer.echo("[2/12] Discovering pools ...")
    timer.begin("[2/12] Discover pools")
    if pools_file:
        pf = Path(pools_file)
        if not pf.exists():
            typer.echo("Pools file not found: {}".format(pf), err=True)
            raise typer.Exit(1)
        result = load_pools_file(pf, token_address, from_block, to_block, chain_id_val)
        typer.echo(
            "  Loaded {} candidate(s) from {} (skipped {})".format(
                len(result["pools"]), pf, result.get("skipped", 0)
            )
        )
        for err in result.get("errors", []):
            typer.echo("  warning: {}".format(err), err=True)
    else:
        result = discover_pools(
            w3,
            token_address,
            from_block,
            to_block,
            chain_id_val,
            cache_dir=out / "dune_cache",
            rpc_mode=discovery_rpc,
            on_progress=lambda msg: typer.echo("  {}".format(msg)),
        )
        typer.echo("  Found {} candidate(s)".format(len(result["pools"])))
        if result.get("dune_error"):
            typer.echo("  Dune warning: {}".format(result["dune_error"]), err=True)
    _write_json(out / "pool_candidates.json", result)
    timer.end("{} candidate(s)".format(len(result["pools"])))

    # Step 3: Verify pools
    typer.echo("[3/12] Verifying pools ...")
    timer.begin("[3/12] Verify pools")
    candidates = [VerifiedPool(**dict(pdata)) for pdata in result["pools"]]
    verified_pools = verify_pools(
        w3, candidates, target_token=token_address,
        from_block=from_block, to_block=to_block,
    )
    verified_count = sum(1 for p in verified_pools if p.verified)
    for p in verified_pools:
        status = "OK" if p.verified else "FAIL"
        typer.echo("  {} {}".format(status, p.pool_address))
    _write_json(out / "verified_pools.json", [to_dict(p) for p in verified_pools])
    typer.echo("  {} verified / {} total".format(verified_count, len(verified_pools)))
    timer.end("{} verified".format(verified_count))

    if verified_count == 0:
        typer.echo("No verified pools found. Cannot proceed with analysis.")
        raise typer.Exit(1)

    token_decimals = profile.decimals or 18

    # Step 4: Holdings / leaderboard FIRST (needed before LP).
    typer.echo("[4/12] Analyzing holdings (leaderboard before LP) ...")
    timer.begin("[4/12] Holdings")
    holdings_result = analyze_holdings(
        w3, target_token, token_decimals, [],
        verified_pools, from_block, to_block,
        output_dir=output_dir,
        source="auto" if holdings_source == "auto" else holdings_source,
        artifact_format=artifact_mode,
    )
    typer.echo("  source={}, balances={}".format(
        holdings_result.get("source", "rpc"),
        holdings_result.get("balance_source", "rpc"),
    ))
    if holdings_result.get("dune_error"):
        typer.echo("  dune fallback: {}".format(holdings_result["dune_error"]))
    leaderboard = [
        h for h in (holdings_result.get("holdings") or [])
        if not h.get("is_pool")
    ]
    # Dashboard table shows top ~20; keep a bit more for LP join.
    owner_allowlist = [
        h.get("address") for h in leaderboard[:100] if h.get("address")
    ]
    typer.echo(
        "  {} ranked holders; LP will only check top {}".format(
            len(leaderboard), len(owner_allowlist)
        )
    )
    timer.end()

    # Step 5: LP only for leaderboard wallets (not every LP in the pool).
    typer.echo("[5/12] Analyzing positions (leaderboard owners only) ...")
    typer.echo("  V3/V4 LP snapshot via Dune; filter to ranked holder addresses")
    timer.begin("[5/12] Positions")
    positions, pos_summary = analyze_positions(
        w3, verified_pools, [], target_token,
        from_block, to_block, output_dir=output_dir,
        allow_rpc_scan=False,
        owner_allowlist=owner_allowlist,
        artifact_format=artifact_mode,
    )
    typer.echo("  {} position(s), {} unique holder(s)".format(
        len(positions), pos_summary.get("total_unique_holders", 0)
    ))
    if not positions:
        typer.echo(
            "  note: none of the ranked holders have open LP at to_block "
            "(or Dune snapshot empty)"
        )
    timer.end()

    # Step 6: Event indexing (withdrawals / movers still need events;
    # volume/TVL charts prefer SQL aggregates and do not require raw swaps).
    typer.echo("[6/12] Indexing events (chunk-level resume enabled; Ctrl+C is safe) ...")
    typer.echo("  Progress: {}/indexer_cache + event_indexer_checkpoint.json".format(output_dir))
    timer.begin("[6/12] Index events")
    indexed = index_events(
        w3,
        verified_pools,
        target_token,
        from_block,
        to_block,
        output_dir=output_dir,
        index_token_transfer=not fast_mode,
        source=index_source,
        artifact_format=artifact_mode,
    )
    swaps = indexed["swaps"]
    liquidity_events = indexed["liquidity_events"]
    transfers = indexed["transfers"]
    position_events = indexed.get("position_events", [])

    typer.echo("  {} swaps, {} liquidity events, {} transfers".format(
        len(swaps), len(liquidity_events), len(transfers)
    ))
    timer.end(
        "{} swaps / {} liq / {} xfer".format(
            len(swaps), len(liquidity_events), len(transfers)
        )
    )

    events_all = combine_event_tables(
        swaps, liquidity_events, transfers, position_events
    )

    # Step 7: Address labeling
    typer.echo("[7/12] Labeling addresses ...")
    timer.begin("[7/12] Labels")
    deployer = None
    try:
        deployer = find_deployer(w3, target_token, from_block)
        if deployer:
            typer.echo("  Deployer: {}".format(deployer))
        else:
            typer.echo("  Deployer: unknown")
    except Exception as exc:
        typer.echo("  Deployer lookup skipped: {}".format(exc))

    labels = analyze_labels(
        target_token, verified_pools, positions,
        swaps, liquidity_events, transfers,
        deployer=deployer, output_dir=output_dir,
    )
    typer.echo("  {} label(s) assigned".format(len(labels)))
    timer.end()

    # Step 8: Metrics calculation
    typer.echo("[8/12] Calculating metrics ...")
    timer.begin("[8/12] Metrics")
    metrics = calculate_all_metrics(
        verified_pools, events_all, liquidity_events,
        positions, target_token, token_decimals,
        incident_block=incident_block, output_dir=output_dir, w3=w3,
        from_block=from_block,
        to_block=to_block,
        chart_span=chart_span,
        artifact_format=artifact_mode,
    )
    typer.echo(
        "  TVL timeline: {} points ({}); chart_span={} ({})".format(
            metrics.get("tvl_timeline_length", 0),
            metrics.get("tvl_timeline_source", "?"),
            metrics.get("chart_span", "?"),
            metrics.get("chart_bucket", "?"),
        )
    )
    pool_conc = metrics.get("pool_concentration", {})
    typer.echo("  Main pool share: {:.2%}".format(pool_conc.get("main_pool_share", 0)))
    timer.end()

    # Step 9: Timeline analysis
    typer.echo("[9/12] Building timeline ...")
    timer.begin("[9/12] Timeline")
    timeline = analyze_timeline(
        events_all, swaps, liquidity_events, transfers,
        verified_pools, target_token,
        incident_block=incident_block, from_block=from_block, to_block=to_block,
        output_dir=output_dir,
    )
    typer.echo("  {} total events in timeline".format(timeline.get("total_events", 0)))
    timer.end()

    # Step 10: Risk assessment
    typer.echo("[10/12] Computing risk score ...")
    timer.begin("[10/12] Risk")
    risk = compute_risk(
        pool_concentration=metrics.get("pool_concentration", {}),
        lp_concentration=metrics.get("lp_concentration", {}),
        withdrawal_severity=metrics.get("withdrawal_severity", {}),
        timeline=metrics.get("tvl_timeline", []),
        labels=[to_dict(l) for l in labels],
        deployer=deployer,
        incident_block=incident_block,
        migration=timeline.get("liquidity_migration"),
        output_dir=output_dir,
    )
    typer.echo("  Risk score: {:.4f} ({})".format(
        risk.get("final_score", 0), risk.get("risk_level", "N/A")
    ))
    timer.end()

    # Step 11: Report generation
    typer.echo("[11/12] Generating report ...")
    timer.begin("[11/12] Report")
    report = generate_report(
        token_profile=profile.__dict__,
        verified_pools=[to_dict(p) for p in verified_pools],
        events_swaps=swaps,
        events_liquidity=liquidity_events,
        events_transfers=transfers,
        positions=[to_dict(p) for p in positions],
        address_labels=[to_dict(l) for l in labels],
        metrics=metrics,
        timeline=timeline,
        risk_assessment=risk,
        incident_block=incident_block,
        output_dir=output_dir,
    )
    typer.echo("  report.md written")
    timer.end()

    # Holdings already computed in step 4 (leaderboard-before-LP).
    # Optionally refresh with indexed transfers for DEX tags / activity.
    if transfers and not fast_mode:
        typer.echo("  Refreshing holdings with indexed transfers ...")
        holdings_result = analyze_holdings(
            w3, target_token, token_decimals, transfers,
            verified_pools, from_block, to_block,
            output_dir=output_dir,
            source=holdings_source,
            artifact_format=artifact_mode,
        )
    eoa = holdings_result.get("real_holder_count", 0)
    typer.echo(
        "  Holdings ready: {} unique, {} EOA".format(
            holdings_result.get("total_unique_addresses", 0), eoa
        )
    )

    # Step 12: Dashboard
    typer.echo("[12/12] Generating dashboard ...")
    timer.begin("[12/12] Dashboard")
    dashboard_path = generate_dashboard(output_dir=output_dir)
    typer.echo("  {}".format(dashboard_path))
    timer.end()

    timing = timer.to_dict()
    _write_json(out / "timing.json", timing)

    # Summary
    typer.echo("\n=== Analysis Complete ===")
    typer.echo("Chain ID: {}  Token: {}".format(chain_id_val, target_token))
    typer.echo("Risk Score: {:.4f} / 1.00 ({})".format(
        risk.get("final_score", 0), risk.get("risk_level", "N/A")
    ))
    typer.echo("Dashboard: {}".format(dashboard_path))
    typer.echo("Output directory: {}".format(out.resolve()))
    typer.echo("")
    for line in timer.summary_lines():
        typer.echo(line)
    typer.echo("Timing saved: {}".format((out / "timing.json").resolve()))


@app.command()
def discover_only(
    token: str = typer.Argument(
        ..., help="Token contract address, symbol, or name (e.g. 0x… / USDC / CREDI)"
    ),
    from_block: int = typer.Option(19000000, help="Start block"),
    to_block: int = typer.Option(19100000, help="End block"),
    rpc_url: str = typer.Option("", envvar="ETH_RPC_URL", help="RPC URL"),
    output_dir: str = typer.Option("output", help="Output directory"),
    pick: int = typer.Option(0, help="When name matches multiple tokens, pick candidate index"),
    chain_id: int = typer.Option(1, help="Chain ID"),
    pools_file: str = typer.Option(
        "",
        help="Load pool candidates from a saved Dune pools JSON (skip live discovery)",
    ),
    discovery_rpc: str = typer.Option(
        "auto",
        help=(
            "RPC discovery after Dune: auto (skip heavy RPC if Dune found pools) | "
            "full | light | off"
        ),
    ),
):
    """Discover and verify pools for a token."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    token_address = _resolve_or_exit(token, chain_id, pick)

    w3 = get_web3(rpc_url or None)
    registry = load_registry()
    chain_id_val = get_chain_id(registry)

    profile = profile_token(w3, token_address, chain_id_val)
    _write_json(out / "token_profile.json", profile.__dict__)

    if pools_file:
        pf = Path(pools_file)
        if not pf.exists():
            typer.echo("Pools file not found: {}".format(pf), err=True)
            raise typer.Exit(1)
        result = load_pools_file(pf, token_address, from_block, to_block, chain_id_val)
        typer.echo(
            "Loaded {} candidate(s) from {} (skipped {})".format(
                len(result["pools"]), pf, result.get("skipped", 0)
            )
        )
        for err in result.get("errors", []):
            typer.echo("  warning: {}".format(err), err=True)
    else:
        result = discover_pools(
            w3,
            token_address,
            from_block,
            to_block,
            chain_id_val,
            cache_dir=out / "dune_cache",
            rpc_mode=discovery_rpc,
            on_progress=lambda msg: typer.echo("  {}".format(msg)),
        )
        typer.echo("Found {} candidate(s)".format(len(result["pools"])))
        if result.get("dune_error"):
            typer.echo("Dune warning: {}".format(result["dune_error"]), err=True)
    _write_json(out / "pool_candidates.json", result)

    candidates = [VerifiedPool(**dict(pdata)) for pdata in result["pools"]]
    verified_pools = verify_pools(
        w3, candidates, target_token=token_address,
        from_block=from_block, to_block=to_block,
    )
    _write_json(out / "verified_pools.json", [to_dict(p) for p in verified_pools])

    for p in verified_pools:
        status = "OK" if p.verified else "FAIL"
        typer.echo("{} {} (conf={})".format(status, p.pool_address, p.verification_confidence))



@app.command()
def holdings(
    token: str = typer.Argument(
        ..., help="Token contract address, symbol, or name (e.g. 0x… / USDC / CREDI)"
    ),
    from_block: int = typer.Option(19000000, help="Start block"),
    to_block: int = typer.Option(19100000, help="End block"),
    rpc_url: str = typer.Option("", envvar="ETH_RPC_URL", help="RPC URL"),
    output_dir: str = typer.Option("output", help="Output directory"),
    pick: int = typer.Option(0, help="When name matches multiple tokens, pick candidate index"),
    chain_id: int = typer.Option(1, help="Chain ID"),
    holdings_source: str = typer.Option(
        "auto",
        help="Holdings address source: auto (Dune if DUNE_API_KEY set) | dune | rpc",
    ),
    artifact_format: str = typer.Option(
        "json",
        help=(
            "Artifact storage: json (legacy default) | both "
            "(JSON + Parquet holdings rows)"
        ),
    ),
):
    """Step 1-2: Analyze token holdings & identify pool accounts.

    Runs:
      1. Basic Token Holdings Analysis - extracts unique addresses from
         Transfer events and queries their token balances
      2. Pool Account Identification - matches pool addresses among holders
    """
    from .token.profiler import profile_token as _profile
    from .discovery.engine import discover_pools as _discover
    from .verification.verifier import verify_pools as _verify
    from .registry.loader import load_registry as _registry, get_chain_id as _chain_id
    from .indexer.indexer import index_events as _index
    from .models import VerifiedPool as _VP, to_dict as _to_dict

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    from .data.artifacts import (
        ArtifactDependencyError,
        validate_artifact_environment,
    )

    try:
        artifact_mode = validate_artifact_environment(artifact_format)
    except (ValueError, ArtifactDependencyError) as exc:
        raise typer.BadParameter(str(exc), param_hint="--artifact-format") from exc
    if artifact_mode == "parquet":
        raise typer.BadParameter(
            "Parquet-only mode is not available during migration; use 'both'",
            param_hint="--artifact-format",
        )

    token_address = _resolve_or_exit(token, chain_id, pick)

    w3 = get_web3(rpc_url or None)
    registry = _registry()
    chain_id_val = _chain_id(registry)

    typer.echo("[1] Profiling token ...")
    profile = _profile(w3, token_address, chain_id_val)
    _write_json(out / "token_profile.json", profile.__dict__)
    typer.echo(
        "  Symbol: {}, Decimals: {} ({})".format(
            profile.symbol, profile.decimals, profile.decimals_source
        )
    )
    target_token = profile.address
    token_decimals = profile.decimals or 18

    typer.echo("[2] Discovering and verifying pools ...")
    result = _discover(
        w3,
        token_address,
        from_block,
        to_block,
        chain_id_val,
        cache_dir=out / "dune_cache",
        rpc_mode="auto",
        on_progress=lambda msg: typer.echo("  {}".format(msg)),
    )
    candidates = [_VP(**dict(pdata)) for pdata in result["pools"]]
    verified_pools = _verify(
        w3, candidates, target_token=token_address,
        from_block=from_block, to_block=to_block,
    )
    _write_json(out / "verified_pools.json", [_to_dict(p) for p in verified_pools])
    verified_count = sum(1 for p in verified_pools if p.verified)
    typer.echo("  {} verified pools".format(verified_count))
    if verified_count == 0:
        typer.echo("No verified pools found. Cannot proceed.")
        raise typer.Exit(1)

    typer.echo("[3] Indexing token transfer events ...")
    indexed = _index(
        w3, verified_pools, target_token, from_block, to_block,
        output_dir=output_dir, index_token_transfer=True, source="auto",
        artifact_format=artifact_mode,
    )
    transfers = indexed["transfers"]
    typer.echo("  {} transfer events indexed".format(len(transfers)))

    typer.echo("[4] Running holdings analysis ...")
    holdings_result = analyze_holdings(
        w3, target_token, token_decimals, transfers,
        verified_pools, from_block, to_block,
        output_dir=output_dir,
        source=holdings_source,
        artifact_format=artifact_mode,
    )
    typer.echo("  source={}, balances={}".format(
        holdings_result.get("source", "rpc"),
        holdings_result.get("balance_source", "rpc"),
    ))
    if holdings_result.get("dune_error"):
        typer.echo("  dune fallback: {}".format(holdings_result["dune_error"]))
    typer.echo("  {} unique addresses found, {} holders with balance".format(
        holdings_result["total_unique_addresses"],
        holdings_result["holdings_count"],
    ))
    pool_identified = [p for p in holdings_result["pool_identification"]
                       if p.get("in_holders_list")]
    typer.echo("  {} pool addresses identified in holder list".format(len(pool_identified)))

    typer.echo("\n=== Holdings Analysis Complete ===")
    typer.echo("Output files:")
    typer.echo("  holdings.json        - Full holdings data (JSON)")
    typer.echo("  holdings_summary.json - Compact run metadata")
    if artifact_mode == "both":
        typer.echo("  tables/holdings.parquet - Typed holdings rows")
    typer.echo("  holdings_table.csv   - Holdings table (CSV)")
    typer.echo("  pool_identification_table.csv - Pool identification table (CSV)")


@app.command()
def dashboard(
    output_dir: str = typer.Option("output", help="Output directory"),
):
    """Step 3: Generate a visual HTML dashboard from analysis results.

    Requires holdings artifacts, verified_pools.json, and other analysis
    output files to already exist in the output directory. Large row tables
    are read Parquet-first with legacy JSON fallback.
    """
    dashboard_path = generate_dashboard(output_dir=output_dir)
    typer.echo("Dashboard generated: {}".format(dashboard_path))


@app.command("serve-dashboard")
def serve_dashboard(
    output_dir: str = typer.Option("output", help="Output directory"),
    port: int = typer.Option(8080, help="HTTP port"),
    host: str = typer.Option("127.0.0.1", help="Bind host"),
):
    """Serve local dashboard.html over HTTP (for Tailscale serve/funnel)."""
    import http.server
    import socketserver
    import webbrowser

    out = Path(output_dir).resolve()
    dash = out / "dashboard.html"
    if not dash.exists():
        typer.echo(
            "Missing {}. Run `python3 -m src.cli dashboard --output-dir {}` first.".format(
                dash, output_dir
            ),
            err=True,
        )
        raise typer.Exit(1)

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(out), **kwargs)

        def log_message(self, fmt, *args):
            typer.echo(fmt % args)

    typer.echo("Serving {} on http://{}:{}/dashboard.html".format(out, host, port))
    typer.echo("For Tailscale: `tailscale serve {}` or `tailscale funnel --https=443 {}`".format(port, port))
    try:
        webbrowser.open("http://{}:{}/dashboard.html".format(host, port))
    except Exception:
        pass
    with socketserver.TCPServer((host, port), _Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            typer.echo("\nStopped.")


@app.command()
def dune(
    action: str = typer.Argument(
        ..., help="Action: pools | swaps | tvl | data-map"
    ),
    token: str = typer.Option(
        "", help="Token address/symbol/name (for pools/tvl)"
    ),
    pool: str = typer.Option(
        "", help="Pool contract address (for swaps/tvl)"
    ),
    from_block: int = typer.Option(19000000, help="Start block"),
    to_block: int = typer.Option(19100000, help="End block"),
    output_dir: str = typer.Option("output", help="Output directory"),
    pick: int = typer.Option(0, help="Token resolve pick"),
):
    """Query Dune directly: pool discovery, swaps, TVL, or data map.

    Examples:
      python3 -m src.cli dune pools CRV --from-block 19000000 --to-block 19000050
      python3 -m src.cli dune swaps 0x... --from-block 19000000 --to-block 19000050
      python3 -m src.cli dune tvl 0x...
      python3 -m src.cli dune data-map
    """
    from .data.dune import DuneError, configured, query

    action_norm = action.strip().lower()
    if action_norm == "data-map":
        _echo_dune_data_map()
        return

    if not configured():
        typer.echo(
            "DUNE_API_KEY is not set. Create a key at "
            "https://dune.com/settings/api and export it, then retry.",
            err=True,
        )
        raise typer.Exit(1)

    cache_dir = Path(output_dir) / "dune_cache"

    if action_norm in ("pools",):
        token_address = _resolve_or_exit(token, 1, pick)
        typer.echo(
            "Querying Dune dex.trades for pools containing {}".format(
                token_address
            )
        )
        try:
            rows = query(
                "pools",
                cache_dir=cache_dir,
                token=token_address,
                from_block=from_block,
                to_block=to_block,
            )
        except DuneError as exc:
            typer.echo("Dune query failed: {}".format(exc), err=True)
            raise typer.Exit(1)
        _write_json(Path(output_dir) / "dune_pools.json", rows)
        typer.echo("Found {} pool(s)".format(len(rows)))
        for r in rows:
            typer.echo(
                "  {:<10} {:<10} {}".format(
                    r.get("project", ""), r.get("version", ""),
                    r.get("pool_address", ""),
                )
            )
        typer.echo("Saved to {}/dune_pools.json".format(output_dir))
        return

    if action_norm == "swaps":
        if not pool:
            typer.echo("--pool is required for swaps", err=True)
            raise typer.Exit(1)
        if not token:
            typer.echo("--token is required for swaps (same as analyze window token)", err=True)
            raise typer.Exit(1)
        token_address = _resolve_or_exit(token, 1, pick)
        typer.echo(
            "Querying Dune dex.trades for pool {}".format(pool)
        )
        try:
            from web3 import Web3
            pool_addr = Web3.to_checksum_address(pool)
            rows = query(
                "swaps",
                cache_dir=cache_dir,
                token=token_address,
                from_block=from_block,
                to_block=to_block,
                pool_filter="AND project_contract_address = {}".format(
                    pool_addr.lower()
                ),
            )
        except DuneError as exc:
            typer.echo("Dune query failed: {}".format(exc), err=True)
            raise typer.Exit(1)
        _write_json(Path(output_dir) / "dune_swaps.json", rows)
        typer.echo("Found {} swap(s)".format(len(rows)))
        for r in rows[:10]:
            typer.echo(
                "  #{} {} {}->{}".format(
                    r.get("block_number", 0),
                    r.get("protocol", ""),
                    str(r.get("token_sold", ""))[:10],
                    str(r.get("token_bought", ""))[:10],
                )
            )
        typer.echo("Saved to {}/dune_swaps.json".format(output_dir))
        return

    if action_norm == "tvl":
        if not pool:
            typer.echo("--pool is required for tvl", err=True)
            raise typer.Exit(1)
        try:
            rows = query(
                "pool_tvl",
                cache_dir=cache_dir,
                pool=pool,
                block_filter="",
            )
        except DuneError as exc:
            typer.echo("Dune query failed: {}".format(exc), err=True)
            raise typer.Exit(1)
        if not rows:
            typer.echo("No TVL row found for {}".format(pool))
        else:
            tvl = rows[0]
            typer.echo("Pool: {}".format(tvl.get("pool_address", pool)))
            typer.echo("Day:  {}".format(tvl.get("day", "")))
            typer.echo("TVL:  ${:,.2f}".format(float(tvl.get("tvl_usd") or 0)))
        return

    typer.echo(
        "Unknown action '{}'. Use: pools | swaps | tvl | data-map".format(
            action
        ),
        err=True,
    )
    raise typer.Exit(1)


def _echo_dune_data_map() -> None:
    """Print the Dune data map (what comes from Dune vs RPC)."""
    typer.echo("=== Dune data map ===")
    typer.echo("API: src.data.dune.configured / query  +  dune_sql/*.sql")
    typer.echo("Pool discovery      : pools.sql + pools_v4.sql (real V4 poolIds)")
    typer.echo("Event indexing      : swaps + V2/V3 Mint/Burn + V4 ModifyLiquidity + transfers")
    typer.echo("V3 LP tokenIds      : liquidity_uniswap_v3_npm_token_ids.sql")
    typer.echo("Holdings (optional) : transfer_addresses.sql + balances.sql")
    typer.echo("Holdings (default)  : index Transfers + RPC balanceOf@to_block")
    typer.echo("Pool TVL (CLI)      : pool_tvl.sql")
    typer.echo("Verification/pos RPC: bytecode, ownerOf, positions(), slot0")


def _write_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


if __name__ == "__main__":
    app()
