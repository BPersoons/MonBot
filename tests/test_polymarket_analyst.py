"""Tests for Polymarket analyst, client, and matcher."""
import pytest
from unittest.mock import patch, MagicMock
from utils.polymarket_matcher import (
    match_ticker, classify_market_direction, get_yes_price,
    _extract_base_ticker, MatchResult,
)


# --- Matcher tests ---

class TestExtractBaseTicker:
    def test_simple_pair(self):
        assert _extract_base_ticker("BTC/USDC") == "BTC"

    def test_xyz_prefix(self):
        assert _extract_base_ticker("XYZ-GOLD/USDC") == "XYZ-GOLD"

    def test_no_pair(self):
        assert _extract_base_ticker("SOL") == "SOL"


SAMPLE_MARKETS = [
    {
        "title": "Will Bitcoin reach $120,000 by July 2026?",
        "outcomes": [{"title": "Yes", "price": 0.72}, {"title": "No", "price": 0.28}],
        "volume": 500000,
        "liquidity": 25000,
    },
    {
        "title": "Will Ethereum ETF be approved by SEC?",
        "outcomes": [{"title": "Yes", "price": 0.55}, {"title": "No", "price": 0.45}],
        "volume": 200000,
        "liquidity": 10000,
    },
    {
        "title": "Will the Fed rate cut happen in June 2026?",
        "outcomes": [{"title": "Yes", "price": 0.40}, {"title": "No", "price": 0.60}],
        "volume": 800000,
        "liquidity": 50000,
    },
    {
        "title": "Will Bitcoin drop below $50,000?",
        "outcomes": [{"title": "Yes", "price": 0.15}, {"title": "No", "price": 0.85}],
        "volume": 300000,
        "liquidity": 20000,
    },
]


class TestMatchTicker:
    def test_btc_explicit_match(self):
        result = match_ticker("BTC/USDC", SAMPLE_MARKETS)
        assert result.match_tier == "explicit"
        assert result.confidence == 1.0
        assert len(result.markets) >= 1
        # Should match bitcoin markets
        titles = [m["title"].lower() for m in result.markets]
        assert any("bitcoin" in t for t in titles)

    def test_eth_explicit_match(self):
        result = match_ticker("ETH/USDC", SAMPLE_MARKETS)
        assert result.match_tier == "explicit"
        assert any("ethereum" in m["title"].lower() for m in result.markets)

    def test_unknown_ticker_macro_fallback(self):
        result = match_ticker("UNKNOWN/USDC", SAMPLE_MARKETS)
        assert result.match_tier == "macro"
        assert result.confidence == 0.5

    def test_no_markets_at_all(self):
        result = match_ticker("BTC/USDC", [])
        assert result.match_tier == "none"
        assert result.confidence == 0.0
        assert len(result.markets) == 0


class TestClassifyDirection:
    def test_bullish(self):
        assert classify_market_direction("Will Bitcoin reach $120K?") == "bullish"

    def test_bearish(self):
        assert classify_market_direction("Will Bitcoin drop below $50K?") == "bearish"

    def test_neutral(self):
        assert classify_market_direction("Bitcoin market cap in 2026") == "neutral"


class TestGetYesPrice:
    def test_standard_yes_no(self):
        market = {"outcomes": [{"title": "Yes", "price": 0.72}, {"title": "No", "price": 0.28}]}
        assert get_yes_price(market) == 0.72

    def test_no_outcomes(self):
        assert get_yes_price({"outcomes": []}) is None

    def test_no_yes_label(self):
        market = {"outcomes": [{"title": "Option A", "price": 0.6}]}
        assert get_yes_price(market) == 0.6  # Falls back to first outcome


# --- Analyst tests ---

class TestPolymarketAnalyst:
    @patch("agents.polymarket_analyst.fetch_crypto_markets")
    def test_analyze_returns_standard_interface(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_MARKETS
        from agents.polymarket_analyst import PolymarketAnalyst
        pa = PolymarketAnalyst()
        result = pa.analyze("BTC/USDC")

        assert "signal" in result
        assert "ticker" in result
        assert "status" in result
        assert "summary" in result
        assert "agent" in result
        assert result["agent"] == "PolymarketAnalyst"
        assert -1.0 <= result["signal"] <= 1.0

    @patch("agents.polymarket_analyst.fetch_crypto_markets")
    def test_no_markets_returns_zero(self, mock_fetch):
        mock_fetch.return_value = []
        from agents.polymarket_analyst import PolymarketAnalyst
        pa = PolymarketAnalyst()
        result = pa.analyze("UNKNOWN_TICKER/USDC")

        assert result["signal"] == 0.0
        assert result["status"] == "NO_MARKETS"

    @patch("agents.polymarket_analyst.fetch_crypto_markets")
    def test_btc_bullish_signal(self, mock_fetch):
        # Markets show BTC likely to reach target (Yes=0.72) and unlikely to crash (Yes=0.15)
        mock_fetch.return_value = SAMPLE_MARKETS
        from agents.polymarket_analyst import PolymarketAnalyst
        pa = PolymarketAnalyst()
        result = pa.analyze("BTC/USDC")

        # With "reach $120K" at 72% Yes and "drop below $50K" at 15% Yes,
        # the volume-weighted signal should be net positive
        assert result["signal"] > 0, f"Expected positive signal, got {result['signal']}"

    @patch("agents.polymarket_analyst.fetch_crypto_markets")
    def test_caching(self, mock_fetch):
        mock_fetch.return_value = SAMPLE_MARKETS
        from agents.polymarket_analyst import PolymarketAnalyst
        pa = PolymarketAnalyst()

        result1 = pa.analyze("BTC/USDC")
        result2 = pa.analyze("BTC/USDC")

        # Second call should use cache, so fetch_crypto_markets called only once
        assert mock_fetch.call_count == 1
        assert result1["signal"] == result2["signal"]


# --- Client tests ---

class TestPolymarketClient:
    @patch("utils.polymarket_client.requests.get")
    def test_fetch_crypto_markets_filters_by_volume(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Mock the events endpoint format — events contain nested markets
        mock_response.json.return_value = [
            {
                "title": "Bitcoin price predictions",
                "markets": [
                    {"conditionId": "1", "question": "Will Bitcoin reach $100K?",
                     "volume": "100000", "volumeNum": 100000, "liquidity": "10000", "liquidityNum": 10000,
                     "outcomes": ["Yes", "No"], "outcomePrices": ["0.6", "0.4"],
                     "clobTokenIds": ["t1", "t2"], "closed": False},
                    {"conditionId": "2", "question": "Low vol BTC market",
                     "volume": "100", "volumeNum": 100, "liquidity": "50", "liquidityNum": 50,
                     "outcomes": ["Yes", "No"], "outcomePrices": ["0.5", "0.5"],
                     "clobTokenIds": ["t3", "t4"], "closed": False},
                ],
            },
        ]
        mock_get.return_value = mock_response

        from utils.polymarket_client import fetch_crypto_markets, clear_cache
        clear_cache()
        result = fetch_crypto_markets(min_volume=50000, min_liquidity=5000)

        # Only the high-volume market should pass
        assert len(result) == 1
        assert "Bitcoin" in result[0]["title"]

    @patch("utils.polymarket_client.requests.get")
    def test_api_error_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("Connection error")

        from utils.polymarket_client import fetch_crypto_markets, clear_cache
        clear_cache()
        result = fetch_crypto_markets()
        assert result == []
