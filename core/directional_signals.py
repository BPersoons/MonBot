"""Directional core — laag 1 richtingsbron (G3a).

Verbatim port of the proven, regime-aware discrete signal functions from
`scripts/strategy_final.py` (backtest +44% mrt-mei 2026, +15pp vs baseline on
current 60d data). These become the LIVE direction source in the directional-core
redesign (docs/DIRECTIONAL_CORE_REDESIGN.md, Optie B), replacing the mini-backtest
direction-picker and the entire threshold-multiplier stack.

Each `signal_*(df, i)` returns an int direction for candle `i`:
    +1 = LONG, -1 = SHORT, 0 = no trade.
They are regime-aware by construction (EMA200 gate + ADX filter + asset-class
specific rules) — no external regime multiplier needed.

`get_signal_for_asset(asset_class, df, i)` routes on the asset class produced by
`detect_asset_class(ticker)` in strategy_logic.py.

The dataframe `df` must carry the indicator columns in REQUIRED_COLUMNS. Use
`add_directional_indicators(df)` to compute them from a raw OHLCV frame, or wire
the live TechnicalAnalyst's equivalents (G3b verifies coverage).
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from core.strategy_logic import detect_asset_class

# Indicator columns the signal functions read (besides open/high/low/close/volume).
REQUIRED_COLUMNS = (
    "ema8", "ema20", "ema50", "ema200",
    "macd", "macd_sig", "macd_hist",
    "bb_upper", "bb_lower", "bb_mid",
    "atr", "adx", "plus_di", "minus_di",
    "rsi", "stoch_k", "st_dir",
    "close_10ago", "rsi_10ago",
)


# ── Signal functions (verbatim port of strategy_final.py) ─────────────
def signal_crypto(df, i):
    """CRYPTO — see strategy_final.py docstring. Returns +1/-1/0."""
    r = df.iloc[i]; p = df.iloc[i - 1]; price = r["close"]
    above_200 = price > r["ema200"]
    adx = r["adx"]

    # --- LONG ---
    if (above_200 and adx > 20
            and p["macd"] < 0 and r["macd"] >= 0
            and r["plus_di"] > r["minus_di"]):
        return 1
    if (above_200 and r["stoch_k"] < 0.20
            and r["stoch_k"] > p["stoch_k"]
            and price > r["ema50"] and adx > 15):
        return 1

    # --- SHORT ---
    prev_touched = p["close"] >= p["bb_upper"] * 0.99
    macd_turning = p["macd_hist"] > 0 and r["macd_hist"] < p["macd_hist"]
    if (prev_touched and macd_turning
            and price < r["bb_mid"] and adx > 15):
        return -1
    if (not above_200
            and p["macd_hist"] > 0 and r["macd_hist"] <= 0
            and adx > 15):
        return -1

    return 0


def signal_tech(df, i):
    """TECH STOCKS — shorts only below EMA200 (bearish divergence). Returns +1/-1/0."""
    r = df.iloc[i]; p = df.iloc[i - 1]; price = r["close"]
    above_200 = price > r["ema200"]
    adx = r["adx"]

    # --- LONG ---
    if p["st_dir"] == -1 and r["st_dir"] == 1 and adx > 18:
        return 1
    if (above_200
            and p["macd_hist"] < 0 and r["macd_hist"] >= 0
            and adx > 15):
        return 1

    # --- SHORT (bear regime only) ---
    if (not above_200
            and not pd.isna(r.get("close_10ago"))
            and price > r["close_10ago"] * 1.01
            and r["rsi"] < r["rsi_10ago"] - 3):
        return -1

    return 0


def signal_commodities(df, i):
    """COMMODITIES — both directions trend cleanly. Returns +1/-1/0."""
    r = df.iloc[i]; p = df.iloc[i - 1]; price = r["close"]
    above_200 = price > r["ema200"]
    adx = r["adx"]

    # --- LONG ---
    if (price > r["ema8"] > r["ema20"] > r["ema50"]
            and 52 <= r["rsi"] <= 72
            and adx > 15):
        return 1

    # --- SHORT ---
    if p["st_dir"] == 1 and r["st_dir"] == -1 and adx > 18:
        return -1
    if (not above_200 and adx > 20
            and p["macd"] > 0 and r["macd"] <= 0
            and r["minus_di"] > r["plus_di"]):
        return -1

    return 0


# ── Routing ───────────────────────────────────────────────────────────
_SIGNAL_BY_CLASS = {
    "crypto": signal_crypto,
    "tech_stock": signal_tech,
    "commodity": signal_commodities,
}


def get_signal_for_asset(asset_class: str, df, i) -> int:
    """Route to the asset-class signal function. Unknown class → crypto rules."""
    fn = _SIGNAL_BY_CLASS.get(asset_class, signal_crypto)
    return int(fn(df, i))


def signal_for_ticker(ticker: str, df, i) -> int:
    """Convenience: detect the asset class from the ticker and route."""
    return get_signal_for_asset(detect_asset_class(ticker), df, i)


# ── Indicators (verbatim port of strategy_final.add_indicators) ───────
def add_directional_indicators(df):
    """Compute REQUIRED_COLUMNS from a raw OHLCV frame. Verbatim port so the live
    direction source and the backtest stay bit-for-bit identical."""
    df = df.copy()
    c = df["close"]; v = df["volume"]
    d = c.diff()
    g = d.where(d > 0, 0).rolling(14).mean(); l = (-d.where(d < 0, 0)).rolling(14).mean()
    df["rsi"] = (100 - (100 / (1 + g / l.replace(0, np.nan)))).fillna(50)
    for span, col in [(8, "ema8"), (20, "ema20"), (50, "ema50"), (200, "ema200")]:
        df[col] = c.ewm(span=span, adjust=False).mean()
    df["macd"] = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    df["macd_sig"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_sig"]
    sma20 = c.rolling(20).mean(); std20 = c.rolling(20).std()
    df["bb_upper"] = sma20 + 2 * std20; df["bb_lower"] = sma20 - 2 * std20; df["bb_mid"] = sma20
    hl2 = df["high"] - df["low"]
    hc = (df["high"] - c.shift()).abs(); lc = (df["low"] - c.shift()).abs()
    df["atr"] = pd.concat([hl2, hc, lc], axis=1).max(axis=1).rolling(14).mean()
    pdm = df["high"].diff().clip(lower=0); ndm = (-df["low"].diff()).clip(lower=0)
    pdm[pdm < ndm] = 0; ndm[ndm < pdm] = 0
    pdi = 100 * pdm.rolling(14).mean() / df["atr"].replace(0, np.nan)
    ndi = 100 * ndm.rolling(14).mean() / df["atr"].replace(0, np.nan)
    dx = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).fillna(0)
    df["adx"] = dx.rolling(14).mean().fillna(0)
    df["plus_di"] = pdi.fillna(0); df["minus_di"] = ndi.fillna(0)
    rsi_min = df["rsi"].rolling(14).min(); rsi_max = df["rsi"].rolling(14).max()
    df["stoch_k"] = ((df["rsi"] - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)).fillna(0.5).rolling(3).mean()
    ub = ((df["high"] + df["low"]) / 2 + 3 * df["atr"]).copy()
    lb = ((df["high"] + df["low"]) / 2 - 3 * df["atr"]).copy()
    st_dir = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if pd.isna(ub.iloc[i]):
            continue
        ub.iloc[i] = min(ub.iloc[i], ub.iloc[i - 1]) if c.iloc[i - 1] <= ub.iloc[i - 1] else ub.iloc[i]
        lb.iloc[i] = max(lb.iloc[i], lb.iloc[i - 1]) if c.iloc[i - 1] >= lb.iloc[i - 1] else lb.iloc[i]
        st_dir.iloc[i] = (-1 if c.iloc[i] < ub.iloc[i] else 1) if st_dir.iloc[i - 1] == -1 else (1 if c.iloc[i] > lb.iloc[i] else -1)
    df["st_dir"] = st_dir
    df["vol_ma20"] = v.rolling(20).mean()
    df["rsi_10ago"] = df["rsi"].shift(10); df["close_10ago"] = c.shift(10)
    return df.dropna(subset=["ema200", "adx", "st_dir"]).copy()
