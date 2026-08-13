"""Token holdings analysis & pool account identification.

1. Extract unique account addresses from Transfer events (RPC index or Dune)
2. Query token balance for each account (Dune balances table or RPC balanceOf)
3. Identify and annotate pool addresses
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from web3 import Web3

from ..client import get_contract, has_bytecode
from ..models import VerifiedPool

_ZERO = "0x0000000000000000000000000000000000000000"


def _chunks(items: list, size: int = 500) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _ingest_transfer_events(
    transfer_events: list[dict],
    unique_addresses: set[str],
    address_tx_count: dict[str, int],
    address_first_seen: dict[str, int],
    address_last_seen: dict[str, int],
) -> None:
    for evt in transfer_events:
        bn = int(evt.get("block_number", 0) or 0)
        for key in ("actor", "recipient"):
            raw = evt.get(key, "")
            if not raw or raw == _ZERO:
                continue
            try:
                addr = Web3.to_checksum_address(raw)
            except Exception:
                continue
            unique_addresses.add(addr)
            address_tx_count[addr] += 1
            if addr not in address_first_seen or bn < address_first_seen[addr]:
                address_first_seen[addr] = bn
            if addr not in address_last_seen or bn > address_last_seen[addr]:
                address_last_seen[addr] = bn


def analyze_holdings(
    w3: Web3,
    token_address: str,
    token_decimals: int,
    transfer_events: list[dict],
    verified_pools: list[VerifiedPool],
    from_block: int,
    to_block: int,
    output_dir: str | Path = "output",
    source: str = "auto",
    *,
    max_rpc_balances: int = 80,
    max_contract_checks: int = 80,
) -> dict[str, Any]:
    """Run the full holdings analysis pipeline.

    ``source``:
      - ``auto`` — prefer already-indexed ``transfer_events`` (from step 4);
        only hit Dune when no transfers were indexed
      - ``dune`` — force Dune address + balance queries
      - ``rpc``  — local ``transfer_events`` + capped ``balanceOf``

    RPC ``balanceOf`` / bytecode checks are capped so holdings cannot dominate
    analyze wall time.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    source_norm = (source or "auto").strip().lower()
    if source_norm not in ("auto", "dune", "rpc"):
        raise ValueError("source must be auto|dune|rpc, got {!r}".format(source))

    used_source = "rpc"
    unique_addresses: set[str] = set()
    address_tx_count: dict[str, int] = defaultdict(int)
    address_first_seen: dict[str, int] = {}
    address_last_seen: dict[str, int] = {}
    balances: dict[str, str] = {}
    balances_start: dict[str, str] = {}
    peak_balances: dict[str, str] = {}
    moved_in: dict[str, str] = {}
    moved_out: dict[str, str] = {}
    row_balance_source: dict[str, str] = {}
    row_trajectory_source: dict[str, str] = {}
    dune_error: Optional[str] = None

    # Fast path: reuse Transfer rows already pulled in [4/12]. Avoids a second
    # multi-minute Dune SQL round-trip for the same window.
    if transfer_events and source_norm in ("auto", "rpc"):
        _ingest_transfer_events(
            transfer_events,
            unique_addresses,
            address_tx_count,
            address_first_seen,
            address_last_seen,
        )
        used_source = "index"

    force_dune = source_norm == "dune" or (
        source_norm == "auto" and not unique_addresses
    )
    if force_dune:
        try:
            from ..data.dune import configured, query
            if not configured() and source_norm == "dune":
                raise RuntimeError("DUNE_API_KEY is not set")
            if configured():
                cache = out / "dune_cache" / "holdings"
                # Primary: balances_ethereum.daily_updates. Fallbacks: transfers.
                def _ingest_holder_rows(rows, *, with_tx_count: bool = False) -> None:
                    for row in rows:
                        try:
                            addr = Web3.to_checksum_address(str(row["address"]))
                        except Exception:
                            continue
                        unique_addresses.add(addr)
                        if with_tx_count:
                            address_tx_count[addr] = int(row.get("tx_count") or 0)
                            address_first_seen[addr] = int(
                                row.get("first_seen_block") or from_block
                            )
                            address_last_seen[addr] = int(
                                row.get("last_seen_block") or to_block
                            )
                        else:
                            address_tx_count.setdefault(addr, 0)
                            address_first_seen.setdefault(addr, from_block)
                            address_last_seen.setdefault(addr, to_block)

                try:
                    _ingest_holder_rows(
                        query(
                            "holders",
                            cache_dir=cache,
                            token=token_address,
                            from_block=from_block,
                            to_block=to_block,
                            chunk_blocks=0,
                        )
                    )
                except Exception as holders_exc:
                    print(
                        "  [holdings] holders (daily_updates) skipped ({}); "
                        "trying holders_from_transfers".format(holders_exc)
                    )
                    try:
                        _ingest_holder_rows(
                            query(
                                "holders_from_transfers",
                                cache_dir=cache,
                                token=token_address,
                                from_block=from_block,
                                to_block=to_block,
                                chunk_blocks=0,
                            )
                        )
                    except Exception as xfer_exc:
                        print(
                            "  [holdings] holders_from_transfers skipped ({}); "
                            "using transfer_addresses".format(xfer_exc)
                        )
                        _ingest_holder_rows(
                            query(
                                "transfer_addresses",
                                cache_dir=cache,
                                token=token_address,
                                from_block=from_block,
                                to_block=to_block,
                            ),
                            with_tx_count=True,
                        )
                ranked = sorted(
                    unique_addresses,
                    key=lambda a: (-address_tx_count.get(a, 0), a.lower()),
                )
                top = ranked[: max(50, max_rpc_balances)]
                if top:
                    try:
                        for row in query(
                            "balances",
                            cache_dir=cache,
                            token=token_address,
                            address_list=top,
                            to_block=to_block,
                            chunk_blocks=0,
                        ):
                            try:
                                addr = Web3.to_checksum_address(str(row["address"]))
                                bal = row.get("balance_raw")
                                if bal is not None:
                                    balances[addr] = str(int(bal))
                            except Exception:
                                continue
                    except Exception as bal_exc:
                        print(
                            "  [holdings] Dune balances skipped ({}); "
                            "will use RPC balanceOf".format(bal_exc)
                        )
                used_source = "dune"
        except Exception as exc:
            dune_error = str(exc)
            # Addresses already found → keep going with RPC balances.
            if unique_addresses:
                print(
                    "  [holdings] Dune partial failure ({}); "
                    "continuing with {} address(es) + RPC".format(
                        dune_error, len(unique_addresses)
                    )
                )
                used_source = used_source or "dune"
            elif source_norm == "dune":
                raise
            elif transfer_events:
                _ingest_transfer_events(
                    transfer_events,
                    unique_addresses,
                    address_tx_count,
                    address_first_seen,
                    address_last_seen,
                )
                used_source = "index"

    if not unique_addresses and transfer_events:
        _ingest_transfer_events(
            transfer_events,
            unique_addresses,
            address_tx_count,
            address_first_seen,
            address_last_seen,
        )
        used_source = "index"

    # Always include verified pools for labeling / balance snapshot.
    # V4 pool_address is often a bytes32 poolId — use custody (PoolManager) instead.
    def _holder_addr(raw: str) -> Optional[str]:
        if not raw or not str(raw).startswith("0x"):
            return None
        if len(str(raw)) != 42:
            return None
        try:
            return Web3.to_checksum_address(raw)
        except Exception:
            return None

    for p in verified_pools:
        for raw in (p.custody_address or "", p.pool_address or ""):
            addr = _holder_addr(raw)
            if not addr:
                continue
            unique_addresses.add(addr)
            address_tx_count.setdefault(addr, 0)
            address_first_seen.setdefault(addr, from_block)
            address_last_seen.setdefault(addr, to_block)

    # Fill missing balances: Dune latest table first (one SQL), then capped
    # historical RPC balanceOf at to_block for gaps (pools prioritized).
    token_contract = get_contract(w3, token_address, "erc20")
    query_timestamp = int(datetime.now(timezone.utc).timestamp())
    balance_block = int(to_block) if to_block else "latest"
    pool_addrs_l: set[str] = set()
    for p in verified_pools:
        for raw in (p.custody_address or "", p.pool_address or ""):
            addr = _holder_addr(raw)
            if addr:
                pool_addrs_l.add(addr.lower())

    # One Dune round-trip per chunk: start snapshot + in-window changes.
    # Locally derive end / peak / moved_in / moved_out so tokens_ethereum.balances
    # is not queried separately for start, end, and trajectory.
    dune_historical_ok = False
    if source_norm in ("auto", "dune"):
        try:
            from ..data.dune_holdings import (
                dune_api_key_configured as _dune_configured,
                fetch_balance_window_from_dune,
                fetch_historical_token_balances_from_dune,
                summarize_balance_trajectory,
            )
            dune_historical_ok = _dune_configured()
        except Exception:
            dune_historical_ok = False
    snapshot_budget = max(100, int(max_rpc_balances) * 2)
    ranked = sorted(
        unique_addresses,
        key=lambda a: (
            0 if a.lower() in pool_addrs_l else 1,
            -address_tx_count.get(a, 0),
            a.lower(),
        ),
    )[:snapshot_budget]
    if dune_historical_ok and ranked:
        window_ok = False
        try:
            for chunk in _chunks(ranked, 500):
                window_map = fetch_balance_window_from_dune(
                    token_address, chunk, int(from_block), int(to_block)
                )
                if window_map:
                    window_ok = True
                for addr in chunk:
                    rows = window_map.get(addr)
                    if not rows:
                        continue
                    summary = summarize_balance_trajectory(
                        rows, int(from_block), int(to_block)
                    )
                    balances[addr] = summary["end"]
                    balances_start[addr] = summary["start"]
                    peak_balances[addr] = summary["peak"]
                    row_balance_source[addr] = "dune_historical"
                    row_trajectory_source[addr] = summary["source"]
                    if summary["source"] == "event_rebuild":
                        moved_in[addr] = summary["moved_in"]
                        moved_out[addr] = summary["moved_out"]
        except Exception:
            window_ok = False
        if not window_ok:
            try:
                for chunk in _chunks(ranked, 500):
                    end_map = fetch_historical_token_balances_from_dune(
                        token_address, chunk, int(to_block)
                    )
                    start_map = fetch_historical_token_balances_from_dune(
                        token_address, chunk, int(from_block)
                    )
                    for addr in chunk:
                        if addr in end_map:
                            balances[addr] = end_map[addr]
                            row_balance_source[addr] = "dune_historical"
                            balances_start[addr] = start_map.get(addr, "0")
                            row_trajectory_source.setdefault(
                                addr, "two_point_snapshot"
                            )
            except Exception:
                pass
    missing = [a for a in unique_addresses if a not in balances]
    missing.sort(
        key=lambda a: (
            0 if a.lower() in pool_addrs_l else 1,
            -address_tx_count.get(a, 0),
            a.lower(),
        )
    )
    dune_filled = 0
    if missing and used_source != "dune":
        try:
            from ..data.dune import configured, query
            if configured():
                cache = out / "dune_cache" / "holdings"
                top = missing[: max(50, max_rpc_balances * 3)]
                for batch_start in range(0, len(top), 80):
                    batch = top[batch_start : batch_start + 80]
                    for row in query(
                        "balances",
                        cache_dir=cache,
                        token=token_address,
                        address_list=batch,
                        to_block=to_block,
                        chunk_blocks=0,
                    ):
                        try:
                            addr = Web3.to_checksum_address(str(row["address"]))
                            bal = row.get("balance_raw")
                            if bal is not None and addr not in balances:
                                balances[addr] = str(int(bal))
                                dune_filled += 1
                        except Exception:
                            continue
                if dune_filled:
                    print(
                        "  [holdings] Dune balances.latest filled {} addr(s)".format(
                            dune_filled
                        )
                    )
                    missing = [a for a in unique_addresses if a not in balances]
                    missing.sort(
                        key=lambda a: (
                            0 if a.lower() in pool_addrs_l else 1,
                            -address_tx_count.get(a, 0),
                            a.lower(),
                        )
                    )
        except Exception as exc:
            print("  [holdings] Dune balance fill skipped: {}".format(exc))
    rpc_budget = max(0, int(max_rpc_balances))
    # Always RPC-check pool custody at to_block (historical accuracy).
    pool_missing = [a for a in missing if a.lower() in pool_addrs_l]
    other_missing = [a for a in missing if a.lower() not in pool_addrs_l]
    to_query = (pool_missing + other_missing)[:rpc_budget]
    skipped_balances = [a for a in missing if a not in to_query]
    for addr in to_query:
        try:
            bal = token_contract.functions.balanceOf(
                Web3.to_checksum_address(addr)
            ).call(block_identifier=balance_block)
            balances[addr] = str(bal)
        except Exception:
            # Archive RPC may reject historical calls — fall back to latest
            try:
                bal = token_contract.functions.balanceOf(
                    Web3.to_checksum_address(addr)
                ).call()
                balances[addr] = str(bal)
            except Exception:
                balances[addr] = "0"
        row_balance_source[addr] = "rpc"
    for addr in skipped_balances:
        balances.setdefault(addr, "0")
        row_balance_source.setdefault(addr, "zero_fill")

    # Fill missing start balances for the same RPC-queried addresses so net
    # change stays available even when Dune has no pre-window row.
    for addr in to_query:
        if addr in balances and addr not in balances_start:
            try:
                balances_start[addr] = str(
                    token_contract.functions.balanceOf(
                        Web3.to_checksum_address(addr)
                    ).call(
                        block_identifier=int(from_block)
                        if from_block else "latest"
                    )
                )
            except Exception:
                balances_start[addr] = "0"

    dune_historical_count = sum(
        1 for v in row_balance_source.values() if v == "dune_historical"
    )
    if dune_historical_count:
        has_rpc_fallback = any(
            v not in ("dune_historical",)
            for v in row_balance_source.values()
        )
        balance_source = (
            "dune_historical+rpc" if has_rpc_fallback else "dune_historical"
        )
    elif used_source == "dune" and to_query:
        balance_source = "dune+rpc"
    elif used_source == "dune" and not missing:
        balance_source = "dune"
    elif dune_filled and to_query:
        balance_source = "dune_latest+rpc_capped"
    elif dune_filled:
        balance_source = "dune_latest"
    elif used_source == "index" and to_query:
        balance_source = "rpc_capped"
    elif skipped_balances and to_query:
        balance_source = "rpc_capped"
    else:
        balance_source = "rpc"

    # Identify pool addresses
    pool_addresses: set[str] = set()
    pool_by_addr: dict[str, VerifiedPool] = {}
    for p in verified_pools:
        pool_addresses.add(p.pool_address.lower())
        pool_by_addr[p.pool_address.lower()] = p
        if p.custody_address:
            pool_addresses.add(p.custody_address.lower())
            pool_by_addr[p.custody_address.lower()] = p

    # Fallback trajectory only for addresses the window query did not cover
    # (e.g. high end-balance whales outside the snapshot budget).
    pool_checksum = [a for a in unique_addresses if a.lower() in pool_addresses]
    non_pool_ranked = sorted(
        [a for a in unique_addresses if a.lower() not in pool_addresses],
        key=lambda a: (
            -int(balances.get(a, "0") or 0)
            if str(balances.get(a, "0") or "0").isdigit() else 0,
            -address_tx_count.get(a, 0),
            a.lower(),
        ),
    )
    trajectory_targets = pool_checksum + non_pool_ranked[:20]
    _seen: set[str] = set()
    trajectory_targets = [
        a for a in trajectory_targets
        if a not in peak_balances
        and not (a.lower() in _seen or _seen.add(a.lower()))
    ]
    if trajectory_targets:
        try:
            from ..data.dune_holdings import fetch_balance_trajectory_from_dune
            for chunk in _chunks(trajectory_targets, 500):
                traj_map = fetch_balance_trajectory_from_dune(
                    token_address, chunk, int(from_block), int(to_block)
                )
                for addr in chunk:
                    rows = traj_map.get(addr)
                    if not rows:
                        continue
                    prev = int(balances_start.get(addr, "0") or "0")
                    peak = prev
                    _in = 0
                    _out = 0
                    for row in rows:
                        cur = int(row["balance_raw"])
                        if cur > peak:
                            peak = cur
                        delta = cur - prev
                        if delta > 0:
                            _in += delta
                        elif delta < 0:
                            _out += -delta
                        prev = cur
                    peak_balances[addr] = str(peak)
                    moved_in[addr] = str(_in)
                    moved_out[addr] = str(_out)
                    row_trajectory_source[addr] = "event_rebuild"
        except Exception:
            pass

    # Two-point peak lower bound when no event-flow rows were fetched.
    for addr in unique_addresses:
        if addr in balances and addr not in peak_balances:
            try:
                start_i = int(balances_start.get(addr, "0") or "0")
                end_i = int(balances[addr] or "0")
                peak_balances[addr] = str(max(start_i, end_i))
            except (TypeError, ValueError):
                pass

    # Check which addresses are contracts (has bytecode on-chain)
    _contract_cache: dict[str, bool] = {}

    def _is_contract(addr: str) -> bool:
        a = addr.lower()
        if a not in _contract_cache:
            try:
                _contract_cache[a] = has_bytecode(
                    w3, Web3.to_checksum_address(addr), block_identifier=balance_block
                )
            except Exception:
                try:
                    _contract_cache[a] = has_bytecode(
                        w3, Web3.to_checksum_address(addr)
                    )
                except Exception:
                    _contract_cache[a] = False
        return _contract_cache[a]

    # ---- Beneficial owner tracing ----
    # For contract addresses, attempt to find the real beneficial owner:
    #   1. Try calling owner() (Ownable pattern, 0x8da5cb5b)
    #   2. If resolved to an EOA, use it; otherwise mark as unresolved
    _resolved_owner: dict[str, str] = {}

    def _resolve_owner(addr: str) -> str:
        a = addr.lower()
        if a in _resolved_owner:
            return _resolved_owner[a]
        if not _is_contract(addr):
            _resolved_owner[a] = addr  # EOA stays itself
            return addr
        # Try owner() call — use raw call to avoid needing a full ABI
        try:
            data = w3.eth.call(
                {
                    "to": Web3.to_checksum_address(addr),
                    "data": "0x8da5cb5b",  # keccak256("owner()")[:4]
                },
                block_identifier=balance_block,
            )
            if data and len(data) >= 36:  # 4 bytes padding + 20 bytes address
                owner_addr = Web3.to_checksum_address("0x" + data[-40:])
                if owner_addr.lower() != _ZERO.lower() and owner_addr.lower() != a:
                    _resolved_owner[a] = owner_addr
                    return owner_addr
        except Exception:
            pass
        _resolved_owner[a] = addr  # unresolved contract
        return addr

    # Rank addresses for expensive contract/owner RPC checks.
    ranked_addrs = sorted(
        unique_addresses,
        key=lambda a: (
            0 if a.lower() in pool_addresses else 1,
            -int(balances.get(a, "0") or "0") if str(balances.get(a, "0")).isdigit() else 0,
            -address_tx_count.get(a, 0),
            a.lower(),
        ),
    )
    contract_check_set = set(ranked_addrs[: max(0, int(max_contract_checks))])

    holdings_rows: list[dict[str, Any]] = []
    for addr in ranked_addrs:
        bal_raw = balances.get(addr, "0")
        try:
            bal_decimal = int(bal_raw) / (10 ** token_decimals)
        except (ValueError, TypeError):
            bal_decimal = 0.0
        start_raw = balances_start.get(addr, "")
        try:
            start_decimal = (
                round(int(start_raw) / (10 ** token_decimals), 6)
                if start_raw not in (None, "")
                else None
            )
        except (TypeError, ValueError):
            start_decimal = None
        net_raw = ""
        if start_raw not in (None, ""):
            try:
                net_raw = str(int(bal_raw) - int(start_raw))
            except (TypeError, ValueError):
                net_raw = ""
        net_decimal = (
            round(int(net_raw) / (10 ** token_decimals), 6)
            if net_raw else None
        )
        peak_raw = peak_balances.get(addr, "")
        try:
            peak_decimal = (
                round(int(peak_raw) / (10 ** token_decimals), 6)
                if peak_raw else None
            )
        except (TypeError, ValueError):
            peak_decimal = None
        is_pool = addr.lower() in pool_addresses
        pool_info = pool_by_addr.get(addr.lower())
        pool_label = ""
        if is_pool and pool_info:
            pool_label = "{} {}".format(pool_info.protocol, pool_info.version).upper()

        if is_pool:
            is_contract_addr = True
            addr_type = "pool"
            resolved = addr
            resolution_method = "pool"
        elif addr in contract_check_set:
            is_contract_addr = _is_contract(addr)
            if is_contract_addr:
                addr_type = "contract"
                # Skip owner() eth_call — doubles RPC cost; label as contract only.
                resolved = addr
                resolution_method = "contract_no_owner_lookup"
            else:
                addr_type = "eoa"
                resolved = addr
                resolution_method = "eoa"
        else:
            # Skip bytecode/owner RPC for the long tail.
            is_contract_addr = False
            addr_type = "unknown"
            resolved = addr
            resolution_method = "skipped_rpc"

        holdings_rows.append({
            "address": addr,
            "balance_raw": bal_raw,
            "balance_decimal": round(bal_decimal, 6),
            "balance_start_raw": start_raw or "",
            "balance_start_decimal": start_decimal,
            "balance_end_raw": bal_raw,
            "net_change_raw": net_raw,
            "net_change_decimal": net_decimal,
            "peak_balance_raw": peak_raw,
            "peak_balance_decimal": peak_decimal,
            "moved_in_raw": moved_in.get(addr, ""),
            "moved_out_raw": moved_out.get(addr, ""),
            "balance_source": row_balance_source.get(addr, "zero_fill"),
            "trajectory_source": (
                row_trajectory_source.get(
                    addr, "two_point_snapshot" if balances_start.get(addr) else "none"
                )
            ),
            "is_pool": is_pool,
            "pool_label": pool_label,
            "is_contract": is_contract_addr,
            "address_type": addr_type,
            "resolved_owner": resolved if resolved != addr else "",
            "resolution_method": resolution_method,
            "tx_count": address_tx_count.get(addr, 0),
            "first_seen_block": address_first_seen.get(addr, 0),
            "last_seen_block": address_last_seen.get(addr, 0),
            "query_timestamp": query_timestamp,
        })

    holdings_rows.sort(key=lambda r: r["balance_decimal"], reverse=True)

    pool_rows: list[dict[str, Any]] = []
    for p in verified_pools:
        pool_addr_lower = p.pool_address.lower()
        holder_info = next(
            (r for r in holdings_rows if r["address"].lower() == pool_addr_lower),
            None,
        )
        pool_rows.append({
            "pool_address": p.pool_address,
            "protocol": p.protocol,
            "version": p.version,
            "token0": p.token0,
            "token1": p.token1,
            "fee": p.fee,
            "balance_raw": holder_info["balance_raw"] if holder_info else "0",
            "balance_decimal": holder_info["balance_decimal"] if holder_info else 0.0,
            "in_holders_list": holder_info is not None,
        })

    eoa_count = sum(1 for r in holdings_rows if r["address_type"] == "eoa")
    contract_count = sum(1 for r in holdings_rows if r["address_type"] == "contract")
    resolved_count = sum(1 for r in holdings_rows if r.get("resolved_owner"))
    unresolved_contract_count = sum(
        1 for r in holdings_rows
        if r["address_type"] == "contract" and not r.get("resolved_owner")
    )
    real_holder_balance = sum(
        r["balance_decimal"] for r in holdings_rows if r["address_type"] == "eoa"
    )
    contract_balance = sum(
        r["balance_decimal"] for r in holdings_rows if r["address_type"] != "eoa"
    )

    result = {
        "total_unique_addresses": len(unique_addresses),
        "real_holder_count": eoa_count,
        "resolved_contract_count": resolved_count,
        "unresolved_contract_count": unresolved_contract_count,
        "total_resolved_holders": eoa_count + resolved_count,
        "contract_count": contract_count,
        "real_holder_balance": round(real_holder_balance, 6),
        "contract_balance": round(contract_balance, 6),
        "from_block": from_block,
        "to_block": to_block,
        "balance_block": balance_block if isinstance(balance_block, int) else to_block,
        "balance_start_block": from_block,
        "balance_end_block": balance_block if isinstance(balance_block, int) else to_block,
        "query_timestamp": query_timestamp,
        "query_time_human": datetime.fromtimestamp(
            query_timestamp, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "holdings_count": len(holdings_rows),
        "pool_count": len(pool_rows),
        "source": used_source,
        "balance_source": balance_source,
        "dune_error": dune_error,
        "dune_historical_balance_count": dune_historical_count,
        "event_rebuild_count": sum(
            1 for v in row_trajectory_source.values() if v == "event_rebuild"
        ),
        "holdings": holdings_rows,
        "pool_identification": pool_rows,
    }

    _write_json(out / "holdings.json", result)

    csv_holdings_path = out / "holdings_table.csv"
    with open(csv_holdings_path, "w", newline="") as f:
        if holdings_rows:
            writer = csv.DictWriter(f, fieldnames=list(holdings_rows[0].keys()))
            writer.writeheader()
            writer.writerows(holdings_rows)

    csv_pool_path = out / "pool_identification_table.csv"
    with open(csv_pool_path, "w", newline="") as f:
        if pool_rows:
            writer = csv.DictWriter(f, fieldnames=list(pool_rows[0].keys()))
            writer.writeheader()
            writer.writerows(pool_rows)

    return result


def _write_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
