"""Toetst de bottleneck-these: hebben 'tolhuisje'-thema's structureel meer
selectiekracht dan 'narratief'-thema's, of is het allebei ruis?

Lang venster (2008+), meerdere cycli (2008, 2015-16, 2018, 2020, 2022) en een
expliciete OOS-splitsing — want korte vensters bedriegen altijd.

Gebruik: python scripts/theme_bottleneck_backtest.py
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import yfinance as yf

# ── Manden ───────────────────────────────────────────────────────────────────
# TOLHUISJE: er is een schakel met prijszettingsmacht waar niemand omheen kan.
TOLLBOOTH = {
    "SMH":  "Halfgeleiders (ASML/TSMC/NVDA)",
    "ITA":  "Defensie & ruimtevaart (certificering, programma's)",
    "IGV":  "Software infrastructuur (switching costs)",
}
# NARRATIEF: verhaal zonder tolhuisje — kapitaalintensief, uitwisselbaar product.
NARRATIVE = {
    "TAN":  "Zonne-energie",
    "PBW":  "Clean energy",
    "LIT":  "Batterij & lithium",
    "ICLN": "Clean energy (global)",
}
BENCH = {"ACWI": "MSCI All-Country World"}

# Indicatieve TER's (jaarlijks, van het rendement af) — thema-ETF's zijn duur.
TER = {"SMH": 0.35, "ITA": 0.40, "IGV": 0.41,
       "TAN": 0.67, "PBW": 0.61, "LIT": 0.75, "ICLN": 0.41,
       "ACWI": 0.32}

START = "2008-01-01"


def fetch(tickers: list[str]) -> pd.DataFrame:
    raw = yf.download(tickers, start=START, auto_adjust=True,
                      progress=False, group_by="column")
    px = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw.to_frame()
    px = px.dropna(how="all").ffill()
    return px


def net_returns(px: pd.Series, ticker: str) -> pd.Series:
    """Dagrendement na aftrek van de TER (pro rata per handelsdag)."""
    daily_ter = (TER.get(ticker, 0.0) / 100.0) / 252.0
    return px.pct_change() - daily_ter


def basket(px: pd.DataFrame, tickers: dict, label: str) -> pd.Series:
    """Gelijkgewogen mand, dagelijks herwogen, alleen over kolommen met data."""
    cols = [t for t in tickers if t in px.columns and px[t].notna().any()]
    rets = pd.DataFrame({t: net_returns(px[t], t) for t in cols})
    # Pas meetellen zodra een ticker data heeft; NaN's tellen niet mee in het gemiddelde.
    out = rets.mean(axis=1, skipna=True).fillna(0.0)
    out.name = label
    return out


def stats(r: pd.Series) -> dict:
    curve = (1 + r).cumprod()
    yrs = len(r) / 252.0
    cagr = curve.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    dd = (curve / curve.cummax() - 1).min()
    vol = r.std() * np.sqrt(252)
    return {
        "totaal_%": (curve.iloc[-1] - 1) * 100,
        "CAGR_%": cagr * 100,
        "maxDD_%": dd * 100,
        "vol_%": vol * 100,
        "Sharpe": (cagr / vol) if vol > 0 else np.nan,
    }


def table(d: dict[str, pd.Series], title: str) -> None:
    print(f"\n{title}")
    print("-" * 78)
    print(f"{'mand':<26}{'totaal %':>11}{'CAGR %':>9}{'maxDD %':>10}{'vol %':>8}{'Sharpe':>9}")
    for name, r in d.items():
        if r.empty:
            continue
        s = stats(r)
        print(f"{name:<26}{s['totaal_%']:>11.1f}{s['CAGR_%']:>9.1f}"
              f"{s['maxDD_%']:>10.1f}{s['vol_%']:>8.1f}{s['Sharpe']:>9.2f}")


def main() -> int:
    tickers = list(TOLLBOOTH) + list(NARRATIVE) + list(BENCH)
    print(f"Ophalen: {', '.join(tickers)}  (vanaf {START})")
    px = fetch(tickers)
    missing = [t for t in tickers if t not in px.columns or px[t].dropna().empty]
    if missing:
        print(f"WAARSCHUWING: geen data voor {missing} — die vallen uit de mand.")
    print(f"Periode: {px.index[0].date()} t/m {px.index[-1].date()} "
          f"({len(px)} handelsdagen)")
    print("\nStartdatum per ticker (bepaalt wanneer hij meetelt):")
    for t in tickers:
        if t in px.columns and px[t].notna().any():
            print(f"  {t:<6}{px[t].first_valid_index().date()}  {(TOLLBOOTH | NARRATIVE | BENCH)[t]}")

    baskets = {
        "TOLHUISJE": basket(px, TOLLBOOTH, "TOLHUISJE"),
        "NARRATIEF": basket(px, NARRATIVE, "NARRATIEF"),
        "Wereldindex (ACWI)": basket(px, BENCH, "Wereldindex (ACWI)"),
    }

    table(baskets, f"VOLLEDIGE PERIODE ({px.index[0].date()} - {px.index[-1].date()}), na TER")

    # OOS-splitsing: drie aaneengesloten delen, elk met eigen regime.
    edges = [("2008-01-01", "2013-12-31"), ("2014-01-01", "2019-12-31"),
             ("2020-01-01", "2026-12-31")]
    for a, b in edges:
        sub = {k: v.loc[a:b] for k, v in baskets.items()}
        if all(len(v) > 60 for v in sub.values()):
            table(sub, f"DEELPERIODE {a[:4]}-{b[:4]}")

    # Losse tickers, zodat zichtbaar is of één naam de mand draagt.
    singles = {f"{t} ({(TOLLBOOTH | NARRATIVE | BENCH)[t][:22]})": net_returns(px[t], t).dropna()
               for t in tickers if t in px.columns and px[t].notna().any()}
    table(singles, "PER TICKER (na TER) — draagt één naam de mand?")

    print("\nLet op: elke mand telt een ticker pas mee vanaf zijn eigen startdatum,")
    print("dus vroege jaren leunen op minder namen. Zie de startdatums hierboven.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
