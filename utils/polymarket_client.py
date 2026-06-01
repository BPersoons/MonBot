import logging
import time
import requests

logger = logging.getLogger("PolymarketClient")

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

# In-memory cache with TTL
_market_cache = {"data": None, "expires": 0}
CACHE_TTL = 4 * 3600  # 4 hours


def fetch_crypto_markets(min_volume: float = 50_000, min_liquidity: float = 5_000, max_results: int = 200) -> list[dict]:
    """
    Fetches active crypto-related prediction markets from Polymarket Gamma API.
    Returns filtered list of markets with sufficient volume and liquidity.
    Uses a 4-hour in-memory cache.
    """
    now = time.time()
    if _market_cache["data"] is not None and now < _market_cache["expires"]:
        return _market_cache["data"]

    EVENT_KEYWORDS = [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol",
        "fed decision", "fed interest", "fed chair", "rate cut", "rate hike",
        "inflation", "cpi",
    ]

    all_markets = []
    try:
        # Fetch high-volume events and filter by crypto/macro keywords
        # Events endpoint groups markets by topic — much more reliable than tag-based search
        for offset in [0, 100]:
            try:
                resp = requests.get(
                    f"{GAMMA_BASE}/events",
                    params={"active": "true", "closed": "false", "limit": 100,
                            "offset": offset, "order": "volume", "ascending": "false"},
                    timeout=15,
                )
                if resp.status_code != 200:
                    continue
                events = resp.json()
                if not events:
                    break
                for event in events:
                    title = (event.get("title", "") or "").lower()
                    if any(kw in title for kw in EVENT_KEYWORDS):
                        for m in event.get("markets", []):
                            if not m.get("closed"):
                                all_markets.append(m)
            except Exception:
                continue

    except Exception as e:
        logger.warning(f"Polymarket Gamma API error: {e}")
        return []

    # Deduplicate by condition_id
    seen = set()
    unique = []
    for m in all_markets:
        cid = m.get("conditionId") or m.get("condition_id") or m.get("id", "")
        if cid not in seen:
            seen.add(cid)
            unique.append(m)

    # Filter by volume & liquidity (prefer numeric fields from API)
    filtered = []
    for m in unique:
        volume = _safe_float(m.get("volumeNum", m.get("volume", 0)))
        liquidity = _safe_float(m.get("liquidityNum", m.get("liquidity", 0)))
        if volume >= min_volume and liquidity >= min_liquidity:
            filtered.append(_normalize_market(m))

    # Sort by volume descending
    filtered.sort(key=lambda x: x["volume"], reverse=True)
    result = filtered[:max_results]

    _market_cache["data"] = result
    _market_cache["expires"] = now + CACHE_TTL
    logger.info(f"Polymarket: cached {len(result)} markets (from {len(unique)} unique)")
    return result


def fetch_price_history(token_id: str, interval: str = "1h", start_ts: int = None) -> list[dict]:
    """
    Fetches price history for a specific market outcome token from CLOB API.
    Returns list of {t: unix_timestamp, p: price} dicts.
    """
    try:
        params = {"market": token_id, "interval": interval, "fidelity": 1}
        if start_ts:
            params["startTs"] = start_ts
        resp = requests.get(f"{CLOB_BASE}/prices-history", params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            # API returns {"history": [...]} or just [...]
            if isinstance(data, dict):
                return data.get("history", [])
            return data
    except Exception as e:
        logger.warning(f"Polymarket price history error for {token_id}: {e}")
    return []


def fetch_market_price(token_id: str) -> float | None:
    """Fetches current midpoint price for a token from CLOB API."""
    try:
        resp = requests.get(f"{CLOB_BASE}/midpoint", params={"token_id": token_id}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return _safe_float(data.get("mid", data.get("midpoint", None)))
    except Exception as e:
        logger.debug(f"Polymarket midpoint error for {token_id}: {e}")
    return None


def clear_cache():
    """Clear the in-memory market cache."""
    _market_cache["data"] = None
    _market_cache["expires"] = 0


def _normalize_market(m: dict) -> dict:
    """Extract relevant fields from raw Gamma API market response."""
    outcomes = m.get("outcomes", [])
    tokens = m.get("clobTokenIds", m.get("clob_token_ids", []))

    outcome_data = []
    if isinstance(outcomes, list):
        for i, outcome in enumerate(outcomes):
            if isinstance(outcome, dict):
                outcome_data.append({
                    "title": outcome.get("title", outcome.get("value", f"Outcome_{i}")),
                    "price": _safe_float(outcome.get("price", 0)),
                    "token_id": tokens[i] if i < len(tokens) else None,
                })
            elif isinstance(outcome, str):
                # Some markets return outcomes as plain strings ["Yes", "No"]
                prices = m.get("outcomePrices", m.get("outcome_prices", []))
                price = _safe_float(prices[i]) if i < len(prices) else 0.0
                outcome_data.append({
                    "title": outcome,
                    "price": price,
                    "token_id": tokens[i] if i < len(tokens) else None,
                })

    return {
        "id": m.get("id", ""),
        "condition_id": m.get("condition_id", m.get("conditionId", "")),
        "title": m.get("question", m.get("title", "")) or m.get("groupItemTitle", ""),
        "outcomes": outcome_data,
        "volume": _safe_float(m.get("volumeNum", m.get("volume", 0))),
        "volume_24h": _safe_float(m.get("volume24hr", m.get("volume_24h", 0))),
        "liquidity": _safe_float(m.get("liquidityNum", m.get("liquidity", 0))),
        "last_trade_price": _safe_float(m.get("lastTradePrice", 0)),
        "best_bid": _safe_float(m.get("bestBid", 0)),
        "best_ask": _safe_float(m.get("bestAsk", 0)),
        "end_date": m.get("endDate", m.get("endDateIso", "")),
        "tags": m.get("tags", []),
    }


def _safe_float(val) -> float:
    """Safely convert a value to float, returning 0.0 on failure."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
