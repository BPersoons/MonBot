import logging
import re

logger = logging.getLogger("PolymarketMatcher")

# Tier 1: Explicit ticker-to-keyword mapping for high-volume assets
TICKER_KEYWORDS = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "eth", "ether"],
    "SOL": ["solana", "sol"],
    "DOGE": ["dogecoin", "doge"],
    "XRP": ["xrp", "ripple"],
    "ADA": ["cardano", "ada"],
    "AVAX": ["avalanche", "avax"],
    "MATIC": ["polygon", "matic"],
    "DOT": ["polkadot", "dot"],
    "LINK": ["chainlink", "link"],
    "ATOM": ["cosmos", "atom"],
    "UNI": ["uniswap", "uni"],
    "ARB": ["arbitrum", "arb"],
    "OP": ["optimism"],
    "SUI": ["sui"],
    "TAO": ["bittensor", "tao"],
    "NEAR": ["near protocol", "near"],
    # Commodities / equities via XYZ prefix
    "XYZ-GOLD": ["gold"],
    "XYZ-SILVER": ["silver"],
    "XYZ-BRENTOIL": ["oil", "crude oil", "brent"],
    "XYZ-COPPER": ["copper"],
    "XYZ-SP500": ["s&p 500", "sp500", "s&p500"],
    "XYZ-NVDA": ["nvidia", "nvda"],
    "XYZ-TSLA": ["tesla", "tsla"],
}

# Keywords that indicate a macro market (relevant to all crypto)
MACRO_KEYWORDS = [
    "fed rate", "federal reserve", "interest rate",
    "inflation", "cpi",
    "crypto regulation", "sec crypto", "bitcoin etf",
    "crypto market cap", "bitcoin dominance",
    "recession", "quantitative",
]

# Keywords that indicate bearish direction in market title
BEARISH_KEYWORDS = [
    "drop below", "fall below", "crash", "decline",
    "bear market", "down", "decrease", "below",
    "dip to", "dip below",
]

# Keywords that indicate bullish direction in market title
BULLISH_KEYWORDS = [
    "reach", "above", "exceed", "surpass", "rise",
    "bull market", "up", "all-time high", "ath",
]


class MatchResult:
    """Result of matching a ticker to Polymarket markets."""
    def __init__(self, markets: list[dict], match_tier: str, confidence: float):
        self.markets = markets
        self.match_tier = match_tier  # "explicit", "keyword", "macro", "none"
        self.confidence = confidence  # 1.0, 0.8, 0.5, 0.0

    def __repr__(self):
        return f"MatchResult(tier={self.match_tier}, markets={len(self.markets)}, conf={self.confidence})"


def match_ticker(ticker: str, available_markets: list[dict]) -> MatchResult:
    """
    Matches a trading ticker to relevant Polymarket prediction markets.

    Three-tier matching:
    1. Explicit map (confidence 1.0) — curated keywords for known assets
    2. Keyword search (confidence 0.8) — ticker name in market titles
    3. Macro fallback (confidence 0.5) — broad crypto/macro markets

    Returns MatchResult with matched markets and confidence level.
    """
    base_ticker = _extract_base_ticker(ticker)

    # Tier 1: Explicit map
    keywords = TICKER_KEYWORDS.get(base_ticker)
    if keywords:
        matched = _search_markets(available_markets, keywords)
        if matched:
            return MatchResult(matched, "explicit", 1.0)

    # Tier 2: Keyword search using ticker name
    search_terms = [base_ticker.lower().replace("xyz-", "")]
    matched = _search_markets(available_markets, search_terms)
    if matched:
        return MatchResult(matched, "keyword", 0.8)

    # Macro fallback removed: homogeneous signal across all non-explicit tickers
    # contaminated shadow-log correlation. Return none so altcoins cleanly opt out.
    return MatchResult([], "none", 0.0)


def classify_market_direction(title: str) -> str:
    """
    Classifies whether a market title implies bullish or bearish direction.
    Returns: "bullish", "bearish", or "neutral"
    """
    title_lower = title.lower()

    bearish_score = sum(1 for kw in BEARISH_KEYWORDS if kw in title_lower)
    bullish_score = sum(1 for kw in BULLISH_KEYWORDS if kw in title_lower)

    if bearish_score > bullish_score:
        return "bearish"
    if bullish_score > bearish_score:
        return "bullish"
    return "neutral"


def get_yes_price(market: dict) -> float | None:
    """Extract the 'Yes' outcome price from a normalized market dict."""
    for outcome in market.get("outcomes", []):
        price = outcome.get("price", 0)
        if price and outcome.get("title", "").lower() in ("yes", "y"):
            return price
    # If no explicit Yes/No with price, take first outcome with price
    for outcome in market.get("outcomes", []):
        price = outcome.get("price", 0)
        if price:
            return price
    # Fallback to last_trade_price or best_bid
    ltp = market.get("last_trade_price", 0)
    if ltp:
        return ltp
    bid = market.get("best_bid", 0)
    if bid:
        return bid
    return None


def _extract_base_ticker(ticker: str) -> str:
    """Extract base ticker from trading pair. 'BTC/USDC' -> 'BTC', 'XYZ-GOLD/USDC' -> 'XYZ-GOLD'."""
    base = ticker.split("/")[0] if "/" in ticker else ticker
    # Remove -USDC, -USDT suffixes if present but keep XYZ- prefix
    for suffix in ["-USDC", "-USDT"]:
        if base.endswith(suffix):
            base = base[:-len(suffix)]
    return base.upper()


def _search_markets(markets: list[dict], keywords: list[str]) -> list[dict]:
    """Search market titles for any of the given keywords. Case-insensitive, word-boundary matching."""
    matched = []
    for m in markets:
        title = m.get("title", "").lower()
        for kw in keywords:
            kw_lower = kw.lower()
            # Use word boundary matching to avoid false positives
            # ("eth" should not match "Netherlands", "gold" should not match "Golden")
            pattern = r'\b' + re.escape(kw_lower) + r'\b'
            if re.search(pattern, title):
                matched.append(m)
                break
    # Sort by volume (highest first)
    matched.sort(key=lambda x: x.get("volume", 0), reverse=True)
    return matched[:10]  # Cap at 10 most liquid matches
