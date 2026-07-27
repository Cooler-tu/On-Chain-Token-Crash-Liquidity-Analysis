"""Uniswap V4 pool discovery via PoolKey hash + StateView + Initialize / PM activity."""
from __future__ import annotations

from typing import Optional

from eth_abi import decode as abi_decode
from eth_abi import encode
from eth_utils import keccak
from web3 import Web3

from ..client import get_contract
from ..models import VerifiedPool
from ..registry.loader import get_chain_id, get_v4_fee_tiers, load_registry
from .base import PoolDiscoveryAdapter
from .log_utils import address_topic, dedupe_pools, get_logs_chunked, get_logs_with_topics

_ZERO = "0x0000000000000000000000000000000000000000"

# keccak256("Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)")
INITIALIZE_TOPIC = (
    "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"
)


def compute_pool_id(
    currency0: str,
    currency1: str,
    fee: int,
    tick_spacing: int,
    hooks: str = _ZERO,
) -> str:
    """Off-chain PoolId = keccak256(abi.encode(PoolKey))."""
    c0 = Web3.to_checksum_address(currency0)
    c1 = Web3.to_checksum_address(currency1)
    if c0.lower() > c1.lower():
        c0, c1 = c1, c0
    h = Web3.to_checksum_address(hooks)
    encoded = encode(
        ["address", "address", "uint24", "int24", "address"],
        [c0, c1, int(fee), int(tick_spacing), h],
    )
    return "0x" + keccak(encoded).hex()


def _sign_extend_24(value: int) -> int:
    value &= 0xFFFFFF
    if value & 0x800000:
        value -= 0x1000000
    return value


def decode_position_info(info: int) -> tuple[int, int]:
    """Decode tickLower / tickUpper from V4 PositionInfo packed uint256."""
    tick_lower = _sign_extend_24(info >> 8)
    tick_upper = _sign_extend_24(info >> 32)
    return tick_lower, tick_upper


class UniswapV4Adapter(PoolDiscoveryAdapter):
    """Discover V4 pools via PoolKey probe + Initialize + PM transfers."""

    def discover(
        self,
        token_address: str,
        from_block: int,
        to_block: int,
        quote_assets: Optional[list[dict]] = None,
    ) -> list[VerifiedPool]:
        token = Web3.to_checksum_address(token_address)
        registry = load_registry()
        chain_id = get_chain_id(registry)
        fee_tiers = get_v4_fee_tiers(registry) or [
            {"fee": 100, "tick_spacing": 1},
            {"fee": 500, "tick_spacing": 10},
            {"fee": 3000, "tick_spacing": 60},
            {"fee": 10000, "tick_spacing": 200},
        ]

        state_view_addr = self.deployment.state_view
        if not state_view_addr:
            return []

        state_view = get_contract(self.w3, state_view_addr, "uniswap_v4_state_view")
        pool_manager = self.deployment.factory
        seen: set[str] = set()
        pools: list[VerifiedPool] = []

        quotes: list[str] = [_ZERO]  # native ETH
        if quote_assets:
            for qa in quote_assets:
                quotes.append(Web3.to_checksum_address(qa["address"]))
        # Also probe token vs itself as a fallback (catches single-sided pools)
        # and use known canonical tokens from the registry
        for known in ("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",):  # WETH
            if Web3.to_checksum_address(known).lower() != token.lower():
                quotes.append(Web3.to_checksum_address(known))

        # Fast path: probe known fee/tick + zero hooks
        for q in quotes:
            if q.lower() == token.lower():
                continue
            for tier in fee_tiers:
                fee = int(tier["fee"])
                tick_spacing = int(tier.get("tick_spacing", 60))
                pid = compute_pool_id(token, q, fee, tick_spacing, _ZERO)
                if pid.lower() in seen:
                    continue
                if not self._pool_exists(state_view, pid, to_block):
                    continue
                seen.add(pid.lower())
                c0, c1 = (token, q) if token.lower() < q.lower() else (q, token)
                pools.append(self._make_pool(
                    chain_id, pid, c0, c1, fee, _ZERO, pool_manager
                ))

        search_from = max(from_block, self.deployment.deployment_block)
        total_blocks = to_block - search_from + 1

        # Exhaustive Initialize scan for small windows (catches hooks ≠ 0 created in-window)
        if total_blocks <= 5000 and total_blocks > 0:
            self._scan_initialize(
                token, chain_id, pool_manager, search_from, to_block, seen, pools
            )

        # PM Transfer activity in window → PoolKey (catches hooked pools with LP activity)
        if self.deployment.position_manager and total_blocks > 0:
            self._scan_pm_transfers(
                token, chain_id, pool_manager, search_from, to_block, seen, pools
            )

        return dedupe_pools(pools)

    def _pool_exists(self, state_view, pool_id: str, block: int) -> bool:
        try:
            kwargs = {}
            if block and block > 0:
                kwargs["block_identifier"] = block
            slot0 = state_view.functions.getSlot0(pool_id).call(**kwargs)
            return int(slot0[0]) > 0
        except Exception:
            return False

    def _scan_initialize(
        self,
        token: str,
        chain_id: int,
        pool_manager: str,
        from_block: int,
        to_block: int,
        seen: set[str],
        pools: list[VerifiedPool],
    ) -> None:
        token_topic = address_topic(token)
        for topics in (
            [INITIALIZE_TOPIC, None, token_topic, None],
            [INITIALIZE_TOPIC, None, None, token_topic],
        ):
            try:
                logs = get_logs_with_topics(
                    self.w3, pool_manager, topics, from_block, to_block
                )
            except Exception:
                continue
            for log in logs:
                try:
                    pool = self._pool_from_initialize_log(log, chain_id, pool_manager)
                except Exception:
                    continue
                if pool.pool_id and pool.pool_id.lower() not in seen:
                    seen.add(pool.pool_id.lower())
                    pools.append(pool)

    def _scan_pm_transfers(
        self,
        token: str,
        chain_id: int,
        pool_manager: str,
        from_block: int,
        to_block: int,
        seen: set[str],
        pools: list[VerifiedPool],
    ) -> None:
        pm_addr = self.deployment.position_manager
        if not pm_addr:
            return
        try:
            pm = get_contract(self.w3, pm_addr, "uniswap_v4_position_manager")
            transfers = get_logs_chunked(pm.events.Transfer, from_block, to_block)
        except Exception:
            return

        token_l = token.lower()
        checked: set[int] = set()
        for evt in transfers:
            try:
                tid = int(evt["args"].get("id", evt["args"].get("tokenId")))
            except Exception:
                continue
            if tid in checked:
                continue
            checked.add(tid)
            try:
                pool_key, _info = pm.functions.getPoolAndPositionInfo(tid).call(
                    block_identifier=to_block
                )
            except Exception:
                try:
                    pool_key, _info = pm.functions.getPoolAndPositionInfo(tid).call()
                except Exception:
                    continue
            c0 = Web3.to_checksum_address(pool_key[0])
            c1 = Web3.to_checksum_address(pool_key[1])
            if token_l not in (c0.lower(), c1.lower()):
                continue
            fee = int(pool_key[2])
            tick_spacing = int(pool_key[3])
            hooks = Web3.to_checksum_address(pool_key[4])
            pid = compute_pool_id(c0, c1, fee, tick_spacing, hooks)
            if pid.lower() in seen:
                continue
            seen.add(pid.lower())
            pools.append(self._make_pool(
                chain_id, pid, c0, c1, fee, hooks, pool_manager
            ))

    def _pool_from_initialize_log(
        self, log: dict, chain_id: int, pool_manager: str
    ) -> VerifiedPool:
        topics = log["topics"]
        pool_id = topics[1].hex() if hasattr(topics[1], "hex") else topics[1]
        if not str(pool_id).startswith("0x"):
            pool_id = "0x" + pool_id
        t2 = topics[2].hex() if hasattr(topics[2], "hex") else str(topics[2])
        t3 = topics[3].hex() if hasattr(topics[3], "hex") else str(topics[3])
        currency0 = Web3.to_checksum_address("0x" + t2[-40:])
        currency1 = Web3.to_checksum_address("0x" + t3[-40:])
        data = log["data"]
        if hasattr(data, "hex"):
            data_hex = data.hex()
        else:
            data_hex = data if str(data).startswith("0x") else "0x" + str(data)
        raw = bytes.fromhex(data_hex[2:] if data_hex.startswith("0x") else data_hex)
        fee, tick_spacing, hooks, _sqrt, _tick = abi_decode(
            ["uint24", "int24", "address", "uint160", "int24"], raw
        )
        return self._make_pool(
            chain_id,
            pool_id,
            currency0,
            currency1,
            int(fee),
            Web3.to_checksum_address(hooks),
            pool_manager,
            creation_block=log.get("blockNumber", 0),
            creation_tx=_tx_hex(log.get("transactionHash")),
        )

    def _make_pool(
        self,
        chain_id: int,
        pool_id: str,
        token0: str,
        token1: str,
        fee: int,
        hooks: str,
        pool_manager: str,
        creation_block: int = 0,
        creation_tx: str = "",
    ) -> VerifiedPool:
        return VerifiedPool(
            chain_id=chain_id,
            protocol="uniswap",
            version="v4",
            architecture="singleton",
            factory_address=pool_manager,
            router_addresses=(
                [self.deployment.router] if self.deployment.router else []
            ),
            pool_address=pool_id,
            pool_id=pool_id,
            custody_address=pool_manager,
            position_manager_address=self.deployment.position_manager,
            hooks_address=hooks if hooks.lower() != _ZERO.lower() else None,
            token0=Web3.to_checksum_address(token0),
            token1=Web3.to_checksum_address(token1),
            fee=fee,
            creation_block=creation_block or 0,
            creation_transaction=creation_tx or "",
            verified=False,
            verification_confidence=0.0,
        )


def _tx_hex(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "hex"):
        h = value.hex()
        return h if h.startswith("0x") else "0x" + h
    s = str(value)
    return s if s.startswith("0x") else "0x" + s
