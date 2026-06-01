# Single source of truth for XYZ synthetic equity tokens.
# Add a new entry here to enable yfinance enrichment, market-hours gating,
# and any other equity-specific logic across all agents.
XYZ_EQUITY_MAP: dict[str, str] = {
    "XYZ-NVDA":  "NVDA",
    "XYZ-TSLA":  "TSLA",
    "XYZ-INTC":  "INTC",
    "XYZ-GOOGL": "GOOGL",
    "XYZ-MU":    "MU",
    "XYZ-MSTR":  "MSTR",
    "XYZ-CRCL":  "CRCL",
}

# Derived set — use this for membership checks (e.g. market-hours gating).
XYZ_EQUITY_TICKERS: frozenset[str] = frozenset(XYZ_EQUITY_MAP.keys())
