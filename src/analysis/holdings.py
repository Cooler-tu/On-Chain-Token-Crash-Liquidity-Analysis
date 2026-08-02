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
            from ..data.dune_holdings import (
                dune_api_key_configured,
                fetch_token_balances_from_dune,
                fetch_transfer_addresses_from_dune,
            )
            if not dune_api_key_configured() and source_norm == "dune":
                raise RuntimeError("DUNE_API_KEY is not set")
            if dune_api_key_configured():
                for row in fetch_transfer_addresses_from_dune(
                    token_address, from_block, to_block
                ):
                    addr = row["address"]
                    unique_addresses.add(addr)
                    address_tx_count[addr] = int(row.get("tx_count") or 0)
                    address_first_seen[addr] = int(row.get("first_seen_block") or 0)
                    address_last_seen[addr] = int(row.get("last_seen_block") or 0)
                # Only ask Dune for balances of the busiest addresses.
                ranked = sorted(
                    unique_addresses,
                    key=lambda a: (-address_tx_count.get(a, 0), a.lower()),
                )
                balances.update(
                    fetch_token_balances_from_dune(
                        token_address, ranked[: max(50, max_rpc_balances)]
                    )
                )
                used_source = "dune"
        except Exception as exc:
            dune_error = str(exc)
            if source_norm == "dune":
                raise
            if not unique_addresses and transfer_events:
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

    # Always include verified pools for labeling / balance snapshot
    for p in verified_pools:
        for raw in (p.pool_address, p.custody_address or ""):
            if not raw:
                continue
            try:
                addr = Web3.to_checksum_address(raw)
            except Exception:
                continue
            unique_addresses.add(addr)
            address_tx_count.setdefault(addr, 0)
            address_first_seen.setdefault(addr, from_block)
            address_last_seen.setdefault(addr, to_block)

    # Fill missing balances via RPC balanceOf at analysis window end.
    # Cap calls: prefer pools + highest-activity addresses first.
    token_contract = get_contract(w3, token_address, "erc20")
    query_timestamp = int(datetime.now(timezone.utc).timestamp())
    balance_block = int(to_block) if to_block else "latest"
    pool_addrs_l = {
        Web3.to_checksum_address(p.pool_address).lower()
        for p in verified_pools if p.pool_address
    }
    missing = [a for a in unique_addresses if a not in balances]
    missing.sort(
        key=lambda a: (
            0 if a.lower() in pool_addrs_l else 1,
            -address_tx_count.get(a, 0),
            a.lower(),
        )
    )
    rpc_budget = max(0, int(max_rpc_balances))
    to_query = missing[:rpc_budget]
    skipped_balances = missing[rpc_budget:]
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
    for addr in skipped_balances:
        balances.setdefault(addr, "0")

    if used_source == "dune" and to_query:
        balance_source = "dune+rpc"
    elif used_source == "dune" and not missing:
        balance_source = "dune"
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
        "query_timestamp": query_timestamp,
        "query_time_human": datetime.fromtimestamp(
            query_timestamp, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "holdings_count": len(holdings_rows),
        "pool_count": len(pool_rows),
        "source": used_source,
        "balance_source": balance_source,
        "dune_error": dune_error,
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
