"""Papiertoets (motor trede 1): industrie-momentum op 49 industrieën — thema's op fijner niveau.

    python research/industrie_momentum.py <map met 49_Industry_Portfolios.csv en F-F_Research_Data_Factors.csv>

Vervolg op research/sector_momentum.py: met negen brede sectoren was er geen voorsprong
(8,2-9,3% per jaar tegen 8,6% voor de S&P 500). Negen sectoren zijn veel grover dan de
thema's die Bart bedoelt; het onderzoek vindt momentum juist op industrieniveau.

DATA: Kenneth French Data Library, 49 industrieportefeuilles (waardegewogen, maandelijks,
sinds 1926) en de marktfactor. Opgebouwd uit ALLE Amerikaanse aandelen per periode, dus
zonder overlevingsbias en zonder achteraf gekozen namen.

VOORAF VASTGELEGD — alleen een kandidaat als ALLE vier gelden, voor de hoofdvariant
(top 5 industrieën, terugblik 12-1 maanden, per kwartaal herwegen):
  1. rendement per jaar na kosten >= markt + 1,5 procentpunt, over 1964-2026
  2. maximale daling niet meer dan 5 procentpunt groter dan die van de markt
  3. een voorsprong in minstens 4 van de 6 decennia (1964-1973 ... 2014-2026)
  4. het houdt stand voor een terugblik van 6, 9 én 12 maanden
De kosten zijn hoger dan bij sector-ETF's (smallere industrie-ETF's): 0,3% per kant.
1964 als start: vóór die tijd is de CRSP-dekking dun (weinig aandelen per industrie).
"""

import io
import sys

import numpy as np
import pandas as pd

KOSTEN = 0.003
START = "1964-01"
DECENNIA = [("1964-1973", "1964-01", "1973-12"), ("1974-1983", "1974-01", "1983-12"),
            ("1984-1993", "1984-01", "1993-12"), ("1994-2003", "1994-01", "2003-12"),
            ("2004-2013", "2004-01", "2013-12"), ("2014-2026", "2014-01", "2026-12")]


def lees_blok(pad, kop):
    """Eerste maandblok onder de kop `kop` uit een French-CSV → DataFrame in fracties."""
    regels = open(pad, encoding="latin-1").read().splitlines()
    i = next(n for n, r in enumerate(regels) if kop in r)
    # In het industriebestand staat de kop BOVEN de kolomnamen; in het factorbestand is de
    # regel met de kop zelf de kolomregel (",Mkt-RF,SMB,..").
    kopregel = i if regels[i].startswith(",") else i + 1
    kolommen = [c.strip() for c in regels[kopregel].split(",")]
    data = []
    for r in regels[kopregel + 1:]:
        delen = [c.strip() for c in r.split(",")]
        if len(delen) < 2 or not delen[0].isdigit() or len(delen[0]) != 6:
            break
        data.append(delen)
    df = pd.DataFrame(data, columns=["maand"] + kolommen[1:])
    df.index = pd.PeriodIndex(df.pop("maand"), freq="M")
    df = df.astype(float)
    return df.where(df > -99, np.nan) / 100.0


def strategie(r: pd.DataFrame, terugblik: int, top: int, elke: int) -> pd.Series:
    groei = (1 + r.fillna(0)).cumprod()
    signaal = groei.shift(1) / groei.shift(terugblik + 1) - 1
    beschikbaar = r.notna() & r.shift(terugblik + 1).notna()
    gewicht = pd.DataFrame(0.0, index=r.index, columns=r.columns)
    huidig = None
    for i, m in enumerate(r.index):
        s = signaal.loc[m].where(beschikbaar.loc[m])
        if s.notna().sum() < top * 2:
            continue
        if huidig is None or i % elke == 0:
            huidig = list(s.dropna().sort_values(ascending=False).index[:top])
        gewicht.loc[m, huidig] = 1.0 / top
    omzet = gewicht.diff().abs().sum(axis=1).fillna(0.0)
    uit = (gewicht.shift(1) * r.fillna(0)).sum(axis=1) - omzet.shift(1).fillna(0) * KOSTEN
    begin = gewicht[gewicht.sum(axis=1) > 0].index[0]
    return uit[uit.index > begin]


def maat(r):
    groei = (1 + r).cumprod()
    jaren = len(r) / 12
    dd = ((groei.cummax() - groei) / groei.cummax()).max() * 100
    per_jaar = (1 + r).groupby(r.index.year).prod() - 1
    return {"cagr": (groei.iloc[-1] ** (1 / jaren) - 1) * 100, "dd": dd,
            "slechtste": per_jaar.min() * 100, "slechtste_jaar": int(per_jaar.idxmin())}


def cagr(r, van, tot):
    r = r[(r.index >= pd.Period(van, "M")) & (r.index <= pd.Period(tot, "M"))]
    return ((1 + r).prod() ** (12 / len(r)) - 1) * 100 if len(r) else float("nan")


def main(map_):
    ind = lees_blok(map_ + "/49_Industry_Portfolios.csv", "Average Value Weighted Returns -- Monthly")
    fac = lees_blok(map_ + "/F-F_Research_Data_Factors.csv", "Mkt-RF")
    markt = (fac["Mkt-RF"] + fac["RF"]).rename("markt")
    ind = ind[ind.index >= pd.Period(START, "M")]
    markt = markt.reindex(ind.index)

    print("Industrie-momentum, 49 Fama-French-industrieën, %s .. %s, kosten %.1f%% per kant"
          % (ind.index[0], ind.index[-1], KOSTEN * 100))
    print()
    print("%-36s %8s %9s %16s" % ("", "per jaar", "max daling", "slechtste jaar"))
    m_markt = maat(markt.dropna())
    print("%-36s %+7.1f%% %8.1f%% %9.1f%% (%d)" % ("markt (alle Amerikaanse aandelen)",
          m_markt["cagr"], m_markt["dd"], m_markt["slechtste"], m_markt["slechtste_jaar"]))
    gelijk = ind.mean(axis=1)
    m_g = maat(gelijk)
    print("%-36s %+7.1f%% %8.1f%% %9.1f%% (%d)" % ("49 industrieën gelijk gewogen",
          m_g["cagr"], m_g["dd"], m_g["slechtste"], m_g["slechtste_jaar"]))
    print("-" * 74)
    res = {}
    for terug in (6, 9, 12):
        for top in (3, 5, 10):
            for elke, lab in ((1, "mnd"), (3, "kw")):
                r = strategie(ind, terug, top, elke)
                m = maat(r)
                res[(terug, top, elke)] = (r, m)
                print("%-36s %+7.1f%% %8.1f%% %9.1f%% (%d)"
                      % ("top %2d, %2d mnd terug, per %s" % (top, terug, lab),
                         m["cagr"], m["dd"], m["slechtste"], m["slechtste_jaar"]))

    print()
    print("Per decennium (per jaar), hoofdvariant top 5 per kwartaal:")
    print("%-10s %8s %8s %8s %8s" % ("", "markt", "6 mnd", "9 mnd", "12 mnd"))
    wint = {6: 0, 9: 0, 12: 0}
    for lab, van, tot in DECENNIA:
        mk = cagr(markt, van, tot)
        regel = [mk]
        for terug in (6, 9, 12):
            c = cagr(res[(terug, 5, 3)][0], van, tot)
            regel.append(c)
            wint[terug] += c > mk
        print("%-10s %+7.1f%% %+7.1f%% %+7.1f%% %+7.1f%%" % (lab, *regel))

    print()
    print("OORDEEL (vooraf vastgelegd), hoofdvariant top 5 per kwartaal:")
    alle = True
    for terug in (6, 9, 12):
        m = res[(terug, 5, 3)][1]
        c1 = m["cagr"] >= m_markt["cagr"] + 1.5
        c2 = m["dd"] <= m_markt["dd"] + 5.0
        c3 = wint[terug] >= 4
        alle = alle and c1 and c2 and c3
        print("  %2d mnd: 1 >= markt+1,5pp %-3s (%+.1f%% vs %+.1f%%) | 2 daling %-3s (%.0f%% vs %.0f%%) | 3 decennia %d/6 %-3s"
              % (terug, "JA" if c1 else "NEE", m["cagr"], m_markt["cagr"], "JA" if c2 else "NEE",
                 m["dd"], m_markt["dd"], wint[terug], "JA" if c3 else "NEE"))
    print("  4 houdt stand voor 6, 9 en 12 maanden: %s" % ("JA" if alle else "NEE"))
    print("  => %s" % ("KANDIDAAT — door naar de vertaling naar koopbare ETF's" if alle
                       else "GEEN KANDIDAAT in deze vorm"))
    return 0


# ── Variant 2, VOORAF VASTGELEGD op 2026-09-21 ná de uitslag van variant 1 ─────────────
#
# Variant 1 haalde het rendement (9 en 12 mnd: +3,6 tot +5,9pp per jaar, 5 van 6 decennia)
# maar niet het risico (daling 56-62% tegen 50% voor de markt). Dit is GEEN herziening van
# variant 1 — die blijft "geen kandidaat" — maar één nieuwe hypothese met een bekende reden:
# momentum stort vooral in wanneer een dalende markt keert (Daniel & Moskowitz 2016,
# "Momentum crashes"). De standaardremedie is een trendfilter op de markt zelf.
#
# Instellingen gekozen UIT DE LITERATUUR, niet uit de tabel van variant 1:
#   - terugblik 12-1 maanden (de standaard), top 10 van 49 (het bovenste vijfde deel),
#     maandelijks herwegen;
#   - trendfilter: staat de markt onder haar 10-maandsgemiddelde, dan kas (T-bills, RF).
# Criteria (vooraf): rendement >= markt + 1,5pp; daling <= markt; >= 4 van 6 decennia beter.
# Eén run. Slaagt hij, dan is dat geen bewijs (de data is al gezien) maar een reden om hem
# vooruit te volgen in de schaduw (motor trede 2) met koopbare UCITS-ETF's.

def variant2(map_):
    ind = lees_blok(map_ + "/49_Industry_Portfolios.csv", "Average Value Weighted Returns -- Monthly")
    fac = lees_blok(map_ + "/F-F_Research_Data_Factors.csv", "Mkt-RF")
    markt = (fac["Mkt-RF"] + fac["RF"]).rename("markt")
    rf = fac["RF"]
    ind = ind[ind.index >= pd.Period(START, "M")]
    markt, rf = markt.reindex(ind.index), rf.reindex(ind.index)

    mom = strategie(ind, 12, 10, 1)
    niveau = (1 + markt.fillna(0)).cumprod()
    boven = (niveau > niveau.rolling(10).mean()).shift(1).fillna(False)   # causaal: vorige maand
    boven = boven.reindex(mom.index).fillna(False)
    rf_m = rf.reindex(mom.index).fillna(0)
    # Wissel naar kas en terug kost de omzet van de hele portefeuille.
    wissel = boven.astype(int).diff().abs().fillna(0) * KOSTEN
    uit = mom.where(boven, rf_m) - wissel

    mk = markt.reindex(uit.index)
    m_v, m_m = maat(uit), maat(mk)
    print()
    print("VARIANT 2 (vooraf vastgelegd): top 10, 12-1 mnd, maandelijks, trendfilter markt > 10-mnd-gem.")
    print("%-36s %+7.1f%% %8.1f%% %9.1f%% (%d)" % ("markt, zelfde venster", m_m["cagr"], m_m["dd"], m_m["slechtste"], m_m["slechtste_jaar"]))
    print("%-36s %+7.1f%% %8.1f%% %9.1f%% (%d)" % ("variant 2", m_v["cagr"], m_v["dd"], m_v["slechtste"], m_v["slechtste_jaar"]))
    print("  in de markt: %.0f%% van de maanden" % (boven.mean() * 100))
    wint = 0
    for lab, van, tot in DECENNIA:
        a, b = cagr(uit, van, tot), cagr(mk, van, tot)
        wint += a > b
        print("  %-10s variant %+6.1f%%  markt %+6.1f%%" % (lab, a, b))
    c1 = m_v["cagr"] >= m_m["cagr"] + 1.5
    c2 = m_v["dd"] <= m_m["dd"]
    c3 = wint >= 4
    print("  1 >= markt+1,5pp %s | 2 daling <= markt %s | 3 decennia %d/6 %s"
          % ("JA" if c1 else "NEE", "JA" if c2 else "NEE", wint, "JA" if c3 else "NEE"))
    print("  => %s" % ("GESLAAGD — naar de schaduw (trede 2), vooruit gevolgd met UCITS-ETF's"
                       if (c1 and c2 and c3) else "NIET GESLAAGD"))


if __name__ == "__main__":
    map_ = sys.argv[1] if len(sys.argv) > 1 else "."
    if "--variant2" in sys.argv:
        variant2(map_)
    else:
        sys.exit(main(map_))
