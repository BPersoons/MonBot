"""
stocks_risk_manager.py — Position sizing and portfolio risk for stocks.

Responsibilities:
  - Compute limit order price (current price, use limit not market)
  - Size position: floor(allocation / price) whole shares
  - Check sector concentration (max 20%)
  - Check max positions (default 10)
  - Compute stop-loss price (-10% from entry by default)
  - Check if RSI is overbought (>70) — delay entry signal
"""

import logging
from typing import Optional

logger = logging.getLogger("StocksRiskManager")


class StocksRiskManager:
    def __init__(self, auto_params=None):
        self.logger = logging.getLogger("StocksRiskManager")
        self._auto_params = auto_params

    def _get_param(self, key: str, default):
        if self._auto_params:
            try:
                return self._auto_params.get(key, default)
            except Exception:
                pass
        return default

    def get_portfolio_value(self, trade_log: list) -> float:
        """Approximate portfolio value from open positions at last known price."""
        total = 0.0
        for t in trade_log:
            if t.get("status") == "OPEN":
                qty = t.get("quantity", 0)
                price = t.get("current_price") or t.get("entry_price", 0)
                total += qty * price
        return total

    def count_open_positions(self, trade_log: list) -> int:
        return sum(1 for t in trade_log if t.get("status") == "OPEN")

    def get_sector_allocation_pct(self, sector: str, trade_log: list,
                                   portfolio_value: float) -> float:
        """Return current % of portfolio in the given sector."""
        if portfolio_value <= 0:
            return 0.0
        sector_value = 0.0
        for t in trade_log:
            if t.get("status") == "OPEN" and t.get("sector") == sector:
                qty = t.get("quantity", 0)
                price = t.get("current_price") or t.get("entry_price", 0)
                sector_value += qty * price
        return sector_value / portfolio_value

    def compute_position(self, ticker: str, current_price: float,
                          portfolio_cash: float,
                          trade_log: list,
                          sector: str = "Unknown",
                          rsi: Optional[float] = None) -> dict:
        """
        Validate and size a position for ticker.

        Returns dict:
          {
            approved: bool,
            reason: str,
            shares: int,
            limit_price: float,
            total_cost: float,
            portfolio_pct: float,
            stop_price: float,
            stop_pct: float,
          }
        """
        max_positions = self._get_param("max_portfolio_positions", 10)
        max_position_pct = self._get_param("max_position_pct", 0.05)
        sector_limit = self._get_param("sector_concentration_limit", 0.20)
        stop_loss_pct = self._get_param("stop_loss_pct", 0.10)

        open_count = self.count_open_positions(trade_log)
        if open_count >= max_positions:
            return {
                "approved": False,
                "reason": f"Max positions reached ({open_count}/{max_positions})",
                "shares": 0, "limit_price": current_price, "total_cost": 0,
                "portfolio_pct": 0, "stop_price": 0, "stop_pct": stop_loss_pct * 100,
            }

        # RSI overbought check
        if rsi is not None and rsi > 70:
            return {
                "approved": False,
                "reason": f"RSI overbought ({rsi:.0f} > 70) — wait for pullback",
                "shares": 0, "limit_price": current_price, "total_cost": 0,
                "portfolio_pct": 0, "stop_price": 0, "stop_pct": stop_loss_pct * 100,
            }

        # Portfolio value for concentration checks
        portfolio_value = self.get_portfolio_value(trade_log) + portfolio_cash
        if portfolio_value <= 0:
            portfolio_value = portfolio_cash or 10_000  # fallback

        # Sector concentration
        sector_pct = self.get_sector_allocation_pct(sector, trade_log, portfolio_value)
        if sector_pct >= sector_limit:
            return {
                "approved": False,
                "reason": f"Sector {sector} already at {sector_pct:.0%} (limit {sector_limit:.0%})",
                "shares": 0, "limit_price": current_price, "total_cost": 0,
                "portfolio_pct": 0, "stop_price": 0, "stop_pct": stop_loss_pct * 100,
            }

        # Position sizing: max_position_pct of portfolio
        allocation = portfolio_value * max_position_pct
        shares = int(allocation // current_price)  # whole shares only
        if shares < 1:
            return {
                "approved": False,
                "reason": f"Position too small (${allocation:.0f} / ${current_price:.2f} = {shares} shares)",
                "shares": 0, "limit_price": current_price, "total_cost": 0,
                "portfolio_pct": 0, "stop_price": 0, "stop_pct": stop_loss_pct * 100,
            }

        limit_price = round(current_price, 2)  # limit = current price
        total_cost = shares * limit_price
        portfolio_pct = (total_cost / portfolio_value) * 100
        stop_price = round(limit_price * (1 - stop_loss_pct), 2)

        return {
            "approved": True,
            "reason": "Position approved",
            "shares": shares,
            "limit_price": limit_price,
            "total_cost": total_cost,
            "portfolio_pct": portfolio_pct,
            "stop_price": stop_price,
            "stop_pct": stop_loss_pct * 100,
        }

    def check_stop_loss(self, trade: dict, current_price: float) -> dict:
        """
        Evaluate whether a stop-loss or trailing stop should trigger.
        Returns {action: 'HOLD'/'CLOSE', reason: str, new_stop: float or None}.

        Stop-loss logic (stocks-specific):
          - Initial stop: stop_price field from trade
          - Trailing stop activates at +15% gain, trails 25% from peak
          - Hard stop: never wider than -15% from entry
          - Earnings tightening: if earnings < 7 days, tighten to -5%
        """
        entry = trade.get("entry_price", current_price)
        stop = trade.get("stop_price", entry * 0.90)
        peak = trade.get("peak_price", entry)

        trailing_activation = self._get_param("trailing_stop_activation_pct", 0.15)
        trailing_distance = self._get_param("trailing_stop_distance_pct", 0.25)
        hard_stop_pct = 0.15

        pnl_pct = (current_price - entry) / entry if entry > 0 else 0

        # Update peak
        new_peak = max(peak, current_price)

        # Earnings tightening
        earnings_stop = None
        try:
            from stocks.utils.yfinance_client import YFinanceClient
            yf = YFinanceClient()
            days = yf.days_to_earnings(trade.get("ticker", ""))
            if days is not None and 0 <= days <= 7:
                earnings_stop = entry * 0.95  # tighten to -5%
        except Exception:
            pass

        # Trailing stop
        if pnl_pct >= trailing_activation:
            trailing_stop = new_peak * (1 - trailing_distance)
            # Never go wider than hard stop from entry
            hard_floor = entry * (1 - hard_stop_pct)
            trailing_stop = max(trailing_stop, hard_floor)
            new_stop = max(stop, trailing_stop)
        else:
            new_stop = stop

        # Apply earnings tightening if more conservative
        if earnings_stop and earnings_stop > new_stop:
            new_stop = earnings_stop

        # Check hit
        if current_price <= new_stop:
            return {
                "action": "CLOSE",
                "reason": "STOP_LOSS_HIT",
                "new_stop": new_stop,
                "peak_price": new_peak,
            }

        # Update if stop changed
        if abs(new_stop - stop) > 0.01:
            return {
                "action": "UPDATE_STOP",
                "reason": "TRAILING_STOP_UPDATED",
                "new_stop": round(new_stop, 2),
                "peak_price": new_peak,
            }

        return {
            "action": "HOLD",
            "reason": "Within stop levels",
            "new_stop": stop,
            "peak_price": new_peak,
        }
