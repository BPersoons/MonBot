"""Papiertoets (motor trede 1): sector-momentum — 'thema's komen en gaan, pak wat opkomt'.

    python research/sector_momentum.py

HYPOTHESE (Bart, 21-09): thema's komen en gaan; wie ze tijdig herkent, verslaat de markt.
De eenvoudigste toetsbare vorm is sector-momentum: houd de sectoren die het afgelopen
halfjaar tot jaar het sterkst waren, en wissel periodiek. In de literatuur een van de
robuustere effecten (Moskowitz & Grinblatt 1999, "Do Industries Explain Momentum?").

UNIVERSUM: de negen SPDR-sector-ETF's die sinds december 1998 bestaan. Niets is er
tussentijds uit verdwenen, dus geen overlevingsbias — anders dan bij thema-ETF's, waarvan
de mislukte stil worden opgeheven. Nieuwere sectoren (XLRE 2015, XLC 2018) bewust buiten
beschouwing: die zouden alleen in het goede deel van de reeks meedoen.

VOORAF VASTGELEGD — de strategie is alleen een kandidaat als ALLE vier gelden:
  1. rendement per jaar na kosten >= S&P 500 + 1 procentpunt
  2. maximale daling niet groter dan die van de S&P 500
  3. een voorsprong in minstens 2 van de 3 deelperiodes (1999-2008, 2009-2017, 2018-2026)
  4. het houdt stand voor een terugblik van 6, 9 én 12 maanden (geen toevalstreffer op één knop)

KOSTEN: 0,1% per kant bij elke wissel. Box 3 kent geen belasting per transactie, dus die
zit er terecht niet in.
"""

import sys

import numpy as np
import pandas as pd
import yfinance as yf

SECTOREN = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
BENCH = "SPY"
KOSTEN = 0.001
DEELPERIODES = [("1999-2008", "1999-01-01", "2008-12-31"),
                ("2009-2017", "2009-01-01", "2017-12-31"),
                ("2018-2026", "2018-01-01", "2026-12-31")]


def laad():
    d = yf.download(SECTOREN + [BENCH], start="1998-12-01", end="2026-09-20",
                    auto_adjust=True, progress=False)["Close"]
    return d.dropna().resample("ME").last()


def strategie(maand: pd.DataFrame, terugblik: int, top: int, elke: int = 1) -> pd.Series:
    """Maandrendement van: houd de `top` sectoren met het hoogste rendement over
    `terugblik` maanden (de laatste maand overgeslagen, de gangbare 12-1-opzet),
    herweeg elke `elke` maanden. Kosten op de omzet."""
    rend = maand[SECTOREN].pct_change()
    signaal = maand[SECTOREN].shift(1) / maand[SECTOREN].shift(terugblik + 1) - 1
    gewicht = pd.DataFrame(0.0, index=maand.index, columns=SECTOREN)
    huidig = None
    for i, dag in enumerate(maand.index):
        s = signaal.loc[dag]
        if s.isna().any():
            continue
        if huidig is None or i % elke == 0:
            huidig = list(s.sort_values(ascending=False).index[:top])
        gewicht.loc[dag, huidig] = 1.0 / top
    omzet = gewicht.diff().abs().sum(axis=1).fillna(0.0)
    uit = (gewicht.shift(1) * rend).sum(axis=1) - omzet.shift(1).fillna(0.0) * KOSTEN
    begin = gewicht[gewicht.sum(axis=1) > 0].index[0]
    return uit[uit.index > begin]


def maat(r: pd.Series) -> dict:
    groei = (1 + r).cumprod()
    jaren = len(r) / 12
    dd = ((groei.cummax() - groei) / groei.cummax()).max() * 100
    per_jaar = (1 + r).groupby(r.index.year).prod() - 1
    return {"cagr": (groei.iloc[-1] ** (1 / jaren) - 1) * 100, "dd": dd,
            "slechtste": per_jaar.min() * 100, "slechtste_jaar": int(per_jaar.idxmin())}


def cagr(r, van, tot):
    r = r[(r.index >= van) & (r.index <= tot)]
    return ((1 + r).prod() ** (12 / len(r)) - 1) * 100 if len(r) else float("nan")


def main():
    maand = laad()
    spy = maand[BENCH].pct_change().dropna()
    gelijk = maand[SECTOREN].pct_change().mean(axis=1).dropna()

    print("Sector-momentum, 9 SPDR-sectoren, %s .. %s, kosten %.1f%% per kant"
          % (maand.index[0].date(), maand.index[-1].date(), KOSTEN * 100))
    print()
    print("%-34s %8s %9s %16s" % ("", "per jaar", "max daling", "slechtste jaar"))
    rijen = {}
    for naam, r in (("S&P 500 (SPY)", spy), ("9 sectoren gelijk gewogen", gelijk)):
        m = maat(r)
        rijen[naam] = (r, m)
        print("%-34s %+7.1f%% %8.1f%% %9.1f%% (%d)" % (naam, m["cagr"], m["dd"], m["slechtste"], m["slechtste_jaar"]))
    print("-" * 72)
    uitslag = {}
    for terug in (6, 9, 12):
        for top in (2, 3):
            for elke, label in ((1, "maandelijks"), (3, "per kwartaal")):
                r = strategie(maand, terug, top, elke)
                m = maat(r)
                naam = "top %d, %2d mnd terug, %s" % (top, terug, label)
                uitslag[(terug, top, elke)] = (r, m)
                print("%-34s %+7.1f%% %8.1f%% %9.1f%% (%d)" % (naam, m["cagr"], m["dd"], m["slechtste"], m["slechtste_jaar"]))

    # Het oordeel op de vooraf gekozen hoofdvariant: top 3, per kwartaal (realistisch bij
    # DeGiro-kosten), met criterium 4 over alle drie de terugblikken.
    print()
    print("Deelperiodes (per jaar), hoofdvariant top 3 per kwartaal:")
    print("%-10s %8s %8s %8s %8s" % ("periode", "SPY", "6 mnd", "9 mnd", "12 mnd"))
    voorsprong_per_terug = {}
    for label, van, tot in DEELPERIODES:
        regel = [cagr(spy, van, tot)]
        for terug in (6, 9, 12):
            regel.append(cagr(uitslag[(terug, 3, 3)][0], van, tot))
        print("%-10s %+7.1f%% %+7.1f%% %+7.1f%% %+7.1f%%" % (label, *regel))
        for j, terug in enumerate((6, 9, 12)):
            voorsprong_per_terug.setdefault(terug, []).append(regel[j + 1] > regel[0])

    m_spy = rijen["S&P 500 (SPY)"][1]
    print()
    print("OORDEEL (vooraf vastgelegd), hoofdvariant top 3 per kwartaal:")
    alle = True
    for terug in (6, 9, 12):
        m = uitslag[(terug, 3, 3)][1]
        c1 = m["cagr"] >= m_spy["cagr"] + 1.0
        c2 = m["dd"] <= m_spy["dd"]
        c3 = sum(voorsprong_per_terug[terug]) >= 2
        print("  %2d mnd: 1 rendement >= SPY+1pp %-3s | 2 daling <= SPY %-3s | 3 >= 2 van 3 periodes %-3s"
              % (terug, "JA" if c1 else "NEE", "JA" if c2 else "NEE", "JA" if c3 else "NEE"))
        alle = alle and c1 and c2 and c3
    print("  4 houdt stand voor 6, 9 en 12 maanden: %s" % ("JA" if alle else "NEE"))
    print("  => %s" % ("KANDIDAAT — door naar verdieping" if alle else "GEEN KANDIDAAT in deze vorm"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
