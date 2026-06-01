"""
fmp_client.py — Financial Modeling Prep (FMP) API wrapper.

Free tier: 250 calls/day.  We track daily usage and refuse calls once the
budget is exhausted to avoid silent 402 errors corrupting scoring.

Key endpoints used:
  /income-statement           — revenue, EPS history
  /cash-flow-statement        — operating cash flow, capex
  /key-metrics-ttm            — ROIC, EV/EBITDA (cross-check)
  /historical-discounted-cash-flow-statement — analyst EPS growth estimate
  /insider-trading            — insider buy/sell activity (last 90d)
  /insider-ownership          — aggregate insider ownership %
  /profile                    — sector, description, CEO name

Set FMP_API_KEY in .env.adk or GCP Secret Manager.
"""

import json
import logging
import os
import time
from datetime import datetime, date
from typing import Any, Optional

import requests

logger = logging.getLogger("FMPClient")

FMP_BASE = "https://financialmodelingprep.com/api/v3"
CALL_BUDGET_FILE = "stocks_fmp_usage.json"
DAILY_BUDGET = 200  # leave 50 calls headroom on the free 250-call plan


def _load_usage() -> dict:
    try:
        with open(CALL_BUDGET_FILE) as f:
            data = json.load(f)
        if data.get("date") != str(date.today()):
            return {"date": str(date.today()), "calls": 0}
        return data
    except Exception:
        return {"date": str(date.today()), "calls": 0}


def _save_usage(data: dict):
    try:
        with open(CALL_BUDGET_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning(f"Could not save FMP usage: {e}")


class FMPClient:
    def __init__(self, api_key: Optional[str] = None):
        self.logger = logging.getLogger("FMPClient")
        self._api_key = api_key or self._load_api_key()
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "AgentTraderStocks/1.0"})

    def _load_api_key(self) -> Optional[str]:
        key = os.getenv("FMP_API_KEY")
        if not key:
            try:
                from dotenv import load_dotenv
                load_dotenv(".env.adk")
                key = os.getenv("FMP_API_KEY")
            except Exception:
                pass
        if not key:
            self.logger.warning("FMP_API_KEY not set — FMP calls will fail")
        return key

    # ─────────────────────────────────────────────────────────────────
    # Internal request helper
    # ─────────────────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: dict = None, version: str = "v3") -> Any:
        usage = _load_usage()
        if usage["calls"] >= DAILY_BUDGET:
            self.logger.warning(
                f"FMP daily budget exhausted ({usage['calls']}/{DAILY_BUDGET}). Skipping call."
            )
            return None

        base = f"https://financialmodelingprep.com/api/{version}"
        url = f"{base}/{endpoint}"
        p = {"apikey": self._api_key, **(params or {})}
        try:
            r = self._session.get(url, params=p, timeout=15)
            r.raise_for_status()
            usage["calls"] += 1
            _save_usage(usage)
            data = r.json()
            if isinstance(data, dict) and data.get("Error Message"):
                self.logger.warning(f"FMP error for {endpoint}: {data['Error Message']}")
                return None
            return data
        except requests.HTTPError as e:
            self.logger.warning(f"FMP HTTP error {e.response.status_code} for {endpoint}: {e}")
            return None
        except Exception as e:
            self.logger.warning(f"FMP request failed for {endpoint}: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────

    def get_income_statements(self, ticker: str, limit: int = 6) -> list[dict]:
        """Annual income statements, most recent first."""
        data = self._get(f"income-statement/{ticker}", {"limit": limit})
        return data if isinstance(data, list) else []

    def get_cash_flow_statements(self, ticker: str, limit: int = 6) -> list[dict]:
        """Annual cash flow statements, most recent first."""
        data = self._get(f"cash-flow-statement/{ticker}", {"limit": limit})
        return data if isinstance(data, list) else []

    def get_key_metrics_ttm(self, ticker: str) -> dict:
        """Trailing twelve-month key metrics (ROIC, EV/EBITDA, etc.)."""
        data = self._get(f"key-metrics-ttm/{ticker}")
        if isinstance(data, list) and data:
            return data[0]
        return {}

    def get_profile(self, ticker: str) -> dict:
        """Company profile (CEO, sector, description, market cap)."""
        data = self._get(f"profile/{ticker}")
        if isinstance(data, list) and data:
            return data[0]
        return {}

    def get_insider_trading(self, ticker: str, limit: int = 100) -> list[dict]:
        """Recent insider transactions. Sorted newest first by FMP."""
        data = self._get(f"insider-trading", {"symbol": ticker, "limit": limit})
        return data if isinstance(data, list) else []

    def get_insider_ownership(self, ticker: str) -> list[dict]:
        """Aggregate insider ownership (% held by insiders)."""
        data = self._get(f"insider-roaster-statistic", {"symbol": ticker})
        return data if isinstance(data, list) else []

    def get_analyst_estimates(self, ticker: str, limit: int = 4) -> list[dict]:
        """Analyst EPS / revenue estimates by quarter."""
        data = self._get(f"analyst-estimates/{ticker}", {"limit": limit})
        return data if isinstance(data, list) else []

    def get_shares_outstanding_history(self, ticker: str, limit: int = 5) -> list[dict]:
        """Annual shares outstanding history for dilution check."""
        data = self._get(f"shares_float", {"symbol": ticker})
        return data if isinstance(data, list) else []

    # ─────────────────────────────────────────────────────────────────
    # Derived helpers
    # ─────────────────────────────────────────────────────────────────

    def get_revenue_cagr(self, ticker: str, years: int = 3) -> Optional[float]:
        """Compute revenue CAGR over `years` years. Returns None on insufficient data."""
        stmts = self.get_income_statements(ticker, limit=years + 2)
        revenues = [s.get("revenue") for s in stmts if s.get("revenue")]
        if len(revenues) < years + 1:
            return None
        try:
            newest = revenues[0]
            oldest = revenues[years]
            if oldest <= 0:
                return None
            return (newest / oldest) ** (1 / years) - 1
        except Exception:
            return None

    def get_eps_cagr(self, ticker: str, years: int = 3) -> Optional[float]:
        """Compute EPS CAGR over `years` years from income statements."""
        stmts = self.get_income_statements(ticker, limit=years + 2)
        eps_list = [s.get("eps") for s in stmts if s.get("eps") is not None]
        if len(eps_list) < years + 1:
            return None
        try:
            newest = eps_list[0]
            oldest = eps_list[years]
            if oldest <= 0 or newest <= 0:
                return None
            return (newest / oldest) ** (1 / years) - 1
        except Exception:
            return None

    def get_fcf_data(self, ticker: str) -> dict:
        """
        Return latest FCF, FCF margin, and FCF CAGR (3yr).
        Also checks for buyback (share reduction YoY from income statement).
        """
        stmts = self.get_cash_flow_statements(ticker, limit=5)
        income = self.get_income_statements(ticker, limit=5)

        result = {
            "latest_fcf": None,
            "fcf_margin": None,
            "fcf_cagr_3yr": None,
            "has_buyback": False,
        }

        fcf_series = []
        for cf in stmts:
            ocf = cf.get("operatingCashFlow") or 0
            capex = abs(cf.get("capitalExpenditure") or 0)
            fcf_series.append(ocf - capex)

        if not fcf_series:
            return result

        result["latest_fcf"] = fcf_series[0]

        # FCF margin = FCF / revenue
        if income:
            rev = income[0].get("revenue") or 0
            if rev > 0:
                result["fcf_margin"] = fcf_series[0] / rev

        # FCF CAGR (3yr)
        if len(fcf_series) >= 4 and fcf_series[3] > 0 and fcf_series[0] > 0:
            result["fcf_cagr_3yr"] = (fcf_series[0] / fcf_series[3]) ** (1 / 3) - 1

        # Buyback check: shares outstanding reduced YoY
        shares = [s.get("weightedAverageShsOut") for s in income if s.get("weightedAverageShsOut")]
        if len(shares) >= 2 and shares[1] > 0:
            change = (shares[0] - shares[1]) / shares[1]
            result["has_buyback"] = change < -0.005  # > 0.5% reduction

        return result

    def get_insider_net_shares_90d(self, ticker: str) -> int:
        """
        Return net insider shares bought (positive) or sold (negative) in last 90 days.
        """
        from datetime import date, timedelta
        cutoff = date.today() - timedelta(days=90)
        trades = self.get_insider_trading(ticker, limit=100)
        net = 0
        for t in trades:
            try:
                td = datetime.strptime(t.get("transactionDate", ""), "%Y-%m-%d").date()
                if td < cutoff:
                    break
            except Exception:
                continue
            ttype = (t.get("transactionType") or "").lower()
            shares = int(t.get("securitiesTransacted") or 0)
            if "purchase" in ttype or "buy" in ttype or "acquisition" in ttype:
                net += shares
            elif "sale" in ttype or "sell" in ttype or "disposition" in ttype:
                net -= shares
        return net

    def get_roic_ttm(self, ticker: str) -> Optional[float]:
        """Return TTM ROIC as a decimal (e.g. 0.22 = 22%). None if unavailable."""
        metrics = self.get_key_metrics_ttm(ticker)
        roic = metrics.get("roicTTM")
        return float(roic) if roic is not None else None

    def get_daily_calls_used(self) -> int:
        return _load_usage()["calls"]

    def get_daily_calls_remaining(self) -> int:
        return max(0, DAILY_BUDGET - self.get_daily_calls_used())
