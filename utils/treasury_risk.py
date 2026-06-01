"""
Treasury RiskModel — per-protocol risk scoring for yield allocation.

Each protocol is scored on 5 dimensions (0.0–1.0, higher = safer):
  sc          — smart contract audit quality and production track record
  liquidity   — speed of exit (instant vs. days)
  counterparty — exposure to third-party losses (lending vs. trading vault)
  maturity    — protocol age and battle-tested history
  tvl         — TVL depth (computed dynamically from live data)

Overall score = weighted sum. Used by TreasuryAgent to rank protocols by
risk-adjusted APY instead of raw APY, and by AllocationOptimizer (Fase 2)
to determine tranche allocation weights.
"""

import math
import logging

logger = logging.getLogger("TreasuryRisk")

# ── Weights (must sum to 1.0) ─────────────────────────────────────────────────
_WEIGHTS = {
    "sc":           0.25,
    "liquidity":    0.25,
    "counterparty": 0.30,
    "maturity":     0.10,
    "tvl":          0.10,
}

# TVL reference: $100M = perfect TVL score
_TVL_REFERENCE_USD = 100_000_000

# ── Static risk profiles per protocol ID ─────────────────────────────────────
# sc: audit quality + time in production (Aave/Compound = industry standard)
# liquidity: 1.0=instant, 0.75=1-3d, 0.60=variable, 0.40=locked
# counterparty: 1.0=none (lending), 0.5=moderate, 0.35=high (trading vault absorbs losses)
# maturity: years in production at scale (1.0=5+y, 0.75=2-3y, 0.60=1-2y, 0.40=<1y)
_PROFILES: dict[str, dict] = {
    "aave-v3-arbitrum-usdc": {
        "sc":           0.95,
        "liquidity":    1.00,
        "counterparty": 1.00,
        "maturity":     0.95,
        "description":  "Overcollateralized lending; instant withdraw; no counterparty risk. Industry-standard audits.",
        "tranche":      "liquidity_reserve",
    },
    "morpho-bbqusdc-arbitrum": {
        "sc":           0.85,
        "liquidity":    0.75,
        "counterparty": 0.90,
        "maturity":     0.70,
        "description":  "Curated lending vault (Gauntlet USDC Core); exit 1-3d; liquidation risk but no trading counterparty.",
        "tranche":      "yield_core",
    },
    "morpho-gtusdcc-arbitrum": {
        "sc":           0.85,
        "liquidity":    0.75,
        "counterparty": 0.85,
        "maturity":     0.65,
        "description":  "Curated lending vault (Gauntlet USDC Prime); similar to BBQUSDC, smaller TVL.",
        "tranche":      "yield_core",
    },
    "gains-network-arbitrum-usdc": {
        "sc":           0.72,
        "liquidity":    0.60,
        "counterparty": 0.35,
        "maturity":     0.65,
        "description":  "Perp trading fee vault; vault absorbs losses when Gains traders are net profitable. High counterparty risk.",
        "tranche":      "opportunistic",
    },
    "compound-v3-arbitrum-usdc": {
        "sc":           0.90,
        "liquidity":    0.90,
        "counterparty": 0.95,
        "maturity":     0.85,
        "description":  "Overcollateralized lending; near-instant withdraw; battle-tested protocol.",
        "tranche":      "liquidity_reserve",
    },
}

_UNKNOWN_PROFILE = {
    "sc":           0.50,
    "liquidity":    0.50,
    "counterparty": 0.50,
    "maturity":     0.40,
    "description":  "Unknown protocol — defaulting to conservative scores.",
    "tranche":      "opportunistic",
}


def _tvl_score(tvl_usd: float) -> float:
    """Log-scaled TVL score: $0=0.2 floor, $100M=1.0."""
    if tvl_usd <= 0:
        return 0.20
    raw = math.log1p(tvl_usd) / math.log1p(_TVL_REFERENCE_USD)
    return round(min(1.0, max(0.20, raw)), 4)


def _risk_label(score: float) -> str:
    if score >= 0.88:
        return "LOW"
    if score >= 0.75:
        return "MEDIUM-LOW"
    if score >= 0.62:
        return "MEDIUM"
    if score >= 0.50:
        return "MEDIUM-HIGH"
    return "HIGH"


def score_protocol(protocol_id: str, tvl_usd: float = 0.0) -> dict:
    """
    Score a protocol. Returns:
      overall (float 0-1), components (dict), label (str), description (str), tranche (str)
    """
    profile = _PROFILES.get(protocol_id, _UNKNOWN_PROFILE)
    if protocol_id not in _PROFILES:
        logger.debug(f"TreasuryRisk: no profile for '{protocol_id}' — using conservative defaults")

    tvl = _tvl_score(tvl_usd)
    components = {
        "sc":           profile["sc"],
        "liquidity":    profile["liquidity"],
        "counterparty": profile["counterparty"],
        "maturity":     profile["maturity"],
        "tvl":          tvl,
    }
    overall = sum(_WEIGHTS[k] * v for k, v in components.items())

    return {
        "overall":     round(overall, 4),
        "components":  {k: round(v, 4) for k, v in components.items()},
        "label":       _risk_label(overall),
        "description": profile.get("description", ""),
        "tranche":     profile.get("tranche", "opportunistic"),
    }


def risk_adjusted_apy(apy: float, risk_score: float) -> float:
    """Discount raw APY by risk score. 1.0 = no discount, 0.5 = 50% discount."""
    return round(apy * risk_score, 4)


def enrich_opportunities(opportunities: list[dict]) -> list[dict]:
    """
    Add 'risk_score' (dict) and 'risk_adjusted_apy' (float) to each opportunity.
    Re-sorts by risk_adjusted_apy descending.
    """
    for opp in opportunities:
        pid      = (opp.get("protocol_config") or {}).get("id", "")
        tvl      = float(opp.get("tvl_usd") or 0)
        rs       = score_protocol(pid, tvl)
        raw_apy  = float(opp.get("apy") or 0)
        opp["risk_score"]        = rs
        opp["risk_adjusted_apy"] = risk_adjusted_apy(raw_apy, rs["overall"])

    opportunities.sort(key=lambda x: -x.get("risk_adjusted_apy", 0))
    return opportunities
