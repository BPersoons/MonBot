"""Papiertoets (motor trede 1), derde bezitsklasse: de uitstapregel op een thema.

    python research/uitstapregel_thema.py <map met de French-CSV's>

Waarom: het tweede broker-slot (GRID, stroom en net) is een themafonds, geen brede index.
De regel slaagde op brede markten (VS, buiten de VS, Europa) en zakte door op crypto. Een
thema zit daartussen: smaller en beweeglijker dan de index. De regel mag pas een signaal
voor GRID geven als hij ook op smalle stukken van de markt werkt.

DE REGEL: ongewijzigd (10-maandsgemiddelde, kas = T-bills, 0,1% per wissel), per industrie.

DATA: Kenneth French, 49 industrieën (waardegewogen), 1926-2026. GRID lijkt het meest op
'ElcEq' (elektrische apparatuur) en 'Util' (nutsbedrijven); die staan erbij ter informatie,
maar het oordeel gaat over alle industrieën, anders kies je achteraf de gunstige.

VOORAF VASTGELEGD (21-09, vóór de run), dezelfde maat als bij de andere klassen:
  1. per industrie: diepste daling hooguit 60% van die van vasthouden
  2. per industrie: rendement per jaar gedeeld door de diepste daling hoger dan vasthouden
  3. 1 én 2 gelden voor minstens 2/3 van de industrieën met volledige reeks, 1927-2026
  4. 1 én 2 gelden voor minstens 2/3 van de industrieën in 2007-2026 (na de publicatie)
"""

import sys

sys.path.insert(0, ".")
from research.industrie_momentum import lees_blok  # noqa: E402
from research.uitstapregel import maat, plak, regel  # noqa: E402


def beoordeel(m, u):
    mm, mu = maat(m), maat(u)
    rd_m, rd_u = mm["cagr"] / mm["dd"], mu["cagr"] / mu["dd"]
    return (mu["dd"] <= 0.60 * mm["dd"] and rd_u > rd_m), mm, mu


def main(map_):
    ind = lees_blok(map_ + "/49_Industry_Portfolios.csv", "Average Value Weighted Returns -- Monthly")
    fac = lees_blok(map_ + "/F-F_Research_Data_Factors.csv", "Mkt-RF")
    rf = fac["RF"]
    volledig = [c for c in ind.columns if ind[c].loc[:"1927-12"].notna().all()]
    print("49 industrieën, %d met een volledige reeks vanaf 1926" % len(volledig))

    telling = {"heel": [0, 0], "2007": [0, 0]}
    uitkomst = {}
    for c in ind.columns:
        r = ind[c].dropna()
        u, _ = regel(r, rf.reindex(r.index).fillna(0.0))
        r, u = r.iloc[10:], u.iloc[10:]
        for periode, van in (("heel", "1927-01"), ("2007", "2007-01")):
            if periode == "heel" and c not in volledig:
                continue
            ok, mm, mu = beoordeel(plak(r, van, "2026-12"), plak(u, van, "2026-12"))
            telling[periode][0] += ok
            telling[periode][1] += 1
            uitkomst[(c, periode)] = (ok, mm, mu)

    for c in ("ElcEq", "Util"):
        for periode in ("heel", "2007"):
            if (c, periode) not in uitkomst:
                continue
            ok, mm, mu = uitkomst[(c, periode)]
            print("  %-6s %-5s vasthouden %+5.1f%%/jaar daling %4.1f%% | regel %+5.1f%%/jaar daling %4.1f%%  %s"
                  % (c, periode, mm["cagr"], mm["dd"], mu["cagr"], mu["dd"], "JA" if ok else "NEE"))

    mediaan = {}
    for periode in ("heel", "2007"):
        rijen = [v for (c, p), v in uitkomst.items() if p == periode]
        kost = sorted(v[2]["cagr"] - v[1]["cagr"] for v in rijen)
        dd = sorted(v[2]["dd"] / v[1]["dd"] for v in rijen)
        mediaan[periode] = (kost[len(kost) // 2], dd[len(dd) // 2])
    print()
    for periode, label in (("heel", "1927-2026"), ("2007", "2007-2026")):
        ja, n = telling[periode]
        print("  %s: %d van %d industrieën voldoen aan 1 en 2  (mediaan: rendement %+.1fpp, daling x%.2f)"
              % (label, ja, n, mediaan[periode][0], mediaan[periode][1]))

    c3 = telling["heel"][0] >= 2 / 3 * telling["heel"][1]
    c4 = telling["2007"][0] >= 2 / 3 * telling["2007"][1]
    print()
    print("OORDEEL (vooraf vastgelegd): 3 %s | 4 %s  => %s"
          % ("JA" if c3 else "NEE", "JA" if c4 else "NEE",
             "GESLAAGD — het signaal mag ook voor GRID" if c3 and c4 else "NIET GESLAAGD — geen signaal voor GRID"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
