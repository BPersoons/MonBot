"""
Replay pre-Phase-1 closed trades with current and variant exit geometry.

Goal: validate (a) Phase 1 params would have improved baseline, (b) whether
loosening profit-lock from 0.50 -> 0.60 helps winners run further.

Approach:
- For each valid pre-Phase-1 trade in trade_log_full.json, fetch 5m OHLCV
  from entry_time forward up to time_exit_hours of the timeframe.
- Replay candle-by-candle using high/low for SL/TP hits.
- Track stage transitions and simulated exit price.
- Compare three variants:
    * actual:   what really happened
    * phase1:   current production geometry (be 0.15/0.20, lock 0.50, trail 1.5x sl_pct, time 72/168h)
    * loose:    same but lock 0.60, trail 2.0x  (test "trail too tight" hypothesis)
"""
import ccxt
import json
import time
import datetime as dt
from collections import Counter

CUTOFF_TS = dt.datetime(2026, 4, 21, 18, 0, tzinfo=dt.timezone.utc).timestamp()
TIMEFRAME = "5m"
TF_MS = 5 * 60 * 1000


def is_swing(tf):
    return isinstance(tf, str) and tf.strip() == "4h Swing"


def hl_symbol(ticker):
    return ticker if ticker.endswith(":USDC") else f"{ticker}:USDC"


def fetch_ohlcv(ex, ticker, since_ts_ms, limit_hours):
    sym = hl_symbol(ticker)
    bars_needed = int((limit_hours * 60) / 5) + 10
    out = []
    cur = since_ts_ms
    end = since_ts_ms + limit_hours * 3600 * 1000
    while cur < end and len(out) < bars_needed:
        try:
            ohlcv = ex.fetch_ohlcv(sym, TIMEFRAME, since=cur, limit=500)
        except Exception as e:
            return None
        if not ohlcv:
            break
        out.extend(ohlcv)
        last_ts = ohlcv[-1][0]
        if last_ts <= cur:
            break
        cur = last_ts + TF_MS
    return out


def replay(trade, candles, params):
    """Returns (exit_price, close_reason, hours_held, max_stage_reached)."""
    entry = trade["entry_price"]
    is_long = trade["action"] == "BUY"
    sl = trade["stop_loss"]
    tp = trade["take_profit"]
    sl_pct = trade["sl_pct"]
    tf = trade["timeframe"]
    swing = is_swing(tf)

    time_exit = params["time_swing"] if swing else params["time_macro"]
    be_trig = params["be_swing"] if swing else params["be_macro"]
    lock_trig = params["lock_trigger"]
    trail_mult = params["trail_mult"]
    fee_buf = 0.001

    sl_stage = 0
    peak = entry
    entry_ms = candles[0][0]
    max_stage = 0

    tp_dist = abs(tp - entry)

    for c in candles:
        ts, o, h, l, cl, v = c
        hours_held = (ts - entry_ms) / 3600_000.0

        if is_long:
            peak = max(peak, h)
        else:
            peak = min(peak, l)

        # 1. SL hit (use low for long, high for short)
        if is_long and l <= sl:
            return sl, "STOP_LOSS", hours_held, max_stage
        if not is_long and h >= sl:
            return sl, "STOP_LOSS", hours_held, max_stage

        # 2. TP hit
        if is_long and h >= tp:
            return tp, "TAKE_PROFIT", hours_held, max_stage
        if not is_long and l <= tp:
            return tp, "TAKE_PROFIT", hours_held, max_stage

        # 3. Progress (use close as conservative measure)
        cur_profit = (cl - entry) if is_long else (entry - cl)
        progress = cur_profit / tp_dist if tp_dist > 0 else 0.0

        # 4. Time exit
        if hours_held > time_exit and progress < 0.15:
            return cl, "TIME_EXIT", hours_held, max_stage

        # 5. Stage transitions
        if sl_stage == 0 and progress >= be_trig:
            new_sl = entry * (1 + fee_buf) if is_long else entry * (1 - fee_buf)
            if (is_long and new_sl > sl) or (not is_long and new_sl < sl):
                sl = new_sl
                sl_stage = 1
                max_stage = max(max_stage, 1)
        elif sl_stage == 1 and progress >= lock_trig:
            lock_sl = (entry + cur_profit * 0.33) if is_long else (entry - cur_profit * 0.33)
            if (is_long and lock_sl > sl) or (not is_long and lock_sl < sl):
                sl = lock_sl
                sl_stage = 2
                max_stage = max(max_stage, 2)
        elif sl_stage >= 2:
            trail_pct = (sl_pct / 100.0) * trail_mult
            trail_sl = peak * (1 - trail_pct) if is_long else peak * (1 + trail_pct)
            if (is_long and trail_sl > sl) or (not is_long and trail_sl < sl):
                sl = trail_sl

    # End of window without exit
    last = candles[-1]
    hours_held = (last[0] - entry_ms) / 3600_000.0
    return last[4], "WINDOW_END", hours_held, max_stage


def pnl_pct(trade, exit_price):
    e = trade["entry_price"]
    if trade["action"] == "BUY":
        return (exit_price - e) / e * 100.0
    return (e - exit_price) / e * 100.0


def aggregate(results, label):
    n = len(results)
    if n == 0:
        return f"{label}: no trades"
    pnls = [r["pnl_pct"] for r in results]
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    pf = sum(wins) / sum(losses) if losses else 999.0
    avg_r = sum(pnls) / n
    stage1_reach = sum(1 for r in results if r["max_stage"] >= 1) / n * 100
    stage2_reach = sum(1 for r in results if r["max_stage"] >= 2) / n * 100
    reasons = Counter(r["reason"] for r in results)
    return (
        f"{label}: n={n} wr={len(wins)/n*100:.1f}% pf={pf:.2f} "
        f"avg_pct={avg_r:+.2f}% stage1={stage1_reach:.0f}% stage2={stage2_reach:.0f}% "
        f"reasons={dict(reasons.most_common())}"
    )


def main():
    trades = json.load(open("trade_log_full.json"))
    closed = [x for x in trades if x.get("status") == "CLOSED" and x.get("exit_time")]
    pre = [x for x in closed if x.get("entry_time", 0) < CUTOFF_TS]

    def valid(t):
        e, tp, sl = t["entry_price"], t.get("take_profit"), t.get("stop_loss")
        if not (e and tp and sl and t.get("sl_pct") and t.get("timeframe") in ("1h Macro", "4h Swing", "Macro News")):
            return False
        if t["action"] == "BUY":
            return tp > e > sl
        return tp < e < sl

    valid_trades = [x for x in pre if valid(x)]
    print(f"Replaying {len(valid_trades)} valid pre-Phase-1 trades")

    ex = ccxt.hyperliquid({"enableRateLimit": True, "options": {"defaultType": "swap"}})

    variants = {
        "phase1": dict(time_macro=72, time_swing=168, be_macro=0.15, be_swing=0.20,
                       lock_trigger=0.50, trail_mult=1.5),
        "loose":  dict(time_macro=72, time_swing=168, be_macro=0.15, be_swing=0.20,
                       lock_trigger=0.60, trail_mult=2.0),
    }
    sim_results = {k: [] for k in variants}
    actual_results = []
    skipped = 0

    for i, t in enumerate(valid_trades, 1):
        ticker = t["ticker"]
        is_swing_tf = is_swing(t.get("timeframe"))
        win_h = 168 if is_swing_tf else 72
        since_ms = int(t["entry_time"] * 1000)

        candles = fetch_ohlcv(ex, ticker, since_ms, win_h)
        if not candles or len(candles) < 5:
            skipped += 1
            print(f"  [{i}/{len(valid_trades)}] {ticker} — no candles, skipped")
            continue

        actual_results.append({
            "ticker": ticker, "pnl_pct": t.get("pnl_percent", 0.0) or 0.0,
            "reason": t.get("close_reason", "?"), "max_stage": t.get("sl_stage", 0)
        })

        for vname, params in variants.items():
            ex_price, reason, hours, max_stage = replay(t, candles, params)
            sim_results[vname].append({
                "ticker": ticker, "pnl_pct": pnl_pct(t, ex_price),
                "reason": reason, "max_stage": max_stage, "hours": hours
            })

        if i % 10 == 0:
            print(f"  [{i}/{len(valid_trades)}] processed ...")
        time.sleep(0.05)  # gentle rate limit

    print(f"\nSkipped (no candles): {skipped}")
    print()
    print(aggregate(actual_results, "ACTUAL "))
    for vname in variants:
        print(aggregate(sim_results[vname], vname.upper().ljust(7)))

    # Save raw output for inspection
    with open("scripts/replay_geometry_results.json", "w") as f:
        json.dump({
            "actual": actual_results,
            **sim_results,
            "variant_params": variants,
        }, f, indent=2, default=str)
    print("\nFull results saved to scripts/replay_geometry_results.json")


if __name__ == "__main__":
    main()
