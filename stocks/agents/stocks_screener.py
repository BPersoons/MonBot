"""
stocks_screener.py — Stage 1+2 screening: Universe → ~50 candidates.

Stage 1 (~5000 → ~500): Filter by market cap, volume, sector, exchange.
Stage 2 (~500 → ~50):  Fast quantitative pre-screen (revenue growth, EPS trend,
                        price momentum) using yfinance only — no FMP calls.

Universe: S&P 500 + NASDAQ 100 tickers, fetched from Wikipedia / hardcoded CSVs.
"""

import logging
import time
from typing import Optional

from stocks.utils.yfinance_client import YFinanceClient
from stocks.utils.sector_benchmarks import is_excluded_sector

logger = logging.getLogger("StocksScreener")

# Stage 1 prefilter thresholds
MIN_MARKET_CAP = 500_000_000      # $500M
MIN_AVG_VOLUME = 500_000           # 500K shares/day (30d average)
EARNINGS_BLACKOUT_DAYS = 5         # skip if earnings within N days

# Stage 2 fast score threshold
FAST_SCORE_THRESHOLD = 0.45


def _fetch_sp500_tickers() -> list[str]:
    """Fetch S&P 500 tickers from Wikipedia."""
    try:
        import pandas as pd
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url, header=0)
        tickers = tables[0]["Symbol"].tolist()
        # Normalize: BRK.B → BRK-B (yfinance format)
        return [t.replace(".", "-") for t in tickers]
    except Exception as e:
        logger.warning(f"Could not fetch S&P 500 tickers: {e}")
        return []


def _fetch_nasdaq100_tickers() -> list[str]:
    """Fetch NASDAQ 100 tickers from Wikipedia."""
    try:
        import pandas as pd
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        tables = pd.read_html(url, header=0)
        # Table index can vary; find the one with a 'Ticker' column
        for table in tables:
            cols = [c.lower() for c in table.columns]
            for col_name in ("ticker", "symbol"):
                if col_name in cols:
                    real_col = table.columns[[c.lower() for c in table.columns].index(col_name)]
                    return [t.replace(".", "-") for t in table[real_col].tolist()]
    except Exception as e:
        logger.warning(f"Could not fetch NASDAQ 100 tickers: {e}")
    return []


class StocksScreener:
    def __init__(self, auto_params=None):
        self.logger = logging.getLogger("StocksScreener")
        self.yf = YFinanceClient()
        self._auto_params = auto_params

    def _get_param(self, key: str, default):
        if self._auto_params:
            try:
                return self._auto_params.get(key, default)
            except Exception:
                pass
        return default

    # ─────────────────────────────────────────────────────────────────
    # Stage 1: Universe → ~500
    # ─────────────────────────────────────────────────────────────────

    def fetch_universe(self) -> list[str]:
        """Return deduplicated list of S&P500 + NASDAQ100 tickers."""
        self.logger.info("Fetching universe (S&P500 + NASDAQ100)...")
        sp500 = _fetch_sp500_tickers()
        ndx100 = _fetch_nasdaq100_tickers()
        combined = list(dict.fromkeys(sp500 + ndx100))  # preserve order, deduplicate
        self.logger.info(f"Universe: {len(combined)} tickers ({len(sp500)} S&P500, {len(ndx100)} NASDAQ100)")
        return combined

    def stage1_filter(self, tickers: list[str]) -> list[str]:
        """
        Apply hard filters to reduce universe to ~500 candidates.
        Uses yfinance info dict — no FMP calls.
        """
        self.logger.info(f"Stage 1 filtering {len(tickers)} tickers...")
        passed = []
        blackout_days = self._get_param("earnings_blackout_days", EARNINGS_BLACKOUT_DAYS)

        for ticker in tickers:
            try:
                info = self.yf.get_info(ticker)
                if not info:
                    continue

                # Market cap filter
                mkt_cap = info.get("marketCap") or 0
                if mkt_cap < MIN_MARKET_CAP:
                    continue

                # Volume filter (use averageVolume)
                avg_vol = info.get("averageVolume") or info.get("averageDailyVolume3Month") or 0
                if avg_vol < MIN_AVG_VOLUME:
                    continue

                # Sector exclusion
                sector = info.get("sector", "Unknown")
                if is_excluded_sector(sector):
                    continue

                # Exchange filter (NYSE / NASDAQ only)
                exchange = (info.get("exchange") or "").upper()
                if exchange not in ("NYQ", "NMS", "NGM", "NCM", "NYSE", "NASDAQ",
                                    "NYSE ARCA", "BATS"):
                    # yfinance uses NYQ for NYSE, NMS for NASDAQ
                    if exchange not in ("NYQ", "NMS", "NGM", "NCM"):
                        # allow if exchange contains NYSE or NASDAQ substring
                        if "NYSE" not in exchange and "NASDAQ" not in exchange:
                            # last resort: if quoteType is EQUITY, include
                            if info.get("quoteType", "").upper() != "EQUITY":
                                continue

                # Earnings blackout
                days = self.yf.days_to_earnings(ticker)
                if days is not None and 0 <= days <= blackout_days:
                    self.logger.debug(f"  {ticker}: earnings in {days}d — blackout skip")
                    continue

                passed.append(ticker)
            except Exception as e:
                self.logger.debug(f"  {ticker}: Stage 1 error — {e}")
            time.sleep(0.1)  # gentle rate limiting

        self.logger.info(f"Stage 1: {len(passed)}/{len(tickers)} passed")
        return passed

    # ─────────────────────────────────────────────────────────────────
    # Stage 2: ~500 → ~50
    # ─────────────────────────────────────────────────────────────────

    def _fast_score(self, ticker: str) -> Optional[float]:
        """
        Compute a fast_score [0..1] from yfinance info only.
        Components:
          - revenue_growth (revenueGrowth): 0.35 weight
          - eps_trend (earningsQuarterlyGrowth): 0.40 weight
          - price_momentum (52w position): 0.25 weight
        Returns None if data is too sparse.
        """
        info = self.yf.get_info(ticker)
        if not info:
            return None

        scores = []
        weights = []

        # Revenue growth (yfinance ttm growth %)
        rev_growth = info.get("revenueGrowth")  # e.g. 0.18 = 18%
        if rev_growth is not None:
            # Map: >30%=1.0, >20%=0.85, >10%=0.70, >5%=0.55, >0%=0.35, <0=0.10
            if rev_growth > 0.30:
                rg_score = 1.0
            elif rev_growth > 0.20:
                rg_score = 0.85
            elif rev_growth > 0.10:
                rg_score = 0.70
            elif rev_growth > 0.05:
                rg_score = 0.55
            elif rev_growth > 0:
                rg_score = 0.35
            else:
                rg_score = 0.10
            scores.append(rg_score)
            weights.append(0.35)

        # EPS quarterly growth trend
        eps_growth = info.get("earningsQuarterlyGrowth")
        if eps_growth is not None:
            if eps_growth > 0.30:
                eg_score = 1.0
            elif eps_growth > 0.15:
                eg_score = 0.80
            elif eps_growth > 0.05:
                eg_score = 0.60
            elif eps_growth > 0:
                eg_score = 0.40
            else:
                eg_score = 0.10
            scores.append(eg_score)
            weights.append(0.40)

        # Price momentum (52w position)
        momentum = self.yf.get_price_momentum(ticker)
        if momentum is not None:
            # Mid-range momentum preferred (not at 52w high already)
            # 0.3–0.7 range = healthy momentum without being overbought
            mom_score = 1.0 - abs(momentum - 0.50) * 1.5
            mom_score = max(0.1, min(1.0, mom_score))
            scores.append(mom_score)
            weights.append(0.25)

        if not scores:
            return None

        total_weight = sum(weights)
        fast_score = sum(s * w for s, w in zip(scores, weights)) / total_weight
        return round(fast_score, 3)

    def stage2_prescreen(self, tickers: list[str]) -> list[dict]:
        """
        Apply fast quantitative pre-screen. Returns list of
        {ticker, fast_score, info_snapshot} for tickers passing threshold.
        """
        self.logger.info(f"Stage 2 pre-screening {len(tickers)} tickers...")
        passed = []
        threshold = self._get_param("fast_score_threshold", FAST_SCORE_THRESHOLD)

        for ticker in tickers:
            try:
                fast_score = self._fast_score(ticker)
                if fast_score is None:
                    continue
                if fast_score >= threshold:
                    info = self.yf.get_info(ticker)
                    passed.append({
                        "ticker": ticker,
                        "fast_score": fast_score,
                        "sector": info.get("sector", "Unknown"),
                        "market_cap": info.get("marketCap", 0),
                        "revenue_growth": info.get("revenueGrowth"),
                        "eps_quarterly_growth": info.get("earningsQuarterlyGrowth"),
                        "momentum": self.yf.get_price_momentum(ticker),
                        "current_price": self.yf.get_current_price(ticker),
                    })
            except Exception as e:
                self.logger.debug(f"  {ticker}: Stage 2 error — {e}")
            time.sleep(0.05)

        # Sort by fast_score descending, cap at 50
        passed.sort(key=lambda x: x["fast_score"], reverse=True)
        passed = passed[:50]
        self.logger.info(f"Stage 2: {len(passed)} candidates (threshold={threshold:.2f})")
        return passed

    # ─────────────────────────────────────────────────────────────────
    # Combined run
    # ─────────────────────────────────────────────────────────────────

    def run(self) -> list[dict]:
        """
        Full Stage 1+2 run. Returns up to 50 pre-screened candidates.
        Clears yfinance cache at start of each full run.
        """
        self.yf.clear_cache()
        universe = self.fetch_universe()
        if not universe:
            self.logger.error("Empty universe — cannot screen")
            return []
        stage1 = self.stage1_filter(universe)
        candidates = self.stage2_prescreen(stage1)
        self.logger.info(f"Screening complete: {len(candidates)} candidates from {len(universe)} universe")
        return candidates
