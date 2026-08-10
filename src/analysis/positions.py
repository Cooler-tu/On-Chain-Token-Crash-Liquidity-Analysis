"""Position analysis — reconstruct V2/V3 LP holders at the analysis window end."""
from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict
from typing import Any, Optional

from web3 import Web3

from ..client import get_contract
from ..discovery.log_utils import get_logs_chunked
from ..models import Position, VerifiedPool
from .v3_math import get_amounts_for_liquidity, value_in_token1_raw

_ZERO = "0x0000000000000000000000000000000000000000"


def _parse_uint(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, int):
            return int(value)
        s = str(value).strip()
        if not s:
            return default
        if "e" in s.lower() or "." in s:
            return int(float(s))
        return int(s, 0) if s.startswith("0x") else int(s)
    except (TypeError, ValueError):
        return default


def _dune_cache(cache_dir: Optional[str | Path]) -> Path:
    if cache_dir is None:
        return Path("output") / "dune_cache" / "positions"
    return Path(cache_dir).parent / "dune_cache" / "positions"


def _salt_to_token_id(salt: Any) -> Optional[int]:
    """V4 PositionManager uses bytes32(tokenId) as ModifyLiquidity.salt."""
    if salt is None:
        return None
    try:
        if isinstance(salt, (bytes, bytearray)):
            return int.from_bytes(salt, "big")
        if isinstance(salt, int):
            return int(salt)
        s = str(salt).strip().lower()
        if s.startswith("\\x"):
            s = "0x" + s[2:]
        if s.startswith("0x"):
            return int(s, 16)
        return int(s)
    except (TypeError, ValueError):
        return None


def _chunked(items: list[Any], size: int = 400) -> list[list[Any]]:
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


def _v3_pool_state_rpc(
    w3: Web3,
    pools_by_addr: dict[str, VerifiedPool],
    to_block: int,
    sqrt_from_dune: Optional[dict[str, int]] = None,
) -> dict[str, dict[str, Any]]:
    """Per-pool sqrt price + reserve TVL. Prefers Dune sqrt; balances stay RPC."""
    pool_state: dict[str, dict[str, Any]] = {}
    for pool in pools_by_addr.values():
        key = pool.pool_address.lower()
        sqrt_price_x96 = int((sqrt_from_dune or {}).get(key) or 0)
        try:
            if sqrt_price_x96 <= 0:
                pool_contract = get_contract(w3, pool.pool_address, "uniswap_v3_pool")
                slot0 = pool_contract.functions.slot0().call(block_identifier=to_block)
                sqrt_price_x96 = int(slot0[0])
            t0 = get_contract(w3, pool.token0, "erc20")
            t1 = get_contract(w3, pool.token1, "erc20")
            bal0 = int(
                t0.functions.balanceOf(pool.pool_address).call(
                    block_identifier=to_block
                )
            )
            bal1 = int(
                t1.functions.balanceOf(pool.pool_address).call(
                    block_identifier=to_block
                )
            )
            pool_state[key] = {
                "sqrt_price_x96": sqrt_price_x96,
                "tvl_token1": value_in_token1_raw(bal0, bal1, sqrt_price_x96),
            }
        except Exception:
            pool_state[key] = {"sqrt_price_x96": sqrt_price_x96, "tvl_token1": 0.0}
    return pool_state


def reconstruct_v2_holders(
    w3: Web3,
    pools: list[VerifiedPool],
    events_by_pool: dict[str, list[dict]],
    from_block: int,
    to_block: int,
    *,
    allow_rpc_scan: bool = False,
) -> list[Position]:
    """Snapshot V2 LP-token holders at ``to_block``.

    Discovers candidate addresses from in-window Pair Transfer / pool events,
    then reads ``balanceOf`` / ``totalSupply`` at ``to_block`` (not latest).
    """
    positions: list[Position] = []

    for pool in pools:
        if pool.version != "v2" or not pool.verified:
            continue
        pair_addr = pool.pool_address
        try:
            pair_contract = get_contract(w3, pair_addr, "uniswap_v2_pair")
            total_supply = int(
                pair_contract.functions.totalSupply().call(
                    block_identifier=to_block
                )
            )
        except Exception:
            total_supply = 0

        if total_supply == 0:
            continue

        candidates: set[str] = set()
        for evt in events_by_pool.get(pair_addr.lower(), []):
            for key in ("actor", "recipient"):
                a = evt.get(key) or ""
                if a and a.lower() not in (_ZERO.lower(), pair_addr.lower()):
                    try:
                        candidates.add(Web3.to_checksum_address(a))
                    except Exception:
                        continue

        # Optional: scan Pair Transfer logs (slow on free RPC). Off by default.
        if allow_rpc_scan and not candidates:
            try:
                for evt in get_logs_chunked(
                    pair_contract.events.Transfer, from_block, to_block
                ):
                    args = evt["args"]
                    for raw in (args["from"], args["to"]):
                        addr = Web3.to_checksum_address(raw)
                        if addr.lower() != _ZERO.lower():
                            candidates.add(addr)
            except Exception:
                pass

        for addr in sorted(candidates):
            try:
                bal = int(
                    pair_contract.functions.balanceOf(addr).call(
                        block_identifier=to_block
                    )
                )
            except Exception:
                continue
            if bal <= 0:
                continue
            share = bal / total_supply * 100
            positions.append(Position(
                pool_address=pair_addr,
                owner=addr,
                lp_token_address=pair_addr,
                liquidity=str(bal),
                share_pct=round(share, 6),
                resolution_method="v2_balanceof_at_to_block",
                confidence=0.95,
            ))

    return positions


def _match_v3_pool_at_block(
    pm_contract,
    token_id: int,
    pool_map: dict[tuple[str, str, int], VerifiedPool],
    cache: dict[int, Optional[tuple]],
    block_identifier: int | str,
) -> Optional[tuple]:
    """Return (pool, liquidity, tick_lower, tick_upper) at block, or None."""
    if token_id in cache:
        return cache[token_id]
    try:
        pos = pm_contract.functions.positions(token_id).call(
            block_identifier=block_identifier
        )
        # pos: nonce, operator, token0, token1, fee, tickLower, tickUpper, liquidity, ...
        key = (
            Web3.to_checksum_address(pos[2]),
            Web3.to_checksum_address(pos[3]),
            int(pos[4]),
        )
        matched = pool_map.get(key)
        if not matched:
            cache[token_id] = None
            return None
        result = (matched, int(pos[7]), int(pos[5]), int(pos[6]))
        cache[token_id] = result
        return result
    except Exception:
        cache[token_id] = None
        return None


def reconstruct_v3_position_owners(
    w3: Web3,
    pools: list[VerifiedPool],
    position_manager_address: str,
    from_block: int,
    to_block: int,
    indexed_events: Optional[list[dict]] = None,
    cache_dir: Optional[str | Path] = None,
    *,
    allow_rpc_scan: bool = False,
    owner_filter: str = "",
) -> list[Position]:
    """Snapshot V3 LP NFTs at ``to_block``.

    Prefer Dune (full snapshot, then staged base+L+owners) over per-NFT RPC.
    Pool reserves for share% still use a few RPC calls.
    ``owner_filter`` is optional SQL fragment, e.g. ``AND o.owner IN (...)``.
    """
    pools_by_addr: dict[str, VerifiedPool] = {}
    for p in pools:
        if p.version == "v3" and p.verified and p.pool_address:
            pools_by_addr[p.pool_address.lower()] = p
    if not pools_by_addr:
        return []

    pm_addr = Web3.to_checksum_address(position_manager_address)
    try:
        from ..data.dune import configured, query

        if configured():
            dune_dir = _dune_cache(cache_dir)
            rows: list[dict[str, Any]] = []
            try:
                rows = query(
                    "positions_uniswap_v3_snapshot",
                    cache_dir=dune_dir,
                    npm=pm_addr,
                    pool_list=list(pools_by_addr.keys()),
                    to_block=to_block,
                    owner_filter=owner_filter or "",
                    chunk_blocks=0,
                )
                print(
                    "  [positions] Dune V3 snapshot: {} open NFT(s)".format(
                        len(rows)
                    )
                )
            except Exception as snap_exc:
                print(
                    "  [positions] Dune V3 snapshot missed ({}) — "
                    "staged queries".format(snap_exc)
                )
                rows = _dune_v3_staged_snapshot(
                    query, dune_dir, pm_addr, pools_by_addr, to_block
                )

            if rows:
                sqrt_map: dict[str, int] = {}
                try:
                    for srow in query(
                        "pool_sqrt_price_v3",
                        cache_dir=dune_dir,
                        pool_list=list(pools_by_addr.keys()),
                        to_block=to_block,
                        chunk_blocks=0,
                    ):
                        pa = str(srow.get("pool_address") or "").lower()
                        sqrt_map[pa] = _parse_uint(srow.get("sqrt_price_x96"))
                except Exception as exc:
                    print(
                        "  [positions] Dune V3 sqrt fallback to RPC: {}".format(
                            exc
                        )
                    )

                pool_state = _v3_pool_state_rpc(
                    w3, pools_by_addr, to_block, sqrt_map
                )
                positions = _positions_from_v3_dune_rows(
                    rows, pools_by_addr, pool_state
                )
                if positions:
                    return positions
            print("  [positions] Dune V3 empty — falling back to RPC")
    except Exception as exc:
        print("  [positions] Dune V3 failed: {} — RPC fallback".format(exc))

    return _reconstruct_v3_rpc(
        w3,
        pools,
        position_manager_address,
        from_block,
        to_block,
        indexed_events=indexed_events,
        cache_dir=cache_dir,
        allow_rpc_scan=allow_rpc_scan,
    )


def _dune_v3_staged_snapshot(
    query,
    dune_dir: Path,
    pm_addr: str,
    pools_by_addr: dict[str, VerifiedPool],
    to_block: int,
) -> list[dict[str, Any]]:
    """base (mint→tokenId) + chunked liquidity, then owners only for open L."""
    base = query(
        "positions_uniswap_v3_base",
        cache_dir=dune_dir,
        npm=pm_addr,
        pool_list=list(pools_by_addr.keys()),
        to_block=to_block,
        chunk_blocks=0,
    )
    if not base:
        return []
    by_tid: dict[int, dict[str, Any]] = {}
    for row in base:
        tid = _parse_uint(row.get("nft_token_id"))
        if tid <= 0:
            continue
        by_tid[tid] = {
            "nft_token_id": str(tid),
            "pool_address": row.get("pool_address"),
            "tick_lower": row.get("tick_lower"),
            "tick_upper": row.get("tick_upper"),
            "liquidity": "0",
            "owner": None,
        }
    token_ids = sorted(by_tid.keys())
    open_ids: list[int] = []
    for batch in _chunked(token_ids, 400):
        for row in query(
            "positions_uniswap_v3_liquidity",
            cache_dir=dune_dir,
            token_id_list=batch,
            to_block=to_block,
            chunk_blocks=0,
        ):
            tid = _parse_uint(row.get("nft_token_id"))
            if tid not in by_tid:
                continue
            liq = str(row.get("liquidity") or "0")
            by_tid[tid]["liquidity"] = liq
            if _parse_uint(liq) > 0:
                open_ids.append(tid)
    for batch in _chunked(sorted(set(open_ids)), 400):
        for row in query(
            "positions_nft_owners",
            cache_dir=dune_dir,
            npm=pm_addr,
            token_id_list=batch,
            to_block=to_block,
            chunk_blocks=0,
        ):
            tid = _parse_uint(row.get("nft_token_id"))
            if tid in by_tid:
                by_tid[tid]["owner"] = row.get("owner")
    out = [
        r
        for r in by_tid.values()
        if _parse_uint(r.get("liquidity")) > 0 and r.get("owner")
    ]
    print(
        "  [positions] Dune V3 staged: {} open NFT(s) from {} base".format(
            len(out), len(base)
        )
    )
    return out


def _positions_from_v3_dune_rows(
    rows: list[dict[str, Any]],
    pools_by_addr: dict[str, VerifiedPool],
    pool_state: dict[str, dict[str, Any]],
) -> list[Position]:
    positions: list[Position] = []
    for row in rows:
        pool_key = str(row.get("pool_address") or "").lower()
        matched = pools_by_addr.get(pool_key)
        if not matched:
            continue
        token_id = _parse_uint(row.get("nft_token_id"))
        liquidity = _parse_uint(row.get("liquidity"))
        tick_lower = _parse_uint(row.get("tick_lower"))
        tick_upper = _parse_uint(row.get("tick_upper"))
        if token_id <= 0 or liquidity <= 0:
            continue
        try:
            owner_addr = Web3.to_checksum_address(str(row.get("owner") or ""))
        except Exception:
            continue
        if owner_addr.lower() == _ZERO.lower():
            continue
        state = pool_state.get(pool_key, {})
        sqrt_price_x96 = int(state.get("sqrt_price_x96") or 0)
        pool_tvl = float(state.get("tvl_token1") or 0.0)
        if sqrt_price_x96 <= 0:
            continue
        amount0, amount1 = get_amounts_for_liquidity(
            sqrt_price_x96, tick_lower, tick_upper, liquidity
        )
        pos_tvl = value_in_token1_raw(amount0, amount1, sqrt_price_x96)
        share = (pos_tvl / pool_tvl * 100.0) if pool_tvl > 0 else 0.0
        positions.append(
            Position(
                pool_address=matched.pool_address,
                owner=owner_addr,
                nft_token_id=token_id,
                liquidity=str(liquidity),
                share_pct=round(share, 6),
                resolution_method="v3_dune_snapshot_at_to_block",
                confidence=0.95,
                tick_lower=tick_lower,
                tick_upper=tick_upper,
                token0_amount=str(amount0),
                token1_amount=str(amount1),
            )
        )
    return positions


def _reconstruct_v3_rpc(
    w3: Web3,
    pools: list[VerifiedPool],
    position_manager_address: str,
    from_block: int,
    to_block: int,
    indexed_events: Optional[list[dict]] = None,
    cache_dir: Optional[str | Path] = None,
    *,
    allow_rpc_scan: bool = False,
) -> list[Position]:
    """RPC fallback: tokenId discovery + per-NFT ``positions`` / ``ownerOf``."""
    positions: list[Position] = []
    pm_addr = Web3.to_checksum_address(position_manager_address)

    try:
        pm_contract = get_contract(w3, pm_addr, "uniswap_v3_position_manager")
    except Exception:
        return positions

    pool_map: dict[tuple[str, str, int], VerifiedPool] = {}
    pools_by_addr: dict[str, VerifiedPool] = {}
    for p in pools:
        if p.version == "v3" and p.verified:
            fee = p.fee
            if fee is None:
                try:
                    pc = get_contract(w3, p.pool_address, "uniswap_v3_pool")
                    fee = int(pc.functions.fee().call())
                    p.fee = fee
                except Exception:
                    fee = 0
            pool_map[(
                Web3.to_checksum_address(p.token0),
                Web3.to_checksum_address(p.token1),
                int(fee or 0),
            )] = p
            pools_by_addr[p.pool_address.lower()] = p

    if not pool_map:
        return positions

    discover_cache: dict[int, Optional[tuple]] = {}
    relevant_ids: set[int] = set()

    def _consider(token_id: int) -> bool:
        matched = _match_v3_pool_at_block(
            pm_contract, token_id, pool_map, discover_cache, to_block
        )
        if matched:
            relevant_ids.add(token_id)
            return True
        latest_cache: dict[int, Optional[tuple]] = {}
        matched_latest = _match_v3_pool_at_block(
            pm_contract, token_id, pool_map, latest_cache, "latest"
        )
        if matched_latest:
            relevant_ids.add(token_id)
            return True
        return False

    if cache_dir is not None:
        map_path = (
            Path(cache_dir)
            / "pm_token_pool_map_{}.json".format(pm_addr.lower())
        )
        if map_path.exists():
            try:
                raw_map = json.loads(map_path.read_text())
                for tid_s, pool_addr in raw_map.items():
                    if str(pool_addr).lower() not in pools_by_addr:
                        continue
                    relevant_ids.add(int(tid_s))
            except Exception:
                pass

    for evt in indexed_events or []:
        tid = evt.get("nft_token_id")
        if tid is None:
            continue
        try:
            token_id = int(tid)
        except (TypeError, ValueError):
            continue
        src = evt.get("source_event", "")
        et = evt.get("event_type", "")
        if src in (
            "Transfer", "IncreaseLiquidity", "DecreaseLiquidity", "Collect"
        ) or et in (
            "POSITION_TRANSFER", "LIQUIDITY_ADD", "LIQUIDITY_REMOVE", "COLLECT_FEES"
        ):
            pool_hint = (evt.get("pool_address") or "").lower()
            if pool_hint and pool_hint in pools_by_addr:
                relevant_ids.add(token_id)
            else:
                _consider(token_id)

    if not relevant_ids:
        try:
            from ..data.dune import configured, query

            if configured():
                rows = query(
                    "liquidity_uniswap_v3_npm_token_ids",
                    cache_dir=_dune_cache(cache_dir),
                    npm=pm_addr,
                    pool_list=list(pools_by_addr.keys()),
                    from_block=from_block,
                    to_block=to_block,
                )
                print(
                    "  [positions] Dune Mint→NPM tokenIds: {} candidate(s)".format(
                        len(rows)
                    )
                )
                for row in rows:
                    tid = _parse_uint(row.get("nft_token_id"))
                    pool_hint = str(row.get("pool_address") or "").lower()
                    if pool_hint and pool_hint in pools_by_addr:
                        relevant_ids.add(tid)
                    else:
                        _consider(tid)
        except Exception as exc:
            print("  [positions] Dune tokenId recovery failed: {}".format(exc))

    if not relevant_ids and allow_rpc_scan:
        try:
            for evt in get_logs_chunked(
                pm_contract.events.IncreaseLiquidity, from_block, to_block
            ):
                _consider(int(evt["args"]["tokenId"]))
        except Exception:
            pass
        try:
            for evt in get_logs_chunked(
                pm_contract.events.DecreaseLiquidity, from_block, to_block
            ):
                _consider(int(evt["args"]["tokenId"]))
        except Exception:
            pass

    if not relevant_ids:
        return positions

    pool_state = _v3_pool_state_rpc(w3, pools_by_addr, to_block)
    snapshot_cache: dict[int, Optional[tuple]] = {}
    for token_id in sorted(relevant_ids):
        matched = _match_v3_pool_at_block(
            pm_contract, token_id, pool_map, snapshot_cache, to_block
        )
        if not matched:
            continue
        matched_pool, liquidity, tick_lower, tick_upper = matched
        if liquidity <= 0:
            continue

        try:
            owner_addr = Web3.to_checksum_address(
                pm_contract.functions.ownerOf(token_id).call(
                    block_identifier=to_block
                )
            )
        except Exception:
            continue
        if owner_addr.lower() == _ZERO.lower():
            continue

        state = pool_state.get(matched_pool.pool_address.lower(), {})
        sqrt_price_x96 = int(state.get("sqrt_price_x96") or 0)
        pool_tvl = float(state.get("tvl_token1") or 0.0)
        if sqrt_price_x96 <= 0:
            continue

        amount0, amount1 = get_amounts_for_liquidity(
            sqrt_price_x96, tick_lower, tick_upper, liquidity
        )
        pos_tvl = value_in_token1_raw(amount0, amount1, sqrt_price_x96)
        share = (pos_tvl / pool_tvl * 100.0) if pool_tvl > 0 else 0.0

        positions.append(Position(
            pool_address=matched_pool.pool_address,
            owner=owner_addr,
            nft_token_id=token_id,
            liquidity=str(liquidity),
            share_pct=round(share, 6),
            resolution_method="v3_tick_amounts_at_to_block",
            confidence=0.95,
            tick_lower=tick_lower,
            tick_upper=tick_upper,
            token0_amount=str(amount0),
            token1_amount=str(amount1),
        ))

    return positions


def reconstruct_v1_holders(
    w3: Web3,
    pools: list[VerifiedPool],
    from_block: int,
    to_block: int,
) -> list[Position]:
    """Snapshot V1 exchange LP-token holders at ``to_block``."""
    positions: list[Position] = []
    for pool in pools:
        if pool.version != "v1" or not pool.verified:
            continue
        exchange = pool.pool_address
        try:
            contract = get_contract(w3, exchange, "uniswap_v1_exchange")
            total_supply = int(
                contract.functions.totalSupply().call(block_identifier=to_block)
            )
        except Exception:
            continue
        if total_supply == 0:
            continue

        candidates: set[str] = set()
        try:
            for evt in get_logs_chunked(
                contract.events.Transfer, from_block, to_block
            ):
                args = evt["args"]
                # V1 ABI uses _from / _to
                for key in ("_from", "from", "_to", "to"):
                    raw = args.get(key)
                    if not raw:
                        continue
                    addr = Web3.to_checksum_address(raw)
                    if addr.lower() != _ZERO.lower():
                        candidates.add(addr)
        except Exception:
            pass
        try:
            for evt in get_logs_chunked(
                contract.events.AddLiquidity, from_block, to_block
            ):
                candidates.add(Web3.to_checksum_address(evt["args"]["provider"]))
        except Exception:
            pass

        for addr in sorted(candidates):
            try:
                bal = int(
                    contract.functions.balanceOf(addr).call(
                        block_identifier=to_block
                    )
                )
            except Exception:
                continue
            if bal <= 0:
                continue
            share = bal / total_supply * 100
            positions.append(Position(
                pool_address=exchange,
                owner=addr,
                lp_token_address=exchange,
                liquidity=str(bal),
                share_pct=round(share, 6),
                resolution_method="v1_balanceof_at_to_block",
                confidence=0.9,
            ))
    return positions


def _match_v4_pool_at_block(
    pm_contract,
    token_id: int,
    pools_by_id: dict[str, VerifiedPool],
    cache: dict[int, Optional[tuple]],
    block_identifier: int | str,
) -> Optional[tuple]:
    """Return (pool, liquidity, tick_lower, tick_upper) at block, or None."""
    if token_id in cache:
        return cache[token_id]
    try:
        from ..discovery.uniswap_v4 import compute_pool_id, decode_position_info
        pool_key, info = pm_contract.functions.getPoolAndPositionInfo(
            token_id
        ).call(block_identifier=block_identifier)
        pid = compute_pool_id(
            pool_key[0], pool_key[1], pool_key[2], pool_key[3], pool_key[4]
        ).lower()
        matched = pools_by_id.get(pid)
        if not matched:
            cache[token_id] = None
            return None
        liquidity = int(
            pm_contract.functions.getPositionLiquidity(token_id).call(
                block_identifier=block_identifier
            )
        )
        tick_lower, tick_upper = decode_position_info(int(info))
        result = (matched, liquidity, tick_lower, tick_upper)
        cache[token_id] = result
        return result
    except Exception:
        cache[token_id] = None
        return None


def reconstruct_v4_position_owners(
    w3: Web3,
    pools: list[VerifiedPool],
    position_manager_address: str,
    state_view_address: str,
    from_block: int,
    to_block: int,
    indexed_events: Optional[list[dict]] = None,
    cache_dir: Optional[str | Path] = None,
    *,
    allow_rpc_scan: bool = False,
) -> list[Position]:
    """Snapshot V4 LP NFTs at ``to_block``.

    Prefer Dune net-liquidity by (poolId, salt) + batched ERC721 owners.
    StateView slot0 / active L stay as a few RPC calls per pool.
    """
    pools_by_id: dict[str, VerifiedPool] = {}
    for p in pools:
        if p.version == "v4" and p.verified:
            pid = (p.pool_id or p.pool_address or "").lower()
            if pid:
                pools_by_id[pid] = p
    if not pools_by_id:
        return []

    pm_addr = Web3.to_checksum_address(position_manager_address)
    try:
        from ..data.dune import configured, query

        if configured():
            dune_dir = _dune_cache(cache_dir)
            liq_rows = query(
                "positions_uniswap_v4_liquidity",
                cache_dir=dune_dir,
                pool_id_list=list(pools_by_id.keys()),
                to_block=to_block,
                chunk_blocks=0,
            )
            # (token_id -> list of position rows) — salt usually == tokenId
            by_tid: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for row in liq_rows:
                tid = _salt_to_token_id(row.get("salt"))
                if tid is None or tid < 0:
                    continue
                liquidity = _parse_uint(row.get("liquidity"))
                if liquidity <= 0:
                    continue
                by_tid[tid].append(row)

            token_ids = sorted(by_tid.keys())
            owners: dict[int, str] = {}
            for batch in _chunked(token_ids, 400):
                if not batch:
                    continue
                for orow in query(
                    "positions_nft_owners",
                    cache_dir=dune_dir,
                    npm=pm_addr,
                    token_id_list=batch,
                    to_block=to_block,
                    chunk_blocks=0,
                ):
                    tid = _parse_uint(orow.get("nft_token_id"))
                    try:
                        owners[tid] = Web3.to_checksum_address(
                            str(orow.get("owner") or "")
                        )
                    except Exception:
                        continue

            print(
                "  [positions] Dune V4: {} open salt(s), {} owner(s)".format(
                    len(token_ids), len(owners)
                )
            )

            try:
                state_view = get_contract(
                    w3, state_view_address, "uniswap_v4_state_view"
                )
            except Exception:
                state_view = None

            pool_state: dict[str, dict[str, Any]] = {}
            for pid, pool in pools_by_id.items():
                pool_id = pool.pool_id or pool.pool_address
                try:
                    if state_view is None:
                        raise RuntimeError("no state_view")
                    slot0 = state_view.functions.getSlot0(pool_id).call(
                        block_identifier=to_block
                    )
                    active_l = int(
                        state_view.functions.getLiquidity(pool_id).call(
                            block_identifier=to_block
                        )
                    )
                    pool_state[pid] = {
                        "sqrt_price_x96": int(slot0[0]),
                        "tick": int(slot0[1]),
                        "active_liquidity": active_l,
                    }
                except Exception:
                    pool_state[pid] = {
                        "sqrt_price_x96": 0,
                        "tick": 0,
                        "active_liquidity": 0,
                    }

            positions: list[Position] = []
            for token_id, rows in by_tid.items():
                owner_addr = owners.get(token_id)
                if not owner_addr or owner_addr.lower() == _ZERO.lower():
                    continue
                for row in rows:
                    pid = str(row.get("pool_id") or "").lower()
                    matched = pools_by_id.get(pid)
                    if not matched:
                        continue
                    liquidity = _parse_uint(row.get("liquidity"))
                    tick_lower = _parse_uint(row.get("tick_lower"))
                    tick_upper = _parse_uint(row.get("tick_upper"))
                    if liquidity <= 0:
                        continue
                    state = pool_state.get(pid, {})
                    sqrt_price_x96 = int(state.get("sqrt_price_x96") or 0)
                    current_tick = int(state.get("tick") or 0)
                    active_l = int(state.get("active_liquidity") or 0)
                    if sqrt_price_x96 <= 0:
                        continue
                    amount0, amount1 = get_amounts_for_liquidity(
                        sqrt_price_x96, tick_lower, tick_upper, liquidity
                    )
                    in_range = tick_lower <= current_tick < tick_upper
                    if in_range and active_l > 0:
                        share = liquidity / active_l * 100.0
                        method = "v4_dune_active_liquidity_share_at_to_block"
                    else:
                        share = 0.0
                        method = "v4_dune_tick_amounts_out_of_range_at_to_block"
                    positions.append(
                        Position(
                            pool_address=matched.pool_address,
                            owner=owner_addr,
                            nft_token_id=token_id,
                            liquidity=str(liquidity),
                            share_pct=round(share, 6),
                            resolution_method=method,
                            confidence=0.95 if in_range else 0.9,
                            tick_lower=tick_lower,
                            tick_upper=tick_upper,
                            token0_amount=str(amount0),
                            token1_amount=str(amount1),
                        )
                    )
            if positions:
                return positions
            print("  [positions] Dune V4 empty — falling back to RPC")
    except Exception as exc:
        print("  [positions] Dune V4 failed: {} — RPC fallback".format(exc))

    return _reconstruct_v4_rpc(
        w3,
        pools,
        position_manager_address,
        state_view_address,
        from_block,
        to_block,
        indexed_events=indexed_events,
        cache_dir=cache_dir,
        allow_rpc_scan=allow_rpc_scan,
    )


def _reconstruct_v4_rpc(
    w3: Web3,
    pools: list[VerifiedPool],
    position_manager_address: str,
    state_view_address: str,
    from_block: int,
    to_block: int,
    indexed_events: Optional[list[dict]] = None,
    cache_dir: Optional[str | Path] = None,
    *,
    allow_rpc_scan: bool = False,
) -> list[Position]:
    """RPC fallback for V4 LP NFT snapshot."""
    positions: list[Position] = []
    pm_addr = Web3.to_checksum_address(position_manager_address)

    try:
        pm_contract = get_contract(w3, pm_addr, "uniswap_v4_position_manager")
        state_view = get_contract(w3, state_view_address, "uniswap_v4_state_view")
    except Exception:
        return positions

    pools_by_id: dict[str, VerifiedPool] = {}
    for p in pools:
        if p.version == "v4" and p.verified:
            pid = (p.pool_id or p.pool_address or "").lower()
            if pid:
                pools_by_id[pid] = p
    if not pools_by_id:
        return positions

    discover_cache: dict[int, Optional[tuple]] = {}
    relevant_ids: set[int] = set()

    def _consider(token_id: int) -> bool:
        matched = _match_v4_pool_at_block(
            pm_contract, token_id, pools_by_id, discover_cache, to_block
        )
        if matched:
            relevant_ids.add(token_id)
            return True
        latest_cache: dict[int, Optional[tuple]] = {}
        matched_latest = _match_v4_pool_at_block(
            pm_contract, token_id, pools_by_id, latest_cache, "latest"
        )
        if matched_latest:
            relevant_ids.add(token_id)
            return True
        return False

    if cache_dir is not None:
        map_path = (
            Path(cache_dir)
            / "pm_token_pool_map_{}.json".format(pm_addr.lower())
        )
        if map_path.exists():
            try:
                raw_map = json.loads(map_path.read_text())
                for tid_s, pool_key in raw_map.items():
                    if str(pool_key).lower() not in pools_by_id:
                        continue
                    relevant_ids.add(int(tid_s))
            except Exception:
                pass

    for evt in indexed_events or []:
        if evt.get("version") and evt.get("version") != "v4":
            continue
        tid = evt.get("nft_token_id")
        if tid is None:
            continue
        try:
            token_id = int(tid)
        except (TypeError, ValueError):
            continue
        if token_id <= 0:
            continue
        src = evt.get("source_event", "")
        et = evt.get("event_type", "")
        if src in ("Transfer", "ModifyLiquidity") or et in (
            "POSITION_TRANSFER", "LIQUIDITY_ADD", "LIQUIDITY_REMOVE"
        ):
            pool_hint = (evt.get("pool_address") or "").lower()
            if pool_hint and pool_hint in pools_by_id:
                relevant_ids.add(token_id)
            else:
                _consider(token_id)

    if not relevant_ids and allow_rpc_scan:
        try:
            for evt in get_logs_chunked(
                pm_contract.events.Transfer, from_block, to_block
            ):
                args = evt["args"]
                tid = args.get("id", args.get("tokenId"))
                if tid is not None:
                    _consider(int(tid))
        except Exception:
            pass

    if not relevant_ids:
        return positions

    pool_state: dict[str, dict[str, Any]] = {}
    for pid, pool in pools_by_id.items():
        pool_id = pool.pool_id or pool.pool_address
        try:
            slot0 = state_view.functions.getSlot0(pool_id).call(
                block_identifier=to_block
            )
            active_l = int(
                state_view.functions.getLiquidity(pool_id).call(
                    block_identifier=to_block
                )
            )
            pool_state[pid] = {
                "sqrt_price_x96": int(slot0[0]),
                "tick": int(slot0[1]),
                "active_liquidity": active_l,
            }
        except Exception:
            pool_state[pid] = {
                "sqrt_price_x96": 0,
                "tick": 0,
                "active_liquidity": 0,
            }

    snapshot_cache: dict[int, Optional[tuple]] = {}
    for token_id in sorted(relevant_ids):
        matched = _match_v4_pool_at_block(
            pm_contract, token_id, pools_by_id, snapshot_cache, to_block
        )
        if not matched:
            continue
        matched_pool, liquidity, tick_lower, tick_upper = matched
        if liquidity <= 0:
            continue
        try:
            owner_addr = Web3.to_checksum_address(
                pm_contract.functions.ownerOf(token_id).call(
                    block_identifier=to_block
                )
            )
        except Exception:
            continue
        if owner_addr.lower() == _ZERO.lower():
            continue

        pid = (matched_pool.pool_id or matched_pool.pool_address).lower()
        state = pool_state.get(pid, {})
        sqrt_price_x96 = int(state.get("sqrt_price_x96") or 0)
        current_tick = int(state.get("tick") or 0)
        active_l = int(state.get("active_liquidity") or 0)
        if sqrt_price_x96 <= 0:
            continue

        amount0, amount1 = get_amounts_for_liquidity(
            sqrt_price_x96, tick_lower, tick_upper, liquidity
        )

        in_range = tick_lower <= current_tick < tick_upper
        if in_range and active_l > 0:
            share = liquidity / active_l * 100.0
            method = "v4_active_liquidity_share_at_to_block"
        else:
            share = 0.0
            method = "v4_tick_amounts_out_of_range_at_to_block"

        positions.append(Position(
            pool_address=matched_pool.pool_address,
            owner=owner_addr,
            nft_token_id=token_id,
            liquidity=str(liquidity),
            share_pct=round(share, 6),
            resolution_method=method,
            confidence=0.95 if in_range else 0.9,
            tick_lower=tick_lower,
            tick_upper=tick_upper,
            token0_amount=str(amount0),
            token1_amount=str(amount1),
        ))

    return positions




def _curve_lp_token(w3, pool):
    """Resolve the Curve LP token address for a pool."""
    try:
        contract = get_contract(w3, pool.pool_address, "curve_pool")
        return Web3.to_checksum_address(contract.functions.token().call())
    except Exception:
        return pool.pool_address


def reconstruct_curve_holders(
    w3: Web3,
    pools: list[VerifiedPool],
    events_by_pool: dict[str, list[dict]],
    from_block: int,
    to_block: int,
) -> list[Position]:
    """Snapshot Curve LP-token holders at ``to_block``.

    Candidate addresses come from in-window AddLiquidity / RemoveLiquidity
    providers and LP-token Transfer events.  Share = balanceOf / totalSupply.
    """
    positions: list[Position] = []
    for pool in pools:
        if pool.protocol != "curve" or not pool.verified:
            continue
        lp_addr = _curve_lp_token(w3, pool)
        try:
            lp_contract = get_contract(w3, lp_addr, "erc20")
            total_supply = int(
                lp_contract.functions.totalSupply().call(
                    block_identifier=to_block
                )
            )
        except Exception:
            total_supply = 0
        if total_supply == 0:
            continue

        candidates: set[str] = set()
        for evt in events_by_pool.get(pool.pool_address.lower(), []):
            for key in ("actor", "recipient"):
                a = evt.get(key) or ""
                if a and a.lower() != _ZERO.lower():
                    try:
                        candidates.add(Web3.to_checksum_address(a))
                    except Exception:
                        continue
        try:
            for evt in get_logs_chunked(
                lp_contract.events.Transfer, from_block, to_block
            ):
                args = evt["args"]
                for raw in (args["from"], args["to"]):
                    addr = Web3.to_checksum_address(raw)
                    if addr.lower() != _ZERO.lower():
                        candidates.add(addr)
        except Exception:
            pass

        for addr in sorted(candidates):
            try:
                bal = int(
                    lp_contract.functions.balanceOf(addr).call(
                        block_identifier=to_block
                    )
                )
            except Exception:
                continue
            if bal <= 0:
                continue
            share = bal / total_supply * 100
            positions.append(Position(
                pool_address=pool.pool_address,
                owner=addr,
                lp_token_address=lp_addr,
                liquidity=str(bal),
                share_pct=round(share, 6),
                resolution_method="curve_balanceof_at_to_block",
                confidence=0.9,
            ))
    return positions


def reconstruct_balancer_holders(
    w3: Web3,
    pools: list[VerifiedPool],
    events_by_pool: dict[str, list[dict]],
    from_block: int,
    to_block: int,
) -> list[Position]:
    """Snapshot Balancer V2 BPT holders at ``to_block``.

    BPT (Balancer Pool Token) is the pool contract itself.  Candidates come
    from Vault PoolBalanceChanged liquidityProvider events and BPT Transfers.
    """
    positions: list[Position] = []
    for pool in pools:
        if pool.protocol != "balancer" or not pool.verified:
            continue
        bpt_addr = pool.pool_address
        try:
            bpt_contract = get_contract(w3, bpt_addr, "erc20")
            total_supply = int(
                bpt_contract.functions.totalSupply().call(
                    block_identifier=to_block
                )
            )
        except Exception:
            total_supply = 0
        if total_supply == 0:
            continue

        candidates: set[str] = set()
        for evt in events_by_pool.get(bpt_addr.lower(), []):
            for key in ("actor", "recipient"):
                a = evt.get(key) or ""
                if a and a.lower() != _ZERO.lower():
                    try:
                        candidates.add(Web3.to_checksum_address(a))
                    except Exception:
                        continue
        try:
            for evt in get_logs_chunked(
                bpt_contract.events.Transfer, from_block, to_block
            ):
                args = evt["args"]
                for raw in (args["from"], args["to"]):
                    addr = Web3.to_checksum_address(raw)
                    if addr.lower() != _ZERO.lower():
                        candidates.add(addr)
        except Exception:
            pass

        for addr in sorted(candidates):
            try:
                bal = int(
                    bpt_contract.functions.balanceOf(addr).call(
                        block_identifier=to_block
                    )
                )
            except Exception:
                continue
            if bal <= 0:
                continue
            share = bal / total_supply * 100
            positions.append(Position(
                pool_address=bpt_addr,
                owner=addr,
                lp_token_address=bpt_addr,
                liquidity=str(bal),
                share_pct=round(share, 6),
                resolution_method="balancer_bpt_balanceof_at_to_block",
                confidence=0.9,
            ))
    return positions


def analyze_positions(
    w3: Web3,
    verified_pools: list[VerifiedPool],
    events_all: list[dict],
    target_token: str,
    from_block: int,
    to_block: int,
    output_dir: str | Path = "output",
    *,
    allow_rpc_scan: bool = False,
    owner_allowlist: Optional[set[str] | list[str]] = None,
) -> tuple[list[Position], dict[str, Any]]:
    """Reconstruct LP positions as of ``to_block`` and write summary files.

    When ``owner_allowlist`` is set (leaderboard addresses), only keep positions
    owned by those wallets — do not treat every LP in the pool as a dashboard row.
    ``allow_rpc_scan=False`` (default) never scans global PM / Pair Transfer
    logs — required for usable speed after Dune indexing.
    """
    out = Path(output_dir)
    cache_dir = out / "indexer_cache"
    positions: list[Position] = []
    allow = {
        Web3.to_checksum_address(a).lower()
        for a in (owner_allowlist or [])
        if a and str(a).startswith("0x") and len(str(a)) == 42
    }
    owner_filter = ""
    if allow:
        owner_filter = "AND o.owner IN ({})".format(", ".join(sorted(allow)))
    elif owner_allowlist is not None:
        # Explicit empty allowlist → skip expensive LP reconstruction.
        print("  [positions] empty leaderboard allowlist — skipping LP snapshot")
        summary = {
            "total_positions": 0,
            "total_unique_holders": 0,
            "snapshot_block": to_block,
            "owner_allowlist_size": 0,
            "top_5_holders": [],
        }
        _write_json(out / "positions.json", [])
        _write_json(out / "position_summary.json", summary)
        return [], summary

    events_by_pool: dict[str, list[dict]] = defaultdict(list)
    for evt in events_all:
        pa = evt.get("pool_address", "").lower()
        if pa:
            events_by_pool[pa].append(evt)

    positions.extend(reconstruct_v1_holders(
        w3, verified_pools, from_block, to_block
    ))
    positions.extend(reconstruct_curve_holders(
        w3, verified_pools, events_by_pool, from_block, to_block
    ))
    positions.extend(reconstruct_balancer_holders(
        w3, verified_pools, events_by_pool, from_block, to_block
    ))
    positions.extend(reconstruct_v2_holders(
        w3, verified_pools, events_by_pool, from_block, to_block,
        allow_rpc_scan=allow_rpc_scan,
    ))

    pm_addresses = {
        p.position_manager_address
        for p in verified_pools
        if p.version == "v3" and p.position_manager_address
    }
    for pm_addr in pm_addresses:
        positions.extend(reconstruct_v3_position_owners(
            w3,
            verified_pools,
            pm_addr,
            from_block,
            to_block,
            indexed_events=events_all,
            cache_dir=cache_dir,
            allow_rpc_scan=allow_rpc_scan,
            owner_filter=owner_filter,
        ))

    # V4 PMs + StateView from registry / pool fields
    from ..registry.loader import get_enabled_protocols, load_registry
    registry = load_registry()
    state_view_by_factory: dict[str, str] = {}
    for dep in get_enabled_protocols(registry):
        if dep.version == "v4" and dep.state_view:
            state_view_by_factory[dep.factory.lower()] = dep.state_view
            state_view_by_factory[dep.position_manager.lower()] = dep.state_view

    v4_pm_addresses = {
        p.position_manager_address
        for p in verified_pools
        if p.version == "v4" and p.position_manager_address
    }
    for pm_addr in v4_pm_addresses:
        state_view = None
        pm_lower = pm_addr.lower()
        for p in verified_pools:
            if (
                p.version == "v4"
                and p.position_manager_address
                and p.position_manager_address.lower() == pm_lower
            ):
                state_view = state_view_by_factory.get(p.factory_address.lower())
                if state_view:
                    break
        if not state_view:
            state_view = state_view_by_factory.get(pm_lower)
        if not state_view:
            continue
        positions.extend(reconstruct_v4_position_owners(
            w3,
            verified_pools,
            pm_addr,
            state_view,
            from_block,
            to_block,
            indexed_events=events_all,
            cache_dir=cache_dir,
            allow_rpc_scan=allow_rpc_scan,
        ))

    if allow:
        before = len(positions)
        positions = [
            p for p in positions
            if (p.owner or "").lower() in allow
        ]
        print(
            "  [positions] leaderboard filter: {} → {} ({} allowlisted)".format(
                before, len(positions), len(allow)
            )
        )

    pos_dicts = [p.__dict__ for p in positions]
    _write_json(out / "positions.json", pos_dicts)

    total_lp_holders = len(set(p.owner for p in positions))
    top_holders = sorted(positions, key=lambda x: x.share_pct, reverse=True)[:5]
    summary = {
        "total_positions": len(positions),
        "total_unique_holders": total_lp_holders,
        "snapshot_block": to_block,
        "owner_allowlist_size": len(allow),
        "share_basis": (
            "v3_tick_token_value_over_pool_balances;"
            "v4_in_range_L_over_pool_active_liquidity;"
            "v1_v2_lp_balance_share"
        ),
        "top_5_holders": [
            {
                "owner": h.owner,
                "share_pct": h.share_pct,
                "pool": h.pool_address,
                "liquidity": h.liquidity,
                "token0_amount": h.token0_amount,
                "token1_amount": h.token1_amount,
                "tick_lower": h.tick_lower,
                "tick_upper": h.tick_upper,
                "resolution_method": h.resolution_method,
            }
            for h in top_holders
        ],
    }
    _write_json(out / "position_summary.json", summary)

    return positions, summary


def _write_json(path: Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
