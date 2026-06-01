"""
yfinance_client.py — Cached yfinance wrapper for the stocks department.

Caches info dicts and price history to avoid redundant network calls
within the same screening cycle. Cache TTL: 4 hours for info, 1 hour for prices.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger("YFinanceClient")

# In-memory cache: {ticker: {"data": ..., "fetched_at": float}}
_info_cache: dict = {}
_price_cache: dict = {}

INFO_TTL = 4 * 3600   # 4 hours
PRICE_TTL = 1 * 3600  # 1 hour


class YFinanceClient:
    def __init__(self):
        self.logger = logging.getLogger("YFinanceClient")

    def get_info(self, ticker: str, force_refresh: bool = False) -> dict:
        """
        Return yfinance Ticker.info dict. Cached for INFO_TTL seconds.
        Returns {} on failure.
        """
        cached = _info_cache.get(ticker)
        if cached and not force_refresh and (time.time() - cached["fetched_at"] < INFO_TTL):
            return cached["data"]
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            info = t.info or {}
            _info_cache[ticker] = {"data": info, "fetched_at": time.time()}
            return info
        except Exception as e:
            self.logger.warning(f"yfinance info failed for {ticker}: {e}")
            return {}

    def get_price_history(self, ticker: str, period: str = "1y",
                          interval: str = "1d", force_refresh: bool = False):
        """
        Return yfinance historical OHLCV DataFrame. Cached for PRICE_TTL seconds.
        Returns None on failure.
        """
        cache_key = f"{ticker}_{period}_{interval}"
        cached = _price_cache.get(cache_key)
        if cached and not force_refresh and (time.time() - cached["fetched_at"] < PRICE_TTL):
            return cached["data"]
        try:
            import yfinance as yf
            df = yf.download(ticker, period=period, interval=interval,
                             auto_adjust=True, progress=False)
            _price_cache[cache_key] = {"data": df, "fetched_at": time.time()}
            return df
        except Exception as e:
            self.logger.warning(f"yfinance price history failed for {ticker}: {e}")
            return None

    def get_current_price(self, ticker: str) -> Optional[float]:
        """Return latest close price from info dict."""
        info = self.get_info(ticker)
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price:
            return float(price)
        # Fallback: last close from history
        df = self.get_price_history(ticker, period="5d", interval="1d")
        if df is not None and not df.empty:
            return float(df["Close"].iloc[-1])
        return None

    def get_52w_range(self, ticker: str) -> tuple[Optional[float], Optional[float]]:
        """Return (52w_low, 52w_high)."""
        info = self.get_info(ticker)
        lo = info.get("fiftyTwoWeekLow")
        hi = info.get("fiftyTwoWeekHigh")
        return (float(lo) if lo else None, float(hi) if hi else None)

    def get_rsi(self, ticker: str, period: int = 14) -> Optional[float]:
        """Compute RSI(14) on daily closes. Returns None on failure."""
        try:
            df = self.get_price_history(ticker, period="3mo", interval="1d")
            if df is None or len(df) < period + 1:
                return None
            closes = df["Close"].dropna()
            delta = closes.diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
            rs = gain / loss.replace(0, float("nan"))
            rsi = 100 - (100 / (1 + rs))
            val = rsi.iloc[-1]
            return float(val) if val == val else None  # NaN check
        except Exception as e:
            self.logger.warning(f"RSI calculation failed for {ticker}: {e}")
            return None

    def get_price_momentum(self, ticker: str) -> Optional[float]:
        """
        Price momentum = (current - 52w_low) / (52w_high - 52w_low).
        Returns 0.0–1.0; None if data unavailable.
        """
        price = self.get_current_price(ticker)
        lo, hi = self.get_52w_range(ticker)
        if price is None or lo is None or hi is None:
            return None
        rng = hi - lo
        if rng <= 0:
            return 0.5
        return max(0.0, min(1.0, (price - lo) / rng))

    def get_earnings_date(self, ticker: str) -> Optional[str]:
        """Return next earnings date as ISO string, or None."""
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            cal = t.calendar
            if cal is not None and not cal.empty:
                # calendar is a DataFrame with columns as dates
                first_col = cal.columns[0]
                return str(first_col.date()) if hasattr(first_col, "date") else str(first_col)
        except Exception:
            pass
        return None

    def days_to_earnings(self, ticker: str) -> Optional[int]:
        """Return days until next earnings, or None if unknown."""
        from datetime import datetime, date
        ed = self.get_earnings_date(ticker)
        if not ed:
            return None
        try:
            earnings_date = datetime.fromisoformat(ed).date()
            return (earnings_date - date.today()).days
        except Exception:
            return None

    def clear_cache(self):
        """Clear all cached data (call between full screening cycles)."""
        _info_cache.clear()
        _price_cache.clear()
        self.logger.info("YFinanceClient cache cleared")
