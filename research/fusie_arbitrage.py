"""Fusie-arbitrage op papier (idee 12-10, papierstap werkronde 10-11).

Vraag: levert de premie op aangekondigde overnames, zoals professionele fondsen hem na kosten
oogsten, genoeg boven kasrente, en wat blijft daarvan over op onze omvang bij DeGiro?

Criteria VOORAF vastgelegd (10-11, voor de eerste run):
  A. Fonds-exces boven kas (BIL) >= 2,0 pp/jaar in BEIDE helften (lat: Aave + 2pp; Aave ~ kas).
  B. Beta tegen de markt (SPY) in maanden dat SPY > 5% daalt: gemeld, geen drempel.
  C. Op onze omvang, na DeGiro-kosten: brutopremie (fonds-exces + fondskosten) minus onze kosten
     per deal x deals per jaar, op $500 (proeftuin) en op $5.000 (hele veilige potje als
     bovengrens), >= 2,0 pp/jaar boven kas.
Door naar trede 2 alleen als A en C (op $500) allebei gehaald zijn; anders stoppen.

Maandrendementen (regel 8: geen dagkoersen voor beta), dividend herbelegd (auto_adjust).
MERFX = The Merger Fund (sinds 1989), ARBFX = The Arbitrage Fund (sinds 2000),
MNA = IQ Merger Arbitrage ETF (sinds 2009); de meetperiode begint in 2007 door kasreeks BIL. Deze fondsen zijn zelf niet koopbaar voor een
EU-particulier (PRIIPs); ze dienen als meting van de premie na professionele uitvoering.

    python research/fusie_arbitrage.py
"""
import json
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

FONDSKOSTEN = {"MERFX": 1.5, "ARBFX": 1.7, "MNA": 0.77}  # expense ratio incl. shortkosten, ruw (%/jr)
LAT_PP = 2.0
DEALS_PER_POS_PER_JAAR = 3.0     # cash-deals lopen gemiddeld ~4 maanden
DEGIRO_EUR = 2.0                 # aankoop VS-aandeel; uitbetaling bij afronding zonder order
AUTOFX = 0.0025                  # heen en terug, zoals research/aandelen_basis.py
EURUSD = 1.15


def maand(tk, start):
    """Maandrendementen uit de Yahoo-chart-API, met dividend herbelegd (adjclose)."""
    p1 = int(pd.Timestamp(start, tz="UTC").timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}?period1={p1}&period2={int(time.time())}"
           "&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    res = json.load(urllib.request.urlopen(req, timeout=30))["chart"]["result"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    d = pd.Series(adj, index=pd.to_datetime(res["timestamp"], unit="s"), dtype=float).dropna()
    return d.resample("ME").last().pct_change().dropna()


def ann(r):
    return (1 + r).prod() ** (12 / len(r)) - 1


def dd(r):
    c = (1 + r).cumprod()
    return (c / c.cummax() - 1).min()


def meting(tk, start):
    r, m, f = maand(tk, start), maand("SPY", start), maand("BIL", "2007-06-01")
    df = pd.concat([r, m, f], axis=1, join="inner").dropna()
    df.columns = ["p", "m", "f"]
    ep, em = df.p - df.f, df.m - df.f
    beta = np.cov(ep, em)[0, 1] / em.var()
    h = len(df) // 2
    d1, d2 = df.iloc[:h], df.iloc[h:]
    x1, x2 = (ann(d1.p) - ann(d1.f)) * 100, (ann(d2.p) - ann(d2.f)) * 100
    crash = df[df.m < -0.05]
    bc = np.polyfit(crash.m, crash.p, 1)[0] if len(crash) >= 3 else float("nan")
    print(f"{tk}: {df.index[0]:%Y-%m}..{df.index[-1]:%Y-%m} n={len(df)}")
    print(f"  rendement {ann(df.p):6.2%}/jr, kas {ann(df.f):5.2%}/jr, exces {(ann(df.p)-ann(df.f))*100:+.2f} pp, "
          f"daling {dd(df.p):6.1%} (markt {dd(df.m):6.1%}), vol {df.p.std()*12**.5:5.1%}, beta {beta:4.2f}")
    print(f"  1e helft {d1.index[0]:%Y-%m}..{d1.index[-1]:%Y-%m}: exces {x1:+.2f} pp | "
          f"2e helft {d2.index[0]:%Y-%m}..{d2.index[-1]:%Y-%m}: exces {x2:+.2f} pp")
    print(f"  beta in {len(crash)} maanden met markt < -5%: {bc:.2f}; slechtste maand {df.p.min():.1%}")
    return {"tk": tk, "x": (ann(df.p) - ann(df.f)) * 100, "x1": x1, "x2": x2, "beta": beta}


def op_onze_omvang(bruto_pp, totaal_usd, deals_tegelijk):
    per_deal = totaal_usd / deals_tegelijk
    kosten_per_deal = DEGIRO_EUR * EURUSD / per_deal + 2 * AUTOFX
    return bruto_pp - kosten_per_deal * DEALS_PER_POS_PER_JAAR * 100


uit = []
for tk, start in (("MERFX", "1996-01-01"), ("ARBFX", "2000-10-01"), ("MNA", "2009-12-01")):
    try:
        uit.append(meting(tk, start))
    except Exception as e:
        print(f"{tk}: ONMEETBAAR ({type(e).__name__}: {e})")

print()
print(f"Criterium A: exces >= {LAT_PP} pp in beide helften")
a = bool(uit)
for u in uit:
    ok = u["x1"] >= LAT_PP and u["x2"] >= LAT_PP
    a = a and ok
    print(f"  {u['tk']}: {u['x1']:+.2f} / {u['x2']:+.2f} pp -> {'gehaald' if ok else 'NIET gehaald'}")

print()
print("Criterium C: brutopremie (exces + fondskosten) minus onze kosten, pp/jaar boven kas")
c500 = bool(uit)
for u in uit:
    bruto = u["x"] + FONDSKOSTEN[u["tk"]]
    r = [(t, n, op_onze_omvang(bruto, t, n)) for t, n in ((500, 5), (500, 10), (5000, 5), (5000, 10), (5000, 20))]
    print(f"  {u['tk']}: bruto {bruto:.2f} pp -> " + ", ".join(f"${t}/{n} deals {v:+.2f}" for t, n, v in r))
    c500 = c500 and max(v for t, _, v in r if t == 500) >= LAT_PP

print()
print(f"UITKOMST: A {'gehaald' if a else 'NIET gehaald'}, C op $500 {'gehaald' if c500 else 'NIET gehaald'} -> "
      f"{'door naar schaduw' if a and c500 else 'STOPPEN'}")
