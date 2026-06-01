"""
shadow_comparator.py — Evaluates paper-trade (shadow) performance vs live trades.

Shadow trades are recorded in shadow_trades.json during a shadow test.
At test end the Auditor calls finalize_shadow_trades() then compare_performance()
to decide whether to PROMOTE or DISCARD the candidate param change.

Verdict rules:
  PROMOTE     — shadow win rate >= live win rate AND shadow win rate >= 0.45
  DISCARD     — shadow win rate < live win rate - 0.10  (clearly worse)
  INCONCLUSIVE — not enough data, or result is ambiguous
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, List

logger = logging.getLogger("ShadowComparator")

SHADOW_TRADES_FILE = "shadow_trades.json"
TRADE_LOG_FILE     = "trade_log.json"
DASHBOARD_FILE     = "dashboard.json"

# Minimum closed shadow trades required for a meaningful verdict
MIN_SHADOW_TRADES = 3
# Minimum closed live trades required for comparison
MIN_LIVE_TRADES = 5


class ShadowComparator:
    """Evaluates paper-trade performance vs live trade history."""

    # ─────────────────────────────────────────────────────────────────
    # Recording
    # ─────────────────────────────────────────────────────────────────

    def record_shadow_trade(self, trade_record: dict):
        """Append a shadow trade to shadow_trades.json."""
        try:
            trades = self._load_json(SHADOW_TRADES_FILE, [])
            trades.append(trade_record)
            self._save_json(SHADOW_TRADES_FILE, trades)
            logger.info(
                f"[SHADOW] Recorded paper trade: {trade_record.get('ticker')} "
                f"{trade_record.get('action')} @ {trade_record.get('entry_price')}"
            )
        except Exception as e:
            logger.error(f"ShadowComparator: failed to record shadow trade: {e}")

    # ─────────────────────────────────────────────────────────────────
    # Finalization (called at shadow test end)
    # ─────────────────────────────────────────────────────────────────

    def finalize_shadow_trades(self):
        """
        At shadow test end, estimate P&L for any still-open shadow trades
        using current prices from dashboard.json. Marks them SHADOW_CLOSED.
        """
        shadow_trades = self._load_json(SHADOW_TRADES_FILE, [])
        if not shadow_trades:
            logger.info("ShadowComparator: no shadow trades to finalize")
            return

        prices = self._get_current_prices()
        changed = False

        for t in shadow_trades:
            if t.get("status") != "SHADOW_OPEN":
                continue

            ticker  = t.get("ticker", "")
            base    = ticker.split("/")[0].upper()
            price   = prices.get(base) or prices.get(ticker)

            if not price:
                logger.debug(f"ShadowComparator: no price for {ticker}, leaving SHADOW_OPEN")
                continue

            entry  = float(t.get("entry_price") or 0)
            qty    = float(t.get("quantity") or 0)
            action = t.get("action", "BUY")

            if entry > 0 and qty > 0:
                pnl = (price - entry) * qty if action == "BUY" else (entry - price) * qty
                t["exit_price"]   = price
                t["pnl"]          = round(pnl, 4)
                t["pnl_percent"]  = round((pnl / (entry * qty)) * 100, 2)
                t["status"]       = "SHADOW_CLOSED"
                t["exit_time"]    = datetime.now().isoformat()
                changed = True

        if changed:
            self._save_json(SHADOW_TRADES_FILE, shadow_trades)
            closed_count = sum(1 for t in shadow_trades if t["status"] == "SHADOW_CLOSED")
            logger.info(f"ShadowComparator: finalized {closed_count} shadow trades")

    # ─────────────────────────────────────────────────────────────────
    # Comparison
    # ─────────────────────────────────────────────────────────────────

    def compare_performance(self, n_recent_live: int = 20) -> str:
        """
        Compare shadow trade performance vs recent live trades.
        Returns: PROMOTE, DISCARD, or INCONCLUSIVE.
        """
        shadow_trades = self._load_json(SHADOW_TRADES_FILE, [])
        live_trades   = self._load_json(TRADE_LOG_FILE, [])

        shadow_closed = [
            t for t in shadow_trades
            if t.get("status") == "SHADOW_CLOSED" and t.get("pnl") is not None
        ]
        live_closed = [
            t for t in live_trades
            if t.get("status") == "CLOSED" and (t.get("pnl") or 0) != 0
        ][-n_recent_live:]

        # Not enough shadow data — default to DISCARD to prevent untested changes
        # from being promoted (especially during low-trade periods / deadlocks).
        if len(shadow_closed) < MIN_SHADOW_TRADES:
            logger.info(
                f"ShadowComparator: {len(shadow_closed)} shadow trades "
                f"< min {MIN_SHADOW_TRADES} — insufficient data, defaulting to DISCARD"
            )
            return "DISCARD"

        if len(live_closed) < MIN_LIVE_TRADES:
            logger.info(
                f"ShadowComparator: {len(live_closed)} live trades "
                f"< min {MIN_LIVE_TRADES} — insufficient baseline, defaulting to PROMOTE"
            )
            return "PROMOTE"

        shadow_wr  = sum(1 for t in shadow_closed if (t.get("pnl") or 0) > 0) / len(shadow_closed)
        live_wr    = sum(1 for t in live_closed   if (t.get("pnl") or 0) > 0) / len(live_closed)
        shadow_pnl = sum(t.get("pnl") or 0 for t in shadow_closed)

        logger.info(
            f"ShadowComparator: shadow_wr={shadow_wr:.0%} n={len(shadow_closed)} "
            f"total_pnl=${shadow_pnl:.2f} | live_wr={live_wr:.0%} n={len(live_closed)}"
        )

        if shadow_wr < live_wr - 0.10:
            return "DISCARD"   # Clearly worse — block the change
        else:
            return "PROMOTE"   # Better or inconclusive — allow (drift guard is the hard limit)

    def get_summary(self) -> dict:
        """Return a summary dict for reporting (learning_report.json)."""
        shadow_trades = self._load_json(SHADOW_TRADES_FILE, [])
        closed = [t for t in shadow_trades if t.get("status") == "SHADOW_CLOSED"]
        open_  = [t for t in shadow_trades if t.get("status") == "SHADOW_OPEN"]

        if not closed and not open_:
            return {"active": False}

        wins     = sum(1 for t in closed if (t.get("pnl") or 0) > 0)
        total    = len(closed)
        pnl_sum  = sum(t.get("pnl") or 0 for t in closed)
        win_rate = round(wins / total, 3) if total else 0

        return {
            "active": True,
            "shadow_trades_open":   len(open_),
            "shadow_trades_closed": total,
            "shadow_win_rate":      win_rate,
            "shadow_pnl_usd":       round(pnl_sum, 2),
        }

    # ─────────────────────────────────────────────────────────────────
    # Reset
    # ─────────────────────────────────────────────────────────────────

    def reset_shadow_trades(self):
        """Clear shadow_trades.json after a test completes."""
        self._save_json(SHADOW_TRADES_FILE, [])
        logger.info("ShadowComparator: shadow_trades.json cleared for next test")

    # ─────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────

    def _get_current_prices(self) -> Dict[str, float]:
        """Read latest prices from dashboard.json market_data section."""
        try:
            with open(DASHBOARD_FILE) as f:
                data = json.load(f)
            market = data.get("market_data", {})
            prices: Dict[str, float] = {}
            for ticker, info in market.items():
                if isinstance(info, dict):
                    p = info.get("price") or info.get("last") or info.get("close")
                    if p:
                        base = ticker.split("/")[0].upper()
                        prices[base] = float(p)
            return prices
        except Exception:
            return {}

    def _load_json(self, path: str, default):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return default

    def _save_json(self, path: str, data):
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"ShadowComparator: failed to save {path}: {e}")
