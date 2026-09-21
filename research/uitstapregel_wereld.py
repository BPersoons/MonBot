"""Papiertoets (motor trede 1), tweede dataset: de uitstapregel buiten de VS.

    python research/uitstapregel_wereld.py <map met de French-CSV's>

Waarom: de eerste toets (research/uitstapregel.py) gebruikte de Amerikaanse markt, precies
de markt waarop Faber de regel vond. Een regel die alleen daar werkt, is een toevalstreffer.
Bart koos 21-09 voor stabiel groeien (docs/besluiten.md); het wereldindexfonds (WEBN) is
voor ~60% Amerika en voor de rest vooral Europa en Japan.

DE REGEL: ongewijzigd — maandslot onder het 10-maandsgemiddelde, dan de volgende maand in
kas (T-bills); erboven, dan in de markt. Hergebruikt `regel` en `maat` uit uitstapregel.py.

DATA: Kenneth French, Developed ex US en Europe (1990-2026, in dollars), met de
Amerikaanse T-bill als kas. Developed (incl. de VS) staat erbij ter informatie. Het fonds
in euro's (IWDA.AS, MSCI World, 2009-2026) staat er ook bij, ALLEEN ter informatie: 16
jaar zonder trage bear in euro's is te kort om crashbescherming te beoordelen; het laat de
kosten zien.

VOORAF VASTGELEGD (21-09, vóór de run), dezelfde maat als bij crypto — doel stabiel groeien:
  1. diepste daling hooguit 60% van die van vasthouden
  2. rendement per jaar gedeeld door de diepste daling is hoger dan bij vasthouden
  3. 1 en 2 gelden voor Developed ex US 1991-2026 én voor Europa 1991-2026
  4. 1 en 2 gelden ook voor Developed ex US in 2007-2026 (na de publicatie)
Kosten: 0,1% per wissel.
"""

import sys

import pandas as pd

sys.path.insert(0, ".")
from research.industrie_momentum import lees_blok  # noqa: E402
from research.uitstapregel import maat, plak, regel  # noqa: E402


def reeks(pad):
    fac = lees_blok(pad, "Mkt-RF")
    markt = (fac["Mkt-RF"] + fac["RF"]).dropna()
    rf = fac["RF"].reindex(markt.index)
    uit, boven = regel(markt, rf)
    return markt.iloc[10:], uit.iloc[10:], boven.iloc[10:]


def regel_uit(label, m, u):
    mm, mu = maat(m), maat(u)
    for naam, x in (("vasthouden", mm), ("regel", mu)):
        x["rd"] = x["cagr"] / x["dd"]
        print("  %-22s %-10s %+6.1f%%/jaar  daling %5.1f%%  rend/daling %.2f  slechtste jaar %+6.1f%% (%d)"
              % (label if naam == "vasthouden" else "", naam, x["cagr"], x["dd"], x["rd"],
                 x["slechtste"], x["slechtste_jaar"]))
        label = ""
    return mu["dd"] <= 0.60 * mm["dd"], mu["rd"] > mm["rd"]


def main(map_):
    uitslag = {}
    for naam, bestand in (("Developed ex US", "Developed_ex_US_3_Factors.csv"),
                          ("Europa", "Europe_3_Factors.csv"),
                          ("Developed (info)", "Developed_3_Factors.csv")):
        m, u, b = reeks(map_ + "/" + bestand)
        print("%s  %s .. %s  (in de markt %.0f%%, %d wissels)"
              % (naam, m.index[0], m.index[-1], b.mean() * 100, int(b.astype(int).diff().abs().sum())))
        uitslag[(naam, "heel")] = regel_uit("hele reeks", m, u)
        uitslag[(naam, "2007")] = regel_uit("2007-2026", plak(m, "2007-01", "2026-12"), plak(u, "2007-01", "2026-12"))
        print()

    try:
        import yfinance as yf
        d = yf.download("IWDA.AS", start="2009-01-01", end="2026-09-01", auto_adjust=True,
                        progress=False)["Close"].squeeze().dropna()
        maand = d.resample("ME").last()
        m = maand.pct_change().dropna()
        m.index = m.index.to_period("M")
        rf = pd.Series(0.015 / 12, index=m.index)  # euro-kas, grof; alleen ter informatie
        u, b = regel(m, rf)
        m, u, b = m.iloc[10:], u.iloc[10:], b.iloc[10:]
        print("MSCI World in euro's, IWDA.AS  %s .. %s  (ALLEEN INFORMATIE)" % (m.index[0], m.index[-1]))
        regel_uit("fonds in euro's", m, u)
        print()
    except Exception as exc:  # informatief; mag de toets niet breken
        print("IWDA.AS niet op te halen: %s" % exc)

    print("OORDEEL (vooraf vastgelegd, doel = stabiel groeien):")
    eisen = [("Developed ex US", "heel"), ("Europa", "heel"), ("Developed ex US", "2007")]
    ok = True
    for naam, periode in eisen:
        c1, c2 = uitslag[(naam, periode)]
        ok = ok and c1 and c2
        print("  %-16s %-5s 1 daling <= 60%% %-3s | 2 rendement/daling beter %-3s"
              % (naam, periode, "JA" if c1 else "NEE", "JA" if c2 else "NEE"))
    print("  => %s" % ("GESLAAGD op de vooraf vastgelegde criteria" if ok else "NIET GESLAAGD"))
    na_de_audit(map_)
    return 0


def na_de_audit(map_):
    """Toegevoegd NA de audit van 21-09; verandert het vooraf vastgelegde oordeel niet, maar
    zegt wat het waard is. Twee vragen die de criteria niet stelden:
    1. Tegen een VASTE MIX met dezelfde gemiddelde blootstelling (markt x e + kas x (1-e)):
       100% vasthouden is de verkeerde maatstaf voor een regel die 70-80% belegd is.
    2. ZONDER 2008 (2010-2026): Faber gebruikte EAFE 1973-2005 al, dus buiten de VS is pas
       2007+ nieuw, en daarin beslist 2008."""
    print()
    print("NA DE AUDIT (informatie): regel tegen een vaste mix met dezelfde blootstelling")
    for naam, bestand in (("VS", "F-F_Research_Data_Factors.csv"),
                          ("Developed ex US", "Developed_ex_US_3_Factors.csv"),
                          ("Europa", "Europe_3_Factors.csv"),
                          ("Developed", "Developed_3_Factors.csv")):
        m, u, b = reeks(map_ + "/" + bestand)
        rf = lees_blok(map_ + "/" + bestand, "Mkt-RF")["RF"].reindex(m.index)
        for van in ("2007-01", "2010-01"):
            mm, uu, rr = (plak(x, van, "2026-12") for x in (m, u, rf))
            e = plak(b.astype(float), van, "2026-12").mean()
            mix = e * mm + (1 - e) * rr
            r, x = maat(uu), maat(mix)
            print("  %-16s %s  belegd %.0f%%  regel %+5.1f%%/jaar daling %4.1f%% | mix %+5.1f%%/jaar daling %4.1f%%"
                  % (naam, van, e * 100, r["cagr"], r["dd"], x["cagr"], x["dd"]))
    print("  => Met 2008 verlaagt de regel de diepste daling met een kwart tot ruim de helft, ook")
    print("     tegen de mix. Zonder zo'n trage crash (2010-2026) wint de mix: meer rendement bij een")
    print("     ongeveer gelijke daling. De regel is een verzekering tegen trage, diepe dalingen,")
    print("     geen beter beleggen. In euro's (IWDA 2010-2026) haalt hij criterium 1 niet (x0,65).")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
