"""Papiertoets (motor trede 1): een uitstapregel tegen crashes — "verkoop vóór de crash".

    python research/uitstapregel.py <map met F-F_Research_Data_Factors.csv>

HYPOTHESE (Bart, 21-09): "Crashes gaan er zeker komen en we moeten daarvoor uitstappen.
We moeten niet oneindig uitzitten." Vóór een crash verkopen kan niemand betrouwbaar; elk
signaal gaat af als de daling al loopt. De toetsbare vraag is daarom: haalt een simpele
uitstapregel een wezenlijk deel van de crashdiepte weg, zonder dat je er veel rendement
voor inlevert?

DE REGEL (niet door ons bedacht of afgesteld): het 10-maandsgemiddelde van Faber,
gepubliceerd in 2007 ("A Quantitative Approach to Tactical Asset Allocation"). Staat de
markt aan het eind van de maand onder haar 10-maandsgemiddelde, dan de volgende maand in
kas (T-bills); erboven, dan in de markt. Omdat de regel in 2007 is gepubliceerd, is
**2007-2026 een echte toets buiten de steekproef**: de regel kende die periode niet.

DATA: Kenneth French, Amerikaanse markt (alle aandelen) en T-bills, 1926-2026. Daarin
zitten 1929, 1937, 1973-74, 1987, 2000-02, 2008, 2020 en 2022.

VOORAF VASTGELEGD (21-09, vóór de run) — Barts doel is crashbescherming, niet meer rendement:
  1. diepste daling hooguit 60% van die van de markt
  2. rendement per jaar hooguit 1,5pp lager dan de markt
  3. beide gelden OOK in 2007-2026 (buiten de steekproef)
  4. het slechtste kalenderjaar is beter dan dat van de markt
Kosten: 0,1% per wissel (een ETF-order bij DeGiro, ruim genomen). Box 3 kent geen
belasting per transactie.
"""

import sys

import pandas as pd

sys.path.insert(0, ".")
from research.industrie_momentum import lees_blok  # noqa: E402

KOSTEN = 0.001
CRASHES = [("1929-1932 (Grote Depressie)", "1929-08", "1932-12"),
           ("1973-1974 (oliecrisis)", "1973-01", "1974-12"),
           ("1987 (Black Monday)", "1987-08", "1987-12"),
           ("2000-2002 (dotcom)", "2000-03", "2002-12"),
           ("2007-2009 (kredietcrisis)", "2007-10", "2009-03"),
           ("2020 (corona)", "2020-01", "2020-06"),
           ("2022 (rente)", "2022-01", "2022-12")]


def regel(markt: pd.Series, rf: pd.Series, venster: int = 10):
    """Maandrendement van de regel, plus de in/uit-reeks."""
    niveau = (1 + markt).cumprod()
    boven = (niveau > niveau.rolling(venster).mean()).shift(1)
    boven = boven.astype("boolean").fillna(True).astype(bool)
    wissel = boven.astype(int).diff().abs().fillna(0) * KOSTEN
    return markt.where(boven, rf) - wissel, boven


def maat(r):
    groei = (1 + r).cumprod()
    jaren = len(r) / 12
    dd = ((groei.cummax() - groei) / groei.cummax()).max() * 100
    per_jaar = (1 + r).groupby(r.index.year).prod() - 1
    return {"cagr": (groei.iloc[-1] ** (1 / jaren) - 1) * 100, "dd": dd,
            "slechtste": per_jaar.min() * 100, "slechtste_jaar": int(per_jaar.idxmin())}


def plak(r, van, tot):
    return r[(r.index >= pd.Period(van, "M")) & (r.index <= pd.Period(tot, "M"))]


def main(map_):
    fac = lees_blok(map_ + "/F-F_Research_Data_Factors.csv", "Mkt-RF")
    markt = (fac["Mkt-RF"] + fac["RF"]).dropna()
    rf = fac["RF"].reindex(markt.index)
    uit, boven = regel(markt, rf)
    uit, markt, boven = uit.iloc[10:], markt.iloc[10:], boven.iloc[10:]

    print("Uitstapregel (Faber 10-maandsgemiddelde), Amerikaanse markt %s .. %s" % (markt.index[0], markt.index[-1]))
    print("In de markt: %.0f%% van de maanden · %d wissels (%.1f per jaar)"
          % (boven.mean() * 100, int(boven.astype(int).diff().abs().sum()),
             boven.astype(int).diff().abs().sum() / (len(boven) / 12)))
    print()
    oordeel = {}
    for label, van, tot in (("hele periode 1927-2026", "1927-01", "2026-12"),
                            ("BUITEN de steekproef 2007-2026", "2007-01", "2026-12")):
        mm, mr = maat(plak(markt, van, tot)), maat(plak(uit, van, tot))
        oordeel[label] = (mm, mr)
        print("%s" % label)
        print("  %-10s %+6.1f%%/jaar  diepste daling %5.1f%%  slechtste jaar %+6.1f%% (%d)"
              % ("markt", mm["cagr"], mm["dd"], mm["slechtste"], mm["slechtste_jaar"]))
        print("  %-10s %+6.1f%%/jaar  diepste daling %5.1f%%  slechtste jaar %+6.1f%% (%d)"
              % ("regel", mr["cagr"], mr["dd"], mr["slechtste"], mr["slechtste_jaar"]))
        print()

    print("Per crash: diepste daling markt vs regel")
    for label, van, tot in CRASHES:
        m, r = plak(markt, van, tot), plak(uit, van, tot)
        def diepte(x):
            g = (1 + x).cumprod()
            return ((g.cummax() - g) / g.cummax()).max() * 100
        print("  %-30s markt %5.1f%%   regel %5.1f%%" % (label, diepte(m), diepte(r)))

    print()
    print("Waar de regel geld kost (jaren waarin de markt het minstens 10pp beter deed):")
    pm = (1 + markt).groupby(markt.index.year).prod() - 1
    pr = (1 + uit).groupby(uit.index.year).prod() - 1
    slecht = [(j, pm[j] * 100, pr[j] * 100) for j in pm.index if pm[j] - pr[j] >= 0.10]
    for j, a, b in slecht:
        print("  %d: markt %+6.1f%%  regel %+6.1f%%" % (j, a, b))

    mm, mr = oordeel["hele periode 1927-2026"]
    om, orr = oordeel["BUITEN de steekproef 2007-2026"]
    c1 = mr["dd"] <= 0.60 * mm["dd"]
    c2 = mr["cagr"] >= mm["cagr"] - 1.5
    c3 = orr["dd"] <= 0.60 * om["dd"] and orr["cagr"] >= om["cagr"] - 1.5
    c4 = mr["slechtste"] > mm["slechtste"]
    print()
    print("OORDEEL (vooraf vastgelegd, doel = crashbescherming):")
    for naam, ok in (("1 diepste daling <= 60% van de markt", c1),
                     ("2 rendement hooguit 1,5pp lager", c2),
                     ("3 beide ook in 2007-2026 (buiten de steekproef)", c3),
                     ("4 slechtste jaar beter dan de markt", c4)):
        print("  %-48s %s" % (naam, "JA" if ok else "NEE"))
    print("  => %s" % ("GESLAAGD — naar de schaduw (trede 2) op WEBN in euro's" if all((c1, c2, c3, c4))
                       else "NIET GESLAAGD"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
