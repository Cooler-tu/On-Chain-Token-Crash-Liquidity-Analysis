"""Event indexer with chunk-level checkpoint/resume.

Progress is saved after every successful eth_getLogs chunk:
  - output/event_indexer_checkpoint.json
  - output/indexer_cache/*.jsonl

Re-running with the same output_dir / token / from_block continues from the
last completed block. Ctrl+C is safe.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

from web3 import Web3
from web3.types import EventData

from ..client import get_contract
from ..discovery.log_utils import DEFAULT_CHUNK_SIZE, get_logs_chunked
from ..models import NormalizedEvent, VerifiedPool


def _fetch_block_timestamps(
    w3: Web3, block_numbers: set[int], cache: Optional[dict[int, int]] = None
) -> dict[int, int]:
    if cache is None:
        cache = {}
    for bn in sorted(block_numbers):
        if bn in cache:
            continue
        try:
            block = w3.eth.get_block(bn)
            cache[bn] = block.get("timestamp", 0)
        except Exception:
            cache[bn] = 0
    return cache


def _load_checkpoint(checkpoint_path: Path) -> dict[str, Any]:
    if checkpoint_path.exists():
        with open(checkpoint_path) as f:
            data = json.load(f)
        if "streams" not in data:
            # Migrate legacy flat keys → streams map
            streams = {
                k: v for k, v in data.items()
                if k not in ("meta", "streams") and isinstance(v, int)
            }
            return {"meta": {}, "streams": streams}
        return data
    return {"meta": {}, "streams": {}}


def _save_checkpoint(checkpoint_path: Path, state: dict[str, Any]) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = checkpoint_path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, default=str)
    tmp.replace(checkpoint_path)


def _stream_key(kind: str, address: str, event_name: str) -> str:
    return "{}:{}:{}".format(kind, address.lower(), event_name)


def _stream_cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / "{}.jsonl".format(key.replace(":", "_"))


def _dedupe_events(events: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for e in events:
        key = (
            e.get("transaction_hash"),
            e.get("log_index"),
            e.get("event_type"),
            e.get("source_event"),
            e.get("_stream"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return _dedupe_events(rows)


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _progress(msg: str) -> None:
    print("  {}".format(msg), file=sys.stderr, flush=True)


def _event_to_dict(evt: NormalizedEvent) -> dict:
    return evt.__dict__ if hasattr(evt, "__dict__") else dict(evt)


def _tx_hash_hex(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "hex"):
        h = value.hex()
        return h if h.startswith("0x") else "0x" + h
    return str(value)


def _prepare_checkpoint(
    checkpoint: dict[str, Any],
    target_token: str,
    from_block: int,
    to_block: int,
    cache_dir: Path,
) -> dict[str, Any]:
    meta = checkpoint.setdefault("meta", {})
    streams = checkpoint.setdefault("streams", {})
    token = Web3.to_checksum_address(target_token)
    prev_token = meta.get("target_token", "")
    prev_from = meta.get("from_block")

    incompatible = False
    if prev_token and prev_token.lower() != token.lower():
        incompatible = True
    if prev_from is not None and int(prev_from) != int(from_block):
        incompatible = True

    if incompatible:
        _progress("Checkpoint incompatible (token/from_block changed); resetting cache")
        if cache_dir.exists():
            for p in cache_dir.glob("*.jsonl"):
                p.unlink()
            for p in cache_dir.glob("pm_token_pool_map_*.json"):
                p.unlink()
        streams.clear()

    # Migrate old flat keys like v2_0xabc into nothing useful for per-event streams;
    # drop non stream-shaped keys that are ints at top-level leftovers
    bad = [k for k in list(streams) if ":" not in str(k)]
    for k in bad:
        streams.pop(k, None)

    meta["target_token"] = token
    meta["from_block"] = from_block
    meta["to_block"] = to_block
    return checkpoint


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------

def _normalize_v2_event(
    evt: EventData,
    pool: VerifiedPool,
    block_timestamps: dict[int, int],
) -> Optional[NormalizedEvent]:
    args = evt["args"]
    bn = evt["blockNumber"]
    evt_name = evt.get("event", "")
    base = {
        "block_number": bn,
        "block_timestamp": block_timestamps.get(bn, 0),
        "transaction_hash": _tx_hash_hex(evt["transactionHash"]),
        "log_index": evt.get("logIndex", 0),
        "protocol": "uniswap",
        "version": "v2",
        "pool_address": pool.pool_address,
        "verified": True,
    }
    if evt_name == "Swap":
        return NormalizedEvent(
            **base,
            event_type="SWAP",
            actor=Web3.to_checksum_address(args["sender"]),
            recipient=Web3.to_checksum_address(args["to"]),
            token0_amount=str(args["amount0In"]) if int(args["amount0In"]) > 0 else "-{}".format(args['amount0Out']),
            token1_amount=str(args["amount1In"]) if int(args["amount1In"]) > 0 else "-{}".format(args['amount1Out']),
            source_event="Swap",
        )
    if evt_name == "Mint":
        return NormalizedEvent(
            **base,
            event_type="LIQUIDITY_ADD",
            actor=Web3.to_checksum_address(args["sender"]),
            recipient=Web3.to_checksum_address(args["sender"]),
            token0_amount=str(args["amount0"]),
            token1_amount=str(args["amount1"]),
            source_event="Mint",
        )
    if evt_name == "Burn":
        return NormalizedEvent(
            **base,
            event_type="LIQUIDITY_REMOVE",
            actor=Web3.to_checksum_address(args["sender"]),
            recipient=Web3.to_checksum_address(args["to"]),
            token0_amount=str(args["amount0"]),
            token1_amount=str(args["amount1"]),
            source_event="Burn",
        )
    return None


def _normalize_v3_pool_event(
    evt: EventData,
    pool: VerifiedPool,
    block_timestamps: dict[int, int],
) -> Optional[NormalizedEvent]:
    args = evt["args"]
    bn = evt["blockNumber"]
    evt_name = evt.get("event", "")
    base = {
        "block_number": bn,
        "block_timestamp": block_timestamps.get(bn, 0),
        "transaction_hash": _tx_hash_hex(evt["transactionHash"]),
        "log_index": evt.get("logIndex", 0),
        "protocol": "uniswap",
        "version": "v3",
        "pool_address": pool.pool_address,
        "verified": True,
    }
    if evt_name == "Swap":
        amount0 = int(args["amount0"])
        amount1 = int(args["amount1"])
        return NormalizedEvent(
            **base,
            event_type="SWAP",
            actor=Web3.to_checksum_address(args["sender"]),
            recipient=Web3.to_checksum_address(args["recipient"]),
            token0_amount=str(abs(amount0)),
            token1_amount=str(abs(amount1)),
            source_event="Swap",
        )
    if evt_name == "Mint":
        return NormalizedEvent(
            **base,
            event_type="LIQUIDITY_ADD",
            actor=Web3.to_checksum_address(args["sender"]),
            recipient=Web3.to_checksum_address(args["owner"]),
            token0_amount=str(args["amount0"]),
            token1_amount=str(args["amount1"]),
            liquidity_delta=str(args["amount"]),
            source_event="Mint",
        )
    if evt_name == "Burn":
        owner = Web3.to_checksum_address(args["owner"])
        return NormalizedEvent(
            **base,
            event_type="LIQUIDITY_REMOVE",
            actor=owner,
            recipient=owner,
            token0_amount=str(args["amount0"]),
            token1_amount=str(args["amount1"]),
            liquidity_delta="-{}".format(args['amount']),
            source_event="Burn",
        )
    if evt_name == "Collect":
        return NormalizedEvent(
            **base,
            event_type="COLLECT_FEES",
            actor=Web3.to_checksum_address(args["owner"]),
            recipient=Web3.to_checksum_address(args["recipient"]),
            token0_amount=str(args["amount0"]),
            token1_amount=str(args["amount1"]),
            source_event="Collect",
        )
    return None


def _normalize_v3_position_event(
    evt: EventData,
    pool_map: dict,
    block_timestamps: dict[int, int],
) -> Optional[NormalizedEvent]:
    args = evt["args"]
    bn = evt["blockNumber"]
    evt_name = evt.get("event", "")
    token_id = int(args.get("tokenId", 0))
    base = {
        "block_number": bn,
        "block_timestamp": block_timestamps.get(bn, 0),
        "transaction_hash": _tx_hash_hex(evt["transactionHash"]),
        "log_index": evt.get("logIndex", 0),
        "protocol": "uniswap",
        "version": "v3",
        "verified": True,
    }
    pm_pool = pool_map.get(token_id)
    pool_addr = pm_pool.pool_address if isinstance(pm_pool, VerifiedPool) else (
        pm_pool if isinstance(pm_pool, str) else ""
    )
    if evt_name == "Transfer":
        return NormalizedEvent(
            **base,
            event_type="POSITION_TRANSFER",
            actor=Web3.to_checksum_address(args["from"]),
            recipient=Web3.to_checksum_address(args["to"]),
            pool_address=pool_addr,
            source_event="Transfer",
            nft_token_id=token_id,
        )
    if evt_name == "IncreaseLiquidity":
        return NormalizedEvent(
            **base,
            event_type="LIQUIDITY_ADD",
            pool_address=pool_addr,
            actor="",
            recipient="",
            token0_amount=str(args["amount0"]),
            token1_amount=str(args["amount1"]),
            liquidity_delta=str(args["liquidity"]),
            source_event="IncreaseLiquidity",
            nft_token_id=token_id,
        )
    if evt_name == "DecreaseLiquidity":
        return NormalizedEvent(
            **base,
            event_type="LIQUIDITY_REMOVE",
            pool_address=pool_addr,
            actor="",
            recipient="",
            token0_amount=str(args["amount0"]),
            token1_amount=str(args["amount1"]),
            liquidity_delta="-{}".format(args['liquidity']),
            source_event="DecreaseLiquidity",
            nft_token_id=token_id,
        )
    if evt_name == "Collect":
        return NormalizedEvent(
            **base,
            event_type="COLLECT_FEES",
            pool_address=pool_addr,
            actor="",
            recipient=Web3.to_checksum_address(args["recipient"]),
            token0_amount=str(args["amount0"]),
            token1_amount=str(args["amount1"]),
            source_event="Collect",
            nft_token_id=token_id,
        )
    return None


def _pool_id_hex(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, int):
        return "0x" + value.to_bytes(32, "big").hex()
    s = str(value)
    if s.startswith("0x"):
        return s
    return "0x" + s


def _topic_filter_ids(raw_ids: list[str]) -> list[str]:
    """Normalize bytes32 pool IDs for eth_getLogs argument_filters."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_ids:
        pid = _pool_id_hex(raw).lower()
        if not pid:
            continue
        # eth_getLogs topics are 32-byte; pad short values on the left.
        body = pid[2:] if pid.startswith("0x") else pid
        if len(body) < 64:
            pid = "0x" + body.zfill(64)
        elif len(body) > 64:
            pid = "0x" + body[-64:]
        if pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
    return out


def _id_argument_filter(field: str, raw_ids: list[str]) -> Optional[dict[str, Any]]:
    ids = _topic_filter_ids(raw_ids)
    if not ids:
        return None
    return {field: ids[0] if len(ids) == 1 else ids}


def _normalize_v4_pool_event(
    evt: EventData,
    pools_by_id: dict[str, VerifiedPool],
    block_timestamps: dict[int, int],
) -> Optional[NormalizedEvent]:
    args = evt["args"]
    bn = evt["blockNumber"]
    evt_name = evt.get("event", "")
    pool_id = _pool_id_hex(args.get("id"))
    pool = pools_by_id.get(pool_id.lower())
    if pool is None:
        return None
    base = {
        "block_number": bn,
        "block_timestamp": block_timestamps.get(bn, 0),
        "transaction_hash": _tx_hash_hex(evt["transactionHash"]),
        "log_index": evt.get("logIndex", 0),
        "protocol": "uniswap",
        "version": "v4",
        "pool_address": pool.pool_address,
        "verified": True,
    }
    if evt_name == "Swap":
        amount0 = int(args["amount0"])
        amount1 = int(args["amount1"])
        return NormalizedEvent(
            **base,
            event_type="SWAP",
            actor=Web3.to_checksum_address(args["sender"]),
            recipient="",
            token0_amount=str(abs(amount0)),
            token1_amount=str(abs(amount1)),
            source_event="Swap",
        )
    if evt_name == "ModifyLiquidity":
        delta = int(args["liquidityDelta"])
        # PositionManager uses bytes32(tokenId) as salt
        nft_id = None
        salt = args.get("salt")
        if salt is not None:
            try:
                if isinstance(salt, (bytes, bytearray)):
                    nft_id = int.from_bytes(salt, "big")
                elif isinstance(salt, int):
                    nft_id = int(salt)
                else:
                    s = str(salt)
                    if s.startswith("0x"):
                        nft_id = int(s, 16)
                    else:
                        nft_id = int(s)
            except Exception:
                nft_id = None
        return NormalizedEvent(
            **base,
            event_type="LIQUIDITY_ADD" if delta >= 0 else "LIQUIDITY_REMOVE",
            actor=Web3.to_checksum_address(args["sender"]),
            recipient=Web3.to_checksum_address(args["sender"]),
            liquidity_delta=str(delta),
            source_event="ModifyLiquidity",
            nft_token_id=nft_id,
        )
    return None


def _normalize_v4_position_event(
    evt: EventData,
    pool_map: dict,
    block_timestamps: dict[int, int],
) -> Optional[NormalizedEvent]:
    args = evt["args"]
    bn = evt["blockNumber"]
    evt_name = evt.get("event", "")
    token_id = int(args.get("id", args.get("tokenId", 0)))
    base = {
        "block_number": bn,
        "block_timestamp": block_timestamps.get(bn, 0),
        "transaction_hash": _tx_hash_hex(evt["transactionHash"]),
        "log_index": evt.get("logIndex", 0),
        "protocol": "uniswap",
        "version": "v4",
        "verified": True,
    }
    pm_pool = pool_map.get(token_id)
    pool_addr = pm_pool.pool_address if isinstance(pm_pool, VerifiedPool) else (
        pm_pool if isinstance(pm_pool, str) else ""
    )
    if evt_name == "Transfer":
        return NormalizedEvent(
            **base,
            event_type="POSITION_TRANSFER",
            actor=Web3.to_checksum_address(args["from"]),
            recipient=Web3.to_checksum_address(args["to"]),
            pool_address=pool_addr,
            source_event="Transfer",
            nft_token_id=token_id,
        )
    if evt_name == "ModifyLiquidity":
        delta = int(args.get("liquidityChange", 0))
        return NormalizedEvent(
            **base,
            event_type="LIQUIDITY_ADD" if delta >= 0 else "LIQUIDITY_REMOVE",
            pool_address=pool_addr,
            actor="",
            recipient="",
            liquidity_delta=str(delta),
            source_event="ModifyLiquidity",
            nft_token_id=token_id,
        )
    return None


class _StreamIndexer:
    """One event stream with per-chunk checkpoint + JSONL persist."""

    def __init__(
        self,
        w3: Web3,
        key: str,
        from_block: int,
        to_block: int,
        checkpoint: dict[str, Any],
        checkpoint_path: Path,
        cache_dir: Path,
        ts_cache: dict[int, int],
        normalize: Callable[[EventData, dict[int, int]], Optional[NormalizedEvent]],
        on_raw_chunk: Optional[Callable[[list[EventData]], None]] = None,
        argument_filters: Optional[dict[str, Any]] = None,
    ):
        self.w3 = w3
        self.key = key
        self.from_block = from_block
        self.to_block = to_block
        self.checkpoint = checkpoint
        self.checkpoint_path = checkpoint_path
        self.cache_path = _stream_cache_path(cache_dir, key)
        self.ts_cache = ts_cache
        self.normalize = normalize
        self.on_raw_chunk = on_raw_chunk
        self.argument_filters = argument_filters
        self.events: list[dict] = _load_jsonl(self.cache_path)

    @property
    def last_block(self) -> int:
        return int(self.checkpoint["streams"].get(self.key, self.from_block - 1))

    def run(self, event_obj) -> list[dict]:
        start = max(self.from_block, self.last_block + 1)
        if start > self.to_block:
            _progress("{} already complete through {}".format(self.key, self.last_block))
            return self.events

        _progress("{} resuming from block {} → {}".format(self.key, start, self.to_block))
        stream_started = time.time()
        resume_from = start
        last_logged_block = start - 1
        last_log_time = stream_started

        def on_chunk(chunk_start: int, chunk_end: int, entries: list[EventData]) -> None:
            nonlocal last_logged_block, last_log_time
            if self.on_raw_chunk is not None:
                self.on_raw_chunk(entries)
            block_nums = {e["blockNumber"] for e in entries}
            timestamps = _fetch_block_timestamps(self.w3, block_nums, self.ts_cache)
            new_rows: list[dict] = []
            for evt in entries:
                ne = self.normalize(evt, timestamps)
                if ne is not None:
                    row = _event_to_dict(ne)
                    row["_stream"] = self.key
                    new_rows.append(row)
            _append_jsonl(self.cache_path, new_rows)
            self.events.extend(new_rows)
            self.checkpoint["streams"][self.key] = chunk_end
            _save_checkpoint(self.checkpoint_path, self.checkpoint)

            now = time.time()
            should_log = (
                len(new_rows) > 0
                or chunk_end - last_logged_block >= 500
                or now - last_log_time >= 12
                or chunk_end >= self.to_block
            )
            if should_log:
                done = max(0, chunk_end - resume_from + 1)
                elapsed = max(0.001, now - stream_started)
                speed = done / elapsed
                remaining = max(0, self.to_block - chunk_end)
                eta_s = int(remaining / speed) if speed > 0 else 0
                _progress(
                    "{} {:,}/{:,} ({:.1f}%) +{} evt | ~{:.0f} blk/s | ETA {}s".format(
                        self.key,
                        chunk_end,
                        self.to_block,
                        100.0 * (chunk_end - self.from_block + 1)
                        / max(1, self.to_block - self.from_block + 1),
                        len(self.events),
                        speed,
                        eta_s,
                    )
                )
                last_logged_block = chunk_end
                last_log_time = now

        # Start large; adaptive logic shrinks (and caps) if the RPC rejects the range.
        # Free-tier Alchemy often falls to ~10; Infura/paid nodes can stay at 2k+.
        get_logs_chunked(
            event_obj,
            start,
            self.to_block,
            argument_filters=self.argument_filters,
            chunk_size=DEFAULT_CHUNK_SIZE,
            on_chunk=on_chunk,
        )
        self.checkpoint["streams"][self.key] = self.to_block
        _save_checkpoint(self.checkpoint_path, self.checkpoint)
        return self.events


def _load_pm_token_map(cache_dir: Path, pm_address: str) -> dict[int, str]:
    path = cache_dir / "pm_token_pool_map_{}.json".format(pm_address.lower())
    if not path.exists():
        return {}
    with open(path) as f:
        raw = json.load(f)
    return {int(k): v for k, v in raw.items()}


def _save_pm_token_map(cache_dir: Path, pm_address: str, mapping: dict[int, str]) -> None:
    path = cache_dir / "pm_token_pool_map_{}.json".format(pm_address.lower())
    _write_json(path, {str(k): v for k, v in mapping.items()})


def _public_event(e: dict) -> dict:
    return {k: v for k, v in e.items() if not k.startswith("_")}


def _assemble_outputs(
    events: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    swaps: list[dict] = []
    liquidity: list[dict] = []
    transfers: list[dict] = []
    position_events: list[dict] = []

    for e in events:
        stream = e.get("_stream", "")
        et = e.get("event_type", "")
        src = e.get("source_event", "")
        pub = _public_event(e)

        if stream.startswith("token:"):
            transfers.append(pub)
        elif stream.startswith("v3_pm:"):
            # Keep PM liquidity + NFT transfers so position analysis can recover tokenIds.
            if et in ("LIQUIDITY_ADD", "LIQUIDITY_REMOVE", "COLLECT_FEES", "POSITION_TRANSFER"):
                if et in ("LIQUIDITY_ADD", "LIQUIDITY_REMOVE", "COLLECT_FEES"):
                    liquidity.append(pub)
                else:
                    position_events.append(pub)
        # V2 / V3 / V4 pool events (v4id = topic-filtered PoolManager streams)
        elif (
            stream.startswith("v2:")
            or stream.startswith("v3:")
            or stream.startswith("v4:")
            or stream.startswith("v4id:")
        ):
            if et == "SWAP":
                swaps.append(pub)
            elif src in ("Mint", "Burn", "Collect", "ModifyLiquidity"):
                liquidity.append(pub)

        # V4 Position Manager events
        elif stream.startswith("v4pm:"):
            if et in ("LIQUIDITY_ADD", "LIQUIDITY_REMOVE", "POSITION_TRANSFER"):
                if et in ("LIQUIDITY_ADD", "LIQUIDITY_REMOVE"):
                    liquidity.append(pub)
                else:
                    position_events.append(pub)

        # V1 pool events
        elif stream.startswith("v1:"):
            if et == "SWAP":
                swaps.append(pub)
            elif src in ("AddLiquidity", "RemoveLiquidity"):
                liquidity.append(pub)

        # Curve pool events
        elif (
            stream.startswith("curve:")
            or stream.startswith("curve_v1:")
            or stream.startswith("curve_crypto:")
        ):
            if et == "SWAP":
                swaps.append(pub)
            elif src in ("AddLiquidity", "RemoveLiquidity", "RemoveLiquidityOne", "RemoveLiquidityImbalance"):
                liquidity.append(pub)

        # Balancer V2 pool events (balid = topic-filtered Vault streams)
        elif stream.startswith("balancer:") or stream.startswith("balid:"):
            if et == "SWAP":
                swaps.append(pub)
            elif et in ("LIQUIDITY_ADD", "LIQUIDITY_REMOVE"):
                liquidity.append(pub)

    return swaps, liquidity, transfers, position_events


def _flush_outputs(
    out: Path,
    all_stream_events: list[dict],
    from_block: Optional[int] = None,
    to_block: Optional[int] = None,
) -> dict[str, list]:
    events = _dedupe_events(all_stream_events)
    if from_block is not None and to_block is not None:
        events = [
            e for e in events
            if from_block <= int(e.get("block_number", 0)) <= to_block
        ]
    swaps, liquidity, transfers, position_events = _assemble_outputs(events)
    _write_json(out / "swaps.json", swaps)
    _write_json(out / "liquidity_events.json", liquidity)
    _write_json(out / "transfers.json", transfers)
    _write_json(out / "position_events.json", position_events)
    return {
        "swaps": swaps,
        "liquidity_events": liquidity,
        "transfers": transfers,
        "position_events": position_events,
    }



# ---------------------------------------------------------------------------
# Curve normalizer
# ---------------------------------------------------------------------------

def _normalize_curve_event(evt, pool, block_timestamps):
    from ..models import NormalizedEvent
    from web3 import Web3
    args = evt.get("args", {})
    bn = evt["blockNumber"]
    evt_name = evt.get("event", "")
    base = {
        "block_number": bn,
        "block_timestamp": block_timestamps.get(bn, 0),
        "transaction_hash": _tx_hash_hex(evt["transactionHash"]),
        "log_index": evt.get("logIndex", 0),
        "protocol": "curve",
        "version": pool.version or "v1",
        "pool_address": pool.pool_address,
        "verified": True,
    }
    try:
        if evt_name == "TokenExchange" or evt_name == "TokenExchangeUnderlying":
            buyer = Web3.to_checksum_address(args.get("buyer", ""))
            tokens_sold = int(args.get("tokens_sold", 0))
            tokens_bought = int(args.get("tokens_bought", 0))
            return NormalizedEvent(
                **base,
                event_type="SWAP",
                actor=buyer,
                recipient=buyer,
                token0_amount=str(tokens_sold),
                token1_amount=str(tokens_bought),
                source_event=evt_name,
            )
        if evt_name in ("AddLiquidity",):
            provider = Web3.to_checksum_address(args.get("provider", ""))
            return NormalizedEvent(
                **base,
                event_type="LIQUIDITY_ADD",
                actor=provider,
                recipient=provider,
                token0_amount=str(args.get("token_amounts", [0])[0]),
                token1_amount=str(args.get("token_amounts", [0, 0])[1]),
                source_event=evt_name,
            )
        if evt_name in ("RemoveLiquidity", "RemoveLiquidityImbalance"):
            provider = Web3.to_checksum_address(args.get("provider", ""))
            return NormalizedEvent(
                **base,
                event_type="LIQUIDITY_REMOVE",
                actor=provider,
                recipient=provider,
                token0_amount=str(args.get("token_amounts", [0])[0]),
                token1_amount=str(args.get("token_amounts", [0, 0])[1]),
                source_event=evt_name,
            )
        if evt_name == "RemoveLiquidityOne":
            provider = Web3.to_checksum_address(args.get("provider", ""))
            return NormalizedEvent(
                **base,
                event_type="LIQUIDITY_REMOVE",
                actor=provider,
                recipient=provider,
                token0_amount=str(args.get("coin_amount", 0)),
                token1_amount="0",
                source_event=evt_name,
            )
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Balancer V2 normalizer
# ---------------------------------------------------------------------------

def _normalize_balancer_event(evt, pool_id_map, block_timestamps):
    from ..models import NormalizedEvent
    from web3 import Web3
    args = evt.get("args", {})
    bn = evt["blockNumber"]
    evt_name = evt.get("event", "")
    try:
        pool_id = args.get("poolId")
        if pool_id is None:
            topics = evt.get("topics") or []
            pool_id = topics[1] if len(topics) > 1 else None
        if pool_id is not None:
            if hasattr(pool_id, "hex"):
                pool_id_hex = pool_id.hex()
            else:
                pool_id_hex = str(pool_id)
        else:
            return None
    except Exception:
        return None

    pool_addr = pool_id_map.get(pool_id_hex.lower(), "")
    base = {
        "block_number": bn,
        "block_timestamp": block_timestamps.get(bn, 0),
        "transaction_hash": _tx_hash_hex(evt["transactionHash"]),
        "log_index": evt.get("logIndex", 0),
        "protocol": "balancer",
        "version": "v2",
        "pool_address": pool_addr,
        "verified": True,
    }
    try:
        if evt_name == "Swap":
            token_in = Web3.to_checksum_address(args.get("tokenIn", ""))
            token_out = Web3.to_checksum_address(args.get("tokenOut", ""))
            amount_in = int(args.get("amountIn", 0))
            amount_out = int(args.get("amountOut", 0))
            actor = Web3.to_checksum_address(args.get("sender", args.get("liquidityProvider", "")))
            return NormalizedEvent(
                **base,
                event_type="SWAP",
                actor=actor,
                recipient=actor,
                token0_amount=str(amount_in),
                token1_amount=str(amount_out),
                source_event="Swap",
            )
        if evt_name == "PoolBalanceChanged":
            provider = Web3.to_checksum_address(args.get("liquidityProvider", ""))
            deltas = [int(d) for d in args.get("deltas", [0])]
            total_delta = sum(abs(d) for d in deltas)
            event_type = "LIQUIDITY_ADD" if any(d > 0 for d in deltas) else "LIQUIDITY_REMOVE"
            return NormalizedEvent(
                **base,
                event_type=event_type,
                actor=provider,
                recipient=provider,
                token0_amount=str(total_delta),
                token1_amount="0",
                source_event=evt_name,
            )
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Curve indexer
# ---------------------------------------------------------------------------

def index_curve_pool_events(
    w3, pool, from_block, to_block, checkpoint, checkpoint_path, cache_dir, ts_cache,
):
    from ..client import get_contract
    events = []
    abi_name = "curve_pool_crypto" if pool.version == "v2" else "curve_pool"
    contract = get_contract(w3, pool.pool_address, abi_name)
    stream_prefix = "curve_crypto" if pool.version == "v2" else "curve_v1"
    event_names = (
        ("TokenExchange",)
        if pool.version == "v2"
        else ("TokenExchange", "AddLiquidity", "RemoveLiquidity",
              "RemoveLiquidityOne", "RemoveLiquidityImbalance",
              "TokenExchangeUnderlying")
    )
    for evt_name in event_names:
        if not hasattr(contract.events, evt_name):
            continue
        key = _stream_key(stream_prefix, pool.pool_address, evt_name)

        def make_norm(name=evt_name):
            def _norm(evt, timestamps):
                if not getattr(evt, "event", None):
                    evt = dict(evt)
                    evt["event"] = name
                return _normalize_curve_event(evt, pool, timestamps)
            return _norm

        stream = _StreamIndexer(
            w3, key, from_block, to_block, checkpoint, checkpoint_path,
            cache_dir, ts_cache, make_norm(),
        )
        try:
            events.extend(stream.run(getattr(contract.events, evt_name)))
        except Exception as exc:
            _progress("{} skipped: {}".format(key, exc))
    return events


# ---------------------------------------------------------------------------
# Balancer V2 indexer
# ---------------------------------------------------------------------------

def index_balancer_events(
    w3, vault_address, verified_pools, from_block, to_block,
    checkpoint, checkpoint_path, cache_dir, ts_cache,
):
    from ..client import get_contract
    vault_addr = Web3.to_checksum_address(vault_address)
    contract = get_contract(w3, vault_addr, "balancer_vault")

    # Build pool ID -> pool address map from each pool's on-chain getPoolId().
    # Dune's pool_address is the pool contract; the Vault emits Swap/PoolBalanceChanged
    # with the real bytes32 poolId, so address-padded IDs are not reliable.
    pool_id_map = {}
    for p in verified_pools:
        if p.protocol == "balancer" and p.verified:
            try:
                if p.pool_id:
                    pid = p.pool_id
                else:
                    raw_pid = w3.eth.call({
                        "to": Web3.to_checksum_address(p.pool_address),
                        "data": "0xf89b4d55",
                    })
                    pid = raw_pid.hex() if hasattr(raw_pid, "hex") else str(raw_pid)
                pool_id_map[_pool_id_hex(pid).lower()] = p.pool_address
            except Exception as exc:
                _progress("balancer pool {} skipped (no getPoolId): {}".format(
                    p.pool_address, exc
                ))

    if not pool_id_map:
        return []

    # Vault is a singleton — filter by indexed poolId at eth_getLogs time.
    id_filter = _id_argument_filter("poolId", list(pool_id_map.keys()))
    _progress(
        "balancer {}: topic-filter {} poolId(s)".format(
            vault_addr, len(pool_id_map)
        )
    )

    events = []
    for evt_name in ("Swap", "PoolBalanceChanged"):
        if not hasattr(contract.events, evt_name):
            continue
        # Stream key versioned (`balid`) so old unfiltered vault scans are not resumed.
        key = _stream_key("balid", vault_addr, evt_name)

        def make_norm(name=evt_name, pim=pool_id_map):
            def _norm(evt, timestamps):
                if not getattr(evt, "event", None):
                    evt = dict(evt)
                    evt["event"] = name
                return _normalize_balancer_event(evt, pim, timestamps)
            return _norm

        stream = _StreamIndexer(
            w3, key, from_block, to_block, checkpoint, checkpoint_path,
            cache_dir, ts_cache, make_norm(), argument_filters=id_filter,
        )
        try:
            events.extend(stream.run(getattr(contract.events, evt_name)))
        except Exception as exc:
            _progress("balancer {} skipped: {}".format(evt_name, exc))
    return events


def _normalize_v1_event(
    evt,
    pool,
    block_timestamps,
):
    """Normalize V1 exchange events into NormalizedEvent format."""
    from ..models import NormalizedEvent
    from web3 import Web3
    args = evt.get("args", {})
    bn = evt["blockNumber"]
    evt_name = evt.get("event", "")
    base = {
        "block_number": bn,
        "block_timestamp": block_timestamps.get(bn, 0),
        "transaction_hash": _tx_hash_hex(evt["transactionHash"]),
        "log_index": evt.get("logIndex", 0),
        "protocol": "uniswap",
        "version": "v1",
        "pool_address": pool.pool_address,
        "verified": True,
    }
    try:
        if evt_name == "EthPurchase":
            buyer_key = "buyer" if "buyer" in args else "_buyer"
            tokens_key = "tokens_bought" if "tokens_bought" in args else "_tokens_bought"
            return NormalizedEvent(
                **base,
                event_type="SWAP",
                actor=Web3.to_checksum_address(args[buyer_key]),
                recipient=Web3.to_checksum_address(args[buyer_key]),
                token0_amount="0",
                token1_amount=str(args[tokens_key]),
                source_event="EthPurchase",
            )
        if evt_name == "TokenPurchase":
            buyer_key = "buyer" if "buyer" in args else "_buyer"
            sold_key = "tokens_sold" if "tokens_sold" in args else "_tokens_sold"
            return NormalizedEvent(
                **base,
                event_type="SWAP",
                actor=Web3.to_checksum_address(args[buyer_key]),
                recipient=Web3.to_checksum_address(args[buyer_key]),
                token0_amount=str(args[sold_key]),
                token1_amount="0",
                source_event="TokenPurchase",
            )
        if evt_name in ("AddLiquidity",):
            provider_key = "provider" if "provider" in args else "_provider"
            eth_key = "eth_amount" if "eth_amount" in args else "_eth_amount"
            token_key = "token_amount" if "token_amount" in args else "_token_amount"
            return NormalizedEvent(
                **base,
                event_type="LIQUIDITY_ADD",
                actor=Web3.to_checksum_address(args[provider_key]),
                recipient=Web3.to_checksum_address(args[provider_key]),
                token0_amount=str(args.get(eth_key, 0)),
                token1_amount=str(args.get(token_key, 0)),
                source_event="AddLiquidity",
            )
        if evt_name in ("RemoveLiquidity",):
            provider_key = "provider" if "provider" in args else "_provider"
            eth_key = "eth_amount" if "eth_amount" in args else "_eth_amount"
            token_key = "token_amount" if "token_amount" in args else "_token_amount"
            return NormalizedEvent(
                **base,
                event_type="LIQUIDITY_REMOVE",
                actor=Web3.to_checksum_address(args[provider_key]),
                recipient=Web3.to_checksum_address(args[provider_key]),
                token0_amount=str(args.get(eth_key, 0)),
                token1_amount=str(args.get(token_key, 0)),
                source_event="RemoveLiquidity",
            )
    except Exception:
        pass
    return None


def index_v1_pool_events(
    w3,
    pool,
    from_block,
    to_block,
    checkpoint,
    checkpoint_path,
    cache_dir,
    ts_cache,
):
    """Index V1 exchange events: EthPurchase, TokenPurchase, AddLiquidity, RemoveLiquidity."""
    from ..client import get_contract
    contract = get_contract(w3, pool.pool_address, "uniswap_v1_exchange")
    events = []
    for evt_name in ("EthPurchase", "TokenPurchase", "AddLiquidity", "RemoveLiquidity"):
        if not hasattr(contract.events, evt_name):
            continue
        key = _stream_key("v1", pool.pool_address, evt_name)

        def make_norm(name=evt_name):
            def _norm(evt, timestamps):
                if not getattr(evt, "event", None):
                    evt = dict(evt)
                    evt["event"] = name
                return _normalize_v1_event(evt, pool, timestamps)
            return _norm

        stream = _StreamIndexer(
            w3, key, from_block, to_block, checkpoint, checkpoint_path,
            cache_dir, ts_cache, make_norm(),
        )
        try:
            events.extend(stream.run(getattr(contract.events, evt_name)))
        except Exception:
            pass
    return events


def index_v2_pool_events(
    w3: Web3,
    pool: VerifiedPool,
    from_block: int,
    to_block: int,
    checkpoint: dict,
    checkpoint_path: Path,
    cache_dir: Path,
    ts_cache: dict[int, int],
) -> list[dict]:
    contract = get_contract(w3, pool.pool_address, "uniswap_v2_pair")
    events: list[dict] = []
    for evt_name in ("Swap", "Mint", "Burn"):
        key = _stream_key("v2", pool.pool_address, evt_name)

        def make_norm(name=evt_name):
            def _norm(evt: EventData, timestamps: dict[int, int]):
                if not evt.get("event"):
                    evt = dict(evt)
                    evt["event"] = name
                return _normalize_v2_event(evt, pool, timestamps)
            return _norm

        stream = _StreamIndexer(
            w3, key, from_block, to_block, checkpoint, checkpoint_path,
            cache_dir, ts_cache, make_norm(),
        )
        events.extend(stream.run(getattr(contract.events, evt_name)))
    return events


def index_v3_pool_events(
    w3: Web3,
    pool: VerifiedPool,
    from_block: int,
    to_block: int,
    checkpoint: dict,
    checkpoint_path: Path,
    cache_dir: Path,
    ts_cache: dict[int, int],
) -> list[dict]:
    contract = get_contract(w3, pool.pool_address, "uniswap_v3_pool")
    events: list[dict] = []
    for evt_name in ("Swap", "Mint", "Burn", "Collect"):
        key = _stream_key("v3", pool.pool_address, evt_name)

        def make_norm(name=evt_name):
            def _norm(evt: EventData, timestamps: dict[int, int]):
                if not evt.get("event"):
                    evt = dict(evt)
                    evt["event"] = name
                return _normalize_v3_pool_event(evt, pool, timestamps)
            return _norm

        stream = _StreamIndexer(
            w3, key, from_block, to_block, checkpoint, checkpoint_path,
            cache_dir, ts_cache, make_norm(),
        )
        events.extend(stream.run(getattr(contract.events, evt_name)))
    return events


def index_v3_position_events(
    w3: Web3,
    position_manager_address: str,
    verified_pools: list[VerifiedPool],
    from_block: int,
    to_block: int,
    checkpoint: dict,
    checkpoint_path: Path,
    cache_dir: Path,
    ts_cache: dict[int, int],
) -> tuple[list[dict], dict]:
    pm_contract = get_contract(w3, position_manager_address, "uniswap_v3_position_manager")
    v3_pools_by_tokens: dict = {}
    for p in verified_pools:
        if p.version == "v3" and p.verified:
            v3_pools_by_tokens[
                (
                    Web3.to_checksum_address(p.token0),
                    Web3.to_checksum_address(p.token1),
                    p.fee,
                )
            ] = p

    addr_map = _load_pm_token_map(cache_dir, position_manager_address)
    pool_map: dict = {}
    for tid, addr in addr_map.items():
        match = next((p for p in verified_pools if p.pool_address.lower() == addr.lower()), None)
        pool_map[tid] = match if match else addr

    def update_map_from_increase(entries: list[EventData]) -> None:
        changed = False
        for evt in entries:
            try:
                token_id = int(evt["args"]["tokenId"])
            except Exception:
                continue
            if token_id in pool_map:
                continue
            try:
                pos = pm_contract.functions.positions(token_id).call()
                t0 = Web3.to_checksum_address(pos[2])
                t1 = Web3.to_checksum_address(pos[3])
                fee = pos[4]
                match_pool = v3_pools_by_tokens.get((t0, t1, fee))
                if match_pool:
                    pool_map[token_id] = match_pool
                    addr_map[token_id] = match_pool.pool_address
                    changed = True
            except Exception:
                pass
        if changed:
            _save_pm_token_map(cache_dir, position_manager_address, addr_map)

    events: list[dict] = []
    # Skip Transfer: NPM Transfer is global across all Uniswap V3 NFTs and cannot
    # be topic-filtered by pool. Liquidity deltas already come from pool Mint/Burn
    # plus Increase/DecreaseLiquidity below.
    ordered = ("IncreaseLiquidity", "DecreaseLiquidity", "Collect")
    _progress(
        "v3_pm {}: indexing {} (skipping Transfer)".format(
            position_manager_address, ", ".join(ordered)
        )
    )
    for evt_name in ordered:
        key = _stream_key("v3_pm", position_manager_address, evt_name)

        def make_norm(name=evt_name):
            def _norm(evt: EventData, timestamps: dict[int, int]):
                if not evt.get("event"):
                    evt = dict(evt)
                    evt["event"] = name
                return _normalize_v3_position_event(evt, pool_map, timestamps)
            return _norm

        # Resolve tokenId→pool for every PM event (not only IncreaseLiquidity).
        # Otherwise DecreaseLiquidity in-window for older NFTs keeps pool_address empty.
        stream = _StreamIndexer(
            w3, key, from_block, to_block, checkpoint, checkpoint_path,
            cache_dir, ts_cache, make_norm(), on_raw_chunk=update_map_from_increase,
        )
        events.extend(stream.run(getattr(pm_contract.events, evt_name)))

    return events, pool_map


def index_token_transfers(
    w3: Web3,
    token_address: str,
    from_block: int,
    to_block: int,
    checkpoint: dict,
    checkpoint_path: Path,
    cache_dir: Path,
    ts_cache: dict[int, int],
) -> list[dict]:
    token = Web3.to_checksum_address(token_address)
    contract = get_contract(w3, token, "erc20")
    key = _stream_key("token", token, "Transfer")

    def _norm(evt: EventData, timestamps: dict[int, int]) -> Optional[NormalizedEvent]:
        bn = evt["blockNumber"]
        args = evt["args"]
        return NormalizedEvent(
            block_number=bn,
            block_timestamp=timestamps.get(bn, 0),
            transaction_hash=_tx_hash_hex(evt["transactionHash"]),
            log_index=evt.get("logIndex", 0),
            protocol="",
            version="",
            pool_address="",
            event_type="TOKEN_TRANSFER",
            actor=Web3.to_checksum_address(args["from"]),
            recipient=Web3.to_checksum_address(args["to"]),
            token0_amount=str(args["value"]),
            source_event="Transfer",
            verified=True,
        )

    stream = _StreamIndexer(
        w3, key, from_block, to_block, checkpoint, checkpoint_path,
        cache_dir, ts_cache, _norm,
    )
    return stream.run(contract.events.Transfer)


def index_v4_pool_events(
    w3: Web3,
    pool_manager: str,
    v4_pools: list[VerifiedPool],
    from_block: int,
    to_block: int,
    checkpoint: dict,
    checkpoint_path: Path,
    cache_dir: Path,
    ts_cache: dict[int, int],
) -> list[dict]:
    """Index Swap/ModifyLiquidity on PoolManager, filtered to discovered pool IDs.

    PoolManager is a singleton: without a topic filter this downloads every V4
    swap on Ethereum.  ``id`` is indexed, so we push pool IDs into eth_getLogs.
    """
    if not v4_pools:
        return []
    contract = get_contract(w3, pool_manager, "uniswap_v4_pool_manager")
    pools_by_id: dict[str, VerifiedPool] = {}
    raw_ids: list[str] = []
    for p in v4_pools:
        pid = _pool_id_hex(p.pool_id or p.pool_address).lower()
        if not pid:
            continue
        pools_by_id[pid] = p
        # also index padded form used in topics
        padded = _topic_filter_ids([pid])
        if padded:
            pools_by_id[padded[0].lower()] = p
        raw_ids.append(pid)

    id_filter = _id_argument_filter("id", raw_ids)
    if not id_filter:
        _progress("v4 {}: no pool IDs to filter — skipping".format(pool_manager))
        return []
    _progress(
        "v4 {}: topic-filter {} pool id(s)".format(pool_manager, len(raw_ids))
    )

    events: list[dict] = []
    for evt_name in ("Swap", "ModifyLiquidity"):
        # Stream key versioned (`v4id`) so old unfiltered PoolManager scans are not resumed.
        key = _stream_key("v4id", pool_manager, evt_name)

        def make_norm(name=evt_name):
            def _norm(evt: EventData, timestamps: dict[int, int]):
                if not evt.get("event"):
                    evt = dict(evt)
                    evt["event"] = name
                return _normalize_v4_pool_event(evt, pools_by_id, timestamps)
            return _norm

        stream = _StreamIndexer(
            w3, key, from_block, to_block, checkpoint, checkpoint_path,
            cache_dir, ts_cache, make_norm(), argument_filters=id_filter,
        )
        events.extend(stream.run(getattr(contract.events, evt_name)))
    return events


def index_v4_position_events(
    w3: Web3,
    position_manager_address: str,
    verified_pools: list[VerifiedPool],
    from_block: int,
    to_block: int,
    checkpoint: dict,
    checkpoint_path: Path,
    cache_dir: Path,
    ts_cache: dict[int, int],
) -> tuple[list[dict], dict]:
    pm_contract = get_contract(
        w3, position_manager_address, "uniswap_v4_position_manager"
    )
    v4_by_id: dict[str, VerifiedPool] = {}
    for p in verified_pools:
        if p.version == "v4" and p.verified:
            pid = (p.pool_id or p.pool_address or "").lower()
            if pid:
                v4_by_id[pid] = p

    addr_map = _load_pm_token_map(cache_dir, position_manager_address)
    pool_map: dict = dict(addr_map)

    def resolve_token(token_id: int) -> None:
        if token_id in pool_map and isinstance(pool_map[token_id], str):
            pid = pool_map[token_id].lower()
            if pid in v4_by_id:
                pool_map[token_id] = v4_by_id[pid]
            return
        if token_id in pool_map:
            return
        try:
            from ..discovery.uniswap_v4 import compute_pool_id
            pool_key, _info = pm_contract.functions.getPoolAndPositionInfo(
                token_id
            ).call()
            pid = compute_pool_id(
                pool_key[0], pool_key[1], pool_key[2], pool_key[3], pool_key[4]
            ).lower()
            match = v4_by_id.get(pid)
            if match:
                pool_map[token_id] = match
                addr_map[token_id] = match.pool_address
            else:
                addr_map[token_id] = pid
                pool_map[token_id] = pid
        except Exception:
            pass

    def on_raw(entries: list[EventData]) -> None:
        for evt in entries:
            args = evt.get("args", {})
            tid = args.get("id", args.get("tokenId"))
            if tid is None:
                continue
            resolve_token(int(tid))
        _save_pm_token_map(cache_dir, position_manager_address, addr_map)

    events: list[dict] = []
    # Skip Transfer: V4 PM Transfer is global across all position NFTs and has no
    # poolId topic. Liquidity already comes from PoolManager ModifyLiquidity.
    evt_names = ("ModifyLiquidity",)
    _progress(
        "v4pm {}: indexing {} (skipping Transfer)".format(
            position_manager_address, ", ".join(evt_names)
        )
    )
    for evt_name in evt_names:
        if not hasattr(pm_contract.events, evt_name):
            continue
        key = _stream_key("v4pm", position_manager_address, evt_name)

        def make_norm(name=evt_name):
            def _norm(evt: EventData, timestamps: dict[int, int]):
                if not evt.get("event"):
                    evt = dict(evt)
                    evt["event"] = name
                return _normalize_v4_position_event(evt, pool_map, timestamps)
            return _norm

        stream = _StreamIndexer(
            w3, key, from_block, to_block, checkpoint, checkpoint_path,
            cache_dir, ts_cache, make_norm(), on_raw_chunk=on_raw,
        )
        try:
            events.extend(stream.run(getattr(pm_contract.events, evt_name)))
        except Exception as exc:
            _progress("v4pm {} skipped: {}".format(evt_name, exc))
    _save_pm_token_map(cache_dir, position_manager_address, addr_map)
    return events, pool_map


def index_events(
    w3: Web3,
    verified_pools: list[VerifiedPool],
    target_token: str,
    from_block: int,
    to_block: int,
    output_dir: str | Path = "output",
    checkpoint_file: str = "event_indexer_checkpoint.json",
    index_token_transfer: bool = True,
    source: str = "auto",
    force_dune_refresh: bool = False,
    artifact_format: str = "json",
) -> dict[str, list]:
    """Index swaps / liquidity / transfers.

    ``source``:
      - ``auto`` (default): Dune when ``DUNE_API_KEY`` is set, else RPC
      - ``dune``: require Dune (raise on failure)
      - ``rpc``: Alchemy/Infura eth_getLogs path (slow on free tiers)
    """
    from ..data.artifacts import validate_artifact_environment

    artifact_mode = validate_artifact_environment(artifact_format)
    if artifact_mode == "parquet":
        raise ValueError(
            "Parquet-only analysis is not available during migration; use "
            "artifact_format='both' so legacy JSON readers keep working"
        )

    mode = (source or "auto").strip().lower()
    if mode not in ("auto", "dune", "rpc"):
        mode = "auto"

    prefer_dune = mode == "dune"
    if mode == "auto":
        try:
            from ..data.dune import configured
            prefer_dune = configured()
        except Exception:
            prefer_dune = False

    if prefer_dune:
        try:
            from .dune_index import index_events_from_dune

            _progress("Indexing via Dune (source={}) ...".format(mode))
            return index_events_from_dune(
                verified_pools,
                target_token,
                from_block,
                to_block,
                output_dir=output_dir,
                index_token_transfer=index_token_transfer,
                force_refresh=force_dune_refresh,
                artifact_format=artifact_mode,
                on_progress=lambda m: _progress(m),
            )
        except Exception as exc:
            if mode == "dune":
                raise
            from ..data.dune import DuneQuotaError

            if isinstance(exc, DuneQuotaError):
                _progress(
                    "Dune still over quota after chunked retries ({}) — "
                    "falling back to RPC eth_getLogs".format(exc)
                )
            else:
                _progress(
                    "Dune indexing failed ({}) — falling back to RPC eth_getLogs".format(
                        exc
                    )
                )

    _progress("Indexing via RPC eth_getLogs (source={}) ...".format(mode))
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    cache_dir = out / "indexer_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cp_path = out / checkpoint_file
    checkpoint = _load_checkpoint(cp_path)
    checkpoint = _prepare_checkpoint(
        checkpoint, target_token, from_block, to_block, cache_dir
    )
    _save_checkpoint(cp_path, checkpoint)

    ts_cache: dict[int, int] = {}
    collected: list[dict] = []

    v3_pools = [p for p in verified_pools if p.protocol == "uniswap" and p.version == "v3" and p.verified]
    v2_pools = [p for p in verified_pools if p.protocol == "uniswap" and p.version == "v2" and p.verified]
    v4_pools = [p for p in verified_pools if p.protocol == "uniswap" and p.version == "v4" and p.verified]

    for pool in v2_pools:
        evts = index_v2_pool_events(
            w3, pool, from_block, to_block, checkpoint, cp_path, cache_dir, ts_cache
        )
        collected.extend(evts)
        _flush_outputs(out, collected, from_block, to_block)

    v1_pools = [p for p in verified_pools if p.protocol == "uniswap" and p.version == "v1" and p.verified]
    for pool in v1_pools:
        evts = index_v1_pool_events(
            w3, pool, from_block, to_block, checkpoint, cp_path, cache_dir, ts_cache
        )
        collected.extend(evts)
        _flush_outputs(out, collected, from_block, to_block)

    curve_pools = [p for p in verified_pools if p.protocol == "curve" and p.verified]
    for pool in curve_pools:
        evts = index_curve_pool_events(
            w3, pool, from_block, to_block, checkpoint, cp_path, cache_dir, ts_cache
        )
        collected.extend(evts)
        _flush_outputs(out, collected, from_block, to_block)

    balancer_vaults = {
        p.factory_address
        for p in verified_pools
        if p.protocol == "balancer" and p.verified and p.factory_address
    }
    for vault_addr in balancer_vaults:
        evts = index_balancer_events(
            w3, vault_addr, verified_pools, from_block, to_block,
            checkpoint, cp_path, cache_dir, ts_cache,
        )
        collected.extend(evts)
        _flush_outputs(out, collected, from_block, to_block)

    for pool in v3_pools:
        evts = index_v3_pool_events(
            w3, pool, from_block, to_block, checkpoint, cp_path, cache_dir, ts_cache
        )
        collected.extend(evts)
        _flush_outputs(out, collected, from_block, to_block)

    pm_addresses = {
        p.position_manager_address
        for p in v3_pools
        if p.position_manager_address
    }
    for pm_addr in pm_addresses:
        pm_evts, _token_map = index_v3_position_events(
            w3, pm_addr, verified_pools, from_block, to_block,
            checkpoint, cp_path, cache_dir, ts_cache,
        )
        collected.extend(pm_evts)
        _flush_outputs(out, collected, from_block, to_block)

    v4_managers = {p.factory_address for p in v4_pools if p.factory_address}
    for mgr in v4_managers:
        mgr_pools = [p for p in v4_pools if p.factory_address == mgr]
        evts = index_v4_pool_events(
            w3, mgr, mgr_pools, from_block, to_block,
            checkpoint, cp_path, cache_dir, ts_cache,
        )
        collected.extend(evts)
        _flush_outputs(out, collected, from_block, to_block)

    v4_pm_addresses = {
        p.position_manager_address
        for p in v4_pools
        if p.position_manager_address
    }
    for pm_addr in v4_pm_addresses:
        pm_evts, _token_map = index_v4_position_events(
            w3, pm_addr, verified_pools, from_block, to_block,
            checkpoint, cp_path, cache_dir, ts_cache,
        )
        collected.extend(pm_evts)
        _flush_outputs(out, collected, from_block, to_block)

    if index_token_transfer:
        token_evts = index_token_transfers(
            w3, target_token, from_block, to_block,
            checkpoint, cp_path, cache_dir, ts_cache,
        )
        collected.extend(token_evts)

    result = _flush_outputs(out, collected, from_block, to_block)
    from ..data.artifacts import write_table

    table_artifacts = {
        "swaps": write_table(
            "swaps", result["swaps"], out, artifact_format=artifact_mode
        ),
        "liquidity_events": write_table(
            "liquidity_events",
            result["liquidity_events"],
            out,
            artifact_format=artifact_mode,
        ),
        "transfers": write_table(
            "transfers", result["transfers"], out, artifact_format=artifact_mode
        ),
        "position_events": write_table(
            "position_events",
            result["position_events"],
            out,
            artifact_format=artifact_mode,
        ),
    }
    _write_json(
        out / "index_source.json",
        {
            "source": "rpc",
            "from_block": from_block,
            "to_block": to_block,
            "token": target_token,
            "artifact_format": artifact_mode,
            "artifacts": table_artifacts,
            "counts": {
                "swaps": len(result["swaps"]),
                "liquidity_events": len(result["liquidity_events"]),
                "transfers": len(result["transfers"]),
                "position_events": len(result["position_events"]),
            },
        },
    )
    _progress(
        "Indexing done: {} swaps, {} liquidity, {} transfers".format(
            len(result["swaps"]),
            len(result["liquidity_events"]),
            len(result["transfers"]),
        )
    )
    return result
