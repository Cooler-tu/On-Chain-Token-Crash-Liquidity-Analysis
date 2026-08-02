"""Unified Dune query layer with SQL execution, polling, and local caching.

Purpose: make Dune the primary data source where practical, with RPC as
fallback.  Every query here returns plain dict rows; callers decide whether
to fall back to RPC when a query fails.

Caching: results are cached under ``<output_dir>/dune_cache/<key>.json`` so
re-running an analysis with the same window does not re-hit the API.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import requests
from web3 import Web3


class DuneQueryError(RuntimeError):
    """Raised when a Dune query fails (network, auth, SQL, or timeout)."""


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


def _cache_key(prefix: str, *parts: Any) -> str:
    raw = "|".join([prefix] + [str(p) for p in parts])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


class DuneClient:
    """Execute Dune SQL with polling and JSON caching.

    Args:
        api_key: Dune API key; defaults to ``DUNE_API_KEY`` env var.
        cache_dir: directory for query cache; if None, caching is disabled.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_dir: Optional[str | Path] = None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("DUNE_API_KEY") or "").strip()
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if not self.api_key:
            raise DuneQueryError("DUNE_API_KEY is not set")

    # -- cache helpers ----------------------------------------------------

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / "{}.json".format(key)

    def _load_cache(self, key: str) -> Optional[list[dict]]:
        if not self.cache_dir:
            return None
        p = self._cache_path(key)
        if not p.exists():
            return None
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            return None

    def _save_cache(self, key: str, rows: list[dict]) -> None:
        if not self.cache_dir:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._cache_path(key).with_suffix(".tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(rows, f, default=str)
            tmp.replace(self._cache_path(key))
        except Exception:
            pass

    # -- core SQL runner --------------------------------------------------

    def run_sql(
        self,
        sql: str,
        cache_key: Optional[str] = None,
        force: bool = False,
        poll_seconds: float = 1.5,
        max_polls: int = 120,
        on_status: Optional[Any] = None,
    ) -> list[dict[str, Any]]:
        """Execute SQL via Dune /sql/execute, polling until completion.

        If ``cache_key`` is provided and a cached result exists, it is returned
        without hitting the API (unless ``force=True``).

        ``on_status`` is an optional ``(poll_index, state) -> None`` callback
        invoked on each status poll (useful for CLI progress).
        """
        if cache_key:
            cached = self._load_cache(cache_key)
            if cached is not None and not force:
                if on_status is not None:
                    on_status(-1, "CACHED")
                return cached

        headers = {
            "X-DUNE-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                f"{_DUNE_API}/sql/execute",
                headers=headers,
                json={"sql": sql},
                timeout=60,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise DuneQueryError("Dune SQL execute failed: {}".format(exc)) from exc

        execution_id = (resp.json() or {}).get("execution_id")
        if not execution_id:
            raise DuneQueryError("Dune SQL execute returned no execution_id")

        for poll_i in range(max_polls):
            try:
                status = requests.get(
                    f"{_DUNE_API}/execution/{execution_id}/status",
                    headers=headers,
                    timeout=30,
                )
                status.raise_for_status()
            except requests.RequestException as exc:
                raise DuneQueryError(
                    "Dune status poll failed: {}".format(exc)
                ) from exc
            state = (status.json().get("state") or "").upper()
            if on_status is not None:
                on_status(poll_i, state)
            if "COMPLETED" in state:
                break
            if "FAIL" in state or "CANCEL" in state:
                raise DuneQueryError(
                    "Dune execution {}: {}".format(
                        state, status.text[:4000]
                    )
                )
            time.sleep(poll_seconds)
        else:
            raise DuneQueryError("Dune SQL execution timed out")

        try:
            results = requests.get(
                f"{_DUNE_API}/execution/{execution_id}/results",
                headers=headers,
                timeout=120,
            )
            results.raise_for_status()
        except requests.RequestException as exc:
            raise DuneQueryError(
                "Dune results fetch failed: {}".format(exc)
            ) from exc

        payload = results.json()
        rows = (payload.get("result") or {}).get("rows") or []
        if cache_key:
            self._save_cache(cache_key, rows)
        return rows

    # -- pool discovery ----------------------------------------------------

    def fetch_pools_for_token(
        self,
        token_address: str,
        from_block: int,
        to_block: int,
        blockchain: str = "ethereum",
        on_status: Optional[Any] = None,
    ) -> list[dict[str, Any]]:
        """Find pools that traded a token via ``dex.trades``.

        Returns rows with ``pool_id`` (pool contract), ``project``,
        ``version``, trade_count, first/last block, and last pool name.
        """
        token = Web3.to_checksum_address(token_address).lower()
        sql = f"""
SELECT
  project,
  version,
  CAST(project_contract_address AS varchar) AS pool_address,
  COUNT(*) AS trade_count,
  MIN(block_number) AS first_seen_block,
  MAX(block_number) AS last_seen_block,
  MAX(CAST(token_bought_address AS varchar)) AS token_hint,
  MAX(CAST(token_sold_address AS varchar)) AS token_hint2
FROM dex.trades
WHERE blockchain = '{blockchain}'
  AND (token_bought_address = {token} OR token_sold_address = {token})
  AND block_number BETWEEN {int(from_block)} AND {int(to_block)}
GROUP BY 1, 2, 3
ORDER BY trade_count DESC
"""
        key = _cache_key(
            "pools", token, from_block, to_block, blockchain
        )
        rows = self.run_sql(sql, cache_key=key, on_status=on_status)
        out = []
        for row in rows:
            addr = _normalize_addr(row.get("pool_address"))
            if not addr:
                continue
            hints = set()
            for k in ("token_hint", "token_hint2"):
                h = row.get(k)
                if h:
                    hints.add(h.lower())
            out.append({
                "pool_address": addr,
                "project": (row.get("project") or "").lower(),
                "version": (row.get("version") or "").lower(),
                "trade_count": int(row.get("trade_count") or 0),
                "first_seen_block": int(row.get("first_seen_block") or 0),
                "last_seen_block": int(row.get("last_seen_block") or 0),
                "pool_name": row.get("pool_name") or "",
                "token_hints": sorted(hints),
            })
        return out

    # -- swaps -------------------------------------------------------------

    def fetch_swaps_for_pool(
        self,
        pool_address: str,
        from_block: int,
        to_block: int,
        blockchain: str = "ethereum",
        limit: int = 20000,
    ) -> list[dict[str, Any]]:
        """Fetch swap rows for a single pool via ``dex.trades``.

        Each row: block_time, block_number, tx_hash, taker,
        token_bought_address, token_sold_address, amount_bought_raw,
        amount_sold_raw, project, version, amount_usd.
        """
        pool = Web3.to_checksum_address(pool_address).lower()
        sql = f"""
SELECT
  block_number,
  CAST(block_time AS varchar) AS block_time,
  CAST(tx_hash AS varchar) AS tx_hash,
  evt_index AS log_index,
  project,
  version,
  CAST(project_contract_address AS varchar) AS pool_address,
  CAST(taker AS varchar) AS taker,
  CAST(token_bought_address AS varchar) AS token_bought_address,
  CAST(token_sold_address AS varchar) AS token_sold_address,
  CAST(token_bought_amount_raw AS varchar) AS amount_bought_raw,
  CAST(token_sold_amount_raw AS varchar) AS amount_sold_raw,
  amount_usd
FROM dex.trades
WHERE blockchain = '{blockchain}'
  AND project_contract_address = {pool}
  AND block_number BETWEEN {int(from_block)} AND {int(to_block)}
ORDER BY block_number, evt_index
LIMIT {int(limit)}
"""
        key = _cache_key(
            "swaps", pool, from_block, to_block, blockchain
        )
        return self.run_sql(sql, cache_key=key)

    # -- Balancer liquidity events -----------------------------------------

    def fetch_balancer_pool_balance_changed(
        self,
        vault_address: str,
        pool_id: str,
        from_block: int,
        to_block: int,
    ) -> list[dict[str, Any]]:
        """Fetch PoolBalanceChanged events from the Balancer Vault.

        ``pool_id`` is the Balancer bytes32 poolId (hex).  The Vault emits a
        single event stream, so this is Dune-friendly (one contract).
        """
        vault = Web3.to_checksum_address(vault_address).lower()
        pid = pool_id.lower()
        sql = f"""
SELECT
  evt_block_time AS block_time,
  evt_block_number AS block_number,
  evt_tx_hash AS tx_hash,
  liquidityProvider AS provider,
  tokens,
  deltas,
  "evt_index" AS log_index
FROM balancer_v2_ethereum.Vault_evt_PoolBalanceChanged
WHERE contract_address = {vault}
  AND poolId = {pid}
  AND evt_block_number BETWEEN {int(from_block)} AND {int(to_block)}
ORDER BY evt_block_number
"""
        key = _cache_key("bal_lp", vault, pid, from_block, to_block)
        return self.run_sql(sql, cache_key=key)

    # -- TVL / pool depth ---------------------------------------------------

    def fetch_pool_tvl(
        self,
        pool_address: str,
        block: Optional[int] = None,
        blockchain: str = "ethereum",
    ) -> Optional[dict[str, Any]]:
        """Fetch latest USD TVL for a pool via ``dex.pool_tvl``.

        Returns the most recent day row, or None if unavailable.
        """
        pool = Web3.to_checksum_address(pool_address).lower()
        block_filter = ""
        if block:
            block_filter = "AND block_number <= {}".format(int(block))
        sql = f"""
SELECT
  day,
  pool AS pool_address,
  tvl_usd,
  token_count
FROM dex.pool_tvl
WHERE blockchain = '{blockchain}'
  AND pool = {pool}
  {block_filter}
ORDER BY day DESC
LIMIT 1
"""
        key = _cache_key("tvl", pool, block or "latest", blockchain)
        rows = self.run_sql(sql, cache_key=key)
        if not rows:
            return None
        row = rows[0]
        return {
            "day": str(row.get("day") or ""),
            "pool_address": _normalize_addr(row.get("pool_address") or pool),
            "tvl_usd": float(row.get("tvl_usd") or 0),
            "token_count": int(row.get("token_count") or 0),
        }


def get_dune_client(cache_dir: Optional[str | Path] = None) -> DuneClient:
    """Convenience factory: returns a DuneClient or raises DuneQueryError."""
    return DuneClient(cache_dir=cache_dir)
