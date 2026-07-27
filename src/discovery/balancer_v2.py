"""Balancer V2 pool discovery via Vault Swap events and factory PoolCreated events."""
from __future__ import annotations

from typing import Optional

from web3 import Web3

from ..client import get_contract, has_bytecode
from ..models import VerifiedPool
from ..registry.loader import get_chain_id, load_registry
from .base import PoolDiscoveryAdapter
from .log_utils import (
    address_topic,
    dedupe_pools,
    get_logs_chunked,
    get_logs_with_topics,
)
import time as _time

_ZERO = "0x0000000000000000000000000000000000000000"

# ERC20 Transfer topic
_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Balancer PoolFactory PoolCreated topics (various factory versions)
_POOL_CREATED_TOPICS = [
    "0x3e84c58c9c8b08324e0c4d63f6b3091a6ab2d3e6e361b6bdfc0575a4705b51f",  # WeightedPool/StablePool
    "0x90a599bd3df3b3741b84f369cd4a3f4333955397932822e399c8e7a191405b1d",  # composable
    "0xeb672cc5bb2e9c903352c6e8e4f9e3c4dec99272a4b7c1a8c6508c2651a3f98",  # others
]

# Balancer Pool Factories on Ethereum mainnet
_DEFAULT_POOL_FACTORIES = [
    "0x8E9aa87E45e92bad84D5F8DD1bff34Fb92637dE9",  # WeightedPoolFactory
    "0xf9ac7B9dF2b3454E841110CcE1810B85404a5f6A",  # ComposableStablePoolFactory
]


def _pool_id_to_address(pool_id: bytes) -> str:
    """Extract pool contract address from a Balancer poolId (first 20 bytes)."""
    if isinstance(pool_id, str):
        pool_id = bytes.fromhex(pool_id.replace("0x", ""))
    return Web3.to_checksum_address("0x" + pool_id[:20].hex())


def _topic_to_address(topic_val) -> str:
    """Convert an indexed event topic param (address) to checksum address."""
    if hasattr(topic_val, "hex"):
        h = topic_val.hex()
    else:
        h = str(topic_val).replace("0x", "")
    return Web3.to_checksum_address("0x" + h[-40:])


class BalancerV2Adapter(PoolDiscoveryAdapter):
    """Discover Balancer V2 pools via Vault swap events + factory PoolCreated scans."""

    def discover(
        self,
        token_address: str,
        from_block: int,
        to_block: int,
        quote_assets: Optional[list[dict]] = None,
    ) -> list[VerifiedPool]:
        target = Web3.to_checksum_address(token_address).lower()
        chain_id = get_chain_id(load_registry())
        vault_addr = Web3.to_checksum_address(self.deployment.factory)
        seen: set[str] = set()
        pools: list[VerifiedPool] = []

        search_from = max(from_block, self.deployment.deployment_block)

        # Path 1: Scan Vault Swap events for poolIds involving the target token
        try:
            self._scan_vault_events(target, vault_addr, search_from, to_block, chain_id, seen, pools)
        except Exception:
            pass

        # Path 2: Scan pool factories for PoolCreated events (small window only)
        total_blocks = to_block - search_from + 1
        if total_blocks <= 5000:
            for factory_addr in _DEFAULT_POOL_FACTORIES:
                try:
                    self._scan_pool_factory(factory_addr, target, vault_addr,
                                             search_from, to_block, chain_id, seen, pools)
                except Exception:
                    pass

        return dedupe_pools(pools)

    def _scan_vault_events(
        self, target: str, vault_addr: str, from_block: int, to_block: int,
        chain_id: int, seen: set[str], pools: list[VerifiedPool],
    ) -> None:
        """Discover pools from Vault Swap events where tokenIn/tokenOut == target."""
        vault = get_contract(self.w3, vault_addr, "balancer_vault")
        # Filter Swap events for tokenIn == target or tokenOut == target
        token_topic = address_topic("0x" + target[2:])  # already checksum, re-topic
        try:
            raw_logs = get_logs_with_topics(
                self.w3, vault_addr, [None, token_topic, None],
                from_block, to_block,
            )
        except Exception:
            raw_logs = []
        try:
            raw_logs2 = get_logs_with_topics(
                self.w3, vault_addr, [None, None, token_topic],
                from_block, to_block,
            )
        except Exception:
            raw_logs2 = []
        raw_logs = raw_logs + raw_logs2

        for raw in raw_logs:
            topics = raw.get("topics", [])
            if len(topics) < 2:
                continue
            pool_id_data = topics[0] if hasattr(topics[0], "hex") else topics[0]
            if isinstance(pool_id_data, str):
                pool_id_data = bytes.fromhex(pool_id_data.replace("0x", ""))
            pool_addr = _pool_id_to_address(pool_id_data)
            addr_lower = pool_addr.lower()
            if addr_lower in seen or addr_lower == _ZERO.lower():
                continue
            if not has_bytecode(self.w3, pool_addr):
                continue
            seen.add(addr_lower)

            # Verify via Vault.getPoolTokens
            t0, t1 = self._get_pool_tokens(vault, raw)
            if t0 and target in (t0.lower(), t1.lower()):
                pools.append(VerifiedPool(
                    chain_id=chain_id,
                    protocol="balancer",
                    version="v2",
                    architecture="weighted_pool",
                    factory_address=vault_addr,
                    router_addresses=[vault_addr],
                    pool_address=pool_addr,
                    custody_address=pool_addr,
                    token0=Web3.to_checksum_address(t0),
                    token1=Web3.to_checksum_address(t1),
                    verified=False,
                    verification_confidence=0.0,
                ))

    def _get_pool_tokens(self, vault_contract, event_log) -> tuple[Optional[str], Optional[str]]:
        """Extract tokenIn/tokenOut from a Swap event, or return (None, None)."""
        try:
            topics = event_log.get("topics", [])
            if len(topics) < 3:
                return None, None
            t_in = _topic_to_address(topics[1])
            t_out = _topic_to_address(topics[2])
            return t_in, t_out
        except Exception:
            return None, None

    def _scan_pool_factory(
        self, factory_addr: str, target: str, vault_addr: str,
        from_block: int, to_block: int,
        chain_id: int, seen: set[str], pools: list[VerifiedPool],
    ) -> None:
        """Scan a pool factory for PoolCreated events."""
        factory_checksum = Web3.to_checksum_address(factory_addr)
        token_topic = address_topic("0x" + target[2:])

        for create_topic in _POOL_CREATED_TOPICS:
            try:
                raw_logs = get_logs_with_topics(
                    self.w3, factory_checksum,
                    [create_topic],
                    from_block, to_block,
                )
            except Exception:
                continue
            for raw in raw_logs:
                # Pool address is in topics[1] or data
                topics = raw.get("topics", [])
                pool_addr_str = ""
                if len(topics) >= 2:
                    pool_addr_str = _topic_to_address(topics[1])
                else:
                    # fallback: extract from data
                    data = raw.get("data", "")
                    if data and len(str(data)) >= 42:
                        pool_addr_str = Web3.to_checksum_address("0x" + str(data)[-40:])
                if not pool_addr_str or pool_addr_str.lower() == _ZERO.lower():
                    continue
                if pool_addr_str.lower() in seen:
                    continue
                if not has_bytecode(self.w3, pool_addr_str):
                    continue
                seen.add(pool_addr_str.lower())

                # Verify via Vault
                vault = get_contract(self.w3, vault_addr, "balancer_vault")
                try:
                    tokens, balances, _ = vault.functions.getPoolTokens(
                        "0x" + pool_addr_str[2:].zfill(64)
                    ).call()
                except Exception:
                    continue
                token_list = [t.lower() for t in tokens]
                if target not in token_list:
                    continue
                pools.append(VerifiedPool(
                    chain_id=chain_id,
                    protocol="balancer",
                    version="v2",
                    architecture="weighted_pool",
                    factory_address=Web3.to_checksum_address(factory_addr),
                    router_addresses=[vault_addr],
                    pool_address=pool_addr_str,
                    custody_address=pool_addr_str,
                    token0=Web3.to_checksum_address(tokens[0]),
                    token1=Web3.to_checksum_address(tokens[1]),
                    verified=False,
                    verification_confidence=0.0,
                ))
