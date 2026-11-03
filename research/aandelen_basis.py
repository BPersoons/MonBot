"""Aandelen-basis (idee 12-10, papier 03-11): het echte aandeel long bij DeGiro, dezelfde
xyz-perp short op Hyperliquid, en de funding innen die de longs op xyz betalen.

Papierstap 1, 2 en 4 uit config/experimenten.json > basis_aandelen_degiro:
  (1) fundinghistorie per naam sinds notering, per maand, met de slechtste hele maand;
  (2) netto op KAPITAAL: aandeel 100% + perp-marge (hefboom 1x = marge 100%, 2x = 50%),
      min een rondgang aan kosten (DeGiro 2 x EUR 2, AutoFX 2 x 0,25%, perp 2 x 0,045%),
      een jaar aangehouden; dividend op de long niet meegeteld (klein, conservatief);
  (4) margerisico: de grootste stijging binnen 3 en 12 maanden sinds 2010 (dagslot, Yahoo).
      De short liquideert grofweg bij +90% (1x) of +45% (2x) zonder bijstorten.
Lat: Aave 90 dagen (kpi.json) + 2pp, besluit 12-10.

Uitkomst 03-11 (xyz sinds 11-2025/06-2026, alleen een stijgende markt): funding 6,6-10,7%/jr
op de positie (AAPL 2,2%), 83-91% van de uren positief, TSM april -19%. Op kapitaal bij 1x:
hooguit de lat (AVGO/GOOGL 5,0% op $5.000, lat 4,95%), en ook 1x overleeft de grootste
3-maandsstijging niet (TSLA 218%, NVDA 113%, ORCL 103%, AVGO 92%, BABA 90%). Bij 2x halen zes
van de tien de lat (5,1-6,7% op $5.000), maar de short liquideert dan rond +45%. De hedge staat
op twee rekeningen: bij een stijging staat de winst bij DeGiro en het verlies bij HL. Zonder geld
uit DeGiro moet de aanvulling uit Aave komen, en een stijging als NVDA (+375% in 12 maanden)
vraagt een reserve groter dan de positie zelf; met die reserve als kapitaal zakt het onder de
lat. Gestopt in deze vorm.

    python research/aandelen_basis.py [--aave 2.95]
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import funding_historie as fh  # noqa: E402

NAMEN = {"xyz:ORCL": "ORCL", "xyz:AVGO": "AVGO", "xyz:BABA": "BABA", "xyz:NVDA": "NVDA",
         "xyz:TSM": "TSM", "xyz:GOLD": "GC=F", "xyz:TSLA": "TSLA", "xyz:GOOGL": "GOOGL",
         "xyz:MSFT": "MSFT", "xyz:AAPL": "AAPL"}
EUR_USD = 1.08
DEGIRO_ORDER_EUR = 2.0
AUTOFX = 0.0025
PERP_TAKER = 0.00045


def dagsloten(ticker):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s?period1=1262304000&period2=%d"
           "&interval=1d" % (ticker.replace("=", "%3D"), int(time.time())))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    res = json.load(urllib.request.urlopen(req, timeout=30))["chart"]["result"][0]
    reeks = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") \
        or res["indicators"]["quote"][0]["close"]
    return [x for x in reeks if x]


def grootste_stijging_pct(p, n):
    """Grootste stijging van een dal naar een later slot binnen n handelsdagen."""
    best, dq = 0.0, deque()
    for i, x in enumerate(p):
        while dq and p[dq[-1]] >= x:
            dq.pop()
        dq.append(i)
        while dq[0] <= i - n:
            dq.popleft()
        best = max(best, x / p[dq[0]] - 1)
    return best * 100


def kosten_pct(positie_usd):
    # Een rondgang: een aankoop en een verkoop bij DeGiro, AutoFX heen en terug, perp in en uit.
    return (2 * DEGIRO_ORDER_EUR * EUR_USD / positie_usd + 2 * AUTOFX + 2 * PERP_TAKER) * 100


def netto_op_kapitaal(funding_pct, kapitaal_per_positie, positie_usd):
    return (funding_pct - kosten_pct(positie_usd)) / kapitaal_per_positie


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    a = argparse.ArgumentParser()
    a.add_argument("--aave", type=float, default=2.95, help="Aave-APY 90 dagen (kpi.json)")
    lat = a.parse_args().aave + 2.0
    print("lat = Aave + 2pp = %.2f%% | kapitaal per positie: 1x = 2,0 · 2x = 1,5" % lat)
    print("%-10s %-7s %6s %8s | %6s %6s | %-15s %-15s" % (
        "naam", "sinds", "F/jr", "slechtst", "max3m", "max12m", "$500 1x / 2x", "$5000 1x / 2x"))
    for coin, tk in NAMEN.items():
        s = fh.samenvatting(coin, fh.historie(coin))
        if not s["uren"]:
            print("%-10s geen historie" % coin)
            continue
        hele = [v["apr_pct"] for v in s["maanden"].values() if v["uren"] >= 600]
        p = dagsloten(tk)
        f = s["apr_pct"]
        print("%-10s %-7s %5.1f%% %7.1f%% | %5.0f%% %5.0f%% | %5.1f / %5.1f   %5.1f / %5.1f" % (
            coin, s["vanaf"][:7], f, min(hele), grootste_stijging_pct(p, 63),
            grootste_stijging_pct(p, 252), netto_op_kapitaal(f, 2.0, 500),
            netto_op_kapitaal(f, 1.5, 500), netto_op_kapitaal(f, 2.0, 5000),
            netto_op_kapitaal(f, 1.5, 5000)))


if __name__ == "__main__":
    main()
