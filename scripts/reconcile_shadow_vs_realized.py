#!/usr/bin/env python3
"""G3 stap 1 — reconcile shadow_book cells vs REALISED trade outcomes per regime×direction.

The shadow_book (shadow_report.json) rates TRENDING_BULL_SHORT as a *winning* cell,
yet the live pipeline lost -$33 shorting the bull on 2026-07-21. Before we calibrate
regime_alignment we must know which source to trust. This script buckets REAL closed
trades (Supabase) by regime×direction — reconstructing the BTC regime at each trade's
entry time exactly as ResearchAgent does — and prints them beside the shadow cells.

Runs INSIDE the container (needs Supabase creds + ccxt). Output is a comparison table.

Caveats printed inline: Supabase stores gross `pnl` (not pnl_net); regime is
reconstructed post-hoc from BTC 4h candles, not the value stored at decision time.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import json
import pandas as pd
import numpy as np


# ── Regime reconstruction (verbatim port of ResearchAgent._detect_market_regime) ──
def _regime_from_window(df: pd.DataFrame) -> str:
    """df = trailing 4h BTC candles (>=25 rows). Returns regime label."""
    if df is None or len(df) < 25:
        return "NEUTRAL"
    sma20 = float(df["close"].rolling(20).mean().iloc[-1])
    current = float(df["close"].iloc[-1])
    if current < sma20 * 0.995:
        direction = "BEARISH"
    elif current > sma20 * 1.005:
        direction = "BULLISH"
    else:
        direction = "NEUTRAL"

    period = 14
    prev_high, prev_low, prev_close = df["high"].shift(1), df["low"].shift(1), df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    plus_dm = np.where((df["high"] - prev_high > prev_low - df["low"]) & (df["high"] - prev_high > 0),
                       df["high"] - prev_high, 0.0)
    minus_dm = np.where((prev_low - df["low"] > df["high"] - prev_high) & (prev_low - df["low"] > 0),
                        prev_low - df["low"], 0.0)
    atr_s = pd.Series(tr.values, index=df.index).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    plus_dm_s = pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    minus_dm_s = pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    atr_safe = atr_s.replace(0, 1e-10)
    plus_di = 100 * plus_dm_s / atr_safe
    minus_di = 100 * minus_dm_s / atr_safe
    di_sum = (plus_di + minus_di).replace(0, 1e-10)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx = float(dx.ewm(alpha=1/period, min_periods=period, adjust=False).mean().iloc[-1])

    recent_atrs = atr_s.dropna().tail(30).values
    atr_now = float(atr_s.iloc[-1])
    atr_rank = float(np.mean(recent_atrs < atr_now)) if len(recent_atrs) > 5 else 0.5

    if atr_rank > 0.80:
        return "VOLATILE"
    if adx > 25:
        return "TRENDING_BULL" if direction == "BULLISH" else "TRENDING_BEAR"
    return "RANGING"


def _parse_ts(raw) -> float | None:
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


def main():
    # 1. Shadow cells
    with open("shadow_report.json") as f:
        shadow = json.load(f)
    shadow_cells = shadow.get("by_regime_x_direction", {})
    shadow_days = shadow.get("window_days")

    # 2. Realised closed trades from Supabase
    # Standalone process: the app populates os.environ at startup, but a fresh
    # `docker exec` does not — load Supabase creds ourselves.
    import os
    if not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY")):
        try:
            from utils.gcp_secrets import get_secret
            for k in ("SUPABASE_URL", "SUPABASE_KEY"):
                if not os.getenv(k):
                    v = get_secret(k, k)
                    if v:
                        os.environ[k] = v
        except Exception as e:
            print(f"[warn] secret bootstrap failed: {e}")
    from utils.db_client import DatabaseClient
    db = DatabaseClient()
    res = db.client.table("trades").select("*").eq("status", "CLOSED") \
        .order("created_at", desc=False).limit(2000).execute()
    trades = res.data or []
    # keep only trades with a usable entry ts and pnl
    usable = []
    for t in trades:
        ent = _parse_ts(t.get("created_at"))
        pnl = t.get("pnl")
        act = (t.get("action") or "").upper()
        if ent is None or pnl is None or act not in ("BUY", "SELL"):
            continue
        usable.append((ent, "LONG" if act == "BUY" else "SHORT", float(pnl), t.get("ticker", "")))
    print(f"Realised CLOSED trades usable: {len(usable)} / {len(trades)}")
    if not usable:
        print("No usable realised trades — cannot reconcile.")
        return
    usable.sort(key=lambda x: x[0])
    span_d = (usable[-1][0] - usable[0][0]) / 86400
    print(f"Realised window: {datetime.fromtimestamp(usable[0][0], tz=timezone.utc):%Y-%m-%d} "
          f"→ {datetime.fromtimestamp(usable[-1][0], tz=timezone.utc):%Y-%m-%d} ({span_d:.0f}d)")
    print(f"Shadow window: {shadow_days}d (generated {shadow.get('generated_at','?')[:10]})")

    # 3. BTC 4h history covering the trade span (+ warmup)
    import ccxt
    ex = ccxt.hyperliquid()
    ex.load_markets()
    since_ms = int((usable[0][0] - 60 * 4 * 3600) * 1000)  # 60 candles warmup
    candles = []
    cursor = since_ms
    while True:
        batch = ex.fetch_ohlcv("BTC/USDC:USDC", timeframe="4h", since=cursor, limit=1000)
        if not batch:
            break
        candles.extend(batch)
        if len(batch) < 1000:
            break
        cursor = batch[-1][0] + 1
        if batch[-1][0] > int(usable[-1][0] * 1000):
            break
    btc = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"]).drop_duplicates("ts")
    btc = btc.sort_values("ts").reset_index(drop=True)
    print(f"BTC 4h candles fetched: {len(btc)}")

    # 4. Bucket realised by reconstructed regime × direction
    cells = defaultdict(list)  # (regime,dir) -> [pnl,...]
    ts_arr = btc["ts"].values
    for ent, direction, pnl, _tk in usable:
        ent_ms = ent * 1000
        idx = int(np.searchsorted(ts_arr, ent_ms, side="right") - 1)
        if idx < 24:
            regime = "NEUTRAL"
        else:
            window = btc.iloc[max(0, idx - 49): idx + 1]
            regime = _regime_from_window(window)
        cells[(regime, direction)].append(pnl)

    # 5. Report
    print("\n" + "=" * 92)
    print("RECONCILIATION — realised (Supabase, gross pnl) vs shadow_book (virtual)")
    print("=" * 92)
    print(f"{'cell':26} | {'REAL n':>6} {'REAL WR':>7} {'REAL avg$':>9} {'REAL tot$':>9} "
          f"| {'SHDW n':>6} {'SHDW WR':>7} {'SHDW avg%':>9}")
    print("-" * 92)
    order = ["TRENDING_BULL", "TRENDING_BEAR", "RANGING", "VOLATILE", "NEUTRAL"]
    all_regimes = order + [r for r in {k[0] for k in cells} if r not in order]
    for reg in all_regimes:
        for d in ("LONG", "SHORT"):
            key = f"{reg}_{d}"
            rp = cells.get((reg, d), [])
            sh = shadow_cells.get(key, {})
            if not rp and not sh:
                continue
            if rp:
                n = len(rp)
                wr = 100.0 * sum(1 for p in rp if p > 0) / n
                avg = sum(rp) / n
                tot = sum(rp)
                real = f"{n:>6} {wr:>6.1f}% {avg:>9.2f} {tot:>9.2f}"
            else:
                real = f"{'—':>6} {'—':>7} {'—':>9} {'—':>9}"
            if sh:
                shw = f"{sh.get('n',0):>6} {sh.get('wr',0):>6.1f}% {sh.get('avg_pnl_pct',0):>9.3f}"
            else:
                shw = f"{'—':>6} {'—':>7} {'—':>9}"
            flag = ""
            if rp and sh:
                real_pos = (sum(rp) > 0)
                shdw_pos = (sh.get("avg_pnl_pct", 0) > 0)
                if real_pos != shdw_pos:
                    flag = "  ⚠️ SIGN DISAGREE"
            print(f"{key:26} | {real} | {shw}{flag}")

    print("\nNotes:")
    print(" • REAL = realised Supabase closed trades, GROSS pnl ($), regime reconstructed post-hoc.")
    print(" • SHDW = shadow_book virtual outcomes (avg % return), fixed SL/TP/24h exits.")
    print(" • ⚠️ SIGN DISAGREE = the two sources disagree on whether the cell makes money.")
    print(" • Windows differ (real spans the full trade history; shadow is 14d) — compare shapes, not absolutes.")


if __name__ == "__main__":
    main()
