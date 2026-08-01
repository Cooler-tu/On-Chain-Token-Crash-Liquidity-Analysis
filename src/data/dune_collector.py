"""Standalone OOP Dune fetcher — SQL lives in ``dune_sql/*.sql``.

Python only: load templates, substitute placeholders, call Dune API, cache, save.

Usage::

    export DUNE_API_KEY=...
    python3 -m src.data.dune_collector \\
        --token 0xD533a949740bb3306d119CC777fa900bA034cd52 \\
        --from-block 22000000 --to-block 22005000 \\
        --out-dir dune_cache/crv
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import requests
from web3 import Web3


# ---------------------------------------------------------------------------
# Paths / errors / utils
# ---------------------------------------------------------------------------

SQL_DIR = Path(__file__).resolve().parent / "dune_sql"
_DUNE_API = "https://api.dune.com/api/v1"
_ZERO = "0x0000000000000000000000000000000000000000"


class DuneCollectorError(RuntimeError):
    """Dune fetch or cache failure."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _checksum(addr: str) -> str:
    return Web3.to_checksum_address(addr)


def _norm_addr(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return _checksum("0x" + bytes(value).hex())
    s = str(value).strip()
    if not s:
        return ""
    if s.startswith("\\x"):
        s = "0x" + s[2:]
    if not s.startswith("0x"):
        s = "0x" + s
    try:
        return _checksum(s)
    except Exception:
        return s.lower()


def _dune_addr_literal(addr: str) -> str:
    return _checksum(addr).lower()


def _stable_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


class SqlTemplateLoader:
    """Load ``dune_sql/<name>.sql`` and replace ``{{placeholders}}``."""

    def __init__(self, sql_dir: Path = SQL_DIR) -> None:
        self.sql_dir = Path(sql_dir)
        if not self.sql_dir.is_dir():
            raise DuneCollectorError(f"SQL directory missing: {self.sql_dir}")

    def render(self, name: str, **params: Any) -> str:
        path = self.sql_dir / f"{name}.sql"
        if not path.exists():
            raise DuneCollectorError(f"SQL template not found: {path}")
        text = path.read_text(encoding="utf-8")
        # Strip SQL line comments for cleaner cache keys / API payload optional;
        # keep comments — Dune accepts them. Only substitute placeholders.
        missing = set(re.findall(r"\{\{(\w+)\}\}", text)) - set(params)
        if missing:
            raise DuneCollectorError(
                f"{path.name}: missing placeholders {sorted(missing)}"
            )

        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            return str(params[key])

        return re.sub(r"\{\{(\w+)\}\}", repl, text).strip()


# ---------------------------------------------------------------------------
# Local cache
# ---------------------------------------------------------------------------


class LocalJsonStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.cache_dir = self.root / "cache"
        self.root.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def dataset_path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def write_dataset(self, name: str, data: Any, meta: Optional[dict] = None) -> Path:
        path = self.dataset_path(name)
        envelope = {
            "saved_at": _now_iso(),
            "dataset": name,
            "meta": meta or {},
            "data": data,
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return path

    def read_dataset(self, name: str) -> Optional[Any]:
        path = self.dataset_path(name)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("data")
        except Exception:
            return None

    def cache_get(self, cache_key: str) -> Optional[list[dict[str, Any]]]:
        path = self.cache_dir / f"{cache_key}.json"
        if not path.exists():
            return None
        try:
            rows = json.loads(path.read_text(encoding="utf-8")).get("rows")
            return rows if isinstance(rows, list) else None
        except Exception:
            return None

    def cache_put(self, cache_key: str, rows: list[dict[str, Any]], sql: str) -> None:
        path = self.cache_dir / f"{cache_key}.json"
        payload = {
            "saved_at": _now_iso(),
            "cache_key": cache_key,
            "row_count": len(rows),
            "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            "rows": rows,
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


# ---------------------------------------------------------------------------
# Dune client
# ---------------------------------------------------------------------------


class DuneSqlClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        store: Optional[LocalJsonStore] = None,
        poll_seconds: float = 1.5,
        max_polls: int = 180,
        force_refresh: bool = False,
        max_retries: int = 4,
    ) -> None:
        self.api_key = (api_key or os.environ.get("DUNE_API_KEY") or "").strip()
        if not self.api_key:
            raise DuneCollectorError("DUNE_API_KEY is not set")
        self.store = store
        self.poll_seconds = poll_seconds
        self.max_polls = max_polls
        self.force_refresh = force_refresh
        self.max_retries = max_retries
        self._headers = {
            "X-DUNE-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }
        self._session = requests.Session()

    def execute(
        self,
        sql: str,
        *,
        cache_parts: Optional[dict[str, Any]] = None,
        label: str = "query",
    ) -> list[dict[str, Any]]:
        sql_norm = re.sub(r"\s+", " ", sql.strip())
        parts = {"label": label, "sql": sql_norm, **(cache_parts or {})}
        cache_key = _stable_hash(parts)

        if self.store is not None and not self.force_refresh:
            cached = self.store.cache_get(cache_key)
            if cached is not None:
                print(f"  [cache hit] {label} ({len(cached)} rows) key={cache_key}")
                return cached

        print(f"  [dune] {label} …")
        rows = self._execute_remote(sql, label=label)
        if self.store is not None:
            self.store.cache_put(cache_key, rows, sql_norm)
            print(f"  [cache save] {label} ({len(rows)} rows) key={cache_key}")
        return rows

    def _request(
        self,
        method: str,
        url: str,
        *,
        label: str,
        timeout: float,
        json_body: Optional[dict] = None,
    ) -> requests.Response:
        last_exc: Optional[BaseException] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.request(
                    method,
                    url,
                    headers=self._headers,
                    json=json_body,
                    timeout=timeout,
                )
                resp.raise_for_status()
                return resp
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                last_exc = exc
                # Retry transient network / 429 / 5xx
                status = getattr(getattr(exc, "response", None), "status_code", None)
                retryable = isinstance(exc, (requests.Timeout, requests.ConnectionError)) or (
                    status in (429, 500, 502, 503, 504)
                )
                if not retryable or attempt >= self.max_retries:
                    break
                wait = min(2 ** attempt, 20)
                print(
                    f"  [retry {attempt}/{self.max_retries}] {label} "
                    f"after {type(exc).__name__}; sleep {wait}s"
                )
                time.sleep(wait)
        raise DuneCollectorError(f"{label}: network/API error: {last_exc}") from last_exc

    def _execute_remote(self, sql: str, *, label: str) -> list[dict[str, Any]]:
        start = self._request(
            "POST",
            f"{_DUNE_API}/sql/execute",
            label=f"{label}:execute",
            timeout=120,
            json_body={"sql": sql},
        )
        execution_id = start.json().get("execution_id")
        if not execution_id:
            raise DuneCollectorError("Dune SQL execute returned no execution_id")

        for i in range(self.max_polls):
            status = self._request(
                "GET",
                f"{_DUNE_API}/execution/{execution_id}/status",
                label=f"{label}:status",
                timeout=60,
            )
            state = (status.json().get("state") or "").upper()
            if "COMPLETED" in state:
                break
            if "FAIL" in state or "CANCEL" in state:
                raise DuneCollectorError(
                    f"Dune SQL execution {state}: {status.text[:500]}"
                )
            if i == 0 or (i + 1) % 10 == 0:
                print(f"  [waiting] {label} state={state or '?'} poll={i + 1}/{self.max_polls}")
            time.sleep(self.poll_seconds)
        else:
            raise DuneCollectorError("Dune SQL execution timed out")

        results = self._request(
            "GET",
            f"{_DUNE_API}/execution/{execution_id}/results",
            label=f"{label}:results",
            timeout=180,
        )
        return list((results.json().get("result") or {}).get("rows") or [])


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchContext:
    token: str
    from_block: int
    to_block: int
    chain: str = "ethereum"

    @property
    def token_lit(self) -> str:
        return _dune_addr_literal(self.token)

    def base_params(self) -> dict[str, Any]:
        return {
            "token": self.token_lit,
            "chain": self.chain,
            "from_block": self.from_block,
            "to_block": self.to_block,
            "zero_address": _dune_addr_literal(_ZERO),
        }


class DatasetFetcher(ABC):
    name: str
    sql_name: str  # file stem under dune_sql/

    def __init__(
        self,
        client: DuneSqlClient,
        store: LocalJsonStore,
        sql: SqlTemplateLoader,
    ) -> None:
        self.client = client
        self.store = store
        self.sql = sql

    @abstractmethod
    def fetch(self, ctx: FetchContext, **kwargs: Any) -> Any:
        ...

    def _run_sql(
        self,
        ctx: FetchContext,
        *,
        sql_name: Optional[str] = None,
        label: Optional[str] = None,
        params: Optional[dict[str, Any]] = None,
        extra_key: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        name = sql_name or self.sql_name
        rendered = self.sql.render(name, **{**ctx.base_params(), **(params or {})})
        return self.client.execute(
            rendered,
            label=label or self.name,
            cache_parts={
                "sql_file": name,
                "token": ctx.token_lit,
                "from_block": ctx.from_block,
                "to_block": ctx.to_block,
                "chain": ctx.chain,
                **(extra_key or {}),
            },
        )


class TokenMetaFetcher(DatasetFetcher):
    name = "token_meta"
    sql_name = "token_meta"

    def fetch(self, ctx: FetchContext, **kwargs: Any) -> dict[str, Any]:
        rows = self._run_sql(ctx)
        if not rows:
            data = {
                "address": _checksum(ctx.token),
                "symbol": None,
                "name": None,
                "decimals": None,
                "source": "dune_missing",
            }
        else:
            r = rows[0]
            data = {
                "address": _norm_addr(r.get("address")) or _checksum(ctx.token),
                "symbol": r.get("symbol"),
                "name": r.get("name"),
                "decimals": _safe_int(r.get("decimals"), default=-1)
                if r.get("decimals") is not None
                else None,
                "source": "dune:tokens.erc20",
            }
        self.store.write_dataset(self.name, data)
        return data


class PoolsFetcher(DatasetFetcher):
    name = "pools"
    sql_name = "pools"

    def fetch(self, ctx: FetchContext, **kwargs: Any) -> list[dict[str, Any]]:
        rows = self._run_sql(ctx)
        out: list[dict[str, Any]] = []
        for r in rows:
            t_bought = _norm_addr(r.get("token_bought"))
            t_sold = _norm_addr(r.get("token_sold"))
            token0, token1 = sorted([t_bought, t_sold])
            out.append({
                "protocol": _safe_str(r.get("project")).lower(),
                "version": _safe_str(r.get("version")).lower(),
                "pool_address": _norm_addr(r.get("pool_address")),
                "token0": token0,
                "token1": token1,
                "token_bought": t_bought,
                "token_sold": t_sold,
                "trade_count": _safe_int(r.get("trade_count")),
                "volume_usd": float(r.get("volume_usd") or 0),
                "first_block": _safe_int(r.get("first_block")),
                "last_block": _safe_int(r.get("last_block")),
                "source": "dune:dex.trades",
            })
        self.store.write_dataset(self.name, out, meta={"row_count": len(out)})
        return out


class SwapsFetcher(DatasetFetcher):
    name = "swaps"
    sql_name = "swaps"

    def fetch(
        self,
        ctx: FetchContext,
        *,
        pool_addresses: Optional[Iterable[str]] = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        pools = [_dune_addr_literal(p) for p in (pool_addresses or []) if p][:40]
        pool_filter = ""
        extra_key: dict[str, Any] = {}
        if pools:
            pool_filter = (
                "AND project_contract_address IN (" + ", ".join(pools) + ")"
            )
            extra_key["pools"] = pools

        rows = self._run_sql(
            ctx,
            params={"pool_filter": pool_filter},
            extra_key=extra_key,
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append({
                "block_number": _safe_int(r.get("block_number")),
                "block_timestamp": _safe_str(r.get("block_time")),
                "transaction_hash": _safe_str(r.get("transaction_hash")).lower(),
                "log_index": _safe_int(r.get("log_index")),
                "protocol": _safe_str(r.get("protocol")).lower(),
                "version": _safe_str(r.get("version")).lower(),
                "pool_address": _norm_addr(r.get("pool_address")),
                "event_type": "SWAP",
                "actor": _norm_addr(r.get("actor") or r.get("tx_from")),
                "recipient": _norm_addr(r.get("actor")),
                "token_bought": _norm_addr(r.get("token_bought")),
                "token_sold": _norm_addr(r.get("token_sold")),
                "token_bought_amount_raw": _safe_str(r.get("token_bought_amount_raw")),
                "token_sold_amount_raw": _safe_str(r.get("token_sold_amount_raw")),
                "amount_usd": float(r.get("amount_usd") or 0),
                "source_event": "dex.trades",
                "verified": True,
            })
        self.store.write_dataset(
            self.name, out, meta={"row_count": len(out), "pool_filter_count": len(pools)}
        )
        return out


class LiquidityEventsFetcher(DatasetFetcher):
    name = "liquidity_events"
    sql_name = "liquidity_events"  # unused aggregate; per-file below

    _SQL_FILES = (
        "liquidity_uniswap_v2_mint",
        "liquidity_uniswap_v2_burn",
        "liquidity_uniswap_v3_mint",
        "liquidity_uniswap_v3_burn",
    )

    def fetch(
        self,
        ctx: FetchContext,
        *,
        pool_addresses: Optional[Iterable[str]] = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        pools = [_dune_addr_literal(p) for p in (pool_addresses or []) if p][:40]
        if not pools:
            self.store.write_dataset(self.name, [], meta={"note": "no pools"})
            return []

        pool_list = ", ".join(pools)
        parts: list[dict[str, Any]] = []
        errors: list[str] = []
        for sql_name in self._SQL_FILES:
            try:
                rows = self._run_sql(
                    ctx,
                    sql_name=sql_name,
                    label=f"{self.name}:{sql_name}",
                    params={"pool_list": pool_list},
                    extra_key={"pools": pools, "sub": sql_name},
                )
                for r in rows:
                    parts.append({
                        "block_number": _safe_int(r.get("block_number")),
                        "block_timestamp": _safe_str(r.get("block_time")),
                        "transaction_hash": _safe_str(r.get("transaction_hash")).lower(),
                        "log_index": _safe_int(r.get("log_index")),
                        "protocol": _safe_str(r.get("protocol")).lower(),
                        "version": _safe_str(r.get("version")).lower(),
                        "pool_address": _norm_addr(r.get("pool_address")),
                        "event_type": _safe_str(r.get("event_type")),
                        "actor": _norm_addr(r.get("actor")),
                        "recipient": _norm_addr(r.get("recipient")),
                        "token0_amount": _safe_str(r.get("token0_amount")),
                        "token1_amount": _safe_str(r.get("token1_amount")),
                        "liquidity_delta": "0",
                        "source_event": _safe_str(r.get("source_event")),
                        "verified": True,
                    })
            except DuneCollectorError as exc:
                errors.append(f"{sql_name}: {exc}")
                print(f"  [skip] {sql_name}: {exc}")

        parts.sort(key=lambda x: (x["block_number"], x["log_index"]))
        self.store.write_dataset(
            self.name,
            parts,
            meta={"row_count": len(parts), "errors": errors, "pools": pools},
        )
        return parts


class TransfersFetcher(DatasetFetcher):
    name = "transfers"
    sql_name = "transfers"

    def fetch(self, ctx: FetchContext, **kwargs: Any) -> list[dict[str, Any]]:
        rows = self._run_sql(ctx)
        out = []
        for r in rows:
            out.append({
                "block_number": _safe_int(r.get("block_number")),
                "block_timestamp": _safe_str(r.get("block_time")),
                "transaction_hash": _safe_str(r.get("transaction_hash")).lower(),
                "log_index": _safe_int(r.get("log_index")),
                "protocol": "",
                "version": "",
                "pool_address": "",
                "event_type": "TOKEN_TRANSFER",
                "actor": _norm_addr(r.get("actor")),
                "recipient": _norm_addr(r.get("recipient")),
                "token0_amount": _safe_str(r.get("amount_raw")),
                "token1_amount": "0",
                "liquidity_delta": "0",
                "source_event": "Transfer",
                "verified": True,
            })
        self.store.write_dataset(self.name, out, meta={"row_count": len(out)})
        return out


class TransferAddressesFetcher(DatasetFetcher):
    name = "transfer_addresses"
    sql_name = "transfer_addresses"

    def fetch(self, ctx: FetchContext, **kwargs: Any) -> list[dict[str, Any]]:
        rows = self._run_sql(ctx)
        out = []
        for r in rows:
            addr = _norm_addr(r.get("address"))
            if not addr or addr.lower() == _ZERO:
                continue
            out.append({
                "address": addr,
                "tx_count": _safe_int(r.get("tx_count")),
                "first_seen_block": _safe_int(r.get("first_seen_block")),
                "last_seen_block": _safe_int(r.get("last_seen_block")),
            })
        self.store.write_dataset(self.name, out, meta={"row_count": len(out)})
        return out


class BalancesFetcher(DatasetFetcher):
    name = "balances"
    sql_name = "balances"

    def fetch(
        self,
        ctx: FetchContext,
        *,
        addresses: Optional[Iterable[str]] = None,
        limit: int = 500,
        **kwargs: Any,
    ) -> dict[str, str]:
        addrs = [_dune_addr_literal(a) for a in (addresses or []) if a][:limit]
        if not addrs:
            self.store.write_dataset(self.name, {}, meta={"note": "no addresses"})
            return {}

        merged: dict[str, str] = {}
        chunk_size = 100
        for i in range(0, len(addrs), chunk_size):
            if i > 0:
                # Free-tier rate limit: pause between balance chunks
                time.sleep(8)
            chunk = addrs[i : i + chunk_size]
            try:
                rows = self._run_sql(
                    ctx,
                    label=f"{self.name}:chunk{i // chunk_size}",
                    params={"address_list": ", ".join(chunk)},
                    extra_key={"chunk": chunk, "sql_ver": "balances_ethereum.latest"},
                )
            except DuneCollectorError as exc:
                print(f"  [skip] balances chunk {i // chunk_size}: {exc}")
                continue
            for r in rows:
                addr = _norm_addr(r.get("address"))
                bal = r.get("balance_raw")
                if not addr or bal is None:
                    continue
                try:
                    merged[addr] = str(int(bal))
                except (TypeError, ValueError):
                    try:
                        merged[addr] = str(int(float(bal)))
                    except (TypeError, ValueError):
                        merged[addr] = str(bal)

        self.store.write_dataset(
            self.name,
            merged,
            meta={"address_requested": len(addrs), "balance_hits": len(merged)},
        )
        return merged


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class CollectResult:
    out_dir: str
    token: str
    from_block: int
    to_block: int
    datasets: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DuneDataCollector:
    def __init__(
        self,
        out_dir: str | Path,
        api_key: Optional[str] = None,
        force_refresh: bool = False,
        sql_dir: Optional[Path] = None,
    ) -> None:
        self.store = LocalJsonStore(out_dir)
        self.sql = SqlTemplateLoader(sql_dir or SQL_DIR)
        self.client = DuneSqlClient(
            api_key=api_key,
            store=self.store,
            force_refresh=force_refresh,
        )
        kw = dict(client=self.client, store=self.store, sql=self.sql)
        self.token_meta = TokenMetaFetcher(**kw)
        self.pools = PoolsFetcher(**kw)
        self.swaps = SwapsFetcher(**kw)
        self.liquidity = LiquidityEventsFetcher(**kw)
        self.transfers = TransfersFetcher(**kw)
        self.transfer_addresses = TransferAddressesFetcher(**kw)
        self.balances = BalancesFetcher(**kw)

    def collect(
        self,
        token: str,
        from_block: int,
        to_block: int,
        *,
        balance_limit: int = 500,
        reuse_datasets: bool = True,
    ) -> CollectResult:
        ctx = FetchContext(
            token=_checksum(token),
            from_block=int(from_block),
            to_block=int(to_block),
        )
        result = CollectResult(
            out_dir=str(self.store.root),
            token=ctx.token,
            from_block=ctx.from_block,
            to_block=ctx.to_block,
        )

        def _is_usable(name: str, existing: Any) -> bool:
            """Empty results from a failed/partial run should be refetched."""
            if existing is None:
                return False
            if name in ("balances", "liquidity_events", "pools", "swaps", "transfers"):
                if isinstance(existing, (list, dict)) and len(existing) == 0:
                    return False
            return True

        def _load_or(name: str, fn):
            if reuse_datasets and not self.client.force_refresh:
                existing = self.store.read_dataset(name)
                if _is_usable(name, existing):
                    print(f"  [dataset hit] {name}")
                    result.datasets[name] = existing
                    return existing
                if existing is not None:
                    print(f"  [dataset stale/empty] {name} → refetch")
            try:
                data = fn()
                result.datasets[name] = data
                return data
            except Exception as exc:
                msg = f"{name}: {exc}"
                result.errors.append(msg)
                print(f"  [error] {msg}")
                return None

        print(f"=== Dune collect {ctx.token} [{ctx.from_block}, {ctx.to_block}] ===")
        print(f"SQL dir: {self.sql.sql_dir}")
        _load_or("token_meta", lambda: self.token_meta.fetch(ctx))
        pools = _load_or("pools", lambda: self.pools.fetch(ctx)) or []
        pool_addrs: list[str] = []
        if isinstance(pools, list) and pools:
            ranked = sorted(
                pools, key=lambda p: int(p.get("trade_count") or 0), reverse=True
            )
            pool_addrs = [p["pool_address"] for p in ranked if p.get("pool_address")]

        _load_or("swaps", lambda: self.swaps.fetch(ctx, pool_addresses=pool_addrs))
        _load_or(
            "liquidity_events",
            lambda: self.liquidity.fetch(ctx, pool_addresses=pool_addrs),
        )
        _load_or("transfers", lambda: self.transfers.fetch(ctx))
        addrs = _load_or(
            "transfer_addresses", lambda: self.transfer_addresses.fetch(ctx)
        ) or []
        addr_list = [
            a.get("address")
            for a in addrs
            if isinstance(a, dict) and a.get("address")
        ][:balance_limit]
        _load_or(
            "balances",
            lambda: self.balances.fetch(ctx, addresses=addr_list, limit=balance_limit),
        )

        events_all: list[dict] = []
        for key in ("swaps", "liquidity_events", "transfers"):
            chunk = result.datasets.get(key) or []
            if isinstance(chunk, list):
                events_all.extend(chunk)
        events_all.sort(
            key=lambda e: (_safe_int(e.get("block_number")), _safe_int(e.get("log_index")))
        )
        self.store.write_dataset(
            "events_all",
            events_all,
            meta={"row_count": len(events_all)},
        )
        result.datasets["events_all"] = events_all

        manifest = {
            "saved_at": _now_iso(),
            "token": ctx.token,
            "from_block": ctx.from_block,
            "to_block": ctx.to_block,
            "out_dir": str(self.store.root),
            "sql_dir": str(self.sql.sql_dir),
            "datasets": {
                k: (len(v) if isinstance(v, (list, dict)) else 1)
                for k, v in result.datasets.items()
            },
            "errors": result.errors,
            "note": "SQL templates in src/data/dune_sql/. Not wired into analyze.",
        }
        self.store.write_dataset("manifest", manifest)
        print(f"=== done → {self.store.root} ===")
        return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Standalone Dune collector (SQL in src/data/dune_sql/)"
    )
    parser.add_argument("--token", required=True)
    parser.add_argument("--from-block", type=int, required=True)
    parser.add_argument("--to-block", type=int, required=True)
    parser.add_argument("--out-dir", default="dune_cache/run")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--no-reuse-datasets", action="store_true")
    parser.add_argument("--balance-limit", type=int, default=500)
    args = parser.parse_args(argv)

    collector = DuneDataCollector(
        out_dir=args.out_dir,
        force_refresh=args.force_refresh,
    )
    collector.collect(
        args.token,
        args.from_block,
        args.to_block,
        balance_limit=args.balance_limit,
        reuse_datasets=not args.no_reuse_datasets,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
