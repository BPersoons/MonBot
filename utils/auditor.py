import json
import os
import logging
import time
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
        # Local ledger of already-audited trade IDs. Supabase has no `audited`
        # column — get_closed_trades(audited=False) returns the latest 100 CLOSED
        # trades EVERY cycle, so without this ledger the same trades were
        # re-audited each run: trades with signals updated the weights again and
        # again (compounding bias toward a handful of old outcomes), trades
        # without signals re-logged a skip warning forever.
        self.audited_ids_file = "audited_trades.json"

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

        # Learning source (2026-07-21 fix): the auditor now learns from the
        # OPERATIONAL source of truth — trade_log.json — NOT the Supabase mirror,
        # which silently stopped syncing in March 2026. Because Supabase was still
        # "available" (just stale), the old code read its 27 frozen March trades,
        # found them all audited, and did nothing — weight-learning had been dead
        # for ~4 months. Dedup is via the audited_ids ledger (id as string), seeded
        # with the pre-redesign backlog so the losing counter-trend shorts from the
        # OLD direction logic are not learned from. Param-tuning stays gated behind
        # AUDITOR_ENABLED. See docs/DIRECTIONAL_CORE_REDESIGN.md + CLAUDE.md.
        audited_ids = set(str(x) for x in self.load_json(self.audited_ids_file, []))
        all_closed = [
            t for t in self.load_json(self.trade_log_file, [])
            if str(t.get("status", "")).startswith("CLOSED")
        ]
        trades = [t for t in all_closed if str(t.get("id")) not in audited_ids]
        self.logger.info(
            f"Auditor: {len(all_closed)} closed trades in trade_log, "
            f"{len(trades)} not yet audited"
        )

        if trades:
            # 1. Weight Updates
            for trade in trades:
                self._audit_trade(trade, use_database=False)
                if trade.get("id") is not None:
                    audited_ids.add(str(trade.get("id")))
            # Bounded ledger: keep the most recent 5000 IDs (sorted as strings
            # so mixed int/str IDs don't crash the sort).
            self.save_json(self.audited_ids_file, sorted(audited_ids, key=str)[-5000:])

            # 2. Asset Off-boarding — uses the full closed history for per-asset stats
            self.check_asset_performance(all_closed)
        else:
            self.logger.info("No trades to audit — skipping weight updates")

        # 3. Shadow check or param tuning (always runs regardless of trade count)
        if self.auto_params.is_shadow_mode():
            self._check_shadow_progress()
        elif trades:
            # Only tune when fresh trade data is available
            self._tune_all_params()

            # Persist quality insights for SwarmLearner / dashboard
            try:
                all_trades = self.load_json(self.trade_log_file, [])
                closed_for_quality = [
                    t for t in all_trades
                    if t.get("status", "").startswith("CLOSED")
                ]
                if len(closed_for_quality) >= 10:
                    quality = self._analyze_trade_quality(closed_for_quality[-200:])
                    if quality:
                        existing = self.load_json("learning_report.json", {})
                        existing["trade_quality"] = quality
                        self.save_json("learning_report.json", existing)
            except Exception as e:
                self.logger.debug(f"Quality report save skipped: {e}")

        # 4. Deadlock recovery — always runs, even when there are no new trades
        if not self.auto_params.is_shadow_mode():
            self._check_deadlock_recovery()

        # 5. Daily RSI digest via Telegram (once per day, 08:00-09:00 UTC)
        self.maybe_send_rsi_digest()

    def _check_deadlock_recovery(self):
        """
        Detect parameter deadlock: if no trade has opened in 48h and params are
        above their defaults, nudge them down by one step directly (bypassing
        shadow tests, which require trade data to evaluate and are useless here).

        This gives the Auditor a reverse gear — it can self-recover without
        requiring a manual parameter reset.
        """
        # Phase 0 freeze: deadlock recovery also writes auto_params.json — gate it.
        if os.getenv("AUDITOR_ENABLED", "false").lower() not in ("1", "true", "yes"):
            return

        from utils.auto_params import DEFAULTS
        DEADLOCK_HOURS = 48
        STEP = 0.02

        try:
            all_trades = self.load_json(self.trade_log_file, [])
            now = time.time()

            latest_entry = max(
                (t.get("entry_time", 0) for t in all_trades if t.get("entry_time")),
                default=0,
            )
            hours_idle = (now - latest_entry) / 3600 if latest_entry else float("inf")

            if hours_idle < DEADLOCK_HOURS:
                return  # No deadlock — trades are flowing normally

            # Deadlock confirmed — nudge params down if they're above their defaults
            nudged = []
            for key in ("score_threshold", "tech_prefilter_min"):
                default_val = DEFAULTS[key]
                current = self.auto_params.get(key)
                if current is not None and current > default_val:
                    new_val = round(max(current - STEP, default_val), 4)
                    result = self.auto_params.update(
                        key=key,
                        new_value=new_val,
                        changed_by="DeadlockRecovery",
                        reason=f"No trade in {hours_idle:.0f}h — auto-recovering from deadlock",
                    )
                    if result is not None:
                        nudged.append(f"{key}: {current} -> {new_val}")

            # Absolute floor — if params are already at defaults but still no trades,
            # nudge toward the hard minimum (bounds floor) as a last resort.
            ABSOLUTE_FLOOR = {"score_threshold": 0.05, "tech_prefilter_min": 0.02}
            if not nudged:
                for key, floor in ABSOLUTE_FLOOR.items():
                    current = self.auto_params.get(key)
                    if current is not None and current > floor:
                        new_val = round(max(current - STEP, floor), 4)
                        result = self.auto_params.update(
                            key=key,
                            new_value=new_val,
                            changed_by="DeadlockRecovery",
                            reason=f"No trade in {hours_idle:.0f}h — nudging toward absolute floor",
                        )
                        if result is not None:
                            nudged.append(f"{key}: {current} -> {new_val} (floor)")

            if nudged:
                msg = (
                    f"[DeadlockRecovery] {hours_idle:.0f}h since last trade — "
                    f"nudged down: {', '.join(nudged)}"
                )
                self.logger.warning(msg)
                self.log_audit_event(msg)
            else:
                self.logger.info(
                    f"[DeadlockRecovery] {hours_idle:.0f}h idle but params already "
                    f"at/below absolute floor — no action needed"
                )

        except Exception as e:
            self.logger.debug(f"_check_deadlock_recovery error: {e}")

    def _audit_trade(self, trade, use_database=False):
        """Audit a single trade for performance tracking."""
        trade_id = trade.get("id")
        ticker = trade.get("ticker")
        pnl = trade.get("pnl") or 0
        signals = trade.get("analyst_signals", {})
        source = (trade.get("source") or "").upper()
        EXTERNAL_SOURCES = {"RECONCILED", "HL_POSITION_SYNC", "HYPERLIQUID", "REANALYZED"}

        self.logger.info(f"Auditing trade {trade_id} ({ticker})...")

        if not signals:
            if source in EXTERNAL_SOURCES:
                self.logger.debug(f"Trade {trade_id} from {source} has no analyst signals — expected, skipping.")
            else:
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

    @staticmethod
    def _last_activity_epoch(t: dict) -> float:
        """Best-available timestamp for a trade (exit_time, else entry_time) as
        a Unix epoch float. exit_time is written as an ISO string by every
        close path; entry_time is written as a raw epoch float at open —
        mixing the two (or hitting an older imported record with either type
        in either field) crashes sort()/comparisons with 'not supported
        between instances of float and str'. Normalize once, here."""
        val = t.get('exit_time') or t.get('entry_time') or 0
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val).timestamp()
            except Exception:
                return 0.0
        try:
            return float(val)
        except Exception:
            return 0.0

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

        # Sort by exit time (if available) or entry time. Source data mixes ISO
        # strings (exit_time, set by the close paths) and raw epoch floats
        # (entry_time, set at open) — plus older imported records can have
        # either type in either field. Normalize to a float epoch so sort()
        # never compares incompatible types (same class of bug already worked
        # around for audited_ids below — see comment there).
        for ticker in asset_history:
            asset_history[ticker].sort(key=self._last_activity_epoch)

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

        # Ghost asset pass: remove tickers with no open trade and no activity in 7 days.
        # This catches assets that were never traded (never get a loss history) and
        # would otherwise stay in active_assets forever, blocking new trades.
        from datetime import timedelta as _td
        _seven_days_ago = (datetime.utcnow() - _td(days=7)).timestamp()
        _norm = lambda s: s.replace("/USDT", "/USDC").upper() if s else s

        open_tickers = {_norm(t["ticker"]) for t in trades if t.get("status") in ("OPEN", "PLACED")}
        recently_traded = {
            _norm(t["ticker"]) for t in trades
            if self._last_activity_epoch(t) >= _seven_days_ago
        }

        for ticker in list(active_assets):
            if _norm(ticker) in open_tickers:
                continue  # Active position — leave it
            if _norm(ticker) in recently_traded:
                continue  # Traded recently — leave it
            self.log_audit_event(
                f"GHOST_ASSET: {ticker} — no open trade and no activity in 7 days. Removed."
            )
            try:
                active_assets.remove(ticker)
                params_changed = True
            except ValueError:
                pass

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

        Phase 0 freeze: gated behind AUDITOR_ENABLED env (default false). Tuning is
        currently aimed at the wrong knobs (entry filters instead of exit geometry);
        Phase 3 will retarget it. Re-enable once retargeted.
        """
        if os.getenv("AUDITOR_ENABLED", "false").lower() not in ("1", "true", "yes"):
            self.logger.info("[RSI] Param tuning DISABLED (AUDITOR_ENABLED env not set)")
            return
        try:
            all_trades = self.load_json(self.trade_log_file, [])
            closed = [
                t for t in all_trades
                if t.get("status", "").startswith("CLOSED")
                and (t.get("pnl") or 0) != 0
                and t.get("close_reason") not in ("EXTERNAL_CLOSURE", "CLOSED_LIQUIDATED")
            ]

            # Rolling windows
            recent_20  = closed[-20:]
            recent_100 = closed[-100:]

            if len(recent_20) < 10:
                self.logger.info(f"[RSI] Param tuning SKIPPED: only {len(recent_20)} non-zero-PnL trades (need 10)")
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

            # Staleness guard: don't tune based on old data — prevents vicious
            # tightening loop when no new trades are being generated.
            if recent_20:
                newest_trade_time = max(
                    t.get("exit_time") or t.get("entry_time", 0) for t in recent_20
                )
                if isinstance(newest_trade_time, str):
                    from datetime import datetime as _dt
                    try:
                        newest_trade_time = _dt.fromisoformat(newest_trade_time).timestamp()
                    except Exception:
                        newest_trade_time = 0
                if isinstance(newest_trade_time, (int, float)) and newest_trade_time > 0:
                    days_since = (time.time() - newest_trade_time) / 86400
                    if days_since > 7:
                        self.logger.info(
                            f"Param tuning SKIPPED: newest closed trade is {days_since:.0f} days old. "
                            f"Stale win rate not actionable — only fresh data should drive tuning."
                        )
                        return

            # Both windows must agree on direction before tuning
            both_high = wr_short >= 0.65 and wr_long >= 0.65
            both_low  = wr_short < 0.45  and wr_long < 0.45

            action = "TIGHTEN" if both_low else ("LOOSEN" if both_high else "HOLD")
            self.logger.info(
                f"[RSI] Tuning check: wr_20={wr_short:.0%} wr_100={wr_long:.0%} "
                f"both_high={both_high} both_low={both_low} → {action}"
            )

            # Root-cause analysis — insights drive smarter tuning
            quality = self._analyze_trade_quality(closed)
            recs = {r["param"] for r in quality.get("recommendations", [])}

            # ── score_threshold ──────────────────────────────────────────
            # Asymmetric: loosen 2x faster than tighten to prevent deadlock
            # Root-cause override: if low conviction is losing, tighten regardless
            score_dir = "down" if both_high else ("up" if both_low else None)
            if "min_conviction" in recs and score_dir != "up":
                score_dir = "up"  # Low conviction losing → be stricter
            self._tune_param(
                key="score_threshold",
                direction=score_dir,
                step=0.02 if both_high else 0.01,
                reason=f"win_rate_20={wr_short:.0%} win_rate_100={wr_long:.0%} quality_recs={recs or 'none'}",
            )

            # ── scan_universe_size ───────────────────────────────────────
            # Scout more when win rate is high; be selective when win rate is low
            # Asymmetric: expand 2x faster than contract
            self._tune_param(
                key="scan_universe_size",
                direction="up" if both_high else ("down" if both_low else None),
                step=2 if both_high else 1,
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
                    # Good win rate + healthy ROI: can relax the pre-filter
                    # Asymmetric: loosen 2x faster than tighten
                    self._tune_param(
                        key="tech_prefilter_min",
                        direction="down",
                        step=0.02,
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

    def _analyze_trade_quality(self, closed_trades: list) -> dict:
        """
        Root-cause analysis of trade outcomes. Analyzes WHY trades fail,
        not just whether they win or lose. Returns actionable insights that
        drive smarter parameter tuning than win-rate alone.

        Analyzes:
        - Close reason distribution (SL hit vs TP vs time exit vs breakeven)
        - SL stage progression (how many reach breakeven? profit lock? trail?)
        - Conviction score vs outcome (do high-conviction trades win more?)
        - SL% bucket performance (which SL range is most profitable?)
        - Breakeven ratio (high BE% = SL too tight or entries too noisy)
        """
        if len(closed_trades) < 10:
            return {}

        from collections import defaultdict

        # 1. Close reason distribution
        close_reasons = defaultdict(int)
        for t in closed_trades:
            close_reasons[t.get("close_reason", "unknown")] += 1

        # 2. SL stage analysis
        stage_stats = defaultdict(lambda: {"n": 0, "pnl": 0.0})
        for t in closed_trades:
            stage = t.get("sl_stage", 0)
            stage_stats[stage]["n"] += 1
            stage_stats[stage]["pnl"] += t.get("pnl", 0) or 0

        # 3. Conviction vs outcome
        conviction_buckets = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0})
        for t in closed_trades:
            c = t.get("conviction", 0) or 0
            bucket = "high" if c >= 0.30 else ("mid" if c >= 0.15 else "low")
            conviction_buckets[bucket]["n"] += 1
            conviction_buckets[bucket]["pnl"] += t.get("pnl", 0) or 0
            if (t.get("pnl") or 0) > 0:
                conviction_buckets[bucket]["wins"] += 1

        # 4. SL% bucket performance
        sl_buckets = defaultdict(lambda: {"n": 0, "pnl": 0.0, "wins": 0, "losses": 0})
        for t in closed_trades:
            sp = t.get("sl_pct", 0) or 0
            if sp <= 2:
                bucket = "tight"
            elif sp <= 5:
                bucket = "medium"
            else:
                bucket = "wide"
            sl_buckets[bucket]["n"] += 1
            sl_buckets[bucket]["pnl"] += t.get("pnl", 0) or 0
            pnl = t.get("pnl", 0) or 0
            if pnl > 0:
                sl_buckets[bucket]["wins"] += 1
            elif pnl < 0:
                sl_buckets[bucket]["losses"] += 1

        # 5. Breakeven ratio
        total = len(closed_trades)
        breakeven = sum(1 for t in closed_trades if (t.get("pnl") or 0) == 0)
        be_ratio = breakeven / total if total > 0 else 0

        # 6. Derive insights
        insights = {
            "close_reasons": dict(close_reasons),
            "sl_stages": {str(k): v for k, v in stage_stats.items()},
            "conviction_buckets": dict(conviction_buckets),
            "sl_buckets": dict(sl_buckets),
            "breakeven_ratio": round(be_ratio, 3),
            "recommendations": [],
        }

        # Recommendation: high breakeven ratio → SL too tight
        if be_ratio > 0.60:
            insights["recommendations"].append({
                "param": "breakeven_progress_threshold",
                "issue": f"breakeven_ratio={be_ratio:.0%} — most trades stopped at BE before developing",
                "suggestion": "lower breakeven trigger or widen initial SL",
            })

        # Recommendation: wide SL losing disproportionately
        wide = sl_buckets.get("wide", {})
        if wide.get("n", 0) >= 5 and wide.get("pnl", 0) < -20:
            insights["recommendations"].append({
                "param": "sl_pct_cap",
                "issue": f"wide SL (>5%) trades: {wide['n']} trades, P&L=${wide['pnl']:.2f}",
                "suggestion": "cap SL at 5% to limit max single-trade loss",
            })

        # Recommendation: low conviction trades losing
        low_conv = conviction_buckets.get("low", {})
        if low_conv.get("n", 0) >= 10:
            low_wr = low_conv["wins"] / low_conv["n"] if low_conv["n"] > 0 else 0
            if low_wr < 0.35 and low_conv.get("pnl", 0) < 0:
                insights["recommendations"].append({
                    "param": "min_conviction",
                    "issue": f"low conviction (<0.15): {low_conv['n']} trades, WR={low_wr:.0%}, P&L=${low_conv['pnl']:.2f}",
                    "suggestion": "raise minimum conviction threshold for execution",
                })

        # Recommendation: sl_stage=0 dominating losses
        stage0 = stage_stats.get(0, {})
        if stage0.get("n", 0) > total * 0.7 and stage0.get("pnl", 0) < -30:
            insights["recommendations"].append({
                "param": "sl_management",
                "issue": f"sl_stage=0 dominates: {stage0['n']}/{total} trades, P&L=${stage0['pnl']:.2f}",
                "suggestion": "trades hit initial SL before reaching breakeven — consider earlier BE move or wider initial SL",
            })

        self.logger.info(
            f"Trade quality: BE_ratio={be_ratio:.0%}, "
            f"stage0={stage0.get('n',0)}/{total}, "
            f"recommendations={len(insights['recommendations'])}"
        )
        for rec in insights["recommendations"]:
            self.logger.info(f"  RSI insight: [{rec['param']}] {rec['issue']}")

        return insights

    def _tune_param(self, key: str, direction, step, reason: str):
        """
        Propose a single-step change to a param.
        Phase 2: initiates a shadow test instead of applying directly.
        Only one shadow test can run at a time.
        """
        if direction is None:
            self.logger.info(f"[RSI] _tune_param({key}): direction=None (windows disagree) — skipped")
            return
        if self.auto_params.is_shadow_mode():
            self.logger.info(f"[RSI] _tune_param({key}): shadow test already running — skipped")
            return

        # Rate limiter: max 1 param change per 24 hours (prevents rapid compounding)
        # Deadlock recovery bypasses this via direct auto_params.update() calls.
        try:
            data = self.auto_params._load()
            last_changed_str = data.get("_meta", {}).get("last_changed_at", "")
            if last_changed_str:
                from datetime import datetime, timezone
                last_dt = datetime.fromisoformat(last_changed_str)
                now_dt = datetime.now(timezone.utc) if last_dt.tzinfo else datetime.utcnow()
                hours_since = (now_dt - last_dt).total_seconds() / 3600
                if hours_since < 24:
                    self.logger.info(
                        f"[AutoTune] Cooldown: last param change was {hours_since:.0f}h ago "
                        f"(min 24h between changes)"
                    )
                    return
        except Exception:
            pass  # fail-open: allow tuning if meta parsing fails

        current = self.auto_params.get(key)
        if current is None:
            return

        new_value = round(current + step if direction == "up" else current - step, 4)

        # Bounds check before starting shadow test
        from utils.auto_params import BOUNDS, MAX_DRIFT_FRACTION
        if key in BOUNDS:
            lo, hi = BOUNDS[key]
            if not (lo <= new_value <= hi):
                self.logger.info(f"[RSI] _tune_param({key}={new_value}): out of bounds [{lo},{hi}] — skipped")
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

    # ──────────────────────────────────────────────────────────────
    # Daily RSI Digest — Telegram summary of learning progress
    # ──────────────────────────────────────────────────────────────

    _DIGEST_STATE_FILE = "rsi_digest_state.json"

    def maybe_send_rsi_digest(self):
        """Send a daily RSI progress digest via Telegram. Called every audit cycle."""
        try:
            # Once-per-day gate
            today = datetime.now().strftime("%Y-%m-%d")
            state = self.load_json(self._DIGEST_STATE_FILE, {})
            if state.get("last_digest_date") == today:
                return
            # Only send between 08:00–09:00 UTC to avoid late-night spam
            hour = datetime.utcnow().hour
            if hour < 8 or hour >= 9:
                return

            msg = self._build_rsi_digest()
            if msg:
                self._send_telegram_digest(msg)
                self.save_json(self._DIGEST_STATE_FILE, {"last_digest_date": today})
                self.logger.info("[RSI] Daily digest sent via Telegram")
        except Exception as e:
            self.logger.warning(f"[RSI] Digest failed: {e}")

    def _build_rsi_digest(self) -> str:
        """Build a readable daily progress message — what happened, effect, next step."""
        from datetime import datetime, timezone, timedelta

        all_trades = self.load_json(self.trade_log_file, [])
        closed = [t for t in all_trades if t.get("status", "").startswith("CLOSED")]
        non_zero = [t for t in closed if (t.get("pnl") or 0) != 0]
        open_t = [t for t in all_trades if t.get("status") == "OPEN"]

        # ---- Today window (last 24h) ----
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(hours=24)

        def _closed_today(t):
            try:
                raw = t.get("exit_time")
                if not raw: return False
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                return dt >= cutoff
            except Exception:
                return False

        def _opened_today(t):
            try:
                ts = float(t.get("entry_time") or 0)
                if ts <= 0: return False
                return datetime.fromtimestamp(ts, tz=timezone.utc) >= cutoff
            except Exception:
                return False

        closed_today = [t for t in closed if _closed_today(t)]
        opened_today = [t for t in all_trades if _opened_today(t)]
        pnl_today = sum(float(t.get("pnl", 0)) for t in closed_today)
        total_pnl = sum(float(t.get("pnl", 0)) for t in closed)

        # ---- Win-rate trend ----
        def _wr(trades):
            if not trades: return None
            wins = sum(1 for t in trades if float(t.get("pnl", 0)) > 0)
            return wins / len(trades) * 100.0
        wr_all = _wr(non_zero)
        wr_20  = _wr(non_zero[-20:])
        wr_100 = _wr(non_zero[-100:])

        if wr_20 is not None and wr_100 is not None:
            delta = wr_20 - wr_100
            if delta >= 5:   trend_txt, trend_icon = "verbeterend", "📈"
            elif delta <= -5: trend_txt, trend_icon = "verslechterend", "📉"
            else:            trend_txt, trend_icon = "stabiel", "➡️"
        else:
            trend_txt, trend_icon = "te weinig data", "❔"

        # ---- Overall health headline ----
        if pnl_today > 0 and trend_txt == "verbeterend":
            headline = "🟢 Groene dag — winst én verbeterende win rate."
        elif pnl_today < -5 and trend_txt == "verslechterend":
            headline = "🔴 Zorgen — verlies vandaag en dalende win rate."
        elif pnl_today >= 0:
            headline = "🟡 Neutrale dag — geen verlies, trend " + trend_txt + "."
        else:
            headline = "🟡 Licht verlies vandaag, trend " + trend_txt + "."

        # ---- Parameters + wat de auto-tuner doet ----
        params = self.auto_params._load()
        shadow_on = bool(params.get("shadow_mode"))
        shadow_info = params.get("_shadow") or {}
        changed_keys = []
        for key in ("score_threshold", "tech_prefilter_min", "scan_universe_size"):
            val = params.get(key)
            init = params.get("_initial", {}).get(key)
            if val != init and val is not None:
                changed_keys.append(f"{key} {init}→{val}")

        # ---- Recent tuning events (parse naar leesbaar) ----
        last_event = None
        try:
            with open(self.audit_log_file, "r") as f:
                audit_lines = f.readlines()
            keep = [l.strip() for l in audit_lines
                    if any(k in l for k in ("Shadow", "PROMOTED", "DISCARDED", "Deadlock"))]
            if keep:
                last_event = keep[-1]
        except Exception:
            pass

        # Volgende stap afleiden
        if shadow_on and shadow_info:
            tested = ", ".join(f"{k}={v}" for k, v in shadow_info.items() if not k.startswith("_"))
            next_step = f"Shadow-test loopt op {tested}. Promotie als 100-trade WR > baseline."
        elif last_event and "DISCARDED" in last_event:
            next_step = "Laatste test afgewezen; auto-tuner probeert binnenkort een volgende candidate."
        elif last_event and "PROMOTED" in last_event:
            next_step = "Laatste test gepromoveerd — effect wordt nu live gemonitord."
        else:
            next_step = "Auto-tuner monitort; geen wijzigingen nodig."

        # ---- Compose ----
        lines = [
            f"📊 *Dagelijks overzicht* — {now_utc.day} {now_utc.strftime('%b')}",
            "",
            headline,
            "",
            "*Vandaag*",
            f"  • {len(opened_today)} trades geopend, {len(closed_today)} gesloten",
            f"  • PnL vandaag: ${pnl_today:+.2f}",
            f"  • Nu open: {len(open_t)}",
            "",
            f"*Trend* {trend_icon} {trend_txt}",
        ]
        if wr_20 is not None and wr_100 is not None:
            lines.append(f"  • Win rate laatste 20: {wr_20:.0f}%  ·  laatste 100: {wr_100:.0f}%")
        if wr_all is not None:
            lines.append(f"  • Totaal: {len(closed)} trades gesloten, WR {wr_all:.0f}%, PnL ${total_pnl:+.2f}")
        lines.append("")

        lines.append("*Auto-tuner*")
        lines.append(f"  • Shadow-test: {'actief' if shadow_on else 'uit'}")
        if changed_keys:
            lines.append("  • Aangepaste parameters: " + "; ".join(changed_keys))
        else:
            lines.append("  • Parameters ongewijzigd t.o.v. initieel")
        lines.append("")

        lines.append("*Volgende stap*")
        lines.append(f"  → {next_step}")

        # Kosten
        try:
            cs = self.cost_tracker.get_daily_summary()
            lines.append("")
            lines.append("*Kosten vandaag*")
            lines.append(f"  LLM ${cs.get('llm_cost_usd', 0):.4f} · Totaal ${cs.get('total_cost_usd', 0):.2f} · Net ROI ${cs.get('net_roi_usd', 0):+.2f}")
        except Exception:
            pass

        return "\n".join(lines)

    def _send_telegram_digest(self, text: str):
        """Send digest via Telegram Bot API."""
        try:
            import urllib.request
            import urllib.parse
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
            if not token or not chat_id:
                self.logger.warning("[RSI] No Telegram credentials for digest")
                return
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            }).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                self.logger.info(f"[RSI] Digest Telegram sent (HTTP {resp.status})")
        except Exception as e:
            self.logger.warning(f"[RSI] Telegram send failed: {e}")


if __name__ == "__main__":
    # Test run
    auditor = PerformanceAuditor()
    auditor.run_audit_cycle()
