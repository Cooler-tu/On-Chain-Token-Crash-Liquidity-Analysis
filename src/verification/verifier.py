"""Pool verification — confirms discovered pools against their Factory."""
from __future__ import annotations

import time as _time
from typing import Optional

from web3 import Web3

from ..client import get_contract, has_bytecode
from ..discovery.log_utils import get_logs_chunked
from ..models import VerifiedPool
from ..registry.loader import (
    get_protocol_by_factory,
    get_v3_fee_tiers,
    is_trusted_factory,
    load_registry,
)

MIN_CONFIDENCE = 0.3
_RPC_DELAY = 0.0
_ZERO = "0x0000000000000000000000000000000000000000"


def verify_pool(
    w3: Web3,
    pool: VerifiedPool,
    target_token: Optional[str] = None,
    from_block: int = 0,
    to_block: int = 0,
) -> VerifiedPool:
    pool = VerifiedPool(**{k: v for k, v in pool.__dict__.items()})
    registry = load_registry()

    checks_passed = 0
    checks_total = 0

    checks_total += 1
    if is_trusted_factory(registry, pool.factory_address):
        checks_passed += 1
    else:
        pool.verified = False
        pool.verification_confidence = 0.0
        return pool

    pool = _resolve_custody(w3, pool, registry)

    if pool.version == "v4":
        return _verify_v4_pool(
            w3, pool, registry, target_token, from_block, to_block,
            checks_passed, checks_total,
        )
    if pool.version == "v1":
        return _verify_v1_pool(
            w3, pool, target_token, checks_passed, checks_total,
        )
    if pool.protocol == "curve":
        return _verify_curve_pool(
            w3, pool, target_token, checks_passed, checks_total,
        )
    if pool.protocol == "balancer":
        return _verify_balancer_pool(
            w3, pool, target_token, checks_passed, checks_total,
        )

    _time.sleep(_RPC_DELAY)
    checks_total += 1
    if has_bytecode(w3, pool.pool_address):
        checks_passed += 1

    contract = None
    try:
        contract = get_contract(w3, pool.pool_address, _abi_name(pool))
    except Exception:
        pass

    if contract is None:
        pool.verified = False
        pool.verification_confidence = round(checks_passed / max(checks_total, 1), 4)
        return pool

    _time.sleep(_RPC_DELAY)
    checks_total += 1
    try:
        onchain_factory = contract.functions.factory().call()
        if Web3.to_checksum_address(onchain_factory) == Web3.to_checksum_address(pool.factory_address):
            checks_passed += 1
    except Exception:
        pass

    _time.sleep(_RPC_DELAY)
    checks_total += 1
    try:
        t0 = Web3.to_checksum_address(contract.functions.token0().call())
        t1 = Web3.to_checksum_address(contract.functions.token1().call())
        if pool.token0 and pool.token1:
            if t0 == Web3.to_checksum_address(pool.token0) and t1 == Web3.to_checksum_address(pool.token1):
                checks_passed += 1
        else:
            pool.token0 = t0
            pool.token1 = t1
            checks_passed += 1
    except Exception:
        pass

    if target_token:
        checks_total += 1
        target = Web3.to_checksum_address(target_token)
        if target in (pool.token0, pool.token1):
            checks_passed += 1

    if pool.version == "v2":
        checks_passed, checks_total = _verify_v2(
            w3, pool, contract, checks_passed, checks_total
        )
    elif pool.version == "v3":
        checks_passed, checks_total = _verify_v3(
            w3, pool, contract, registry, checks_passed, checks_total
        )

    # Event provenance — skip for large ranges (Free tier constraint)
    if to_block - from_block + 1 <= 1000:
        checks_total += 1
        if _verify_event_provenance(w3, pool, from_block, to_block):
            checks_passed += 1

    confidence = checks_passed / max(checks_total, 1)
    pool.verified = confidence >= MIN_CONFIDENCE
    pool.verification_confidence = round(confidence, 4)
    return pool


def verify_pools(
    w3: Web3,
    pools: list[VerifiedPool],
    target_token: Optional[str] = None,
    from_block: int = 0,
    to_block: int = 0,
) -> list[VerifiedPool]:
    results = []
    for i, pool in enumerate(pools):
        result = verify_pool(w3, pool, target_token, from_block, to_block)
        results.append(result)
    return results


def _resolve_custody(w3: Web3, pool: VerifiedPool, registry: dict) -> VerifiedPool:
    deployment = get_protocol_by_factory(registry, pool.factory_address)
    if deployment is None:
        return pool
    pool.architecture = deployment.architecture
    if pool.version == "v2":
        pool.custody_address = pool.pool_address
        if deployment.router and not pool.router_addresses:
            pool.router_addresses = [deployment.router]
    elif pool.version == "v3":
        pool.custody_address = pool.pool_address
        if deployment.position_manager:
            pool.position_manager_address = deployment.position_manager
        if deployment.router and not pool.router_addresses:
            pool.router_addresses = [deployment.router]
    elif pool.version == "v4":
        pool.custody_address = pool.factory_address  # PoolManager
        if deployment.position_manager:
            pool.position_manager_address = deployment.position_manager
        if deployment.router and not pool.router_addresses:
            pool.router_addresses = [deployment.router]
    elif pool.version == "v1":
        pool.custody_address = pool.pool_address
    return pool


def _verify_v4_pool(
    w3: Web3,
    pool: VerifiedPool,
    registry: dict,
    target_token: Optional[str],
    from_block: int,
    to_block: int,
    checks_passed: int,
    checks_total: int,
) -> VerifiedPool:
    deployment = get_protocol_by_factory(registry, pool.factory_address)
    state_view_addr = deployment.state_view if deployment else None

    checks_total += 1
    if has_bytecode(w3, pool.factory_address):
        checks_passed += 1

    if not pool.pool_id:
        # Prefer bytes32 pool_address; never promote the PoolManager (20-byte) to pool_id.
        addr = (pool.pool_address or "").lower()
        factory = (pool.factory_address or "").lower()
        if addr.startswith("0x") and len(addr) == 66:
            pool.pool_id = pool.pool_address
        elif addr and addr != factory:
            pool.pool_id = pool.pool_address

    # Reject obviously wrong IDs (PoolManager address mistaken for poolId).
    pid = (pool.pool_id or "").lower()
    factory = (pool.factory_address or "").lower()
    if pid and len(pid) == 42 and pid == factory:
        pool.pool_id = None
        pool.verified = False
        pool.verification_confidence = 0.0
        return pool

    if not pool.pool_id:
        pool.verified = False
        pool.verification_confidence = 0.0
        return pool

    if state_view_addr:
        checks_total += 1
        try:
            sv = get_contract(w3, state_view_addr, "uniswap_v4_state_view")
            kwargs = {}
            if to_block and to_block > 0:
                kwargs["block_identifier"] = to_block
            slot0 = sv.functions.getSlot0(pool.pool_id).call(**kwargs)
            if int(slot0[0]) > 0:
                checks_passed += 1
            checks_total += 1
            sv.functions.getLiquidity(pool.pool_id).call(**kwargs)
            checks_passed += 1
        except Exception:
            pass

    if pool.token0 and pool.token1:
        checks_total += 1
        checks_passed += 1

    if target_token:
        checks_total += 1
        target = Web3.to_checksum_address(target_token)
        t0 = Web3.to_checksum_address(pool.token0) if pool.token0 else None
        t1 = Web3.to_checksum_address(pool.token1) if pool.token1 else None
        if target in (t0, t1):
            checks_passed += 1

    if pool.position_manager_address:
        checks_total += 1
        if has_bytecode(w3, pool.position_manager_address):
            checks_passed += 1

    confidence = checks_passed / max(checks_total, 1)
    pool.verified = confidence >= MIN_CONFIDENCE
    pool.verification_confidence = round(confidence, 4)
    return pool


def _verify_v1_pool(
    w3: Web3,
    pool: VerifiedPool,
    target_token: Optional[str],
    checks_passed: int,
    checks_total: int,
) -> VerifiedPool:
    checks_total += 1
    if has_bytecode(w3, pool.pool_address):
        checks_passed += 1

    try:
        exchange = get_contract(w3, pool.pool_address, "uniswap_v1_exchange")
        checks_total += 1
        onchain_token = Web3.to_checksum_address(
            exchange.functions.tokenAddress().call()
        )
        if target_token:
            if onchain_token == Web3.to_checksum_address(target_token):
                checks_passed += 1
                # Normalize token fields: ETH = token0 zero, ERC20 = token1
                pool.token0 = _ZERO
                pool.token1 = onchain_token
        else:
            pool.token0 = _ZERO
            pool.token1 = onchain_token
            checks_passed += 1

        checks_total += 1
        onchain_factory = Web3.to_checksum_address(
            exchange.functions.factoryAddress().call()
        )
        if onchain_factory == Web3.to_checksum_address(pool.factory_address):
            checks_passed += 1
    except Exception:
        pass

    confidence = checks_passed / max(checks_total, 1)
    pool.verified = confidence >= MIN_CONFIDENCE
    pool.verification_confidence = round(confidence, 4)
    return pool


def _verify_v2(
    w3: Web3, pool: VerifiedPool, contract,
    checks_passed: int, checks_total: int,
) -> tuple[int, int]:
    _time.sleep(_RPC_DELAY)
    checks_total += 1
    try:
        factory = get_contract(w3, pool.factory_address, "uniswap_v2_factory")
        expected_pair = factory.functions.getPair(
            Web3.to_checksum_address(pool.token0),
            Web3.to_checksum_address(pool.token1),
        ).call()
        if Web3.to_checksum_address(expected_pair) == Web3.to_checksum_address(pool.pool_address):
            checks_passed += 1
    except Exception:
        pass

    _time.sleep(_RPC_DELAY)
    checks_total += 1
    try:
        contract.functions.getReserves().call()
        checks_passed += 1
    except Exception:
        pass

    return checks_passed, checks_total


def _verify_v3(
    w3: Web3, pool: VerifiedPool, contract, registry: dict,
    checks_passed: int, checks_total: int,
) -> tuple[int, int]:
    if pool.fee is not None:
        checks_total += 1
        try:
            _time.sleep(_RPC_DELAY)
            onchain_fee = contract.functions.fee().call()
            if onchain_fee == pool.fee:
                checks_passed += 1
        except Exception:
            pass

        expected_spacing = _expected_tick_spacing(registry, pool.fee)
        if expected_spacing is not None:
            checks_total += 1
            try:
                _time.sleep(_RPC_DELAY)
                onchain_spacing = contract.functions.tickSpacing().call()
                if onchain_spacing == expected_spacing:
                    checks_passed += 1
            except Exception:
                pass

        _time.sleep(_RPC_DELAY)
        checks_total += 1
        try:
            factory = get_contract(w3, pool.factory_address, "uniswap_v3_factory")
            expected_pool = factory.functions.getPool(
                Web3.to_checksum_address(pool.token0),
                Web3.to_checksum_address(pool.token1),
                pool.fee,
            ).call()
            if Web3.to_checksum_address(expected_pool) == Web3.to_checksum_address(pool.pool_address):
                checks_passed += 1
        except Exception:
            pass

    _time.sleep(_RPC_DELAY)
    checks_total += 1
    try:
        contract.functions.slot0().call()
        checks_passed += 1
    except Exception:
        pass

    _time.sleep(_RPC_DELAY)
    checks_total += 1
    try:
        contract.functions.liquidity().call()
        checks_passed += 1
    except Exception:
        pass

    if pool.position_manager_address:
        _time.sleep(_RPC_DELAY)
        checks_total += 1
        if has_bytecode(w3, pool.position_manager_address):
            checks_passed += 1

    return checks_passed, checks_total


def _expected_tick_spacing(registry: dict, fee: int) -> Optional[int]:
    for tier in get_v3_fee_tiers(registry):
        if tier["fee"] == fee:
            return tier.get("tick_spacing")
    return None


def _verify_event_provenance(w3: Web3, pool: VerifiedPool, from_block: int, to_block: int) -> bool:
    try:
        if pool.version == "v2":
            factory = get_contract(w3, pool.factory_address, "uniswap_v2_factory")
            event = factory.events.PairCreated
            pool_key = "pair"
        else:
            factory = get_contract(w3, pool.factory_address, "uniswap_v3_factory")
            event = factory.events.PoolCreated
            pool_key = "pool"

        if pool.creation_block > 0:
            logs = event.get_logs(
                from_block=pool.creation_block,
                to_block=pool.creation_block,
            )
            for log in logs:
                if Web3.to_checksum_address(log["args"][pool_key]) == Web3.to_checksum_address(pool.pool_address):
                    return True
            return False

        search_from = from_block if from_block > 0 else 0
        search_to = to_block if to_block > 0 else w3.eth.block_number
        logs = get_logs_chunked(event, search_from, search_to)
        for log in logs:
            if Web3.to_checksum_address(log["args"][pool_key]) == Web3.to_checksum_address(pool.pool_address):
                if not pool.creation_block:
                    pool.creation_block = log["blockNumber"]
                    pool.creation_transaction = log["transactionHash"].hex()
                return True
        return False
    except Exception:
        return False


def _abi_name(pool: VerifiedPool) -> str:
    if pool.version == "v2":
        return "uniswap_v2_pair"
    if pool.version == "v1":
        return "uniswap_v1_exchange"
    if pool.protocol == "curve":
        return "curve_pool"
    return "uniswap_v3_pool"



def _verify_curve_pool(
    w3,
    pool,
    target_token,
    checks_passed,
    checks_total,
):
    """Verify a Curve pool via bytecode + coin consistency."""
    from ..client import get_contract, has_bytecode

    checks_total += 1
    if has_bytecode(w3, pool.pool_address):
        checks_passed += 1

    # Check token0/token1 are present
    if target_token:
        checks_total += 1
        target = Web3.to_checksum_address(str(target_token))
        t0 = Web3.to_checksum_address(pool.token0) if pool.token0 else None
        t1 = Web3.to_checksum_address(pool.token1) if pool.token1 else None
        if target in (t0, t1):
            checks_passed += 1

    # Try to read coins from the pool directly
    try:
        contract = get_contract(w3, pool.pool_address, "curve_pool")
        checks_total += 1
        coin0 = Web3.to_checksum_address(contract.functions.coins(0).call())
        if coin0.lower() != _ZERO.lower():
            checks_passed += 1
    except Exception:
        pass

    confidence = checks_passed / max(checks_total, 1)
    pool.verified = confidence >= MIN_CONFIDENCE
    pool.verification_confidence = round(confidence, 4)
    return pool


def _verify_balancer_pool(
    w3,
    pool,
    target_token,
    checks_passed,
    checks_total,
):
    """Verify a Balancer V2 pool via bytecode + Vault token check."""
    from ..client import get_contract, has_bytecode

    vault_ok = False

    checks_total += 1
    if has_bytecode(w3, pool.pool_address):
        checks_passed += 1

    # Check token0/token1
    if target_token:
        checks_total += 1
        target = Web3.to_checksum_address(str(target_token))
        t0 = Web3.to_checksum_address(pool.token0) if pool.token0 else None
        t1 = Web3.to_checksum_address(pool.token1) if pool.token1 else None
        if target in (t0, t1):
            checks_passed += 1

    # Check Vault consistency
    vault_addr = pool.factory_address
    if vault_addr:
        checks_total += 1
        try:
            vault = get_contract(w3, vault_addr, "balancer_vault")
            raw_pid = w3.eth.call({
                "to": Web3.to_checksum_address(pool.pool_address),
                "data": "0xf89b4d55",
            })
            pool_id_hex = raw_pid.hex() if hasattr(raw_pid, "hex") else str(raw_pid)
            pool.pool_id = pool_id_hex
            tokens, _, _ = vault.functions.getPoolTokens(pool_id_hex).call()
            token_addrs = [t.lower() for t in tokens]
            if target_token is None or target_token.lower() in token_addrs:
                checks_passed += 1
                vault_ok = True
        except Exception:
            pass

    confidence = checks_passed / max(checks_total, 1)
    pool.verified = vault_ok and confidence >= MIN_CONFIDENCE
    pool.verification_confidence = round(confidence, 4)
    return pool
