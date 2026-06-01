"""
YieldOracle — on-chain APY verification for yield protocols.

Supplements DeFiLlama with exact on-chain rates where possible:
  - Aave v3 Arbitrum: Pool.getReserveData(USDC) → currentLiquidityRate in Ray
  - ERC-4626 vaults (Morpho, Gains): DeFiLlama remains authoritative
    (no standard on-chain APY method; rate is computed off-chain by each protocol)

Integration order in get_yield_opportunities():
  1. Build list from DeFiLlama
  2. enrich_with_onchain_apy()  ← updates 'apy' field for Aave; sets 'apy_source'
  3. enrich_opportunities()     ← risk model uses corrected 'apy' field

Usage:
    from utils.treasury_yield_oracle import enrich_with_onchain_apy
    opportunities = enrich_with_onchain_apy(opportunities)
"""

import json
import logging
import urllib.request

logger = logging.getLogger("YieldOracle")

# ── Constants ─────────────────────────────────────────────────────────────────
_ARB_RPCS  = [
    "https://arbitrum.gateway.tenderly.co",   # public gateway; eth_call works from GCP
    "https://1rpc.io/arb",
    "https://rpc.ankr.com/arbitrum",
]
_AAVE_POOL = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"
_USDC_ARB  = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
_RAY       = 10 ** 27
_SPY       = 365 * 24 * 3600    # seconds per year
_APY_MIN   = 0.0
_APY_MAX   = 50.0               # sanity cap — anything above is likely a bad RPC response


# ── RPC helper (no external deps) ─────────────────────────────────────────────

def _eth_call(to: str, data: str) -> str:
    """eth_call on Arbitrum, tried across multiple RPC fallbacks. Returns hex result."""
    payload = json.dumps({
        "jsonrpc": "2.0", "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
        "id": 1,
    }).encode()
    last_exc: Exception = RuntimeError("no RPCs configured")
    for url in _ARB_RPCS:
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                resp = json.loads(r.read())
            if "error" in resp:
                raise RuntimeError(str(resp["error"]))
            return resp.get("result", "0x")
        except Exception as e:
            last_exc = e
    raise last_exc


# ── On-chain APY queries ───────────────────────────────────────────────────────

def get_aave_supply_apy() -> float:
    """
    Query Aave v3 Pool.getReserveData(USDC) for the current supply APY.

    ABI: getReserveData(address) → selector 0x35ea6a75
    Return struct (each field is one 32-byte ABI slot):
      Slot 0 (bytes   0-31): configuration.data  (uint256)
      Slot 1 (bytes  32-63): liquidityIndex      (uint128)
      Slot 2 (bytes  64-95): currentLiquidityRate (uint128)  ← target

    APY% = ((1 + rate_ray/RAY/SPY)^SPY - 1) × 100
    """
    addr_param = _USDC_ARB.lower().replace("0x", "").zfill(64)
    raw  = _eth_call(_AAVE_POOL, "0x35ea6a75" + addr_param)
    data = bytes.fromhex(raw.removeprefix("0x"))
    if len(data) < 96:
        raise ValueError(f"getReserveData returned {len(data)} bytes — expected ≥96")

    rate_ray     = int.from_bytes(data[64:96], "big")
    rate_per_sec = rate_ray / _RAY / _SPY
    apy_pct      = ((1 + rate_per_sec) ** _SPY - 1) * 100
    return round(apy_pct, 4)


# ── Enrichment ────────────────────────────────────────────────────────────────

def enrich_with_onchain_apy(opportunities: list[dict]) -> list[dict]:
    """
    For Aave v3 Arbitrum, replace the DeFiLlama APY with the exact on-chain
    supply rate. All other protocols keep DeFiLlama as authoritative.

    Sets per-opportunity fields:
      apy_source    — 'on-chain' | 'defillama'
      apy_defillama — original DeFiLlama value (preserved for comparison)
    """
    aave_apy: float | None = None
    try:
        aave_apy = get_aave_supply_apy()
        if not (_APY_MIN <= aave_apy <= _APY_MAX):
            logger.warning(
                f"YieldOracle: Aave on-chain APY {aave_apy:.2f}% outside "
                f"sanity range [{_APY_MIN},{_APY_MAX}%] — falling back to DeFiLlama"
            )
            aave_apy = None
        else:
            logger.info(f"YieldOracle: Aave on-chain supply APY = {aave_apy:.4f}%")
    except Exception as e:
        logger.debug(f"YieldOracle: Aave on-chain query failed ({e}) — using DeFiLlama")

    for opp in opportunities:
        pid = (opp.get("protocol_config") or {}).get("id", "")
        opp.setdefault("apy_defillama", opp.get("apy", 0.0))
        if pid == "aave-v3-arbitrum-usdc" and aave_apy is not None:
            opp["apy"]        = aave_apy
            opp["apy_source"] = "on-chain"
        else:
            opp["apy_source"] = "defillama"

    return opportunities
