"""
stocks_opportunity_manager.py — Watchlist persistence for the stocks department.

Mirrors the crypto OpportunityManager pattern.
State file: stocks_watchlist.json

Statuses:
  WATCHLIST  — scored but below propose threshold, or manually added
  MONITORING — passed score threshold, waiting for entry signal
  PROPOSED   — BUY proposal sent to Telegram, awaiting approval
  APPROVED   — user approved, awaiting execution (Phase 2+)
  REJECTED   — user rejected (SKIP), blackout period enforced
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("StocksOpportunityManager")

WATCHLIST_FILE = "stocks_watchlist.json"
REJECTION_BLACKOUT_DAYS = 7


class StocksOpportunityManager:
    def __init__(self):
        self.logger = logging.getLogger("StocksOpportunityManager")

    def _load(self) -> list:
        if not os.path.exists(WATCHLIST_FILE):
            return []
        try:
            with open(WATCHLIST_FILE) as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning(f"Could not load watchlist: {e}")
            return []

    def _save(self, data: list):
        try:
            with open(WATCHLIST_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.error(f"Could not save watchlist: {e}")

    def get_all(self) -> list:
        return self._load()

    def get_by_status(self, status: str) -> list:
        return [e for e in self._load() if e.get("status") == status]

    def get_ticker(self, ticker: str) -> Optional[dict]:
        for e in self._load():
            if e.get("ticker") == ticker:
                return e
        return None

    def is_blacklisted(self, ticker: str) -> bool:
        """Return True if ticker is in REJECTED blackout period."""
        entry = self.get_ticker(ticker)
        if not entry or entry.get("status") != "REJECTED":
            return False
        rejected_at = entry.get("updated_at", "")
        try:
            dt = datetime.fromisoformat(rejected_at)
            return datetime.utcnow() < dt + timedelta(days=REJECTION_BLACKOUT_DAYS)
        except Exception:
            return False

    def upsert(self, ticker: str, status: str, score: float = 0.0,
               details: dict = None, reason: str = "") -> dict:
        """Add or update a ticker in the watchlist."""
        data = self._load()
        now = datetime.utcnow().isoformat()
        entry = None
        idx = None
        for i, e in enumerate(data):
            if e.get("ticker") == ticker:
                entry = e
                idx = i
                break

        if entry is None:
            entry = {
                "ticker": ticker,
                "added_at": now,
            }
            data.append(entry)
            idx = len(data) - 1

        entry.update({
            "status": status,
            "score": round(score, 4),
            "details": details or {},
            "reason": reason,
            "updated_at": now,
        })
        data[idx] = entry
        self._save(data)
        return entry

    def set_proposed(self, ticker: str, proposal_payload: dict = None):
        entry = self.get_ticker(ticker) or {}
        entry.update({
            "status": "PROPOSED",
            "proposal_payload": proposal_payload or {},
            "proposed_at": datetime.utcnow().isoformat(),
        })
        self._upsert_raw(ticker, entry)

    def set_approved(self, ticker: str):
        entry = self.get_ticker(ticker) or {"ticker": ticker}
        entry["status"] = "APPROVED"
        entry["approved_at"] = datetime.utcnow().isoformat()
        self._upsert_raw(ticker, entry)

    def set_rejected(self, ticker: str):
        entry = self.get_ticker(ticker) or {"ticker": ticker}
        entry["status"] = "REJECTED"
        entry["updated_at"] = datetime.utcnow().isoformat()
        self._upsert_raw(ticker, entry)

    def set_watchlist(self, ticker: str, score: float = 0.0, details: dict = None):
        self.upsert(ticker, "WATCHLIST", score=score, details=details or {},
                    reason="Below propose threshold or user request")

    def remove(self, ticker: str):
        data = [e for e in self._load() if e.get("ticker") != ticker]
        self._save(data)

    def get_monitoring(self) -> list:
        """Return all tickers in MONITORING or WATCHLIST status for hourly re-scoring."""
        return [e for e in self._load() if e.get("status") in ("MONITORING", "WATCHLIST")]

    def expire_old_proposals(self, hours: int = 24):
        """Move PROPOSED entries older than `hours` to WATCHLIST (no-reply = WATCHLIST)."""
        data = self._load()
        changed = False
        for entry in data:
            if entry.get("status") != "PROPOSED":
                continue
            proposed_at = entry.get("proposed_at", "")
            try:
                dt = datetime.fromisoformat(proposed_at)
                if datetime.utcnow() > dt + timedelta(hours=hours):
                    entry["status"] = "WATCHLIST"
                    entry["reason"] = "Approval window expired — auto-moved to WATCHLIST"
                    entry["updated_at"] = datetime.utcnow().isoformat()
                    changed = True
            except Exception:
                pass
        if changed:
            self._save(data)

    def _upsert_raw(self, ticker: str, new_entry: dict):
        data = self._load()
        for i, e in enumerate(data):
            if e.get("ticker") == ticker:
                data[i] = new_entry
                self._save(data)
                return
        data.append(new_entry)
        self._save(data)
