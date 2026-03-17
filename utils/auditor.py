import json
import os
import logging
from datetime import datetime
from utils.db_client import DatabaseClient

class PerformanceAuditor:
    def __init__(self, db_client=None):
        self.logger = logging.getLogger("PerformanceAuditor")
        self.db = db_client or DatabaseClient()
        
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

    def update_weights(self, agent_signals, is_win):
        """
        Updates weights based on prediction accuracy.
        WIN (PnL > 0):
          - Signal > 0.5 (Bullish) -> Correct (+0.05)
          - Signal < -0.5 (Bearish) -> Wrong (-0.05)
        LOSS (PnL < 0):
          - Signal > 0.5 (Bullish) -> Wrong (-0.05)
          - Signal < -0.5 (Bearish) -> Correct (+0.05) (Prevented worse loss / identified risk)
          
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
            
            # Logic
            if is_win:
                if signal > 0.5:
                    change = 0.05 # Reward
                elif signal < -0.5:
                    change = -0.05 # Punish (Bearish on a winner)
            else: # Loss
                if signal > 0.5:
                    change = -0.05 # Punish (Bullish on a loser)
                elif signal < -0.5:
                    change = 0.05 # Reward (Correctly identified weakness)

            if change != 0:
                new_weight = max(0.5, min(1.5, current_weight + change))
                if new_weight != current_weight:
                    weights[agent] = round(new_weight, 3)
                    changes_made = True
                    direction = "increased" if change > 0 else "decreased"
                    log_messages.append(f"{agent.capitalize()} weight {direction} to {new_weight} (Signal: {signal:.2f}, Result: {'WIN' if is_win else 'LOSS'})")

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
        
        if not trades:
            self.logger.info("No trades to audit")
            return
        
        dirty_trades = False
        
        # 1. Weight Updates
        for trade in trades:
            # Check if closed and not yet audited
            if use_database:
                # Supabase trades
                if trade.get("status") == "CLOSED":
                    self._audit_trade(trade, use_database)
            else:
                # JSON trades
                if trade.get("status") == "CLOSED" and not trade.get("audited", False):
                    self._audit_trade(trade, use_database)
                    trade["audited"] = True
                    dirty_trades = True
        
        # Save JSON if using fallback
        if not use_database and dirty_trades:
            self.save_json(self.trade_log_file, trades)
        
        # 2. Asset Off-boarding (Three Strikes)
        self.check_asset_performance(trades)

        # 3. Adaptive threshold tuning
        self._tune_score_threshold()
    
    def _audit_trade(self, trade, use_database=False):
        """Audit a single trade for performance tracking."""
        trade_id = trade.get("id")
        ticker = trade.get("ticker")
        pnl = trade.get("pnl", 0)
        signals = trade.get("analyst_signals", {})
        
        self.logger.info(f"Auditing trade {trade_id} ({ticker})...")
        
        if not signals:
            self.logger.warning(f"Trade {trade_id} has no analyst signals. Skipping weight update.")
            return
        
        is_win = pnl > 0
        self.update_weights(signals, is_win)
        
        # Log performance to Supabase
        if use_database and self.db.is_available():
            entry_price = trade.get("entry_price", 0)
            exit_price = trade.get("exit_price", 0)
            
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
        Removes assets that fail performance criteria:
        - 3 consecutive losses
        - Drawdown > 5% (simulated based on open PnL or closed series, here using consecutive closed losses for simplicity as requested)
        """
        active_assets = self.load_json(self.active_assets_file, [])
        if not active_assets:
            return

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
            # Sort by ID as proxy for time if exit_time missing, but ideally exit_time
            asset_history[ticker].sort(key=lambda x: x.get('exit_time') or x.get('entry_time') or 0)

        params_changed = False
        
        for ticker in list(active_assets): # Copy list to safely remove
            history = asset_history.get(ticker, [])
            if not history:
                continue
                
            # Check 1: 3 Strikes (Consecutive Losses)
            if len(history) >= 3:
                last_3 = history[-3:]
                # Check if all 3 are losses
                if all(t['pnl'] < 0 for t in last_3):
                    self.log_audit_event(f"OFF-BOARDING: {ticker} removed due to 3 consecutive losses.")
                    active_assets.remove(ticker)
                    params_changed = True
                    continue

            # Check 2: Drawdown > 5%
            # Evaluate cumulative PnL or individual large loss?
            # Prompt: "drawdown van > 5%"
            # Simple interpretation: If any trade lost > 5% or cumulative streak?
            # Let's check if any recent trade lost > 5% of entry value.
            for t in history[-5:]: # Check recent history
                pnl_pct = t.get('pnl_percent', 0) # e.g. -0.05
                if pnl_pct < -0.05:
                     self.log_audit_event(f"OFF-BOARDING: {ticker} removed due to significant drawdown ({pnl_pct*100:.1f}%).")
                     if ticker in active_assets:
                        active_assets.remove(ticker)
                        params_changed = True
                     break

        if params_changed:
            self.save_json(self.active_assets_file, active_assets)

    def _tune_score_threshold(self):
        """Nudge score threshold based on recent closed trade win rate."""
        try:
            trades = self.load_json(self.trade_log_file, [])
            closed = [t for t in trades if t.get('status', '').startswith('CLOSED') and (t.get('pnl') or 0) != 0]
            recent = closed[-20:]
            if len(recent) < 10:
                return  # not enough data yet
            win_rate = sum(1 for t in recent if (t.get('pnl') or 0) > 0) / len(recent)

            weights = self.load_json(self.weights_file, {})
            current = float(weights.get("score_threshold", 0.40))

            MIN_THRESHOLD = 0.32
            MAX_THRESHOLD = 0.48
            STEP = 0.01

            if win_rate >= 0.65 and current > MIN_THRESHOLD:
                new_threshold = round(current - STEP, 3)
            elif win_rate < 0.45 and current < MAX_THRESHOLD:
                new_threshold = round(current + STEP, 3)
            else:
                return  # in acceptable range, leave unchanged

            weights["score_threshold"] = new_threshold
            self.save_json(self.weights_file, weights)
            self.logger.info(f"Score threshold auto-tuned: {current:.3f} → {new_threshold:.3f} (win_rate={win_rate:.0%}, n={len(recent)})")
        except Exception as e:
            self.logger.debug(f"Threshold tuning skipped: {e}")


if __name__ == "__main__":
    # Test run
    auditor = PerformanceAuditor()
    auditor.run_audit_cycle()
