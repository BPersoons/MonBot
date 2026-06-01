"""
stocks_auditor.py — Weekly RSI audit for the stocks department.

Run every Sunday 18:00 CET (16:00 UTC). Analyzes closed trades from
stocks_trade_log.json and tunes scoring weights + thresholds.

Phase 1: Mostly a stub — records audit history but has no closed trades yet
to tune from. Weight tuning activates once >= 5 closed positions exist
(gated by minimum sample size).

Mirrors the crypto PerformanceAuditor pattern but adapted for:
  - Weekly cadence (not per-cycle)
  - Stocks-specific params (stocks_auto_params.json)
  - 48h veto window (not 1h like crypto)
  - Shadow test: 2 weeks before promoting param change
"""

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("StocksAuditor")

TRADE_LOG_FILE = "stocks_trade_log.json"
AUDIT_LOG_FILE = "stocks_audit_log.json"
MIN_TRADES_FOR_TUNING = 5
WEIGHT_ADJUSTMENT = 0.02
THRESHOLD_ADJUSTMENT = 0.02
WIN_RATE_TARGET = 0.55  # above this = performing well
ACCURACY_HIGH = 0.65    # dimension accuracy above this → increase weight
ACCURACY_LOW = 0.40     # dimension accuracy below this → decrease weight


class StocksAuditor:
    def __init__(self, auto_params=None):
        self.logger = logging.getLogger("StocksAuditor")
        self._auto_params = auto_params

    def _load_trade_log(self) -> list:
        try:
            if os.path.exists(TRADE_LOG_FILE):
                with open(TRADE_LOG_FILE) as f:
                    return json.load(f)
        except Exception as e:
            self.logger.warning(f"Could not load trade log: {e}")
        return []

    def _get_closed_trades(self) -> list:
        """Return trades with status=CLOSED and pnl_pct available."""
        trades = self._load_trade_log()
        return [
            t for t in trades
            if t.get("status") == "CLOSED" and t.get("pnl_pct") is not None
        ]

    def _classify_trade(self, trade: dict) -> str:
        """WIN, LOSS, or CRASH_LOSS (market-driven, excluded from weight tuning)."""
        pnl_pct = trade.get("pnl_pct", 0)
        # Crash loss: > -15% drawdown in < 5 trading days (market shock)
        hold_days = trade.get("hold_days", 999)
        if pnl_pct < -15 and hold_days < 5:
            return "CRASH_LOSS"
        return "WIN" if pnl_pct > 0 else "LOSS"

    def run_weekly_audit(self) -> dict:
        """
        Main audit entry point. Called every Sunday 18:00 CET.
        Returns audit summary dict.
        """
        self.logger.info("=== StocksAuditor: Weekly RSI Audit ===")
        closed = self._get_closed_trades()

        # Classify trades (exclude CRASH_LOSS from tuning)
        classified = [(t, self._classify_trade(t)) for t in closed]
        tunable = [(t, c) for t, c in classified if c != "CRASH_LOSS"]

        wins = sum(1 for _, c in tunable if c == "WIN")
        losses = sum(1 for _, c in tunable if c == "LOSS")
        total = len(tunable)

        win_rate = wins / total if total > 0 else None
        self.logger.info(
            f"Closed trades: {len(closed)} total, {total} tunable "
            f"(WIN={wins}, LOSS={losses}, win_rate={win_rate:.1%})" if win_rate else
            f"Closed trades: {len(closed)} total, {total} tunable"
        )

        audit_result = {
            "run_at": datetime.now(timezone.utc).isoformat(),
            "closed_trades": len(closed),
            "tunable_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "actions": [],
            "skipped_reason": None,
        }

        if total < MIN_TRADES_FOR_TUNING:
            msg = f"Insufficient data: {total} tunable trades < {MIN_TRADES_FOR_TUNING} minimum"
            self.logger.info(f"Audit: {msg} — weight tuning skipped")
            audit_result["skipped_reason"] = msg
            self._save_audit_log(audit_result)
            return audit_result

        # Compute per-dimension accuracy
        dimension_accuracy = self._compute_dimension_accuracy(tunable)
        audit_result["dimension_accuracy"] = dimension_accuracy

        # Adjust weights
        if self._auto_params:
            actions = self._adjust_weights(dimension_accuracy)
            # Adjust score threshold based on win rate
            if win_rate is not None:
                actions += self._adjust_threshold(win_rate)
            audit_result["actions"] = actions
            self.logger.info(f"Audit actions: {actions}")
        else:
            self.logger.warning("No auto_params configured — skipping weight adjustment")
            audit_result["skipped_reason"] = "auto_params not configured"

        self._save_audit_log(audit_result)
        return audit_result

    def _compute_dimension_accuracy(self, tunable: list) -> dict:
        """
        For each scoring dimension, compute what fraction of WIN trades
        had above-median score in that dimension.
        """
        dimensions = ["growth", "multiple", "management", "moat", "sentiment"]
        accuracy = {}

        for dim in dimensions:
            scores_win = []
            scores_loss = []
            for trade, classification in tunable:
                details = trade.get("analysis_details", {})
                dim_score = details.get(dim, {}).get("score") if isinstance(details.get(dim), dict) else None
                if dim_score is None:
                    dim_score = details.get(f"{dim}_score")
                if dim_score is None:
                    continue
                if classification == "WIN":
                    scores_win.append(dim_score)
                else:
                    scores_loss.append(dim_score)

            if not scores_win and not scores_loss:
                accuracy[dim] = None
                continue

            # Accuracy: what fraction of wins had score > median of all scores
            all_scores = scores_win + scores_loss
            median = sorted(all_scores)[len(all_scores) // 2]
            above_median_wins = sum(1 for s in scores_win if s > median)
            total_above = sum(1 for s in all_scores if s > median)
            acc = above_median_wins / total_above if total_above > 0 else 0.5
            accuracy[dim] = round(acc, 3)

        return accuracy

    def _adjust_weights(self, accuracy: dict) -> list:
        """Adjust w_growth, w_multiple, etc. based on dimension accuracy."""
        actions = []
        param_map = {
            "growth": "w_growth",
            "multiple": "w_multiple",
            "management": "w_management",
            "moat": "w_moat",
            "sentiment": "w_sentiment",
        }
        for dim, param in param_map.items():
            acc = accuracy.get(dim)
            if acc is None:
                continue
            current = self._auto_params.get(param, 0.20)
            if acc > ACCURACY_HIGH:
                new_val = round(current + WEIGHT_ADJUSTMENT, 3)
                result = self._auto_params.update(
                    param, new_val, "StocksAuditor",
                    f"Dimension {dim} accuracy {acc:.1%} > {ACCURACY_HIGH:.0%}"
                )
                if result is not None:
                    actions.append(f"{param}: {current:.3f} → {new_val:.3f} (accuracy={acc:.1%})")
            elif acc < ACCURACY_LOW:
                new_val = round(current - WEIGHT_ADJUSTMENT, 3)
                result = self._auto_params.update(
                    param, new_val, "StocksAuditor",
                    f"Dimension {dim} accuracy {acc:.1%} < {ACCURACY_LOW:.0%}"
                )
                if result is not None:
                    actions.append(f"{param}: {current:.3f} → {new_val:.3f} (accuracy={acc:.1%})")
        return actions

    def _adjust_threshold(self, win_rate: float) -> list:
        """Adjust score_threshold_propose based on portfolio win rate."""
        actions = []
        current = self._auto_params.get("score_threshold_propose", 0.65)
        if win_rate < WIN_RATE_TARGET - 0.10:
            # Too many losers: raise threshold
            new_val = round(current + THRESHOLD_ADJUSTMENT, 3)
            result = self._auto_params.update(
                "score_threshold_propose", new_val, "StocksAuditor",
                f"Win rate {win_rate:.1%} below target {WIN_RATE_TARGET:.0%}"
            )
            if result is not None:
                actions.append(f"score_threshold_propose: {current:.3f} → {new_val:.3f}")
        elif win_rate > WIN_RATE_TARGET + 0.10:
            # High win rate: can lower threshold to find more opportunities
            new_val = round(current - THRESHOLD_ADJUSTMENT, 3)
            result = self._auto_params.update(
                "score_threshold_propose", new_val, "StocksAuditor",
                f"Win rate {win_rate:.1%} above target {WIN_RATE_TARGET:.0%}"
            )
            if result is not None:
                actions.append(f"score_threshold_propose: {current:.3f} → {new_val:.3f}")
        return actions

    def _save_audit_log(self, result: dict):
        try:
            history = []
            if os.path.exists(AUDIT_LOG_FILE):
                try:
                    with open(AUDIT_LOG_FILE) as f:
                        history = json.load(f)
                except Exception:
                    history = []
            history.append(result)
            history = history[-52:]  # Keep 1 year of weekly audits
            with open(AUDIT_LOG_FILE, "w") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            self.logger.error(f"Could not save audit log: {e}")
