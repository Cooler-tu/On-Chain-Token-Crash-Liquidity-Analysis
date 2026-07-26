"""Dune Analytics helpers for token holdings / transfer address discovery."""
from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests
from web3 import Web3


class DuneHoldingsError(RuntimeError):
    """Raised when a Dune holdings query fails."""


_DUNE_API = "https://api.dune.com/api/v1"


def dune_api_key_configured() -> bool:
    return bool((os.environ.get("DUNE_API_KEY") or "").strip())


def _normalize_addr(value: Any) -> str:
    """Normalize Dune address fields (hex string / bytes / 0x-prefixed)."""
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return Web3.to_checksum_address("0x" + bytes(value).hex())
    s = str(value).strip()
    if not s:
        return ""
    if s.startswith("\\x"):
        s = "0x" + s[2:]
    if not s.startswith("0x"):
        s = "0x" + s
    try:
        return Web3.to_checksum_address(s)
    except Exception:
        return s


def _run_sql(sql: str, api_key: str, poll_seconds: float = 1.5) -> list[dict[str, Any]]:
    """Execute SQL via Dune /sql/execute without a performance tier.

    Free-tier keys reject ``performance=medium|large``; omitting the field works.
    """
    headers = {
        "X-DUNE-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    try:
        start = requests.post(
            f"{_DUNE_API}/sql/execute",
            headers=headers,
            json={"sql": sql},
            timeout=60,
        )
        start.raise_for_status()
    except requests.HTTPError as exc:
        body = ""
        if exc.response is not None:
            body = exc.response.text[:400]
        raise DuneHoldingsError(
            "Dune SQL execute failed: {} {}".format(exc, body)
        ) from exc

    execution_id = start.json().get("execution_id")
    if not execution_id:
        raise DuneHoldingsError("Dune SQL execute returned no execution_id")

    # Poll until terminal
    for _ in range(120):
        status = requests.get(
            f"{_DUNE_API}/execution/{execution_id}/status",
            headers=headers,
            timeout=30,
        )
        status.raise_for_status()
        state = (status.json().get("state") or "").upper()
        if "COMPLETED" in state:
            break
        if "FAIL" in state or "CANCEL" in state:
            raise DuneHoldingsError(
                "Dune SQL execution {}: {}".format(state, status.text[:400])
            )
        time.sleep(poll_seconds)
    else:
        raise DuneHoldingsError("Dune SQL execution timed out")

    results = requests.get(
        f"{_DUNE_API}/execution/{execution_id}/results",
        headers=headers,
        timeout=120,
    )
    results.raise_for_status()
    payload = results.json()
    rows = (payload.get("result") or {}).get("rows") or []
    return rows


def fetch_transfer_addresses_from_dune(
    token_address: str,
    from_block: int,
    to_block: int,
    api_key: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return unique Transfer counterparties for ``token`` in ``[from_block, to_block]``.

    Each row: address, tx_count, first_seen_block, last_seen_block.
    Uses ``erc20_ethereum.evt_Transfer`` (covers Transfer from transfer/transferFrom).
    """
    key = (api_key or os.environ.get("DUNE_API_KEY") or "").strip()
    if not key:
        raise DuneHoldingsError("DUNE_API_KEY is not set")

    token = Web3.to_checksum_address(token_address).lower()
    sql = f"""
SELECT
  address,
  COUNT(*) AS tx_count,
  MIN(block_number) AS first_seen_block,
  MAX(block_number) AS last_seen_block
FROM (
  SELECT "from" AS address, evt_block_number AS block_number
  FROM erc20_ethereum.evt_Transfer
  WHERE contract_address = {token}
    AND evt_block_number BETWEEN {int(from_block)} AND {int(to_block)}
  UNION ALL
  SELECT "to" AS address, evt_block_number AS block_number
  FROM erc20_ethereum.evt_Transfer
  WHERE contract_address = {token}
    AND evt_block_number BETWEEN {int(from_block)} AND {int(to_block)}
) t
WHERE address <> 0x0000000000000000000000000000000000000000
GROUP BY 1
ORDER BY tx_count DESC
"""

    rows_raw = _run_sql(sql, key)
    out: list[dict[str, Any]] = []
    for row in rows_raw:
        addr = _normalize_addr(row.get("address"))
        if not addr:
            continue
        out.append({
            "address": addr,
            "tx_count": int(row.get("tx_count") or 0),
            "first_seen_block": int(row.get("first_seen_block") or 0),
            "last_seen_block": int(row.get("last_seen_block") or 0),
        })
    return out


def fetch_token_balances_from_dune(
    token_address: str,
    addresses: list[str],
    api_key: Optional[str] = None,
    limit: int = 500,
) -> dict[str, str]:
    """Best-effort latest raw balances from Dune ``tokens_ethereum.balances``.

    Returns ``{checksum_address: balance_raw_str}``. Empty on failure — caller
    should fall back to RPC ``balanceOf``. Caps IN-list size for free-tier SQL.
    """
    if not addresses:
        return {}

    key = (api_key or os.environ.get("DUNE_API_KEY") or "").strip()
    if not key:
        return {}

    token = Web3.to_checksum_address(token_address).lower()
    addrs = [Web3.to_checksum_address(a).lower() for a in addresses[:limit]]
    addr_list = ", ".join(addrs)
    sql = f"""
SELECT
  wallet_address AS address,
  CAST(amount_raw AS varchar) AS balance_raw
FROM tokens_ethereum.balances
WHERE token_address = {token}
  AND wallet_address IN ({addr_list})
"""

    try:
        rows_raw = _run_sql(sql, key)
    except Exception:
        return {}

    out: dict[str, str] = {}
    for row in rows_raw:
        addr = _normalize_addr(row.get("address"))
        if not addr:
            continue
        bal = row.get("balance_raw")
        if bal is None:
            continue
        try:
            out[addr] = str(int(bal))
        except (TypeError, ValueError):
            try:
                out[addr] = str(int(float(bal)))
            except (TypeError, ValueError):
                out[addr] = str(bal)
    return out
