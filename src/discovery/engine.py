"""Discovery engine — orchestrates all protocol adapters."""
from __future__ import annotations

from typing import Optional

from web3 import Web3

from ..registry.loader import (
    get_chain_id,
    get_enabled_protocols,
    get_quote_assets,
    load_registry,
)
from .log_utils import dedupe_pools
from .base import PoolDiscoveryAdapter
from .uniswap_v1 import UniswapV1Adapter
from .uniswap_v2 import UniswapV2Adapter
from .uniswap_v3 import UniswapV3Adapter
from .uniswap_v4 import UniswapV4Adapter
from .curve import CurveAdapter
from .balancer_v2 import BalancerV2Adapter


_ADAPTER_MAP: dict[str, type[PoolDiscoveryAdapter]] = {
    "UniswapV1Adapter": UniswapV1Adapter,
    "UniswapV2Adapter": UniswapV2Adapter,
    "UniswapV3Adapter": UniswapV3Adapter,
    "UniswapV4Adapter": UniswapV4Adapter,
    "CurveAdapter": CurveAdapter,
    "BalancerV2Adapter": BalancerV2Adapter,
}


def discover_pools(
    w3: Web3,
    token_address: str,
    from_block: int,
    to_block: int,
    chain_id: int = 1,
) -> dict[str, list]:
    """Discover all pools containing *token_address* across all supported protocols.

    When ``DUNE_API_KEY`` is set, Dune ``dex.trades`` pool discovery runs first
    (fast, cross-DEX); RPC adapters still run and are merged in.  Dune results
    are marked ``verified=False`` and resolved during verification.

    Returns {"pools": [...], "protocols_used": [...], "errors": [...]}.
    """
    registry = load_registry()
    chain_id = get_chain_id(registry)
    deployments = get_enabled_protocols(registry)
    quote_assets = get_quote_assets(registry)

    all_pools: list = []
    protocol_names: set[str] = set()
    errors: list[str] = []

    # Optional Dune-first pool discovery (fast, cross-DEX)
    dune_error: Optional[str] = None
    try:
        from ..data.dune_client import DuneClient, dune_api_key_configured
        from ..models import VerifiedPool as _VP
        if dune_api_key_configured():
            client = DuneClient()
            rows = client.fetch_pools_for_token(
                Web3.to_checksum_address(token_address),
                from_block,
                to_block,
            )
            for row in rows:
                project = row["project"]
                version = row["version"]
                pool_addr = row["pool_address"]
                # Map Dune project/version names to our protocol config keys.
                if project in ("uniswap",) and version in ("v2", "v3", "v4"):
                    adapter_name = "Uniswap{}Adapter".format(version.upper())
                elif project == "curve":
                    adapter_name = "CurveAdapter"
                    version = "v2" if "crypto" in row.get("pool_name", "").lower() else "v1"
                elif project in ("balancer", "balancer-v2"):
                    adapter_name = "BalancerV2Adapter"
                    version = "v2"
                else:
                    adapter_name = None
                if adapter_name is None:
                    continue
                # Balancer Dune pool_id is a bytes32 poolId; pool contract is
                # the first 20 bytes.
                if adapter_name == "BalancerV2Adapter":
                    pid_raw = pool_addr
                    if pid_raw.startswith("0x") and len(pid_raw) == 66:
                        try:
                            pool_addr = Web3.to_checksum_address(
                                "0x" + pid_raw[2:42]
                            )
                        except Exception:
                            pass
                # Find a matching deployment to inherit factory/router metadata.
                dep = next(
                    (
                        d for d in deployments
                        if d.adapter == adapter_name
                        and (d.version == version or version in ("v1", "v2", "v3", "v4"))
                    ),
                    None,
                )
                if dep is None:
                    continue
                hints = row.get("token_hints") or []
                t0 = Web3.to_checksum_address(token_address)
                t1 = ""
                for h in hints:
                    try:
                        cand = Web3.to_checksum_address(h)
                    except Exception:
                        continue
                    if cand.lower() != t0.lower():
                        t1 = cand
                        break
                all_pools.append(_VP(
                    chain_id=chain_id,
                    protocol=dep.protocol,
                    version=version,
                    architecture=dep.architecture,
                    factory_address=dep.factory,
                    router_addresses=[dep.router] if dep.router else [],
                    pool_address=pool_addr,
                    custody_address=pool_addr,
                    token0=t0,
                    token1=t1,
                    verified=False,
                    verification_confidence=0.0,
                ))
                protocol_names.add(f"{dep.protocol}_{version}")
    except Exception as e:
        dune_error = str(e)

    for dep in deployments:
        adapter_cls = _ADAPTER_MAP.get(dep.adapter)
        if adapter_cls is None:
            errors.append(f"No adapter registered for {dep.adapter}")
            continue

        adapter = adapter_cls(w3, dep)
        try:
            pools = adapter.discover(
                token_address, from_block, to_block, quote_assets
            )
            all_pools.extend(pools)
            protocol_names.add(f"{dep.protocol}_{dep.version}")
        except Exception as e:
            errors.append(f"{dep.protocol}_{dep.version}: {e}")

    all_pools = dedupe_pools(all_pools)

    result = {
        "pools": [p.__dict__ for p in all_pools],
        "protocols_used": list(protocol_names),
        "errors": errors,
    }
    if dune_error:
        result["dune_error"] = dune_error
    return result
