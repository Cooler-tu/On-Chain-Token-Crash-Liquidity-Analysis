"""Discovery engine — orchestrates all protocol adapters."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from web3 import Web3

from ..registry.loader import (
    get_chain_id,
    get_enabled_protocols,
    get_quote_assets,
    load_registry,
)
from ..models import VerifiedPool
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


def _normalize_dune_row(row: dict) -> dict:
    """Normalize a Dune pool row from either the CLI or a saved web-UI export."""
    hints: list[str] = []
    for key in ("token_hints", "token0", "token1", "token_bought", "token_sold"):
        value = row.get(key)
        if isinstance(value, list):
            hints.extend(value)
        elif value:
            hints.append(value)
    seen: set[str] = set()
    clean_hints: list[str] = []
    for hint in hints:
        hint = str(hint).strip().lower()
        if hint and hint not in seen:
            seen.add(hint)
            clean_hints.append(hint)
    return {
        "pool_address": row.get("pool_address") or row.get("pool_id") or "",
        "project": (row.get("project") or row.get("protocol") or "").lower(),
        "version": (row.get("version") or "").lower(),
        "pool_name": row.get("pool_name") or "",
        "token_hints": clean_hints,
    }


def _map_dune_project(row: dict) -> tuple[Optional[str], Optional[str]]:
    """Map Dune project/version names to adapter + registry version keys."""
    project = row["project"]
    version = row["version"]
    if project == "uniswap":
        v = {
            "1": "v1", "v1": "v1",
            "2": "v2", "v2": "v2",
            "3": "v3", "v3": "v3",
            "4": "v4", "4.0": "v4", "v4": "v4",
        }.get(version)
        if v is None:
            return None, None
        return "Uniswap{}Adapter".format(v.upper()), v
    if project == "curve":
        v = (
            "v2"
            if "crypto" in version
            or "v2" in version
            or "crypto" in row["pool_name"].lower()
            else "v1"
        )
        return "CurveAdapter", v
    if project in ("balancer", "balancer-v2"):
        return "BalancerV2Adapter", "v2"
    return None, None


def _dune_rows_to_pools(
    rows: list[dict],
    token_address: str,
    chain_id: int,
    deployments: list,
) -> tuple[list, set[str]]:
    """Convert Dune pool rows into unverified VerifiedPool candidates."""
    all_pools = []
    protocol_names: set[str] = set()
    target = Web3.to_checksum_address(token_address)

    for row in rows:
        norm = _normalize_dune_row(row)
        if not norm["pool_address"]:
            continue
        adapter_name, version = _map_dune_project(norm)
        if adapter_name is None:
            continue

        pool_addr = norm["pool_address"]
        # Balancer Dune pool_id is a bytes32 poolId; pool contract is the
        # first 20 bytes.
        if adapter_name == "BalancerV2Adapter" and pool_addr.startswith("0x") and len(pool_addr) == 66:
            try:
                pool_addr = Web3.to_checksum_address("0x" + pool_addr[2:42])
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

        t0 = Web3.to_checksum_address(token_address)
        t1 = ""
        explicit_tokens = []
        for key in ("token0", "token1"):
            value = row.get(key)
            if value:
                try:
                    explicit_tokens.append(Web3.to_checksum_address(str(value)))
                except Exception:
                    pass
        if len(explicit_tokens) == 2:
            t0, t1 = explicit_tokens
        else:
            for hint in norm["token_hints"]:
                try:
                    cand = Web3.to_checksum_address(hint)
                except Exception:
                    continue
                if cand.lower() != t0.lower():
                    t1 = cand
                    break
        all_pools.append(VerifiedPool(
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
        protocol_names.add("{}_{}".format(dep.protocol, version))
    return all_pools, protocol_names


def load_pools_file(
    pools_file: Path | str,
    token_address: str,
    from_block: int,
    to_block: int,
    chain_id: int = 1,
) -> dict:
    """Load pool candidates from a saved Dune pools JSON file.

    Accepts either the CLI ``dune pools`` output (a plain list) or a saved
    web-UI export with a ``data`` array.  Records are normalized into
    VerifiedPool candidates with the same shape as ``discover_pools()``.
    """
    path = Path(pools_file)
    if not path.exists():
        raise FileNotFoundError("Pools file not found: {}".format(path))
    with open(path) as f:
        payload = json.load(f)
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("pools") or payload.get("rows")
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError("Unsupported pools file shape in {}".format(path))
    rows = rows or []

    errors: list[str] = []
    file_token = str(payload.get("token") or "").strip().lower() if isinstance(payload, dict) else ""
    if file_token.startswith("0x") and file_token != str(token_address).lower():
        errors.append(
            "Pools file token {} differs from requested token {}".format(
                payload.get("token"), token_address
            )
        )

    registry = load_registry()
    chain_id = get_chain_id(registry)
    deployments = get_enabled_protocols(registry)
    pools, protocol_names = _dune_rows_to_pools(
        rows, token_address, chain_id, deployments
    )
    pools = dedupe_pools(pools)
    return {
        "pools": [p.__dict__ for p in pools],
        "protocols_used": list(protocol_names),
        "errors": errors,
        "pools_file": str(path),
        "skipped": len(rows) - len(pools),
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
        if dune_api_key_configured():
            client = DuneClient()
            rows = client.fetch_pools_for_token(
                Web3.to_checksum_address(token_address),
                from_block,
                to_block,
            )
            dune_pools, dune_protocols = _dune_rows_to_pools(
                rows, token_address, chain_id, deployments
            )
            all_pools.extend(dune_pools)
            protocol_names.update(dune_protocols)
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
