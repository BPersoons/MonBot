"""
Read-only diagnostic: compare current SL/TP of open trades against
structure-based (swing-low/high + Fib 1.618) proposals.

Output per open trade:
  - current levels + sl_stage
  - structure proposal
  - verdict (TIGHTEN_OK / LEAVE / NO_STRUCTURE_DATA / AVOID)

Does NOT modify any trade — pure diagnostic.
Run inside the container:  python -m scripts.diag_structure_sl_tp
"""

import json
import logging

logging.basicConfig(level=logging.WARNING)


def _swing_levels(df, direction: str, price: float, atr_pct: float) -> dict:
    """Mirror of TechnicalAnalyst._compute_swing_levels (standalone, read-only)."""
    out = {"valid": False}
    try:
        if df is None or len(df) < 30 or price <= 0:
            return out
        lookback = 20
        recent = df.tail(lookback)
        swing_low  = float(recent['low'].min())
        swing_high = float(recent['high'].max())
        if swing_high <= swing_low or swing_low <= 0:
            return out
        impulse = swing_high - swing_low
        fib_1618_up   = swing_low  + 1.618 * impulse
        fib_1618_down = swing_high - 1.618 * impulse
        buffer_pct = max(0.003, (atr_pct / 100.0) * 0.3) if atr_pct > 0 else 0.003

        if (direction or "").upper() in ("BUY", "LONG"):
            sl_suggest = swing_low * (1.0 - buffer_pct)
            tp_suggest = fib_1618_up
            risk   = price - sl_suggest
            reward = tp_suggest - price
        else:
            sl_suggest = swing_high * (1.0 + buffer_pct)
            tp_suggest = fib_1618_down
            risk   = sl_suggest - price
            reward = price - tp_suggest

        if risk <= 0 or reward <= 0:
            return out
        return {
            "valid": True,
            "swing_low":  round(swing_low, 6),
            "swing_high": round(swing_high, 6),
            "sl_suggest": round(sl_suggest, 6),
            "tp_suggest": round(tp_suggest, 6),
            "implied_rrr": round(reward / risk, 2),
            "buffer_pct":  round(buffer_pct * 100, 3),
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


def _atr_pct(df, period: int = 14) -> float:
    """Simple ATR% from OHLCV DataFrame."""
    try:
        import pandas as pd  # noqa
        h, l, c = df['high'], df['low'], df['close']
        prev_c = c.shift(1)
        tr = (h - l).combine(
            (h - prev_c).abs(), max
        ).combine((l - prev_c).abs(), max)
        atr = tr.rolling(period).mean().iloc[-1]
        last = float(c.iloc[-1])
        return (float(atr) / last) * 100.0 if last > 0 else 0.0
    except Exception:
        return 0.0


def _verdict(trade: dict, current_price: float, sl_suggest: float,
             tp_suggest: float, implied_rrr_struct: float) -> dict:
    """Decide whether structure proposal is an improvement over current levels."""
    action = trade.get('action', 'BUY')
    cur_sl = float(trade.get('stop_loss') or 0)
    cur_tp = float(trade.get('take_profit') or 0)
    sl_stage = int(trade.get('sl_stage') or 0)
    partial_done = bool(trade.get('partial_tp1_taken'))
    is_long = action in ('BUY', 'LONG')

    # current implied RRR *from now* (not from entry)
    if is_long:
        risk_now   = max(current_price - cur_sl, 1e-9)
        reward_now = max(cur_tp - current_price, 0.0)
    else:
        risk_now   = max(cur_sl - current_price, 1e-9)
        reward_now = max(current_price - cur_tp, 0.0)
    cur_rrr_now = round(reward_now / risk_now, 2) if risk_now > 0 else 0.0

    # SL tightening: only valid direction
    if is_long:
        sl_tighten_ok = sl_suggest > cur_sl   # closer to price from below
        sl_delta_pct  = (sl_suggest - cur_sl) / max(cur_sl, 1e-9) * 100.0
    else:
        sl_tighten_ok = sl_suggest < cur_sl   # closer from above
        sl_delta_pct  = (cur_sl - sl_suggest) / max(cur_sl, 1e-9) * 100.0

    # Never go below entry * (1 + fee_buffer) after BE has been set
    if sl_stage >= 1 and sl_tighten_ok:
        entry = float(trade.get('entry_price') or 0)
        if entry > 0:
            if is_long and sl_suggest < entry:
                sl_tighten_ok = False  # BE already guaranteed; don't regress
            if (not is_long) and sl_suggest > entry:
                sl_tighten_ok = False

    # Hard block when trailing is active
    if sl_stage >= 2:
        recommend = "AVOID — trailing SL already active (sl_stage>=2); don't override"
        action_tag = "LEAVE"
    elif not sl_tighten_ok:
        recommend = "LEAVE — structure SL would loosen current stop; never widen on live trade"
        action_tag = "LEAVE"
    elif sl_delta_pct < 0.2:
        recommend = "LEAVE — structure SL within 0.2% of current (noise)"
        action_tag = "LEAVE"
    else:
        note = " (partial taken — TP edits risky)" if partial_done else ""
        recommend = (f"TIGHTEN_OK — move SL to {sl_suggest:.6f} "
                     f"(+{sl_delta_pct:.2f}% tighter){note}")
        action_tag = "TIGHTEN_OK"

    return {
        "cur_rrr_now":  cur_rrr_now,
        "cur_sl":       cur_sl,
        "cur_tp":       cur_tp,
        "struct_sl":    sl_suggest,
        "struct_tp":    tp_suggest,
        "struct_rrr":   implied_rrr_struct,
        "sl_delta_pct": round(sl_delta_pct, 3),
        "sl_stage":     sl_stage,
        "partial":      partial_done,
        "action_tag":   action_tag,
        "recommend":    recommend,
    }


def main():
    # Load open trades
    try:
        with open("trade_log.json") as f:
            trades = json.load(f)
    except Exception as e:
        print(f"Could not read trade_log.json: {e}")
        return
    open_trades = [t for t in trades if t.get("status") == "OPEN"]
    if not open_trades:
        print("No open trades.")
        return

    from utils.exchange_client import HyperliquidExchange
    from agents.technical_analyst import TechnicalAnalyst
    x = HyperliquidExchange()

    print(f"=== Structure-based SL/TP diagnostic — {len(open_trades)} open trades ===\n")

    for t in open_trades:
        ticker    = t.get("ticker")
        tf        = (t.get("timeframe") or "").strip()
        action    = t.get("action", "BUY")
        entry     = float(t.get("entry_price") or 0)
        ohlcv_tf  = "4h" if tf == "4h Swing" else "1h"

        try:
            df = TechnicalAnalyst(symbol=ticker).fetch_data(timeframe=ohlcv_tf, limit=100)
        except Exception as e:
            print(f"--- {ticker} ({tf}) --- OHLCV fetch failed: {e}\n")
            continue

        if df is None or len(df) < 30:
            print(f"--- {ticker} ({tf}) --- insufficient OHLCV data\n")
            continue

        try:
            price = float(x.get_market_price(ticker) or 0)
        except Exception:
            price = 0.0
        if price <= 0:
            price = float(df['close'].iloc[-1])

        atr = _atr_pct(df, 14)
        sw  = _swing_levels(df, action, price, atr)

        print(f"--- {ticker}  ({tf}, {action})")
        print(f"  entry={entry:.6f}  price_now={price:.6f}  ATR={atr:.2f}%")

        if not sw.get("valid"):
            print(f"  structure: NO_STRUCTURE_DATA  ({sw.get('error', 'insufficient range')})\n")
            continue

        v = _verdict(t, price, sw["sl_suggest"], sw["tp_suggest"], sw["implied_rrr"])
        print(f"  current  SL={v['cur_sl']:.6f}  TP={v['cur_tp']:.6f}  "
              f"sl_stage={v['sl_stage']}  partial={v['partial']}  RRR_now={v['cur_rrr_now']}")
        print(f"  structure SL={v['struct_sl']:.6f}  TP={v['struct_tp']:.6f}  "
              f"RRR(struct)={v['struct_rrr']}  "
              f"[swing_low={sw['swing_low']:.6f}, swing_high={sw['swing_high']:.6f}]")
        print(f"  → {v['recommend']}\n")


if __name__ == "__main__":
    main()
