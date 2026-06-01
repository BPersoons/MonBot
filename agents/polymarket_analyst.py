import logging
import datetime
import json
import os
from utils.polymarket_client import fetch_crypto_markets, fetch_market_price
from utils.polymarket_matcher import match_ticker, classify_market_direction, get_yes_price


class PolymarketAnalyst:
    """
    Polymarket Prediction Market Analyst.

    Uses Polymarket prediction market probabilities as a trading signal.
    Converts market consensus (Yes/No prices) into a directional score [-1.0, +1.0].

    Phase 1: Shadow mode — signal is logged but not used in scoring.
    """

    SHADOW_LOG_FILE = "polymarket_shadow_log.json"

    def __init__(self, db_client=None):
        self.logger = logging.getLogger("PolymarketAnalyst")
        self.db_client = db_client
        self._cache = {}  # {ticker: {"result": dict, "expires": float}}
        self._cache_ttl = 2 * 3600  # 2 hours

    async def analyze_async(self, ticker: str) -> dict:
        import asyncio
        return await asyncio.to_thread(self.analyze, ticker)

    def analyze(self, ticker: str) -> dict:
        """
        Analyzes the ticker using Polymarket prediction market data.
        Returns a signal between -1.0 (Bearish) and +1.0 (Bullish).
        """
        self.logger.info(f"Analyzing Polymarket data for {ticker}...")
        now = datetime.datetime.now()
        now_ts = now.timestamp()

        # Check in-memory cache
        cached = self._cache.get(ticker)
        if cached and now_ts < cached["expires"]:
            self.logger.info(f"Using cached Polymarket data for {ticker}")
            return cached["result"]

        # Check Supabase cache
        cache_key = f"POLYMARKET_{ticker}"
        if self.db_client:
            try:
                cached_result = self.db_client.get_agent_cache(cache_key, ttl_hours=2.0)
                if cached_result:
                    self.logger.info(f"Using Supabase-cached Polymarket data for {ticker}")
                    self._cache[ticker] = {"result": cached_result, "expires": now_ts + self._cache_ttl}
                    return cached_result
            except Exception:
                pass

        # Fetch markets and match
        try:
            markets = fetch_crypto_markets()
        except Exception as e:
            self.logger.warning(f"Failed to fetch Polymarket markets: {e}")
            return self._no_data_result(ticker, f"API error: {e}")

        match = match_ticker(ticker, markets)

        if not match.markets:
            self.logger.info(f"No Polymarket markets found for {ticker}")
            return self._no_data_result(ticker, "No matching prediction markets")

        # Calculate composite signal from matched markets
        signal, summary, market_details = self._calculate_signal(match)

        result = {
            "agent": "PolymarketAnalyst",
            "signal": round(max(-1.0, min(1.0, signal)), 4),
            "ticker": ticker,
            "status": match.match_tier.upper(),
            "summary": summary,
            "markets_matched": len(match.markets),
            "match_tier": match.match_tier,
            "confidence": match.confidence,
            "market_details": market_details[:5],  # Top 5 markets
            "timestamp": now.isoformat(),
        }

        # Cache result
        self._cache[ticker] = {"result": result, "expires": now_ts + self._cache_ttl}
        if self.db_client:
            try:
                self.db_client.set_agent_cache(cache_key, result)
            except Exception:
                pass

        self.logger.info(f"Polymarket signal for {ticker}: {result['signal']:.3f} "
                         f"(tier={match.match_tier}, markets={len(match.markets)})")
        return result

    def _calculate_signal(self, match) -> tuple[float, str, list[dict]]:
        """
        Converts Polymarket probabilities into a directional signal.

        For bullish markets ("Will X reach $Y?"): signal = (yes_price - 0.5) * 2.0
        For bearish markets ("Will X drop below $Y?"): signal = (0.5 - yes_price) * 2.0

        Markets with extreme probabilities (<5% or >95%) are heavily discounted
        because they contain little information — the interesting signal is in
        markets where there's genuine uncertainty (20-80% range).

        Weighted by volume * informativeness. Confidence-discounted by match tier.
        """
        weighted_sum = 0.0
        total_weight = 0.0
        market_details = []

        for market in match.markets:
            yes_price = get_yes_price(market)
            if yes_price is None:
                continue

            volume = market.get("volume", 1)
            direction = classify_market_direction(market.get("title", ""))

            # Convert probability to directional signal
            if direction == "bearish":
                # High prob of bearish event = bearish signal
                raw_signal = (0.5 - yes_price) * 2.0
            else:
                # Bullish or neutral framing: high prob = bullish
                raw_signal = (yes_price - 0.5) * 2.0

            # Informativeness weight: markets near 50% are most informative,
            # markets at extremes (<5% or >95%) tell us very little
            # Uses a bell curve centered at 0.5
            informativeness = 1.0 - (2.0 * abs(yes_price - 0.5)) ** 2
            informativeness = max(0.05, informativeness)  # Floor at 5%

            weight = max(volume, 1) * informativeness
            weighted_sum += raw_signal * weight
            total_weight += weight

            market_details.append({
                "title": market.get("title", "")[:100],
                "yes_price": round(yes_price, 3),
                "direction": direction,
                "raw_signal": round(raw_signal, 3),
                "informativeness": round(informativeness, 3),
                "volume": volume,
            })

        if total_weight == 0:
            return 0.0, "No valid market prices found", []

        avg_signal = weighted_sum / total_weight

        # Apply confidence discount based on match tier
        final_signal = avg_signal * match.confidence

        # Build summary
        top_market = market_details[0] if market_details else {}
        summary = (
            f"Polymarket consensus ({match.match_tier}): "
            f"{len(market_details)} markets matched, "
            f"signal={final_signal:.2f}. "
            f"Top: \"{top_market.get('title', 'N/A')}\" "
            f"(Yes={top_market.get('yes_price', 0):.0%})"
        )

        return final_signal, summary, market_details

    def log_shadow(self, ticker: str, result: dict, existing_signals: dict,
                   combined_score: float, pipeline_outcome: str):
        """
        Appends a shadow log entry for offline analysis.
        Called by ProjectLead during pipeline execution.
        """
        entry = {
            "ticker": ticker,
            "timestamp": datetime.datetime.now().isoformat(),
            "poly_signal": result.get("signal", 0.0),
            "markets_matched": result.get("markets_matched", 0),
            "match_tier": result.get("match_tier", "none"),
            "confidence": result.get("confidence", 0.0),
            "market_details": result.get("market_details", []),
            "existing_signals": existing_signals,
            "combined_score": combined_score,
            "pipeline_outcome": pipeline_outcome,
        }
        try:
            log = []
            if os.path.exists(self.SHADOW_LOG_FILE):
                with open(self.SHADOW_LOG_FILE, "r") as f:
                    log = json.load(f)
            log.append(entry)
            # Keep last 500 entries
            if len(log) > 500:
                log = log[-500:]
            with open(self.SHADOW_LOG_FILE, "w") as f:
                json.dump(log, f, indent=2, default=str)
        except Exception as e:
            self.logger.debug(f"Shadow log write failed: {e}")

    def _no_data_result(self, ticker: str, reason: str) -> dict:
        return {
            "agent": "PolymarketAnalyst",
            "signal": 0.0,
            "ticker": ticker,
            "status": "NO_MARKETS",
            "summary": reason,
            "markets_matched": 0,
            "match_tier": "none",
            "confidence": 0.0,
            "market_details": [],
            "timestamp": datetime.datetime.now().isoformat(),
        }
