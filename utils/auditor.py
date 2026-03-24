import json
import os
import logging
from datetime import datetime
from utils.db_client import DatabaseClient
from utils.auto_params import AutoParams
from utils.cost_tracker import CostTracker
from utils.shadow_comparator import ShadowComparator

class PerformanceAuditor:
    def __init__(self, db_client=None):
        self.logger = logging.getLogger("PerformanceAuditor")
        self.db = db_client or DatabaseClient()
        self.auto_params = AutoParams()
        self.cost_tracker = CostTracker()
        self.shadow_comparator = ShadowComparator()

        # Fallback files (used when DB unavailable)
        self.trade_log_file = "trade_log.json"
        self.weights_file = "core/agent_weights.json"
        self.active_assets_file = "active_assets.json"
        self.audit_log_file = "audit_log.txt"

        self.ensure_audit_log()

    def ensure_audit_log(self):
        if not os.path.exists(self.audit_log_file):
            with open(self.audit_log_file, "w") as f:
                f.write(f"--- Global Governance Audit Log Initialized [{datetime.now()}] ---\n")

    def load_json(self, filepath, default=None):
        if not os.path.exists(filepath):
            return default if default is not None else {}
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Error loading {filepath}: {e}")
            return default if default is not None else {}

    def save_json(self, filepath, data):
        try:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            self.logger.error(f"Error saving {filepath}: {e}")

    def log_audit_event(self, message):
        """Appends an event to the audit log."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {message}"
        print(f"AUDITOR: {message}") # Console feedback
        try:
            with open(self.audit_log_file, "a") as f:
                f.write(entry + "\n")
        except Exception as e:
            self.logger.error(f"Error writing to audit log: {e}")

    def update_weights(self, agent_signals, is_win, direction="LONG"):
        """
        Updates weights based on prediction accuracy.
        For LONG — bullish signal on WIN = correct, bearish signal on WIN = wrong.
        For SHORT — bearish signal on WIN = correct (market went down as expected).
          Achieved by inverting signal sign for SHORT before applying the same logic.

        Floor: 0.5, Ceiling: 1.5
        """
        weights = self.load_json(self.weights_file, {"technical": 1.0, "fundamental": 1.0, "sentiment": 1.0})

        changes_made = False
        log_messages = []

        for agent, signal in agent_signals.items():
            if agent not in weights:
                continue

            current_weight = weights[agent]
            change = 0.0

            # For SHORT: invert signal so bearish signal = "aligned with direction"
            effective_signal = -signal if direction == "SHORT" else signal

            # Logic
            if is_win:
                if effective_signal > 0.5:
                    change = 0.05 # Reward
                elif effective_signal < -0.5:
                    change = -0.05 # Punish (signal opposed to direction on a winner)
            else: # Loss
                if effective_signal > 0.5:
                    change = -0.05 # Punish (signal aligned with direction but lost)
                elif effective_signal < -0.5:
                    change = 0.05 # Reward (correctly identified weakness)

            if change != 0:
                new_weight = max(0.5, min(1.5, current_weight + change))
                if new_weight != current_weight:
                    weights[agent] = round(new_weight, 3)
                    changes_made = True
                    direction_label = "increased" if change > 0 else "decreased"
                    log_messages.append(f"{agent.capitalize()} weight {direction_label} to {new_weight} (Signal: {signal:.2f}, Result: {'WIN' if is_win else 'LOSS'})")

        if changes_made:
            self.save_json(self.weights_file, weights)
            for msg in log_messages:
                self.log_audit_event(msg)

        return changes_made

    def run_audit_cycle(self):
        """
        Main entry point for the Auditor.
        1. Process closed trades to update weights.
        2. Check asset performance for off-boarding.
        3. Tune parameters in auto_params.json.
        """
        self.logger.info("Running Audit Cycle...")

        # Try to fetch trades from Supabase first
        if self.db.is_available():
            trades = self.db.get_closed_trades(audited=False, limit=100)
            self.logger.info(f"Fetched {len(trades)} unaudited trades from Supabase")
            use_database = True
        else:
            # Fallback to JSON
            self.logger.warning("Database unavailable - using trade_log.json")
            trades = self.load_json(self.trade_log_file, [])
            use_database = False

        dirty_trades = False

        if trades:
            # 1. Weight Updates
            for trade in trades:
                if use_database:
                    if trade.get("status") == "CLOSED":
                        self._audit_trade(trade, use_database)
                else:
                    if trade.get("status") == "CLOSED" and not trade.get("audited", False):
                        self._audit_trade(trade, use_database)
                        trade["audited"] = True
                        dirty_trades = True

            if not use_database and dirty_trades:
                self.save_json(self.trade_log_file, trades)

            # 2. Asset Off-boarding
            self.check_asset_performance(trades)
        else:
            self.logger.info("No trades to audit — skipping weight updates")

        # 3. Shadow check or param tuning (always runs regardless of trade count)
        if self.auto_params.is_shadow_mode():
            self._check_shadow_progress()
        elif trades:
            # Only tune when fresh trade data is available
            self._tune_all_params()

    def _audit_trade(self, trade, use_database=False):
        """Audit a single trade for performance tracking."""
        trade_id = trade.get("id")
        ticker = trade.get("ticker")
        pnl = trade.get("pnl") or 0
        signals = trade.get("analyst_signals", {})

        self.logger.info(f"Auditing trade {trade_id} ({ticker})...")

        if not signals:
            self.logger.warning(f"Trade {trade_id} has no analyst signals. Skipping weight update.")
            return

        is_win = pnl > 0
        direction_label = "SHORT" if trade.get("action") == "SELL" else "LONG"
        self.update_weights(signals, is_win, direction=direction_label)

        # Log performance to Supabase
        if use_database and self.db.is_available():
            entry_price = trade.get("entry_price") or 0
            exit_price = trade.get("exit_price") or 0

            if entry_price > 0:
                actual_outcome = (exit_price - entry_price) / entry_price  # Percentage change

                for analyst, prediction in signals.items():
                    metrics = {
                        "trade_id": trade_id,
                        "ticker": ticker,
                        "pnl": pnl,
                        "is_win": is_win
                    }
                    self.db.log_agent_performance(
                        analyst=analyst,
                        ticker=ticker,
                        prediction=prediction,
                        actual_outcome=actual_outcome,
                        metrics=metrics
                    )

    def check_asset_performance(self, trades):
        """
        Removes assets that fail performance criteria.
        Thresholds are read from auto_params.json so the Auditor can tune them.
        """
        active_assets = self.load_json(self.active_assets_file, [])
        if not active_assets:
            return

        consecutive_loss_limit = int(self.auto_params.get("consecutive_loss_offboard", 3))
        drawdown_pct_limit = float(self.auto_params.get("drawdown_offboard_pct", 5.0)) / 100.0

        # Group closed trades by ticker
        asset_history = {}
        for t in trades:
            if t['status'] == 'CLOSED':
                ticker = t['ticker']
                if ticker not in asset_history:
                    asset_history[ticker] = []
                asset_history[ticker].append(t)

        # Sort by exit time (if available) or id
        for ticker in asset_history:
            asset_history[ticker].sort(key=lambda x: x.get('exit_time') or x.get('entry_time') or 0)

        params_changed = False

        for ticker in list(active_assets): # Copy list to safely remove
            history = asset_history.get(ticker, [])
            if not history:
                continue

            # Check 1: Consecutive Losses
            if len(history) >= consecutive_loss_limit:
                last_n = history[-consecutive_loss_limit:]
                if all(t['pnl'] < 0 for t in last_n):
                    self.log_audit_event(f"OFF-BOARDING: {ticker} removed due to {consecutive_loss_limit} consecutive losses.")
                    active_assets.remove(ticker)
                    params_changed = True
                    continue

            # Check 2: Drawdown beyond threshold
            for t in history[-5:]: # Check recent history
                pnl_pct = t.get('pnl_percent', 0)
                if pnl_pct < -drawdown_pct_limit:
                     self.log_audit_event(f"OFF-BOARDING: {ticker} removed due to significant drawdown ({pnl_pct*100:.1f}%).")
                     if ticker in active_assets:
                        active_assets.remove(ticker)
                        params_changed = True
                     break

        if params_changed:
            self.save_json(self.active_assets_file, active_assets)

    def _tune_all_params(self):
        """
        Auto-tune parameters based on recent trade performance and cost metrics.

        Safety rules:
        - Only tune if both the 20-trade short window and 100-trade long window agree.
        - Changes are written to config/auto_params.json via AutoParams (bounds-checked).
        - All changes are appended to audit_log.txt.
        - If net ROI is deeply negative and LLM cost is significant, raise tech_prefilter_min
          to reduce wasteful LLM calls regardless of win-rate.
        """
        try:
            all_trades = self.load_json(self.trade_log_file, [])
            closed = [
                t for t in all_trades
                if t.get("status", "").startswith("CLOSED") and (t.get("pnl") or 0) != 0
            ]

            # Rolling windows
            recent_20  = closed[-20:]
            recent_100 = closed[-100:]

            if len(recent_20) < 10:
                return  # Not enough data yet

            def win_rate(window):
                if not window:
                    return 0.5
                return sum(1 for t in window if (t.get("pnl") or 0) > 0) / len(window)

            wr_short = win_rate(recent_20)
            wr_long  = win_rate(recent_100) if len(recent_100) >= 20 else wr_short

            self.logger.info(
                f"Param tuning: win_rate_20={wr_short:.0%} win_rate_100={wr_long:.0%} "
                f"n_short={len(recent_20)} n_long={len(recent_100)}"
            )

            # Both windows must agree on direction before tuning
            both_high = wr_short >= 0.65 and wr_long >= 0.65
            both_low  = wr_short < 0.45  and wr_long < 0.45

            # ── score_threshold ──────────────────────────────────────────
            self._tune_param(
                key="score_threshold",
                direction="down" if both_high else ("up" if both_low else None),
                step=0.01,
                reason=f"win_rate_20={wr_short:.0%} win_rate_100={wr_long:.0%}",
            )

            # ── scan_universe_size ───────────────────────────────────────
            # Scout more when win rate is high; be selective when win rate is low
            self._tune_param(
                key="scan_universe_size",
                direction="up" if both_high else ("down" if both_low else None),
                step=1,
                reason=f"win_rate_20={wr_short:.0%} win_rate_100={wr_long:.0%}",
            )

            # ── tech_prefilter_min — cost-aware override ─────────────────
            # If LLM cost is high relative to trading P&L, tighten the pre-filter
            # regardless of win rate to reduce wasteful analyst calls.
            try:
                cost_summary = self.cost_tracker.get_daily_summary()
                net_roi      = cost_summary.get("net_roi_usd", 0)
                llm_cost     = cost_summary.get("llm_cost_usd", 0)
                trading_pnl  = cost_summary.get("trading_pnl_usd", 0)

                # LLM cost is eating > 20% of gross P&L AND we're net-negative
                llm_dominant = (
                    abs(trading_pnl) > 0
                    and llm_cost > abs(trading_pnl) * 0.20
                    and net_roi < 0
                )

                if llm_dominant:
                    self._tune_param(
                        key="tech_prefilter_min",
                        direction="up",
                        step=0.01,
                        reason=(
                            f"LLM cost dominance: llm=${llm_cost:.3f} vs "
                            f"pnl=${trading_pnl:.2f}, net_roi=${net_roi:.2f}"
                        ),
                    )
                    self.logger.info(
                        f"Cost-aware tune: raised tech_prefilter_min "
                        f"(llm_cost=${llm_cost:.3f}, net_roi=${net_roi:.2f})"
                    )
                elif both_high:
                    # Good win rate + healthy ROI: can relax the pre-filter slightly
                    self._tune_param(
                        key="tech_prefilter_min",
                        direction="down",
                        step=0.01,
                        reason=f"win_rate_20={wr_short:.0%} win_rate_100={wr_long:.0%}",
                    )
                elif both_low:
                    self._tune_param(
                        key="tech_prefilter_min",
                        direction="up",
                        step=0.01,
                        reason=f"win_rate_20={wr_short:.0%} win_rate_100={wr_long:.0%}",
                    )
            except Exception as e:
                self.logger.debug(f"Cost-aware tuning skipped: {e}")

        except Exception as e:
            self.logger.debug(f"Param tuning skipped: {e}")

    def _tune_param(self, key: str, direction, step, reason: str):
        """
        Propose a single-step change to a param.
        Phase 2: initiates a shadow test instead of applying directly.
        Only one shadow test can run at a time.
        """
        if direction is None:
            return
        if self.auto_params.is_shadow_mode():
            self.logger.debug(f"_tune_param({key}): shadow test already running, skipping")
            return

        current = self.auto_params.get(key)
        if current is None:
            return

        new_value = round(current + step if direction == "up" else current - step, 4)

        # Bounds check before starting shadow test
        from utils.auto_params import BOUNDS, MAX_DRIFT_FRACTION
        if key in BOUNDS:
            lo, hi = BOUNDS[key]
            if not (lo <= new_value <= hi):
                self.logger.debug(f"_tune_param({key}={new_value}): out of bounds [{lo},{hi}] — skipped")
                return

        # Drift guard pre-check — avoid starting a shadow test that will be rejected at PROMOTE
        data = self.auto_params._load()
        initial = data.get("_initial", {}).get(key, new_value)
        if initial not in (None, 0):
            drift = abs(new_value - initial) / abs(initial)
            if drift > MAX_DRIFT_FRACTION:
                self.logger.info(
                    f"[AutoTune] {key}: proposed {new_value} would exceed drift guard "
                    f"({drift:.0%} from initial {initial}) — skipping shadow test"
                )
                return

        self._start_shadow_test(key, new_value, current, reason)

    def _start_shadow_test(self, key: str, new_value, old_value, reason: str):
        """Initiate a 4-hour shadow test for a proposed param change."""
        self.auto_params.start_shadow_test(
            key=key,
            new_value=new_value,
            old_value=old_value,
            reason=reason,
            duration_hours=4.0,
        )
        self.shadow_comparator.reset_shadow_trades()
        self.log_audit_event(
            f"[Shadow] TEST STARTED — {key}: {old_value} -> {new_value} | {reason} | 4h window"
        )

    def _check_shadow_progress(self):
        """
        Called every audit cycle while shadow_mode is active.
        When the 4-hour window expires, evaluate and promote/discard.
        """
        if not self.auto_params.is_shadow_expired():
            shadow = self.auto_params.get_shadow_state()
            end_at = shadow.get("end_at", "?")
            self.logger.info(
                f"[Shadow] Test in progress — {shadow.get('candidate_param')} "
                f"{shadow.get('old_value')} -> {shadow.get('candidate_value')} "
                f"(ends {end_at})"
            )
            return

        # Test window elapsed — evaluate
        shadow = self.auto_params.get_shadow_state()
        key           = shadow.get("candidate_param")
        new_value     = shadow.get("candidate_value")
        old_value     = shadow.get("old_value")
        triggered_by  = shadow.get("triggered_by", "")

        self.logger.info(f"[Shadow] Test window elapsed for {key} — evaluating...")
        self.shadow_comparator.finalize_shadow_trades()
        verdict = self.shadow_comparator.compare_performance()

        if verdict == "PROMOTE":
            promoted = self.auto_params.update(
                key=key,
                new_value=new_value,
                changed_by="ShadowTest",
                reason=f"shadow_verdict=PROMOTE | {triggered_by}",
            )
            if promoted is not None:
                self.log_audit_event(
                    f"[Shadow] PROMOTED {key}: {old_value} -> {new_value} "
                    f"(verdict=PROMOTE | {triggered_by})"
                )
            else:
                self.log_audit_event(
                    f"[Shadow] PROMOTE rejected by bounds/drift guard for {key}: {new_value}"
                )
        else:
            self.log_audit_event(
                f"[Shadow] DISCARDED {key}: {old_value} -> {new_value} "
                f"(verdict={verdict} | {triggered_by})"
            )

        # End shadow test regardless of outcome
        self.auto_params.end_shadow_test()
        self.shadow_comparator.reset_shadow_trades()


if __name__ == "__main__":
    # Test run
    auditor = PerformanceAuditor()
    auditor.run_audit_cycle()
