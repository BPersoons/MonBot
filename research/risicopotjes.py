"""Papiertoets (motor trede 1): risicopotjes — meer rendement voor meer risico, klein gehouden.

    python research/risicopotjes.py

Besluit Bart 21-09: "Meer risico is prima, we kunnen spreiden. We moeten kijken hoe we het
risico kunnen verkleinen. Stabiele groei is het doel, maar met kleinere delen van de
portefeuille kunnen we meer risico nemen." Dus geen jacht op gratis extra rendement (dat
vonden we vijf keer niet), maar bekende RISICOPREMIES in een klein potje, met risicobeheer
waarvan bekend is dat het werkt.

KANDIDATEN (koopbaar bij DeGiro, UCITS, in euro's):
- IS3R.DE  iShares MSCI World Momentum    — momentumpremie (onze industrietoets: +4-6pp/jaar
                                            over 62 jaar, met diepere dalingen)
- EQQQ.DE  Invesco Nasdaq-100             — geconcentreerde tech/groei
- ZPRV.DE  SPDR MSCI USA Small Cap Value  — small/value-premie
KERN: IWDA.AS (MSCI World in euro's, de langste reeks die op WEBN lijkt).

RISICOBEHEER — volatility targeting (Moreira & Muir 2017; voor momentum Barroso & Santa-Clara
2015): belegd deel = min(1, doelvol / gerealiseerde vol van de voorbije 63 handelsdagen), de
rest in kas (1,5% per jaar). Doelvol = de vol van de kern over de hele periode. Maandelijks,
toegepast op de VOLGENDE maand. Niet afgesteld: één doel, één venster.

VENSTER: 2015-03 .. 2026-08 (gemeenschappelijk). WAARSCHUWING vooraf: dit is een uitzonderlijk
goed venster voor Amerikaanse tech; een Nasdaq-uitslag zegt hier weinig over de toekomst
(Nasdaq 2000-2015: -83% en 15 jaar onder water). Een geslaagd potje gaat naar de schaduw,
niet naar geld.

VOORAF VASTGELEGD (21-09, vóór de run):
Een risicopotje is de moeite waard als
  1. rendement per jaar >= kern + 2pp (anders is het extra risico niet de moeite)
  2. diepste daling <= 1,5 x die van de kern (een verlies dat een klein potje kan dragen)
  3. 1 en 2 gelden ook in de tweede helft, 2021-2026
Volatility targeting telt als risicoverkleining als, in BEIDE helften, de diepste daling lager
is dan zonder EN het rendement per eenheid daling hoger.
Kosten: 0,1% per aanpassing van het belegde deel (alleen het verschil).
"""

import sys

import pandas as pd
import yfinance as yf

KERN = "IWDA.AS"
KANDIDATEN = {"IS3R.DE": "momentum", "EQQQ.DE": "Nasdaq-100", "ZPRV.DE": "small cap value"}
KAS = 0.015
KOSTEN = 0.001
VENSTER_VOL = 63
VAN, TOT, HELFT = "2015-03", "2026-08", "2021-01"


def dagkoersen(t):
    d = yf.download(t, start="2014-06-01", end="2026-09-01", auto_adjust=True,
                    progress=False)["Close"].squeeze().dropna()
    return d[~d.index.duplicated()]


def maandreeks(d):
    m = d.resample("ME").last().pct_change().dropna()
    m.index = m.index.to_period("M")
    return m


def vol_getarget(d, doelvol):
    """Maandrendement met belegd deel = min(1, doelvol / vol voorbije 63 dagen), vooraf bepaald."""
    dag = d.pct_change().dropna()
    vol = dag.rolling(VENSTER_VOL).std() * (252 ** 0.5)
    vol_eind = vol.resample("ME").last()
    vol_eind.index = vol_eind.index.to_period("M")
    deel = (doelvol / vol_eind).clip(upper=1.0).shift(1)      # stand eind maand t -> maand t+1
    m = maandreeks(d)
    deel = deel.reindex(m.index)
    kas = (1 + KAS) ** (1 / 12) - 1
    kosten = deel.diff().abs().fillna(0) * KOSTEN
    return (deel * m + (1 - deel) * kas - kosten).dropna(), deel


def maat(r):
    g = (1 + r).cumprod()
    jaren = len(r) / 12
    dd = ((g.cummax() - g) / g.cummax()).max() * 100
    cagr = (g.iloc[-1] ** (1 / jaren) - 1) * 100
    return {"cagr": cagr, "dd": dd, "rd": cagr / dd if dd else float("inf")}


def plak(r, van, tot):
    return r[(r.index >= pd.Period(van, "M")) & (r.index <= pd.Period(tot, "M"))]


def main():
    kern_d = dagkoersen(KERN)
    kern = maandreeks(kern_d)
    doelvol = float(plak(kern, VAN, TOT).std() * (12 ** 0.5))
    print("Kern %s, doelvol %.1f%% per jaar (vol van de kern)" % (KERN, doelvol * 100))
    perioden = (("heel", VAN, TOT), ("2e helft", HELFT, TOT))
    km = {p: maat(plak(kern, a, b)) for p, a, b in perioden}
    for p, _, _ in perioden:
        print("  kern %-8s %+5.1f%%/jaar  daling %4.1f%%  rend/daling %.2f"
              % (p, km[p]["cagr"], km[p]["dd"], km[p]["rd"]))
    print()
    oordeel = {}
    for t, naam in KANDIDATEN.items():
        d = dagkoersen(t)
        ruw = maandreeks(d)
        vt, deel = vol_getarget(d, doelvol)
        print("%s (%s)  gemiddeld belegd met vol-target: %.0f%%" % (t, naam, plak(deel, VAN, TOT).mean() * 100))
        oordeel[t] = {}
        for p, a, b in perioden:
            mr, mv = maat(plak(ruw, a, b)), maat(plak(vt, a, b))
            oordeel[t][p] = (mr, mv)
            print("  %-8s ruw  %+5.1f%%/jaar daling %4.1f%% rd %.2f | vol-target %+5.1f%%/jaar daling %4.1f%% rd %.2f"
                  % (p, mr["cagr"], mr["dd"], mr["rd"], mv["cagr"], mv["dd"], mv["rd"]))
        print()

    print("OORDEEL (vooraf vastgelegd):")
    for t, naam in KANDIDATEN.items():
        for variant, i in (("ruw", 0), ("vol-target", 1)):
            ok = all(oordeel[t][p][i]["cagr"] >= km[p]["cagr"] + 2.0
                     and oordeel[t][p][i]["dd"] <= 1.5 * km[p]["dd"] for p, _, _ in perioden)
            print("  %-16s %-10s risicopotje de moeite waard: %s" % (naam, variant, "JA" if ok else "NEE"))
        verkleint = all(oordeel[t][p][1]["dd"] < oordeel[t][p][0]["dd"]
                        and oordeel[t][p][1]["rd"] > oordeel[t][p][0]["rd"] for p, _, _ in perioden)
        print("  %-16s vol-target verkleint het risico: %s" % (naam, "JA" if verkleint else "NEE"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
