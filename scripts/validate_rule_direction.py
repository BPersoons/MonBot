#!/usr/bin/env python3
"""G3b historical validation — would the discrete regime-aware rules have picked
better DIRECTIONS than the live pipeline, on the trades we actually took?

No waiting, no live shadow: for each recent CLOSED trade, fetch the 1h OHLCV up to
its entry time, run the asset-class rule (core/directional_signals) at that moment,
and compare the rule's direction to what live did — and to the realised pnl.

Answers: did the rules avoid the losing shorts? How often do they fire vs sit out?

Runs inside the container (Supabase creds + ccxt). Reads recent closed trades from
the VM trade_log.json (Supabase closed-sync stopped in March — see reconcile script).
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import pandas as pd

from core.directional_signals import add_directional_indicators, signal_for_ticker
from core.strategy_logic import detect_asset_class


def _parse_ts(raw):
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def main(trade_log_path="trade_log.json"):
    with open(trade_log_path) as f:
        trades = json.load(f)
    if not isinstance(trades, list):
        trades = trades.get("trades", [])

    closed = []
    for t in trades:
        if str(t.get("status", "")).upper() != "CLOSED":
            continue
        ent = _parse_ts(t.get("entry_time") or t.get("entry_fmt"))
        act = (t.get("action") or "").upper()
        pnl = t.get("pnl_net")
        if pnl is None:
            pnl = t.get("pnl")
        if ent is None or act not in ("BUY", "SELL"):
            continue
        closed.append({
            "ticker": t.get("ticker", ""),
            "entry": ent,
            "live_dir": "LONG" if act == "BUY" else "SHORT",
            "pnl": float(pnl or 0.0),
        })
    print(f"Closed trades to validate: {len(closed)}")
    if not closed:
        return

    import ccxt
    ex = ccxt.hyperliquid({"enableRateLimit": True})
    ex.load_markets()

    rows = []
    for tr in closed:
        tk = tr["ticker"]
        hl = tk.replace("/USDC", "/USDC:USDC") if ":USDC" not in tk else tk
        # 25 days of 1h candles ending at entry → enough for ema200 + warmup
        since = int((tr["entry"] - 25 * 24 * 3600) * 1000)
        try:
            ohlcv = ex.fetch_ohlcv(hl, timeframe="1h", since=since, limit=1000)
        except Exception as e:
            rows.append({**tr, "rule_dir": f"FETCH_ERR", "note": str(e)[:30]})
            continue
        if not ohlcv:
            rows.append({**tr, "rule_dir": "NO_DATA"})
            continue
        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        # keep only candles up to entry (no lookahead)
        df = df[df["ts"] <= tr["entry"] * 1000].reset_index(drop=True)
        df = add_directional_indicators(df)
        if len(df) < 2:
            rows.append({**tr, "rule_dir": "INSUFF"})
            continue
        sig = signal_for_ticker(tk, df, len(df) - 1)
        rule_dir = {1: "LONG", -1: "SHORT", 0: "NONE"}[sig]
        rows.append({**tr, "rule_dir": rule_dir})

    # ── Report ──
    print("\n" + "=" * 78)
    print("RULE DIRECTION vs LIVE, per closed trade (no lookahead)")
    print("=" * 78)
    print(f"{'ticker':16} {'live':5} {'rule':6} {'pnl$':>9}  verdict")
    print("-" * 78)
    agree = disagree = ruled_out = 0
    avoided_loss = missed_win = 0.0
    kept_pnl = 0.0
    for r in sorted(rows, key=lambda x: x["pnl"]):
        rd = r["rule_dir"]
        verdict = ""
        if rd in ("LONG", "SHORT"):
            if rd == r["live_dir"]:
                agree += 1
                kept_pnl += r["pnl"]
                verdict = "same dir"
            else:
                disagree += 1
                verdict = "FLIP"
        elif rd == "NONE":
            ruled_out += 1
            verdict = "rule: NO TRADE"
            if r["pnl"] < 0:
                avoided_loss += r["pnl"]
            else:
                missed_win += r["pnl"]
        else:
            verdict = rd
        print(f"{r['ticker']:16} {r['live_dir']:5} {rd:6} {r['pnl']:>9.2f}  {verdict}")

    total = agree + disagree + ruled_out
    print("-" * 78)
    print(f"Agree (same dir): {agree}   Flip: {disagree}   Rule says NO-TRADE: {ruled_out}"
          f"   (of {total} classifiable)")
    print(f"\nPnL live KEPT by rule (same-dir trades):     {kept_pnl:>9.2f}")
    print(f"PnL the rule would have AVOIDED (no-trade losers): {avoided_loss:>9.2f}")
    print(f"PnL the rule would have MISSED (no-trade winners): {missed_win:>9.2f}")
    print(f"\nRule fire distribution: {Counter(r['rule_dir'] for r in rows)}")
    print("\nNote: NONE = the regime-aware rule saw no valid setup at entry → live would")
    print("      not have opened. FLIP = rule picked the opposite direction to live.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "trade_log.json")
