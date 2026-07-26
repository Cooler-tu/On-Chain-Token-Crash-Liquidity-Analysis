"""Uniswap V1 exchange discovery (thin support)."""
from __future__ import annotations

from typing import Optional

from web3 import Web3

from ..client import get_contract, has_bytecode
from ..models import VerifiedPool
from ..registry.loader import get_chain_id, load_registry
from .base import PoolDiscoveryAdapter
from .log_utils import dedupe_pools

_ZERO = "0x0000000000000000000000000000000000000000"


class UniswapV1Adapter(PoolDiscoveryAdapter):
    """Discover the V1 ETH/token exchange via factory.getExchange."""

    def discover(
        self,
        token_address: str,
        from_block: int,
        to_block: int,
        quote_assets: Optional[list[dict]] = None,
    ) -> list[VerifiedPool]:
        token = Web3.to_checksum_address(token_address)
        chain_id = get_chain_id(load_registry())
        factory = get_contract(self.w3, self.deployment.factory, "uniswap_v1_factory")

        try:
            exchange = factory.functions.getExchange(token).call()
        except Exception:
            return []

        if not exchange or exchange == _ZERO:
            return []
        exchange = Web3.to_checksum_address(exchange)
        if not has_bytecode(self.w3, exchange):
            return []

        # V1 is always ETH ↔ ERC20; represent ETH as zero address for token0 order
        eth = _ZERO
        if token.lower() < eth.lower():
            # never true for checksum token vs zero, but keep sort convention
            t0, t1 = token, eth
        else:
            t0, t1 = eth, token

        pool = VerifiedPool(
            chain_id=chain_id,
            protocol="uniswap",
            version="v1",
            architecture="eth_erc20_exchange",
            factory_address=self.deployment.factory,
            pool_address=exchange,
            custody_address=exchange,
            token0=Web3.to_checksum_address(t0),
            token1=Web3.to_checksum_address(t1),
            fee=None,
            verified=False,
            verification_confidence=0.0,
        )
        return dedupe_pools([pool])
