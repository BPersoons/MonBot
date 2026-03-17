import logging
import time
from typing import Dict

class StrategyManager:
    """
    Computes exact trade levels (Entry, Take Profit, Stop Loss) based on RRR and volatility.
    Manages active trailing stops.
    """
    def __init__(self):
        self.logger = logging.getLogger("StrategyManager")

    def calculate_levels(self, current_price: float, action: str, rrr: float, stop_loss_pct: float) -> Dict[str, float]:
        """
        Calculates exact price levels based on technical entry.
        """
        sl_pct_dec = stop_loss_pct / 100.0
        
        if action == "BUY":
            stop_loss = current_price * (1.0 - sl_pct_dec)
            take_profit = current_price * (1.0 + (sl_pct_dec * rrr))
        else: # SELL / SHORT
            stop_loss = current_price * (1.0 + sl_pct_dec)
            take_profit = current_price * (1.0 - (sl_pct_dec * rrr))
            
        return {
            "entry_target": current_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rrr": rrr,
            "sl_pct": stop_loss_pct
        }
        
    def evaluate_position(self, trade: dict, current_price: float) -> dict:
        """
        Evaluates an OPEN position to determine if it should be closed or modified.
        Returns a dict with 'action' key: HOLD, CLOSE_FULL, CLOSE_PARTIAL, UPDATE_SL
        """
        entry     = trade.get('entry_price', 0.0)
        action    = trade.get('action', 'BUY')
        tp        = trade.get('take_profit', 0.0)
        sl        = trade.get('stop_loss', 0.0)
        sl_stage  = trade.get('sl_stage', 0)
        partial_tp1_taken = trade.get('partial_tp1_taken', False)
        sl_pct    = trade.get('sl_pct', 5.0)
        entry_time = trade.get('entry_time', 0.0)
        funding_rate = trade.get('funding_rate', 0.0)

        if not all([entry, tp, sl]):
            return {'action': 'HOLD', 'reason': None}

        is_long = (action == 'BUY')

        # Update running peak
        peak_price = trade.get('peak_price', current_price)
        if is_long:
            peak_price = max(peak_price, current_price)
        else:
            peak_price = min(peak_price, current_price)

        base = {'peak_price': peak_price}

        # 1. SL hit
        if is_long and current_price <= sl:
            return {**base, 'action': 'CLOSE_FULL', 'reason': 'STOP_LOSS'}
        if not is_long and current_price >= sl:
            return {**base, 'action': 'CLOSE_FULL', 'reason': 'STOP_LOSS'}

        # 2. TP hit
        if is_long and current_price >= tp:
            return {**base, 'action': 'CLOSE_FULL', 'reason': 'TAKE_PROFIT'}
        if not is_long and current_price <= tp:
            return {**base, 'action': 'CLOSE_FULL', 'reason': 'TAKE_PROFIT'}

        # 3. Progress toward TP (0.0 = at entry, 1.0 = at TP)
        tp_distance = abs(tp - entry)
        current_profit = (current_price - entry) if is_long else (entry - current_price)
        progress = current_profit / tp_distance if tp_distance > 0 else 0.0

        # 4. Funding cost check (long positions with positive funding held > 16h)
        hours_held = (time.time() - entry_time) / 3600.0 if entry_time else 0.0
        if hours_held > 16 and funding_rate > 0 and is_long and current_profit > 0:
            funding_periods = hours_held / 8.0
            accumulated_funding_pct = funding_rate * funding_periods
            unrealized_pnl_pct = current_profit / entry
            if unrealized_pnl_pct > 0 and accumulated_funding_pct / unrealized_pnl_pct > 0.40:
                return {**base, 'action': 'CLOSE_FULL', 'reason': 'FUNDING_COST'}

        # 5. Partial TP at 1:1 (50% of TP distance)
        if not partial_tp1_taken and progress >= 0.50:
            return {**base, 'action': 'CLOSE_PARTIAL', 'reason': 'PARTIAL_TP', 'close_fraction': 0.40}

        # 6. Multi-stage SL trailing
        FEE_BUFFER = 0.001  # 0.1%

        if sl_stage == 0 and progress >= 0.25:
            new_sl = entry * (1 + FEE_BUFFER) if is_long else entry * (1 - FEE_BUFFER)
            if (is_long and new_sl > sl) or (not is_long and new_sl < sl):
                return {**base, 'action': 'UPDATE_SL', 'reason': 'BREAKEVEN',
                        'new_sl': new_sl, 'sl_stage': 1}

        elif sl_stage == 1 and progress >= 0.65:
            profit_lock_sl = (entry + current_profit * 0.33) if is_long else (entry - current_profit * 0.33)
            if (is_long and profit_lock_sl > sl) or (not is_long and profit_lock_sl < sl):
                return {**base, 'action': 'UPDATE_SL', 'reason': 'PROFIT_LOCK',
                        'new_sl': profit_lock_sl, 'sl_stage': 2}

        elif sl_stage >= 2:
            trail_pct = (sl_pct / 100.0) * 1.5
            trail_sl = peak_price * (1 - trail_pct) if is_long else peak_price * (1 + trail_pct)
            if (is_long and trail_sl > sl) or (not is_long and trail_sl < sl):
                return {**base, 'action': 'UPDATE_SL', 'reason': 'TRAIL',
                        'new_sl': trail_sl, 'sl_stage': 2}

        return {**base, 'action': 'HOLD', 'reason': None}
