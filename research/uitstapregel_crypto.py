"""Papiertoets (motor trede 1): de uitstapregel op de kern-crypto (BTC, ETH).

    python research/uitstapregel_crypto.py

Waarom crypto eerst: het is het deel dat het systeem zelf kan uitvoeren (Hyperliquid, met
reduceOnly), terwijl de aandelen bij DeGiro alleen een signaal naar Bart kunnen worden.
Besluit Bart 21-09: stabiel groeien, met een in- en uitstaplaag per bezit.

DE REGEL: precies die van research/uitstapregel.py (Faber 2007) — maandslot onder het
10-maandsgemiddelde, dan de volgende maand in kas (USDC tegen de gerealiseerde Aave-rente,
voorzichtig op 2% per jaar gezet); erboven, dan in de munt. Niet afgesteld op crypto:
dezelfde regel voor elk bezit, anders zoek je een instelling die toevallig past.

VOORAF VASTGELEGD (21-09, vóór de run). Crypto-rendementen zijn zo groot dat een grens in
procentpunten niets zegt; het doel is stabiel groeien, dus de maat is rendement per eenheid
daling:
  1. diepste daling hooguit 60% van die van vasthouden
  2. rendement per jaar gedeeld door de diepste daling is hoger dan bij vasthouden
  3. 1 en 2 gelden voor BTC én voor ETH afzonderlijk
  4. 1 en 2 gelden ook in de tweede helft van de reeks (2021-2026), dus niet alleen door 2018
Kosten: 0,1% per wissel (HL-taker 0,045% plus slippage, ruim genomen).
"""

import sys

import pandas as pd
import yfinance as yf

KOSTEN = 0.001
KAS_RENTE = 0.02


def regel(koers_maand: pd.Series):
    r = koers_maand.pct_change().dropna()
    gem = koers_maand.rolling(10).mean()
    boven = (koers_maand > gem).shift(1).reindex(r.index)
    boven = boven.astype("boolean").fillna(True).astype(bool)
    kas = (1 + KAS_RENTE) ** (1 / 12) - 1
    wissel = boven.astype(int).diff().abs().fillna(0) * KOSTEN
    uit = r.where(boven, kas) - wissel
    start = gem.dropna().index[0]
    return r[r.index > start], uit[uit.index > start], boven[boven.index > start]


def maat(r):
    groei = (1 + r).cumprod()
    jaren = len(r) / 12
    dd = ((groei.cummax() - groei) / groei.cummax()).max() * 100
    cagr = (groei.iloc[-1] ** (1 / jaren) - 1) * 100
    per_jaar = (1 + r).groupby(r.index.year).prod() - 1
    return {"cagr": cagr, "dd": dd, "calmar": cagr / dd if dd else float("inf"),
            "slechtste": per_jaar.min() * 100, "slechtste_jaar": int(per_jaar.idxmin())}


def main():
    uitslag = {}
    for munt in ("BTC-USD", "ETH-USD"):
        d = yf.download(munt, start="2014-01-01", end="2026-09-01", auto_adjust=True,
                        progress=False)["Close"].squeeze().dropna()
        maand = d.resample("ME").last()
        hold, uit, boven = regel(maand)
        print("%s  %s .. %s  (in de munt %.0f%% van de maanden, %d wissels)"
              % (munt, hold.index[0].date(), hold.index[-1].date(), boven.mean() * 100,
                 int(boven.astype(int).diff().abs().sum())))
        for label, van in (("hele reeks", None), ("tweede helft 2021-2026", "2021-01-01")):
            h = hold if van is None else hold[hold.index >= van]
            u = uit if van is None else uit[uit.index >= van]
            mh, mu = maat(h), maat(u)
            uitslag[(munt, label)] = (mh, mu)
            print("  %-24s vasthouden %+7.1f%%/jaar  daling %4.1f%%  rend/daling %.2f  slechtste jaar %+6.1f%% (%d)"
                  % (label, mh["cagr"], mh["dd"], mh["calmar"], mh["slechtste"], mh["slechtste_jaar"]))
            print("  %-24s regel      %+7.1f%%/jaar  daling %4.1f%%  rend/daling %.2f  slechtste jaar %+6.1f%% (%d)"
                  % ("", mu["cagr"], mu["dd"], mu["calmar"], mu["slechtste"], mu["slechtste_jaar"]))
        print()

    print("OORDEEL (vooraf vastgelegd, doel = stabiel groeien):")
    ok_alles = True
    for munt in ("BTC-USD", "ETH-USD"):
        for label in ("hele reeks", "tweede helft 2021-2026"):
            mh, mu = uitslag[(munt, label)]
            c1 = mu["dd"] <= 0.60 * mh["dd"]
            c2 = mu["calmar"] > mh["calmar"]
            ok_alles = ok_alles and c1 and c2
            print("  %-8s %-24s 1 daling <= 60%% %-3s | 2 rendement/daling beter %-3s"
                  % (munt[:3], label, "JA" if c1 else "NEE", "JA" if c2 else "NEE"))
    print("  => %s" % ("GESLAAGD voor BTC en ETH (criteria 3 en 4 volgen uit bovenstaande) — naar ontwerp en schaduw"
                       if ok_alles else "NIET GESLAAGD"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
