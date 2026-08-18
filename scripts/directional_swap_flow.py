#!/usr/bin/env python3
"""Audit signed V3 swap flow against ERC-20 transfers and pool balances.

Uniswap V3 Swap amounts are signed from the pool's perspective: a positive
amount enters the pool and a negative amount leaves it.  The canonical event
index intentionally stores absolute amounts for cross-protocol volume metrics,
so this research utility re-reads the raw V3 logs without changing that stable
artifact contract.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from src.client import get_contract, get_web3
from src.discovery.log_utils import get_logs_chunked
from src.indexer.indexer import _fetch_block_timestamps
from src.models import VerifiedPool


def _load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _tx_hash(value: Any) -> str:
    if hasattr(value, "hex"):
        text = str(value.hex()).lower()
    else:
        text = str(value or "").lower()
    return text if text.startswith("0x") else "0x" + text


def _decimal_string(raw: int, decimals: int) -> str:
    value = Decimal(raw) / (Decimal(10) ** max(0, int(decimals)))
    return format(value, "f")


def _iso(timestamp: int) -> str:
    return datetime.fromtimestamp(int(timestamp), timezone.utc).isoformat()


def _event_value(args: Any) -> int:
    for key in ("value", "amount", "wad"):
        if key in args:
            return int(args[key])
    raise KeyError("Transfer event has no value/amount/wad field")


def _safe_call(contract: Any, name: str, default: Any) -> Any:
    try:
        return getattr(contract.functions, name)().call()
    except Exception:
        return default


def _fetch_tx_from(w3: Any, hashes: Iterable[str]) -> dict[str, str]:
    """Fetch transaction senders, using JSON-RPC batches when available."""
    ordered = sorted({_tx_hash(value) for value in hashes if value})
    result: dict[str, str] = {}
    endpoint = getattr(w3.provider, "endpoint_uri", "")
    if endpoint and ordered:
        try:
            import requests

            batch_size = max(1, int(os.environ.get("ETH_TX_BATCH_SIZE") or 250))
            for offset in range(0, len(ordered), batch_size):
                chunk = ordered[offset:offset + batch_size]
                payload = [
                    {
                        "jsonrpc": "2.0",
                        "id": index,
                        "method": "eth_getTransactionByHash",
                        "params": [tx],
                    }
                    for index, tx in enumerate(chunk)
                ]
                response = requests.post(endpoint, json=payload, timeout=60)
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, list):
                    break
                for item in body:
                    tx = chunk[int(item.get("id") or 0)]
                    sender = (item.get("result") or {}).get("from")
                    if sender:
                        result[tx] = str(sender).lower()
        except Exception:
            # The safe per-transaction fallback below covers non-batch providers.
            pass
    for tx in ordered:
        if tx in result:
            continue
        try:
            result[tx] = str(w3.eth.get_transaction(tx)["from"]).lower()
        except Exception:
            result[tx] = ""
    return result


def build_signed_swap_rows(
    logs: Iterable[Any],
    *,
    pool: VerifiedPool,
    target_token: str,
    target_symbol: str,
    target_decimals: int,
    quote_symbol: str,
    quote_decimals: int,
    timestamps: dict[int, int],
    tx_from: dict[str, str],
) -> list[dict[str, Any]]:
    target = target_token.lower()
    token0 = pool.token0.lower()
    token1 = pool.token1.lower()
    if target not in {token0, token1}:
        raise ValueError("target token is not part of the selected pool")
    target_is_token0 = target == token0
    rows: list[dict[str, Any]] = []
    for event in logs:
        args = event["args"]
        amount0 = int(args["amount0"])
        amount1 = int(args["amount1"])
        target_raw = amount0 if target_is_token0 else amount1
        quote_raw = amount1 if target_is_token0 else amount0
        direction = (
            "SELL_{}".format(target_symbol.upper()) if target_raw > 0
            else "BUY_{}".format(target_symbol.upper()) if target_raw < 0
            else "ZERO_TARGET"
        )
        target_abs = abs(Decimal(target_raw)) / (Decimal(10) ** target_decimals)
        quote_abs = abs(Decimal(quote_raw)) / (Decimal(10) ** quote_decimals)
        price = quote_abs / target_abs if target_abs else None
        block = int(event["blockNumber"])
        tx = _tx_hash(event["transactionHash"])
        rows.append({
            "block_number": block,
            "block_timestamp": int(timestamps.get(block) or 0),
            "timestamp_utc": _iso(timestamps.get(block) or 0),
            "transaction_hash": tx,
            "log_index": int(event.get("logIndex") or 0),
            "pool_address": pool.pool_address.lower(),
            "tx_from": tx_from.get(tx, ""),
            "swap_sender": str(args.get("sender") or "").lower(),
            "swap_recipient": str(args.get("recipient") or "").lower(),
            "direction": direction,
            "target_symbol": target_symbol,
            "quote_symbol": quote_symbol,
            "amount0_raw_signed": str(amount0),
            "amount1_raw_signed": str(amount1),
            "target_delta_pool_raw_signed": str(target_raw),
            "quote_delta_pool_raw_signed": str(quote_raw),
            "target_amount_abs": format(target_abs, "f"),
            "quote_amount_abs": format(quote_abs, "f"),
            "price_quote_per_target": format(price, "f") if price is not None else "",
            "sqrt_price_x96": str(args.get("sqrtPriceX96") or ""),
            "liquidity": str(args.get("liquidity") or ""),
            "tick": int(args.get("tick") or 0),
        })
    return sorted(rows, key=lambda row: (row["block_number"], row["log_index"]))


def build_transfer_rows(
    inbound_logs: Iterable[Any],
    outbound_logs: Iterable[Any],
    *,
    pool_address: str,
    token_symbol: str,
    token_decimals: int,
    timestamps: dict[int, int],
    tx_from: dict[str, str],
    swap_hashes: set[str],
) -> list[dict[str, Any]]:
    pool = pool_address.lower()
    events: dict[tuple[str, int], Any] = {}
    for event in list(inbound_logs) + list(outbound_logs):
        key = (_tx_hash(event["transactionHash"]), int(event.get("logIndex") or 0))
        events[key] = event
    rows: list[dict[str, Any]] = []
    for (tx, log_index), event in events.items():
        args = event["args"]
        sender = str(args.get("from") or args.get("src") or "").lower()
        recipient = str(args.get("to") or args.get("dst") or "").lower()
        raw = _event_value(args)
        pool_delta = raw if recipient == pool else -raw if sender == pool else 0
        block = int(event["blockNumber"])
        rows.append({
            "block_number": block,
            "block_timestamp": int(timestamps.get(block) or 0),
            "timestamp_utc": _iso(timestamps.get(block) or 0),
            "transaction_hash": tx,
            "log_index": log_index,
            "tx_from": tx_from.get(tx, ""),
            "from_address": sender,
            "to_address": recipient,
            "token_symbol": token_symbol,
            "amount_raw": str(raw),
            "amount": _decimal_string(raw, token_decimals),
            "pool_delta_raw_signed": str(pool_delta),
            "pool_delta_signed": _decimal_string(pool_delta, token_decimals),
            "related_to_swap_tx": tx in swap_hashes,
        })
    return sorted(rows, key=lambda row: (row["block_number"], row["log_index"]))


def build_transaction_rows(
    swap_rows: Iterable[dict[str, Any]],
    transfer_rows: Iterable[dict[str, Any]],
    *,
    token_decimals: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in swap_rows:
        tx = row["transaction_hash"]
        group = grouped.setdefault(tx, {
            "transaction_hash": tx,
            "block_number": row["block_number"],
            "block_timestamp": row["block_timestamp"],
            "timestamp_utc": row["timestamp_utc"],
            "tx_from": row.get("tx_from") or "",
            "swap_event_count": 0,
            "transfer_event_count": 0,
            "swap_target_delta_pool_raw_signed": 0,
            "transfer_target_delta_pool_raw_signed": 0,
        })
        group["swap_event_count"] += 1
        group["swap_target_delta_pool_raw_signed"] += int(
            row["target_delta_pool_raw_signed"]
        )
    for row in transfer_rows:
        tx = row["transaction_hash"]
        group = grouped.setdefault(tx, {
            "transaction_hash": tx,
            "block_number": row["block_number"],
            "block_timestamp": row["block_timestamp"],
            "timestamp_utc": row["timestamp_utc"],
            "tx_from": row.get("tx_from") or "",
            "swap_event_count": 0,
            "transfer_event_count": 0,
            "swap_target_delta_pool_raw_signed": 0,
            "transfer_target_delta_pool_raw_signed": 0,
        })
        group["transfer_event_count"] += 1
        group["transfer_target_delta_pool_raw_signed"] += int(
            row["pool_delta_raw_signed"]
        )
    output: list[dict[str, Any]] = []
    for group in grouped.values():
        swap_raw = int(group.pop("swap_target_delta_pool_raw_signed"))
        transfer_raw = int(group.pop("transfer_target_delta_pool_raw_signed"))
        gap_raw = transfer_raw - swap_raw
        group.update({
            "has_swap": bool(group["swap_event_count"]),
            "swap_target_delta_pool_signed": _decimal_string(
                swap_raw, token_decimals
            ),
            "transfer_target_delta_pool_signed": _decimal_string(
                transfer_raw, token_decimals
            ),
            "transfer_minus_swap_signed": _decimal_string(
                gap_raw, token_decimals
            ),
        })
        output.append(group)
    return sorted(output, key=lambda row: (row["block_number"], row["transaction_hash"]))


def build_address_rows(
    transaction_rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "transaction_count": 0,
        "swap_event_count": 0,
        "sell_volume": Decimal(0),
        "buy_volume": Decimal(0),
        "net_swap_to_pool": Decimal(0),
        "actual_transfer_net_to_pool": Decimal(0),
    })
    for row in transaction_rows:
        address = str(row.get("tx_from") or "unknown").lower()
        group = grouped[address]
        group["transaction_count"] += 1
        group["swap_event_count"] += int(row.get("swap_event_count") or 0)
        swap_delta = Decimal(str(row.get("swap_target_delta_pool_signed") or 0))
        transfer_delta = Decimal(
            str(row.get("transfer_target_delta_pool_signed") or 0)
        )
        if swap_delta > 0:
            group["sell_volume"] += swap_delta
        elif swap_delta < 0:
            group["buy_volume"] += -swap_delta
        group["net_swap_to_pool"] += swap_delta
        group["actual_transfer_net_to_pool"] += transfer_delta
    rows: list[dict[str, Any]] = []
    for address, group in grouped.items():
        rows.append({
            "tx_from": address,
            "transaction_count": group["transaction_count"],
            "swap_event_count": group["swap_event_count"],
            "sell_volume": format(group["sell_volume"], "f"),
            "buy_volume": format(group["buy_volume"], "f"),
            "net_swap_to_pool": format(group["net_swap_to_pool"], "f"),
            "actual_transfer_net_to_pool": format(
                group["actual_transfer_net_to_pool"], "f"
            ),
        })
    return sorted(
        rows,
        key=lambda row: (-Decimal(row["sell_volume"]), row["tx_from"]),
    )


def summarize(
    swap_rows: list[dict[str, Any]],
    transfer_rows: list[dict[str, Any]],
    transaction_rows: list[dict[str, Any]],
    address_rows: list[dict[str, Any]],
    *,
    token_symbol: str,
    token_decimals: int,
    start_balance_raw: int,
    end_balance_raw: int,
    start_balance_block: int,
    end_balance_block: int,
) -> dict[str, Any]:
    swap_raw = [int(row["target_delta_pool_raw_signed"]) for row in swap_rows]
    transfer_raw = [int(row["pool_delta_raw_signed"]) for row in transfer_rows]
    sell_raw = sum(value for value in swap_raw if value > 0)
    buy_raw = -sum(value for value in swap_raw if value < 0)
    net_swap_raw = sum(swap_raw)
    net_transfer_raw = sum(transfer_raw)
    balance_delta_raw = end_balance_raw - start_balance_raw
    swap_tx_transfer_raw = sum(
        int(row["pool_delta_raw_signed"])
        for row in transfer_rows if row["related_to_swap_tx"]
    )
    non_swap_transfer_raw = net_transfer_raw - swap_tx_transfer_raw
    top_five_sell = sum(
        Decimal(row["sell_volume"]) for row in address_rows[:5]
    )
    sell = Decimal(sell_raw) / (Decimal(10) ** token_decimals)
    return {
        "token_symbol": token_symbol,
        "start_balance_block": start_balance_block,
        "end_balance_block": end_balance_block,
        "swap_event_count": len(swap_rows),
        "swap_transaction_count": len({row["transaction_hash"] for row in swap_rows}),
        "transaction_sender_count": len({row["tx_from"] for row in swap_rows if row["tx_from"]}),
        "sell_event_count": sum(value > 0 for value in swap_raw),
        "buy_event_count": sum(value < 0 for value in swap_raw),
        "sell_volume": _decimal_string(sell_raw, token_decimals),
        "buy_volume": _decimal_string(buy_raw, token_decimals),
        "net_swap_to_pool": _decimal_string(net_swap_raw, token_decimals),
        "actual_transfer_in": _decimal_string(
            sum(value for value in transfer_raw if value > 0), token_decimals
        ),
        "actual_transfer_out": _decimal_string(
            -sum(value for value in transfer_raw if value < 0), token_decimals
        ),
        "actual_transfer_net_to_pool": _decimal_string(
            net_transfer_raw, token_decimals
        ),
        "swap_tx_transfer_net_to_pool": _decimal_string(
            swap_tx_transfer_raw, token_decimals
        ),
        "non_swap_tx_transfer_net_to_pool": _decimal_string(
            non_swap_transfer_raw, token_decimals
        ),
        "transfer_minus_swap": _decimal_string(
            net_transfer_raw - net_swap_raw, token_decimals
        ),
        "start_pool_balance": _decimal_string(start_balance_raw, token_decimals),
        "end_pool_balance": _decimal_string(end_balance_raw, token_decimals),
        "pool_balance_delta": _decimal_string(balance_delta_raw, token_decimals),
        "balance_minus_transfer": _decimal_string(
            balance_delta_raw - net_transfer_raw, token_decimals
        ),
        "transfer_balance_reconciliation": (
            "exact" if balance_delta_raw == net_transfer_raw else "mismatch"
        ),
        "top_5_sender_sell_share": (
            format(top_five_sell / sell, ".10f") if sell else None
        ),
        "interpretation": (
            "Positive signed target flow enters the pool (sell target); negative "
            "flow leaves the pool (buy target). ERC-20 transfers, not Swap event "
            "amounts alone, reconcile the actual pool balance."
        ),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with open(path, "w", newline="", encoding="utf-8") as handle:
        if not fields:
            return
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
    tmp.replace(path)


def _write_summary_md(
    path: Path,
    summary: dict[str, Any],
    address_rows: list[dict[str, Any]],
    *,
    pool_address: str,
    from_block: int,
    to_block: int,
) -> None:
    top = address_rows[:5]
    lines = [
        "# Directional Swap Flow Audit",
        "",
        "- Pool: `{}`".format(pool_address.lower()),
        "- Event window: blocks `{}`–`{}`".format(from_block, to_block),
        "- Balance snapshots: blocks `{}` → `{}`".format(
            summary["start_balance_block"], summary["end_balance_block"]
        ),
        "",
        "## Reconciliation",
        "",
        "| Metric | {} |".format(summary["token_symbol"]),
        "|---|---:|",
        "| Sell volume into pool | {} |".format(summary["sell_volume"]),
        "| Buy volume out of pool | {} |".format(summary["buy_volume"]),
        "| Net Swap event flow to pool | {} |".format(summary["net_swap_to_pool"]),
        "| Actual ERC-20 transfer net to pool | {} |".format(
            summary["actual_transfer_net_to_pool"]
        ),
        "| Pool balance delta | {} |".format(summary["pool_balance_delta"]),
        "| Transfer minus Swap | {} |".format(summary["transfer_minus_swap"]),
        "| Balance minus Transfer | {} |".format(summary["balance_minus_transfer"]),
        "",
        "Transfer/balance reconciliation: **{}**.".format(
            summary["transfer_balance_reconciliation"]
        ),
        "",
        "## Activity",
        "",
        "- Swap events: {} ({} sells / {} buys)".format(
            summary["swap_event_count"],
            summary["sell_event_count"],
            summary["buy_event_count"],
        ),
        "- Unique Swap transactions: {}".format(summary["swap_transaction_count"]),
        "- Unique transaction senders: {}".format(summary["transaction_sender_count"]),
        "- Transfer net inside Swap transactions: {} {}".format(
            summary["swap_tx_transfer_net_to_pool"], summary["token_symbol"]
        ),
        "- Transfer net outside Swap transactions: {} {}".format(
            summary["non_swap_tx_transfer_net_to_pool"], summary["token_symbol"]
        ),
        "",
        "## Top transaction senders by sell volume",
        "",
        "| tx.from | Sell | Buy | Net Swap to pool | Transactions |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in top:
        lines.append(
            "| `{}` | {} | {} | {} | {} |".format(
                row["tx_from"], row["sell_volume"], row["buy_volume"],
                row["net_swap_to_pool"], row["transaction_count"]
            )
        )
    lines.extend([
        "",
        "## Interpretation guardrail",
        "",
        "Swap event amounts describe the pool swap calculation. For a token with "
        "custom transfer behavior or other same-window pool movements, they need not "
        "equal the ERC-20 balance change. Here, target-token Transfer logs reconcile "
        "the historical balance exactly; the non-zero Transfer-minus-Swap residual "
        "must be investigated rather than labelled automatically as a fee.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit signed V3 swaps against target-token transfers/balances"
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--pool", required=True)
    parser.add_argument("--from-block", type=int, required=True)
    parser.add_argument("--to-block", type=int, required=True)
    parser.add_argument("--start-balance-block", type=int, default=0)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--rpc-url", default="")
    args = parser.parse_args()
    if args.from_block <= 0 or args.to_block < args.from_block:
        parser.error("invalid block window")
    start_balance_block = args.start_balance_block or args.from_block - 1
    if start_balance_block < 0 or start_balance_block >= args.from_block:
        parser.error("--start-balance-block must be before --from-block")

    source = Path(args.output_dir)
    profile = _load_json(source / "token_profile.json")
    pools = [VerifiedPool(**row) for row in _load_json(source / "verified_pools.json")]
    pool_address = args.pool.lower()
    selected = next((
        pool for pool in pools
        if pool.verified and pool.pool_address.lower() == pool_address
    ), None)
    if selected is None:
        parser.error("selected pool is not present as a verified pool")
    if selected.version != "v3":
        parser.error("directional flow pilot currently supports Uniswap V3")

    target_token = str(profile.get("address") or "")
    target_symbol = str(profile.get("symbol") or "TARGET")
    target_decimals = int(profile.get("decimals") or 18)
    quote_token = selected.token1 if selected.token0.lower() == target_token.lower() else selected.token0
    rpc_url = args.rpc_url or os.environ.get("ETH_RPC_URL") or os.environ.get("RPC_URL")
    w3 = get_web3(rpc_url)
    pool_contract = get_contract(w3, selected.pool_address, "uniswap_v3_pool")
    token_contract = get_contract(w3, target_token, "erc20")
    quote_contract = get_contract(w3, quote_token, "erc20")
    quote_symbol = str(_safe_call(quote_contract, "symbol", "QUOTE"))
    quote_decimals = int(_safe_call(quote_contract, "decimals", 18))

    swap_logs = get_logs_chunked(
        pool_contract.events.Swap(), args.from_block, args.to_block
    )
    if not swap_logs:
        raise RuntimeError("no V3 Swap logs found in the selected block window")
    pool_checksum = w3.to_checksum_address(selected.pool_address)
    inbound = get_logs_chunked(
        token_contract.events.Transfer(), args.from_block, args.to_block,
        {"to": pool_checksum},
    )
    outbound = get_logs_chunked(
        token_contract.events.Transfer(), args.from_block, args.to_block,
        {"from": pool_checksum},
    )
    all_events = list(swap_logs) + list(inbound) + list(outbound)
    block_numbers = {int(event["blockNumber"]) for event in all_events}
    timestamps = _fetch_block_timestamps(w3, block_numbers)
    hashes = {_tx_hash(event["transactionHash"]) for event in all_events}
    tx_from = _fetch_tx_from(w3, hashes)

    swap_rows = build_signed_swap_rows(
        swap_logs,
        pool=selected,
        target_token=target_token,
        target_symbol=target_symbol,
        target_decimals=target_decimals,
        quote_symbol=quote_symbol,
        quote_decimals=quote_decimals,
        timestamps=timestamps,
        tx_from=tx_from,
    )
    transfer_rows = build_transfer_rows(
        inbound, outbound,
        pool_address=selected.pool_address,
        token_symbol=target_symbol,
        token_decimals=target_decimals,
        timestamps=timestamps,
        tx_from=tx_from,
        swap_hashes={row["transaction_hash"] for row in swap_rows},
    )
    transaction_rows = build_transaction_rows(
        swap_rows, transfer_rows, token_decimals=target_decimals
    )
    address_rows = build_address_rows(transaction_rows)
    start_balance_raw = int(token_contract.functions.balanceOf(pool_checksum).call(
        block_identifier=start_balance_block
    ))
    end_balance_raw = int(token_contract.functions.balanceOf(pool_checksum).call(
        block_identifier=args.to_block
    ))
    summary = summarize(
        swap_rows,
        transfer_rows,
        transaction_rows,
        address_rows,
        token_symbol=target_symbol,
        token_decimals=target_decimals,
        start_balance_raw=start_balance_raw,
        end_balance_raw=end_balance_raw,
        start_balance_block=start_balance_block,
        end_balance_block=args.to_block,
    )

    out = Path(args.out_dir) if args.out_dir else source / "research-directional-flow"
    _write_csv(out / "signed_swaps.csv", swap_rows)
    _write_csv(out / "pool_target_transfers.csv", transfer_rows)
    _write_csv(out / "transaction_flows.csv", transaction_rows)
    _write_csv(out / "address_flows.csv", address_rows)
    _write_json(out / "summary.json", summary)
    _write_summary_md(
        out / "summary.md", summary, address_rows,
        pool_address=selected.pool_address,
        from_block=args.from_block,
        to_block=args.to_block,
    )
    print(json.dumps({"out_dir": str(out), **summary}, indent=2))


if __name__ == "__main__":
    main()
