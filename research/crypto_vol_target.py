"""Papiertoets (motor trede 1): volatility targeting op de kern-crypto (BTC, ETH).

    python research/crypto_vol_target.py

Idee `crypto_vol_target` (register, 21-09): de uitstapregel (10-maandsgemiddelde) werkte op
crypto niet, maar volatility targeting verkleinde op aandelen het risico wel
(research/risicopotjes.py). Ander mechanisme: niet uitstappen op de richting, maar kleiner
zitten als de koers wild beweegt. Automatiseerbaar op Hyperliquid (spot UBTC/UETH, dus geen
funding; afbouwen met reduceOnly).

DE REGEL (niet afgesteld, zoals vooraf in het register beschreven):
- belegd deel = min(1, doelvol / gerealiseerde vol van de voorbije 63 dagen)
- doelvol = de MEDIAAN van de eigen 63-dagen-vol tot en met dat moment (uitdijend venster,
  dus zonder vooruitkijken); pas na 12 maanden vol-historie
- maandelijks bepaald op het slot, toegepast op de VOLGENDE maand; rest in USDC tegen 2%
- kosten 0,1% over het verschil in belegd deel

VOORAF VASTGELEGD (22-09, vóór de run). Per munt (BTC, ETH) en per helft (tot en met 2020 /
vanaf 2021):
  1. diepste daling lager dan vasthouden
  2. rendement per eenheid daling minstens gelijk aan vasthouden
  3. rendement per eenheid daling hoger dan een VASTE MIX met dezelfde gemiddelde blootstelling
     (les van de audit van 21-09: anders is 'minder daling' alleen 'minder belegd')
Alle drie, voor beide munten, in beide helften -> naar de schaduw.
"""

import sys

import pandas as pd
import yfinance as yf

KAS = 0.02
KOSTEN = 0.001
VENSTER = 63
MIN_MAANDEN = 12
HELFT = "2021-01"


def dagkoersen(t):
    d = yf.download(t, start="2014-01-01", end="2026-09-01", auto_adjust=True,
                    progress=False)["Close"].squeeze().dropna()
    return d[~d.index.duplicated()]


def reeksen(d):
    dag = d.pct_change().dropna()
    vol = (dag.rolling(VENSTER).std() * (365 ** 0.5)).dropna()     # crypto handelt elke dag
    vol_m = vol.resample("ME").last()
    doel = vol_m.expanding(min_periods=MIN_MAANDEN).median()          # alleen verleden
    deel = (doel / vol_m).clip(upper=1.0).shift(1)                   # stand eind t -> maand t+1
    r = d.resample("ME").last().pct_change()
    kas = (1 + KAS) ** (1 / 12) - 1
    df = pd.DataFrame({"r": r, "deel": deel}).dropna()
    kosten = df["deel"].diff().abs().fillna(0) * KOSTEN
    vt = df["deel"] * df["r"] + (1 - df["deel"]) * kas - kosten
    e = df["deel"].mean()
    return df["r"], vt, df["deel"], kas


def maat(r):
    g = (1 + r).cumprod()
    jaren = len(r) / 12
    dd = ((g.cummax() - g) / g.cummax()).max() * 100
    cagr = (g.iloc[-1] ** (1 / jaren) - 1) * 100
    return {"cagr": cagr, "dd": dd, "rd": cagr / dd if dd else float("inf")}


def main():
    ok_alles = True
    for munt in ("BTC-USD", "ETH-USD"):
        r, vt, deel, kas = reeksen(dagkoersen(munt))
        print("%s  %s .. %s  gemiddeld belegd %.0f%%" % (munt, r.index[0].date(), r.index[-1].date(), deel.mean() * 100))
        for label, masker in (("t/m 2020", r.index < HELFT), ("vanaf 2021", r.index >= HELFT)):
            rr, vv, dd_ = r[masker], vt[masker], deel[masker]
            if len(rr) < 12:
                print("  %-11s te kort (%d maanden)" % (label, len(rr)))
                ok_alles = False
                continue
            e = dd_.mean()
            mix = e * rr + (1 - e) * kas
            mh, mv, mm = maat(rr), maat(vv), maat(mix)
            c1, c2, c3 = mv["dd"] < mh["dd"], mv["rd"] >= mh["rd"], mv["rd"] > mm["rd"]
            ok_alles = ok_alles and c1 and c2 and c3
            print("  %-11s vasthouden %+6.1f%%/jaar daling %4.1f%% rd %.2f | vol-target %+6.1f%%/jaar daling %4.1f%% rd %.2f"
                  " | mix %.0f%% %+6.1f%%/jaar daling %4.1f%% rd %.2f   [1 %s 2 %s 3 %s]"
                  % (label, mh["cagr"], mh["dd"], mh["rd"], mv["cagr"], mv["dd"], mv["rd"],
                     e * 100, mm["cagr"], mm["dd"], mm["rd"],
                     "JA" if c1 else "NEE", "JA" if c2 else "NEE", "JA" if c3 else "NEE"))
        print()
    print("OORDEEL (vooraf vastgelegd): %s" % ("GESLAAGD — naar de schaduw" if ok_alles else "NIET GESLAAGD"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
