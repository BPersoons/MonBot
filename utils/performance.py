import json
import os
import time
from datetime import datetime
import pandas as pd

TRADE_LOG_FILE = "trade_log.json"

class PerformanceTracker:
    """
    Tracks performance of paper trades and simulates trade lifecycle updates.
    """
    def __init__(self):
        pass

    def load_trades(self):
        if not os.path.exists(TRADE_LOG_FILE):
            return []
        try:
            with open(TRADE_LOG_FILE, "r") as f:
                return json.load(f)
        except:
            return []

    def save_trades(self, trades):
        with open(TRADE_LOG_FILE, "w") as f:
            json.dump(trades, f, indent=4)

    def calculate_metrics(self):
        """
        Calculates Win/Loss, Avg PnL, Total PnL from CLOSED trades.
        """
        trades = self.load_trades()
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "open_positions": 0
            }

        df = pd.DataFrame(trades)
        
        # Filter for CLOSED trades for performance metrics
        closed_trades = df[df['status'] == 'CLOSED']
        open_trades = df[df['status'] == 'OPEN']
        
        total_closed = len(closed_trades)
        open_positions = len(open_trades)
        
        if total_closed == 0:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "open_positions": open_positions
            }
            
        wins = closed_trades[closed_trades['pnl'] > 0]
        win_rate = len(wins) / total_closed
        total_pnl = closed_trades['pnl'].sum()
        avg_pnl = closed_trades['pnl'].mean()

        return {
            "total_trades": total_closed,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
            "open_positions": open_positions
        }

    def update_trades(self, current_prices: dict):
        """
        Updates OPEN trades based on current market price.
        Simulates:
        1. Stop Loss (e.g. -2% from entry) - customizable
        2. Time Exit (24h hold)
        """
        trades = self.load_trades()
        updated = False
        
        for trade in trades:
            if trade['status'] != 'OPEN':
                continue
                
            ticker = trade['ticker']
            if ticker not in current_prices:
                continue
                
            current_price = current_prices[ticker]
            entry_price = trade['entry_price']
            qty = trade['quantity']
            
            # 1. Check Time Exit (24h)
            # 24h = 86400 seconds
            if time.time() - trade['entry_time'] >= 86400:
                self._close_trade(trade, current_price, "TIME_EXIT")
                updated = True
                continue
                
            # 2. Check Stop Loss (Simulated at -2%)
            # If BUY: current < entry * 0.98
            # If SELL: current > entry * 1.02
            action = trade['action']
            stop_loss_pct = 0.02
            
            pnl_unrealized = 0.0
            
            if action == "BUY":
                if current_price <= entry_price * (1 - stop_loss_pct):
                    self._close_trade(trade, current_price, "STOP_LOSS")
                    updated = True
                    continue
                pnl_unrealized = (current_price - entry_price) * qty
            elif action == "SELL":
                if current_price >= entry_price * (1 + stop_loss_pct):
                    self._close_trade(trade, current_price, "STOP_LOSS")
                    updated = True
                    continue
                pnl_unrealized = (entry_price - current_price) * qty
                
            # Update unrealized stats for display (optional, keeps json fresh)
            trade['current_price'] = current_price
            trade['unrealized_pnl'] = pnl_unrealized
            updated = True
            
        if updated:
            self.save_trades(trades)

    def _close_trade(self, trade, exit_price, reason):
        trade['status'] = 'CLOSED'
        trade['exit_price'] = exit_price
        trade['exit_time'] = time.time()
        trade['exit_reason'] = reason
        
        qty = trade['quantity']
        fees = trade.get('fees', 0.0)
        
        if trade['action'] == "BUY":
            gross_pnl = (exit_price - trade['entry_price']) * qty
        else:
            gross_pnl = (trade['entry_price'] - exit_price) * qty
            
        trade['pnl'] = gross_pnl - fees # Assuming fees paid on entry only or deduct exit fee here too?
        # Let's deduct another fee for exit to be realistic
        exit_fee = (exit_price * qty) * 0.001
        trade['pnl'] -= exit_fee
        trade['exit_fee'] = exit_fee
        
        trade['pnl_percent'] = (trade['pnl'] / (trade['entry_price'] * qty)) * 100
