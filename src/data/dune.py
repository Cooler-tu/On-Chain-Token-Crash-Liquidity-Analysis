"""Dune access: two functions + SQL files in ``dune_sql/``.

1. ``configured()`` — is ``DUNE_API_KEY`` set?
2. ``query(sql_name, **params)`` — render template, run, cache, return rows.

Everything else (discovery / index / positions / holdings / CLI) just calls ``query``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from web3 import Web3

SQL_DIR = Path(__file__).resolve().parent / "dune_sql"
_QUERIES_FILE = SQL_DIR / "queries.sql"
_SECTION_RE = re.compile(
    r"^-- === name:\s*([A-Za-z0-9_]+)\s*===\s*$",
    re.MULTILINE,
)
_DUNE_API = "https://api.dune.com/api/v1"
_ZERO = "0x0000000000000000000000000000000000000000"
_CACHE_LOCK = threading.Lock()
_PRINT_LOCK = threading.Lock()

StatusFn = Callable[[int, str], None]
_SECTION_CACHE: dict[str, str] | None = None
_SECTION_MTIME: float | None = None


def _load_sections() -> dict[str, str]:
    """Parse named sections from ``dune_sql/queries.sql``."""
    global _SECTION_CACHE, _SECTION_MTIME
    if not _QUERIES_FILE.exists():
        _SECTION_CACHE = {}
        _SECTION_MTIME = None
        return _SECTION_CACHE
    mtime = _QUERIES_FILE.stat().st_mtime
    if _SECTION_CACHE is not None and _SECTION_MTIME == mtime:
        return _SECTION_CACHE
    text = _QUERIES_FILE.read_text(encoding="utf-8")
    matches = list(_SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections[name] = body
    _SECTION_CACHE = sections
    _SECTION_MTIME = mtime
    return sections


def list_sql_sections() -> list[str]:
    """Return available ``query()`` names from the consolidated SQL file."""
    return sorted(_load_sections())


class DuneError(RuntimeError):
    """Dune API / SQL / cache failure."""


class DuneQuotaError(DuneError):
    """Credits / result-size / payment limit — caller should shrink the request."""


def configured() -> bool:
    """True when ``DUNE_API_KEY`` is set."""
    return bool((os.environ.get("DUNE_API_KEY") or "").strip())


# Back-compat name used around the repo
dune_api_key_configured = configured


def _addr(value: Any) -> str:
    if value is None or value == "":
        return _ZERO
    if isinstance(value, (bytes, bytearray)):
        return Web3.to_checksum_address("0x" + bytes(value).hex()).lower()
    s = str(value).strip()
    if s.startswith("\\x"):
        s = "0x" + s[2:]
    if not s.startswith("0x"):
        s = "0x" + s
    return Web3.to_checksum_address(s).lower()


def _addr_list(value: Any) -> str:
    """Comma-separated EIP-55 addresses for SQL IN (...).

    Skips non-address values (e.g. Uniswap V4 bytes32 poolIds) so callers can
    pass mixed pool identifiers without breaking checksum normalization.
    """
    if value is None or value == "":
        return ""

    def one(v: Any) -> str:
        s = str(v or "").strip()
        if not s:
            return ""
        if s.startswith("\\x"):
            s = "0x" + s[2:]
        if not s.startswith("0x"):
            s = "0x" + s
        # V4 poolId is 32 bytes (66 chars with 0x) — not an address.
        if len(s) != 42:
            return ""
        try:
            return Web3.to_checksum_address(s).lower()
        except Exception:
            return ""

    if isinstance(value, str) and "," in value:
        return ", ".join(p for x in value.split(",") if (p := one(x.strip())))
    if isinstance(value, (list, tuple, set)):
        return ", ".join(p for x in value if (p := one(x)))
    return one(value)


def _hex32(value: Any) -> str:
    """Normalize a bytes32 hex id (no EIP-55 checksum — not an address)."""
    s = str(value or "").strip().lower()
    if not s:
        return ""
    if s.startswith("\\x"):
        s = "0x" + s[2:]
    if not s.startswith("0x"):
        s = "0x" + s
    return s


def _hex32_list(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str) and "," in value:
        parts = [_hex32(x.strip()) for x in value.split(",") if x.strip()]
        return ", ".join(p for p in parts if p)
    if isinstance(value, (list, tuple, set)):
        parts = [_hex32(x) for x in value if x]
        return ", ".join(p for p in parts if p)
    return _hex32(value)


def _tx_hash_list(value: Any) -> str:
    """Comma-separated 0x tx hashes for SQL IN (...)."""
    if value is None or value == "":
        return ""

    def one(v: Any) -> str:
        s = str(v or "").strip().lower()
        if not s:
            return ""
        if s.startswith("\\x"):
            s = "0x" + s[2:]
        if not s.startswith("0x"):
            s = "0x" + s
        return s

    if isinstance(value, str) and "," in value:
        parts = [one(x) for x in value.split(",")]
        return ", ".join(p for p in parts if p)
    if isinstance(value, (list, tuple, set)):
        parts = [one(x) for x in value]
        return ", ".join(p for p in parts if p)
    return one(value)


def _render(sql_name: str, params: dict[str, Any]) -> str:
    """Load SQL by section name from ``queries.sql``, else legacy ``<name>.sql``."""
    sections = _load_sections()
    if sql_name in sections:
        text = sections[sql_name]
        source = f"queries.sql#{sql_name}"
    else:
        path = SQL_DIR / f"{sql_name}.sql"
        if not path.exists():
            known = ", ".join(sorted(sections)[:12])
            more = "…" if len(sections) > 12 else ""
            raise DuneError(
                f"SQL template not found: {sql_name} "
                f"(known: {known}{more})"
            )
        text = path.read_text(encoding="utf-8")
        source = path.name

    # Ignore placeholders inside SQL line comments so commented fallbacks
    # (e.g. transfer-based holders) do not force unused params.
    active = "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("--")
    )
    needed = set(re.findall(r"\{\{(\w+)\}\}", active))
    missing = needed - set(params)
    if missing:
        raise DuneError(f"{source}: missing placeholders {sorted(missing)}")

    def repl(m: re.Match[str]) -> str:
        return str(params[m.group(1)])

    return re.sub(r"\{\{(\w+)\}\}", repl, text).strip()


def _prep(params: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and normalize address-like params."""
    out = dict(params)
    out.setdefault("chain", "ethereum")
    out.setdefault("zero_address", _addr(_ZERO))
    out.setdefault("pool_filter", "")
    out.setdefault("block_filter", "")
    out.setdefault("owner_filter", "")
    out.setdefault("limit", 20000)
    # price_timeline / pool_tvl_timeline: day (month windows) or hour (week/day)
    out.setdefault("bucket", "day")

    for key in ("token", "pool", "npm", "zero_address"):
        if key in out:
            out[key] = _addr(out[key])
    for key in ("pool_list", "address_list"):
        if key in out:
            out[key] = _addr_list(out[key])
    if "pool_id_list" in out:
        out["pool_id_list"] = _hex32_list(out["pool_id_list"])
    if "tx_hash_list" in out:
        out["tx_hash_list"] = _tx_hash_list(out["tx_hash_list"])
    if "token_id_list" in out:
        raw = out["token_id_list"]
        if isinstance(raw, (list, tuple, set)):
            out["token_id_list"] = ", ".join(str(int(x)) for x in raw)
        else:
            out["token_id_list"] = str(raw)
    for key in ("from_block", "to_block", "limit"):
        if key in out and out[key] is not None:
            out[key] = int(out[key])
    return out


def _cache_key(sql_name: str, sql: str, params: dict[str, Any]) -> str:
    blob = json.dumps(
        {"sql_name": sql_name, "sql": re.sub(r"\s+", " ", sql), "params": params},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / "cache" / f"{key}.json"


def _cache_get(cache_dir: Path, key: str) -> Optional[list[dict[str, Any]]]:
    path = _cache_path(cache_dir, key)
    with _CACHE_LOCK:
        if not path.exists():
            return None
        try:
            rows = json.loads(path.read_text(encoding="utf-8")).get("rows")
            return rows if isinstance(rows, list) else None
        except Exception:
            return None


def _cache_put(cache_dir: Path, key: str, rows: list[dict[str, Any]]) -> None:
    path = _cache_path(cache_dir, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"cache_key": key, "row_count": len(rows), "rows": rows}
    tmp = path.with_suffix(".json.tmp")
    with _CACHE_LOCK:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def _is_quota_http(exc: BaseException) -> bool:
    """True for credit/payment/result-size limits (not transient 429 rate limits)."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 402:
        return True
    text = ""
    try:
        resp = getattr(exc, "response", None)
        if resp is not None:
            text = (resp.text or "")[:500].lower()
    except Exception:
        pass
    if status == 429 and "rate" in text:
        return False
    markers = (
        "payment required",
        "not enough credits",
        "credit",
        "datapoint",
        "too many rows",
        "result too large",
        "quota",
    )
    return any(m in text for m in markers)


def _execute_remote(
    sql: str,
    *,
    label: str,
    api_key: str,
    on_status: Optional[StatusFn] = None,
    poll_seconds: float = 2.5,
    max_polls: int = 240,
) -> list[dict[str, Any]]:
    headers = {"X-DUNE-API-KEY": api_key, "Content-Type": "application/json"}
    session = requests.Session()

    def req(method: str, url: str, timeout: float, body: Optional[dict] = None):
        last: Optional[BaseException] = None
        for attempt in range(1, 8):
            try:
                r = session.request(
                    method, url, headers=headers, json=body, timeout=timeout
                )
                r.raise_for_status()
                return r
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                last = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status != 429 and _is_quota_http(exc):
                    raise DuneQuotaError(
                        f"{label}: quota/size limit: {exc}"
                    ) from exc
                retryable = isinstance(
                    exc, (requests.Timeout, requests.ConnectionError)
                ) or status in (429, 500, 502, 503, 504)
                if not retryable or attempt >= 7:
                    break
                # 429: back off harder so status polling does not kill the run
                delay = min(5 * attempt, 45) if status == 429 else min(2 ** attempt, 20)
                print(
                    f"  [dune] {label}: HTTP {status or '?'} — retry "
                    f"{attempt}/7 in {delay}s"
                )
                time.sleep(delay)
        detail = ""
        try:
            response = getattr(last, "response", None)
            if response is not None and response.text:
                detail = " — {}".format(response.text[:1000].strip())
        except Exception:
            detail = ""
        raise DuneError(
            f"{label}: network/API error: {last}{detail}"
        ) from last

    # Dune's raw-SQL endpoint now expects an explicit current-engine tier.
    # Omitting it can route requests to the deprecated query engine.
    start = req(
        "POST",
        f"{_DUNE_API}/sql/execute",
        120,
        {"sql": sql, "performance": "medium"},
    )
    execution_id = start.json().get("execution_id")
    if not execution_id:
        raise DuneError("Dune SQL execute returned no execution_id")

    for i in range(max_polls):
        status = req("GET", f"{_DUNE_API}/execution/{execution_id}/status", 60)
        state = (status.json().get("state") or "").upper()
        if on_status is not None:
            on_status(i, state)
        if "COMPLETED" in state:
            break
        if "FAIL" in state or "CANCEL" in state:
            body = status.text[:500]
            if any(
                m in body.lower()
                for m in ("credit", "quota", "datapoint", "too large", "payment")
            ):
                raise DuneQuotaError(
                    f"Dune SQL execution {state}: {body}"
                )
            raise DuneError(f"Dune SQL execution {state}: {body}")
        if on_status is None and (i == 0 or (i + 1) % 10 == 0):
            print(f"  [waiting] {label} state={state or '?'} poll={i + 1}/{max_polls}")
        time.sleep(poll_seconds)
    else:
        raise DuneError("Dune SQL execution timed out")

    results = req("GET", f"{_DUNE_API}/execution/{execution_id}/results", 180)
    return (results.json().get("result") or {}).get("rows") or []


def _query_once(
    sql_name: str,
    *,
    cache_dir: Path,
    on_status: Optional[StatusFn],
    force_refresh: bool,
    api_key: str,
    prepared: dict[str, Any],
) -> list[dict[str, Any]]:
    sql = _render(sql_name, prepared)
    key = _cache_key(sql_name, sql, prepared)

    if not force_refresh:
        cached = _cache_get(cache_dir, key)
        if cached is not None:
            with _PRINT_LOCK:
                print(f"  [cache hit] {sql_name} ({len(cached)} rows)")
            if on_status is not None:
                on_status(-1, "CACHED")
            return cached

    fb = prepared.get("from_block")
    tb = prepared.get("to_block")
    span = ""
    if fb is not None and tb is not None:
        span = f" [{fb}-{tb}]"
    with _PRINT_LOCK:
        print(f"  [dune] {sql_name}{span} …")
    rows = _execute_remote(
        sql, label=f"{sql_name}{span}", api_key=api_key, on_status=on_status
    )
    _cache_put(cache_dir, key, rows)
    with _PRINT_LOCK:
        print(f"  [cache save] {sql_name}{span} ({len(rows)} rows)")
    return rows


def _block_chunks(from_block: int, to_block: int, chunk_blocks: int) -> list[tuple[int, int]]:
    if to_block < from_block:
        return []
    out: list[tuple[int, int]] = []
    cur = from_block
    step = max(1, int(chunk_blocks))
    while cur <= to_block:
        end = min(cur + step - 1, to_block)
        out.append((cur, end))
        cur = end + 1
    return out


def query(
    sql_name: str,
    *,
    cache_dir: Optional[str | Path] = None,
    on_status: Optional[StatusFn] = None,
    force_refresh: bool = False,
    chunk_blocks: Optional[int] = None,
    min_chunk_blocks: int = 200,
    chunk_pause_s: float = 2.0,
    **params: Any,
) -> list[dict[str, Any]]:
    """Load SQL section ``sql_name`` from ``dune_sql/queries.sql``, run, return rows.

    When ``from_block``/``to_block`` span a large window (or a quota/size error
    hits), the range is split into multiple Dune queries and concatenated —
    instead of falling back to RPC.

    ``chunk_blocks``:
      - ``None`` (default): auto — chunk when window > 3000 blocks (size 2000)
      - ``0`` / ``False``: never chunk
      - ``int``: fixed chunk size in blocks
    """
    api_key = (os.environ.get("DUNE_API_KEY") or "").strip()
    if not api_key:
        raise DuneError("DUNE_API_KEY is not set")

    prepared = _prep(params)
    root = Path(cache_dir) if cache_dir else Path("dune_cache") / "query"
    root.mkdir(parents=True, exist_ok=True)

    fb = prepared.get("from_block")
    tb = prepared.get("to_block")
    has_range = isinstance(fb, int) and isinstance(tb, int) and tb >= fb
    span = (tb - fb + 1) if has_range else 0

    if chunk_blocks is None:
        use_chunk = has_range and span > 3000
        size = 2000
    elif not chunk_blocks:
        use_chunk = False
        size = span or 1
    else:
        use_chunk = has_range and span > int(chunk_blocks)
        size = int(chunk_blocks)

    if not use_chunk:
        try:
            return _query_once(
                sql_name,
                cache_dir=root,
                on_status=on_status,
                force_refresh=force_refresh,
                api_key=api_key,
                prepared=prepared,
            )
        except DuneQuotaError:
            if not has_range or span <= min_chunk_blocks:
                raise
            print(
                f"  [dune] {sql_name}: quota/size on full window "
                f"[{fb}-{tb}] — splitting …"
            )
            size = max(min_chunk_blocks, span // 2)

    # Chunked / adaptive path
    pending: list[tuple[int, int]] = _block_chunks(int(fb), int(tb), size)
    merged: list[dict[str, Any]] = []
    first = True
    while pending:
        a, b = pending.pop(0)
        piece = dict(prepared)
        piece["from_block"] = a
        piece["to_block"] = b
        try:
            if not first and chunk_pause_s > 0:
                time.sleep(chunk_pause_s)
            first = False
            rows = _query_once(
                sql_name,
                cache_dir=root,
                on_status=on_status,
                force_refresh=force_refresh,
                api_key=api_key,
                prepared=piece,
            )
            merged.extend(rows)
        except DuneQuotaError as exc:
            width = b - a + 1
            if width <= min_chunk_blocks:
                raise DuneQuotaError(
                    f"{sql_name} [{a}-{b}]: still over quota after min chunk "
                    f"({min_chunk_blocks} blocks): {exc}"
                ) from exc
            mid = a + width // 2 - 1
            left, right = (a, mid), (mid + 1, b)
            print(
                f"  [dune] {sql_name} [{a}-{b}] over quota — "
                f"split → [{left[0]}-{left[1]}] + [{right[0]}-{right[1]}]"
            )
            pending.insert(0, right)
            pending.insert(0, left)

    print(f"  [dune] {sql_name}: {len(merged)} rows across chunked window")
    return merged


def query_parallel(
    jobs: list[tuple[str, dict[str, Any]]],
    *,
    max_workers: int = 4,
) -> list[list[dict[str, Any]]]:
    """Run independent ``query(sql_name, **kwargs)`` jobs concurrently.

    ``jobs`` is a list of ``(sql_name, kwargs)``. Results are returned in the
    same order. Any exception from a job is raised after all workers finish
    (first failure wins).
    """
    if not jobs:
        return []
    if len(jobs) == 1:
        name, kwargs = jobs[0]
        return [query(name, **kwargs)]

    results: list[Optional[list[dict[str, Any]]]] = [None] * len(jobs)
    errors: list[BaseException] = []

    def _run(idx: int, name: str, kwargs: dict[str, Any]) -> None:
        try:
            results[idx] = query(name, **kwargs)
        except BaseException as exc:  # noqa: BLE001 — collect then re-raise
            errors.append(exc)

    workers = max(1, min(int(max_workers), len(jobs)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [
            ex.submit(_run, i, name, dict(kwargs))
            for i, (name, kwargs) in enumerate(jobs)
        ]
        for fut in as_completed(futs):
            fut.result()
    if errors:
        raise errors[0]
    return [r or [] for r in results]


# Aliases some call sites may prefer
DuneQueryError = DuneError
DuneCollectorError = DuneError
