import logging
import time
import datetime
from typing import Dict
from core.strategy_logic import detect_asset_class


def _us_market_is_open() -> bool:
    """Returns True if the US stock market is currently open (Mon–Fri, 14:30–21:00 UTC)."""
    now_utc = datetime.datetime.utcnow()
    if now_utc.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open = now_utc.replace(hour=14, minute=30, second=0, microsecond=0)
    market_close = now_utc.replace(hour=21, minute=0, second=0, microsecond=0)
    return market_open <= now_utc < market_close

class StrategyManager:
    """
    Computes exact trade levels (Entry, Take Profit, Stop Loss) based on RRR and volatility.
    Manages active trailing stops and time-based exits.
    """
    def __init__(self):
        self.logger = logging.getLogger("StrategyManager")
        try:
            from utils.auto_params import AutoParams
            self._auto_params = AutoParams()
        except Exception:
            self._auto_params = None

    def _param(self, key: str, fallback: float) -> float:
        """Read an auto-tunable param, fail-open to the hardcoded fallback."""
        if self._auto_params is not None:
            try:
                return float(self._auto_params.get(key, fallback))
            except Exception:
                pass
        return fallback

    @staticmethod
    def _is_swing(timeframe) -> bool:
        return isinstance(timeframe, str) and timeframe.strip() == "4h Swing"

    def calculate_levels(self, current_price: float, action: str, rrr: float, stop_loss_pct: float, atr_pct: float = 0.0, timeframe: str = None, swing_levels: dict = None) -> Dict[str, float]:
        """
        Calculates exact price levels.

        Priority:
          1) Structure-based (swing_levels): SL at swing low/high + buffer, TP at Fib 1.618.
             Only used when structure math yields RRR >= 1.5 (safety net — project_lead
             normally enforces earlier, but don't corrupt levels if gate was bypassed).
          2) ATR-based fallback: SL = 2x ATR (3x for swing), TP = SL * RRR.
          3) Fixed-percentage fallback from stop_loss_pct.
        """
        is_swing = self._is_swing(timeframe)

        # --- 1) Structure-based levels (preferred when valid) ---
        if swing_levels and swing_levels.get('valid') and current_price > 0:
            sl = float(swing_levels.get('sl_suggest') or 0)
            tp = float(swing_levels.get('tp_suggest') or 0)
            if sl > 0 and tp > 0 and ((action == "BUY" and sl < current_price < tp) or
                                      (action != "BUY" and tp < current_price < sl)):
                risk   = abs(current_price - sl)
                reward = abs(tp - current_price)
                implied_rrr = reward / risk if risk > 0 else 0.0
                if implied_rrr >= 1.5:
                    sl_pct_dec = risk / current_price
                    # Apply same max-SL cap as ATR/fixed path — structure levels can
                    # place swing lows far below entry, creating impractically wide stops.
                    sl_pct_max = 0.05 if is_swing else 0.03
                    if sl_pct_dec > sl_pct_max:
                        self.logger.info(
                            f"Structure SL too wide ({sl_pct_dec*100:.1f}% > {sl_pct_max*100:.0f}% max) "
                            f"— falling back to ATR/fixed"
                        )
                        # Fall through to ATR/fixed path below
                    else:
                        self.logger.info(
                            f"Structure-based levels ({'swing' if is_swing else 'macro'}): "
                            f"SL={sl:.6f} TP={tp:.6f} implied_RRR={implied_rrr:.2f} "
                            f"(structure_tf={swing_levels.get('structure_tf')})"
                        )
                        return {
                            "entry_target": current_price,
                            "stop_loss":   sl,
                            "take_profit": tp,
                            "rrr":         round(implied_rrr, 2),
                            "sl_pct":      round(sl_pct_dec * 100, 2),
                            "atr_based":   False,
                            "structure_based": True,
                            "setup": "4h Swing" if is_swing else "1h Macro",
                        }
                else:
                    self.logger.info(
                        f"Structure levels insufficient RRR {implied_rrr:.2f} — falling back to ATR"
                    )

        # --- 2) ATR-based ---
        if atr_pct > 0:
            atr_mult  = 3.0 if is_swing else 2.0
            sl_pct_dec = (atr_pct * atr_mult) / 100.0
            self.logger.info(
                f"ATR-based SL ({'swing' if is_swing else 'macro'}): ATR={atr_pct:.2f}% "
                f"→ SL={sl_pct_dec*100:.1f}% ({atr_mult}x ATR), RRR={rrr}"
            )
        else:
            # --- 3) Fixed-percentage fallback ---
            sl_pct_dec = stop_loss_pct / 100.0

        # Setup-aware clamps
        # Phase 1 (2026-04-21): tightened from Macro 1.5-5% / Swing 4-8% based on
        # production data showing Stage 0 (initial SL) held 87% of trades for
        # -$177; lower SL widths force more trades to reach Stage 1 (BE) earlier.
        if is_swing:
            sl_pct_dec = max(0.030, min(sl_pct_dec, 0.05))
            effective_rrr = rrr * 1.5
        else:
            sl_pct_dec = max(0.015, min(sl_pct_dec, 0.03))
            effective_rrr = rrr

        if action == "BUY":
            stop_loss = current_price * (1.0 - sl_pct_dec)
            take_profit = current_price * (1.0 + (sl_pct_dec * effective_rrr))
        else: # SELL / SHORT
            stop_loss = current_price * (1.0 + sl_pct_dec)
            take_profit = current_price * (1.0 - (sl_pct_dec * effective_rrr))

        return {
            "entry_target": current_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "rrr": effective_rrr,
            "sl_pct": round(sl_pct_dec * 100, 2),
            "atr_based": atr_pct > 0,
            "structure_based": False,
            "setup": "4h Swing" if is_swing else "1h Macro",
        }

    def evaluate_position(self, trade: dict, current_price: float) -> dict:
        """
        Evaluates an OPEN position to determine if it should be closed or modified.
        Returns a dict with 'action' key: HOLD, CLOSE_FULL, CLOSE_PARTIAL, UPDATE_SL
        """
        if trade.get("harvest"):
            return {"action": "HOLD", "reason": "treasury harvest position"}

        entry     = trade.get('entry_price', 0.0)
        action    = trade.get('action', 'BUY')
        tp        = trade.get('take_profit', 0.0)
        sl        = trade.get('stop_loss', 0.0)
        sl_stage  = trade.get('sl_stage', 0)
        partial_tp1_taken = trade.get('partial_tp1_taken', False)
        sl_pct    = trade.get('sl_pct', 5.0)
        entry_time = trade.get('entry_time', 0.0)
        funding_rate = trade.get('funding_rate', 0.0)
        is_swing  = self._is_swing(trade.get('timeframe'))

        time_exit_hours   = 168.0 if is_swing else 72.0
        partial_fraction  = 0.33  if is_swing else 0.40
        time_exit_reason  = 'TIME_EXIT_168H' if is_swing else 'TIME_EXIT_72H'

        if not all([entry, tp, sl]):
            return {'action': 'HOLD', 'reason': None}

        is_long = (action == 'BUY')

        # 1R = original SL distance (sl_pct preserves initial risk even after SL moves to BE).
        # Anchors triggers to risk taken, not to TP target distance.
        one_r = entry * (sl_pct / 100.0) if sl_pct else abs(entry - sl)

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

        current_profit = (current_price - entry) if is_long else (entry - current_price)

        # 3. Progress toward TP — used only for time-exit gate
        tp_distance = abs(tp - entry)
        progress = current_profit / tp_distance if tp_distance > 0 else 0.0

        # 4. Funding cost check (long positions with positive funding held > 16h)
        hours_held = (time.time() - entry_time) / 3600.0 if entry_time else 0.0
        if hours_held > 16 and funding_rate > 0 and is_long and current_profit > 0:
            funding_periods = hours_held / 8.0
            accumulated_funding_pct = funding_rate * funding_periods
            unrealized_pnl_pct = current_profit / entry
            if unrealized_pnl_pct > 0 and accumulated_funding_pct / unrealized_pnl_pct > 0.40:
                return {**base, 'action': 'CLOSE_FULL', 'reason': 'FUNDING_COST'}

        # 5. Time-based exit: close stale positions that haven't reached 15% of TP.
        if hours_held > time_exit_hours and progress < 0.15:
            return {**base, 'action': 'CLOSE_FULL', 'reason': time_exit_reason,
                    'detail': f'Held {hours_held:.0f}h, only {progress*100:.0f}% toward TP'}

        # 5b. No-momentum early exit: stage=0 trade drifting adversely after 24h.
        # Data shows stage=0 losers drift 30-230h before final SL hit, tying up capital.
        # Exit when price moves >25% of SL distance against us without ever reaching BE.
        # Swing trades get 36h grace (4h setups need more development time).
        # XYZ equity tokens are skipped when US market is closed: weekend/overnight
        # price drift on low-liquidity synthetic perps is noise, not momentum signal.
        # Prefix-based class detection (detect_asset_class) instead of the 7-entry
        # XYZ_EQUITY_TICKERS registry: the pipeline trades ~20 XYZ equities (AAPL,
        # META, SP500, …) that the registry doesn't list — those must not be cut on
        # frozen closed-market prices either.
        no_momentum_hours = 36.0 if is_swing else 24.0
        _skip_no_momentum = (detect_asset_class(trade.get('ticker', '')) == 'tech_stock'
                             and not _us_market_is_open())
        if not _skip_no_momentum and sl_stage == 0 and hours_held >= no_momentum_hours:
            adverse_move = -current_profit
            if adverse_move > one_r * 0.25:
                return {**base, 'action': 'CLOSE_FULL', 'reason': 'NO_MOMENTUM',
                        'detail': f'Held {hours_held:.0f}h at stage=0, adverse {adverse_move/entry*100:.2f}% (>{sl_pct*0.25:.2f}% threshold)'}

        # 5c. No-progress time stop (2026-07-02): cut stage=0 trades that sit at or
        # below entry after a few hours. Production data since 06-12: stage=0 trades
        # 3.4% WR / -$236 vs stage=2 100% WR / +$246 — losers rarely recover and most
        # hit full SL within 1.5-13h, long before the 24h NO_MOMENTUM rule (5b) fires.
        # Swing setups get double grace (4h candles need development time).
        # Same XYZ closed-market guard as 5b: overnight drift is noise, not signal.
        no_progress_hours = self._param("no_progress_exit_hours", 5.0)
        no_progress_min   = self._param("no_progress_min_pct", 0.0)
        if is_swing:
            no_progress_hours *= 2.0
        if (not _skip_no_momentum and sl_stage == 0
                and hours_held >= no_progress_hours and progress <= no_progress_min):
            return {**base, 'action': 'CLOSE_FULL', 'reason': 'NO_PROGRESS_TIMEOUT',
                    'detail': f'Held {hours_held:.1f}h at stage=0, progress {progress*100:.0f}% toward TP'}

        # 6. Partial TP at 1R: take partial when trade is up by the full risk distance.
        #    More achievable than 50% of TP target (which requires 2R move for RRR=2).
        if not partial_tp1_taken and current_profit >= one_r:
            return {**base, 'action': 'CLOSE_PARTIAL', 'reason': 'PARTIAL_TP', 'close_fraction': partial_fraction}

        # 7. Multi-stage SL trailing
        FEE_BUFFER = 0.001  # 0.1%

        # BE at 0.5R: move SL to breakeven when up half the risk distance.
        if sl_stage == 0 and current_profit >= one_r * 0.5:
            new_sl = entry * (1 + FEE_BUFFER) if is_long else entry * (1 - FEE_BUFFER)
            if (is_long and new_sl > sl) or (not is_long and new_sl < sl):
                return {**base, 'action': 'UPDATE_SL', 'reason': 'BREAKEVEN',
                        'new_sl': new_sl, 'sl_stage': 1}

        elif sl_stage == 1 and progress >= 0.50:
            # Phase 1 (2026-04-21): trigger pulled in from 0.65 -> 0.50 so more
            # trades reach Stage 2 (trailing), where production data shows
            # 81% WR / +$2.44 avg. Faster lock-in also reduces give-back risk.
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
