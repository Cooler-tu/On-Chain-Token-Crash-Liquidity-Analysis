"""Curve pool discovery via Registry (StableSwap + CryptoSwap)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from web3 import Web3

from ..client import get_contract
from ..models import VerifiedPool
from ..registry.loader import get_chain_id, load_registry
from .base import PoolDiscoveryAdapter
from .log_utils import dedupe_pools

_ZERO = "0x0000000000000000000000000000000000000000"


def _read_coins(registry_contract, pool_addr: str) -> list[str]:
    """Get non-zero coin addresses for a Curve pool via registry."""
    try:
        raw = registry_contract.functions.get_coins(
            Web3.to_checksum_address(pool_addr)
        ).call()
        return [
            Web3.to_checksum_address(c)
            for c in raw
            if c and str(c).lower() != _ZERO.lower()
        ]
    except Exception:
        return []


class CurveAdapter(PoolDiscoveryAdapter):
    """Discover Curve pools via the Curve Registry or CryptoSwap Factory."""

    _cached_pools: Optional[list[dict]] = None
    _cache_file = ""

    def _cache_path(self) -> Path:
        return Path(os.environ.get("HOME", "/tmp")) / ".codex_curve_pool_cache.json"

    def _load_pool_cache(self) -> list[dict]:
        if self._cached_pools is not None:
            return self._cached_pools
        p = self._cache_path()
        if p.exists():
            try:
                with open(p) as f:
                    self._cached_pools = json.load(f)
                return self._cached_pools
            except Exception:
                pass
        return []

    def _save_pool_cache(self, pools: list[dict]) -> None:
        self._cached_pools = pools
        try:
            with open(self._cache_path(), "w") as f:
                json.dump(pools, f, indent=2, default=str)
        except Exception:
            pass

    def _pool_info_from_registry(self, pool_addr: str, chain_id: int) -> Optional[VerifiedPool]:
        """Create a VerifiedPool from a Curve registry pool address."""
        try:
            reg = get_contract(self.w3, self.deployment.factory, "curve_registry")
            coins = _read_coins(reg, pool_addr)
            if not coins:
                return None
            pool_name = ""
            try:
                pool_name = reg.functions.get_pool_name(
                    Web3.to_checksum_address(pool_addr)
                ).call()
            except Exception:
                pass
            asset_type = 0
            try:
                asset_type = reg.functions.get_pool_asset_type(
                    Web3.to_checksum_address(pool_addr)
                ).call()
            except Exception:
                pass
            version = "v2" if "crypto" in pool_name.lower() or asset_type == 1 else "v1"
            return VerifiedPool(
                chain_id=chain_id,
                protocol="curve",
                version=version,
                architecture="cryptoswap" if version == "v2" else "stableswap",
                factory_address=self.deployment.factory,
                pool_address=Web3.to_checksum_address(pool_addr),
                custody_address=Web3.to_checksum_address(pool_addr),
                token0=coins[0],
                token1=coins[1] if len(coins) > 1 else coins[0],
                verified=False,
                verification_confidence=0.0,
            )
        except Exception:
            return None

    def discover(
        self,
        token_address: str,
        from_block: int,
        to_block: int,
        quote_assets: Optional[list[dict]] = None,
    ) -> list[VerifiedPool]:
        target = Web3.to_checksum_address(token_address).lower()
        chain_id = get_chain_id(load_registry())
        pools: list[VerifiedPool] = []

        try:
            registry = get_contract(self.w3, self.deployment.factory, "curve_registry")
            total = registry.functions.pool_count().call()
        except Exception:
            return []

        # Limit to avoid timeout on huge scans; ~200 pools is enough for most tokens
        max_pools = min(total, 500)

        for idx in range(max_pools):
            try:
                pool_addr = registry.functions.pool_list(idx).call()
            except Exception:
                continue
            if not pool_addr or pool_addr.lower() == _ZERO.lower():
                continue
            pool_addr_checksum = Web3.to_checksum_address(pool_addr)

            coins = _read_coins(registry, pool_addr_checksum)
            if target not in [c.lower() for c in coins]:
                continue

            pool = self._pool_info_from_registry(pool_addr_checksum, chain_id)
            if pool:
                pools.append(pool)

        return dedupe_pools(pools)
