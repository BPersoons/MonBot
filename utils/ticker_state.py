"""
Ticker State Tracker - Per-Ticker Cooldown Management
Tracks when each ticker was last analyzed, what the decision was,
and when it should be re-checked based on decision-tier cooldowns.
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

logger = logging.getLogger("TickerState")

# Cooldown durations per decision tier (in seconds)
COOLDOWN_TIERS = {
    "NO_GO": 1800,        # 30 min — dead chart, wait for new candle cycle
    "MONITOR": 600,       # 10 min — interesting but not ready
    "BUILD_CASE": 300,    # 5 min  — close to entry, watch tightly
    "ENTRY": 60,          # 1 min  — active trade, monitor constantly
    "OPEN": 60,           # 1 min  — open position, constant monitoring
    "PENDING": 0,         # No cooldown — fresh ticker, analyze immediately
}

# Adaptive Scout intervals based on pipeline size
SCOUT_INTERVALS = {
    "empty": 300,         # 5 min  — pipeline < 3 tickers, aggressively fill
    "partial": 900,       # 15 min — 3-10 tickers in pipeline
    "saturated": 1800,    # 30 min — 10+ tickers, conserve API budget
}


class TickerStateTracker:
    """
    JSON-backed per-ticker state tracker.
    Manages cooldowns so the system doesn't waste API tokens
    re-analyzing tickers whose underlying data hasn't changed.
    """

    def __init__(self, storage_file: str = "ticker_state.json"):
        self.storage_file = storage_file
        self.states: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if not os.path.exists(self.storage_file):
            return {}
        try:
            with open(self.storage_file, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"Error loading {self.storage_file}: {e}")
            return {}

    def _save(self):
        try:
            with open(self.storage_file, "w") as f:
                json.dump(self.states, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving {self.storage_file}: {e}")

    def should_analyze(self, ticker: str) -> bool:
        """
        Check if a ticker should be re-analyzed based on its cooldown.
        Returns True if the ticker is eligible for analysis.
        """
        state = self.states.get(ticker)

        if not state:
            return True  # Never analyzed, go ahead

        cooldown_until = state.get("cooldown_until")
        if not cooldown_until:
            return True

        try:
            cooldown_time = datetime.fromisoformat(cooldown_until)
            if datetime.utcnow() >= cooldown_time:
                return True  # Cooldown expired
            else:
                remaining = (cooldown_time - datetime.utcnow()).total_seconds()
                logger.debug(f"[{ticker}] In cooldown ({state.get('last_decision', '?')}), "
                             f"{remaining:.0f}s remaining")
                return False
        except Exception:
            return True  # If parsing fails, allow analysis

    def record_analysis(self, ticker: str, decision: str, score: float = 0.0,
                        extra_meta: dict = None):
        """
        Record the result of an analysis and set the appropriate cooldown
        based on the decision tier.
        """
        now = datetime.utcnow()

        # Normalize decision to a known tier
        decision_upper = decision.upper().replace(" ", "_")
        cooldown_seconds = COOLDOWN_TIERS.get(decision_upper, COOLDOWN_TIERS["MONITOR"])
        cooldown_until = now + timedelta(seconds=cooldown_seconds)

        # Build or update state
        if ticker not in self.states:
            self.states[ticker] = {
                "ticker": ticker,
                "first_seen": now.isoformat(),
                "analysis_count": 0,
            }

        self.states[ticker].update({
            "last_analyzed": now.isoformat(),
            "last_decision": decision_upper,
            "last_score": round(score, 3),
            "cooldown_seconds": cooldown_seconds,
            "cooldown_until": cooldown_until.isoformat(),
            "analysis_count": self.states[ticker].get("analysis_count", 0) + 1,
        })

        if extra_meta:
            self.states[ticker]["meta"] = extra_meta

        logger.info(f"[{ticker}] Recorded: {decision_upper} (score={score:.2f}), "
                    f"cooldown={cooldown_seconds}s, next check at {cooldown_until.strftime('%H:%M:%S')}")

        self._save()

    def get_status(self, ticker: str) -> dict:
        """
        Get the current state of a ticker for dashboard display.
        Returns a dict with human-readable status info.
        """
        state = self.states.get(ticker)
        now = datetime.utcnow()

        if not state:
            return {
                "status": "NEW",
                "last_analyzed": None,
                "last_decision": None,
                "next_check": "Now",
                "cooldown_remaining_s": 0,
            }

        cooldown_until = state.get("cooldown_until")
        if cooldown_until:
            try:
                cooldown_time = datetime.fromisoformat(cooldown_until)
                remaining = max(0, (cooldown_time - now).total_seconds())
            except Exception:
                remaining = 0
        else:
            remaining = 0

        # Human-readable next check
        if remaining <= 0:
            next_check = "Now"
        elif remaining < 60:
            next_check = f"in {int(remaining)}s"
        else:
            next_check = f"in {int(remaining // 60)}min"

        return {
            "status": "COOLDOWN" if remaining > 0 else "READY",
            "last_analyzed": state.get("last_analyzed"),
            "last_decision": state.get("last_decision"),
            "last_score": state.get("last_score", 0.0),
            "next_check": next_check,
            "cooldown_remaining_s": int(remaining),
            "analysis_count": state.get("analysis_count", 0),
        }

    def get_adaptive_scout_interval(self, active_ticker_count: int) -> int:
        """
        Returns the optimal Scout interval based on how full the pipeline is.
        """
        if active_ticker_count < 3:
            interval = SCOUT_INTERVALS["empty"]
            logger.info(f"Scout interval: {interval}s (pipeline nearly empty, {active_ticker_count} tickers)")
        elif active_ticker_count < 10:
            interval = SCOUT_INTERVALS["partial"]
            logger.info(f"Scout interval: {interval}s (pipeline partial, {active_ticker_count} tickers)")
        else:
            interval = SCOUT_INTERVALS["saturated"]
            logger.info(f"Scout interval: {interval}s (pipeline saturated, {active_ticker_count} tickers)")
        return interval

    def get_all_states(self) -> Dict[str, dict]:
        """Get all ticker states for dashboard overview."""
        return {ticker: self.get_status(ticker) for ticker in self.states}

    def cleanup_stale(self, max_age_hours: float = 24.0):
        """Remove tickers that haven't been seen in a long time."""
        now = datetime.utcnow()
        to_remove = []
        for ticker, state in self.states.items():
            try:
                last = datetime.fromisoformat(state.get("last_analyzed", "2000-01-01"))
                if (now - last).total_seconds() > max_age_hours * 3600:
                    to_remove.append(ticker)
            except Exception:
                to_remove.append(ticker)

        for ticker in to_remove:
            logger.info(f"Cleaned up stale ticker state: {ticker}")
            del self.states[ticker]

        if to_remove:
            self._save()
