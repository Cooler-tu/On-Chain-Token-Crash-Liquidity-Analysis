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
) -> list[Position]:
    """Snapshot V3 LP NFTs for verified pools at ``to_block``.

    Candidate tokenIds come from the indexer map / in-window PM events.
    Token amounts and ``share_pct`` use tick-range math at ``to_block``:
    L + tickLower/tickUpper + sqrtPriceX96 → amount0/amount1 → value share.
    Only positions with L > 0 at ``to_block`` are kept.

    When ``allow_rpc_scan`` is False (default), never fall back to scanning
    the global NonfungiblePositionManager logs (very slow on free RPC).
    """
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
            # Dune discovery often omits fee; positions() match needs the real tier.
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

    # Fast path: indexer tokenId→pool map.
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
            # Prefer map/pool_address hint before expensive matches.
            pool_hint = (evt.get("pool_address") or "").lower()
            if pool_hint and pool_hint in pools_by_addr:
                relevant_ids.add(token_id)
            else:
                _consider(token_id)

    # Dune path: recover tokenIds by joining pool Mint → NPM ERC721 mint Transfer.
    # Pool Mint/Burn from dex indexing do not carry nft_token_id (owner is often NPM).
    if not relevant_ids:
        try:
            from ..data.dune_client import dune_api_key_configured
            from ..data.dune_positions import fetch_v3_npm_token_ids_for_pools

            if dune_api_key_configured():
                dune_dir = None
                if cache_dir is not None:
                    dune_dir = Path(cache_dir).parent / "dune_cache" / "positions"
                rows = fetch_v3_npm_token_ids_for_pools(
                    list(pools_by_addr.keys()),
                    pm_addr,
                    from_block,
                    to_block,
                    cache_dir=dune_dir,
                )
                print(
                    "  [positions] Dune Mint→NPM tokenIds: {} candidate(s)".format(
                        len(rows)
                    )
                )
                for row in rows:
                    tid = int(row["nft_token_id"])
                    pool_hint = (row.get("pool_address") or "").lower()
                    if pool_hint and pool_hint in pools_by_addr:
                        relevant_ids.add(tid)
                    else:
                        _consider(tid)
            else:
                print("  [positions] Dune API key missing; cannot recover V3 tokenIds")
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

    # Pool price + reserves at window end (for tick→amounts and value share).
    pool_state: dict[str, dict[str, Any]] = {}
    for pool in pools_by_addr.values():
        key = pool.pool_address.lower()
        try:
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
            pool_tvl_token1 = value_in_token1_raw(bal0, bal1, sqrt_price_x96)
            pool_state[key] = {
                "sqrt_price_x96": sqrt_price_x96,
                "tvl_token1": pool_tvl_token1,
            }
        except Exception:
            pool_state[key] = {"sqrt_price_x96": 0, "tvl_token1": 0.0}

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

    Token amounts use the same tick math as V3.
    ``share_pct`` = position L / pool active liquidity (StateView.getLiquidity)
    when the position is in-range at ``to_block``; otherwise 0.
    This is on-chain exact for *active* liquidity share — not “among discovered”.
    """
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

    # Pool sqrt price + active liquidity at to_block
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

        # Active-liquidity share: only in-range positions contribute to pool L
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
) -> tuple[list[Position], dict[str, Any]]:
    """Reconstruct LP positions as of ``to_block`` and write summary files.

    ``allow_rpc_scan=False`` (default) never scans global PM / Pair Transfer
    logs — required for usable speed after Dune indexing.
    """
    out = Path(output_dir)
    cache_dir = out / "indexer_cache"
    positions: list[Position] = []

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
        ))

    # V4 PMs + StateView from registry / pool fields
    from ..registry.loader import get_enabled_protocols, load_registry
    registry = load_registry()
    state_view_by_factory: dict[str, str] = {}
    for dep in get_enabled_protocols(registry):
        if dep.version == "v4" and dep.state_view:
            state_view_by_factory[dep.factory.lower()] = dep.state_view
            state_view_by_factory[dep.position_manager.lower()] = dep.state_view  # PM→state_view alias

    v4_pm_addresses = {
        p.position_manager_address
        for p in verified_pools
        if p.version == "v4" and p.position_manager_address
    }
    for pm_addr in v4_pm_addresses:
        # Pick any matching factory's state_view
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
        # Fallback: also try looking up by PM address directly
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

    pos_dicts = [p.__dict__ for p in positions]
    _write_json(out / "positions.json", pos_dicts)

    total_lp_holders = len(set(p.owner for p in positions))
    top_holders = sorted(positions, key=lambda x: x.share_pct, reverse=True)[:5]
    summary = {
        "total_positions": len(positions),
        "total_unique_holders": total_lp_holders,
        "snapshot_block": to_block,
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
