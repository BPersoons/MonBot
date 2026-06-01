"""
sector_benchmarks.py — Sector median EV/EBITDA multiples for relative valuation.

Updated quarterly by CPO or manually. Used by TwinEngineAnalyst Engine 2.
Source: Bloomberg / Damodaran databases (approximate medians as of Q1 2025).
"""

# Sector median EV/EBITDA — used to compute relative valuation score
# Key must match yfinance info['sector'] values exactly
SECTOR_EV_EBITDA_MEDIANS: dict[str, float] = {
    "Technology":                   22.0,
    "Healthcare":                   16.0,
    "Financial Services":           12.0,
    "Consumer Cyclical":            14.0,
    "Consumer Defensive":           13.0,
    "Industrials":                  14.0,
    "Communication Services":       13.0,
    "Energy":                        8.0,
    "Basic Materials":               9.0,
    "Utilities":                    11.0,
    "Real Estate":                  18.0,
    # Fallback for unknown sectors
    "Unknown":                      14.0,
}

# Sector exclusions for Phase 1 (regulatory / ESG / complexity)
EXCLUDED_SECTORS = {"Utilities", "Real Estate"}


def get_sector_ev_ebitda(sector: str) -> float:
    """Return the median EV/EBITDA for a given sector, with fallback."""
    return SECTOR_EV_EBITDA_MEDIANS.get(sector, SECTOR_EV_EBITDA_MEDIANS["Unknown"])


def is_excluded_sector(sector: str) -> bool:
    """Return True if this sector is excluded from Phase 1 screening."""
    return sector in EXCLUDED_SECTORS
