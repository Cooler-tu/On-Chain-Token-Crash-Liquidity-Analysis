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
) -> dict[str, Any]:
    """Run the full holdings analysis pipeline.

    ``source``:
      - ``auto`` — use Dune when ``DUNE_API_KEY`` is set, else RPC transfers
      - ``dune`` — require Dune for address discovery
      - ``rpc``  — only use local ``transfer_events`` + ``balanceOf``
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

    prefer_dune = source_norm == "dune"
    if source_norm == "auto":
        from ..data.dune_holdings import dune_api_key_configured
        prefer_dune = dune_api_key_configured()

    if prefer_dune:
        try:
            from ..data.dune_holdings import (
                fetch_token_balances_from_dune,
                fetch_transfer_addresses_from_dune,
            )
            for row in fetch_transfer_addresses_from_dune(
                token_address, from_block, to_block
            ):
                addr = row["address"]
                unique_addresses.add(addr)
                address_tx_count[addr] = int(row.get("tx_count") or 0)
                address_first_seen[addr] = int(row.get("first_seen_block") or 0)
                address_last_seen[addr] = int(row.get("last_seen_block") or 0)
            balances.update(
                fetch_token_balances_from_dune(
                    token_address, sorted(unique_addresses)
                )
            )
            used_source = "dune"
        except Exception as exc:
            dune_error = str(exc)
            if source_norm == "dune":
                raise
            unique_addresses.clear()
            address_tx_count.clear()
            address_first_seen.clear()
            address_last_seen.clear()
            balances.clear()

    if used_source != "dune":
        used_source = "rpc"
        for evt in transfer_events:
            bn = int(evt.get("block_number", 0) or 0)
            for key in ("actor", "recipient"):
                raw = evt.get(key, "")
                if not raw or raw == "0x0000000000000000000000000000000000000000":
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

    # Fill missing balances via RPC balanceOf
    token_contract = get_contract(w3, token_address, "erc20")
    query_timestamp = int(datetime.now(timezone.utc).timestamp())
    missing = [a for a in sorted(unique_addresses) if a not in balances]
    for addr in missing:
        try:
            bal = token_contract.functions.balanceOf(
                Web3.to_checksum_address(addr)
            ).call()
            balances[addr] = str(bal)
        except Exception:
            balances[addr] = "0"

    if used_source == "dune" and missing and len(missing) < len(unique_addresses):
        balance_source = "dune+rpc"
    elif used_source == "dune" and not missing:
        balance_source = "dune"
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
                _contract_cache[a] = has_bytecode(w3, Web3.to_checksum_address(addr))
            except Exception:
                _contract_cache[a] = False
        return _contract_cache[a]

    holdings_rows: list[dict[str, Any]] = []
    for addr in sorted(unique_addresses):
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

        is_contract_addr = _is_contract(addr)
        if is_pool:
            addr_type = "pool"
        elif is_contract_addr:
            addr_type = "contract"
        else:
            addr_type = "eoa"

        holdings_rows.append({
            "address": addr,
            "balance_raw": bal_raw,
            "balance_decimal": round(bal_decimal, 6),
            "is_pool": is_pool,
            "pool_label": pool_label,
            "is_contract": is_contract_addr,
            "address_type": addr_type,
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
    real_holder_balance = sum(
        r["balance_decimal"] for r in holdings_rows if r["address_type"] == "eoa"
    )
    contract_balance = sum(
        r["balance_decimal"] for r in holdings_rows if r["address_type"] != "eoa"
    )

    result = {
        "total_unique_addresses": len(unique_addresses),
        "real_holder_count": eoa_count,
        "contract_count": contract_count,
        "real_holder_balance": round(real_holder_balance, 6),
        "contract_balance": round(contract_balance, 6),
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
