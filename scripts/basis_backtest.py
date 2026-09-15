"""Trage basis-trade op Hyperliquid — backtest op de echte fundinghistorie (plan spoor 3, M6).

    python scripts/basis_backtest.py            # backtest BTC/ETH/HYPE vanaf 2023-05
    python scripts/basis_backtest.py --spot     # verifieer de spot-poot (liquiditeit, koers)
    python scripts/basis_backtest.py --ververs  # data opnieuw ophalen i.p.v. cache

Strategie per munt: short perp + long spot op dezelfde notional, dus zonder
richtingsrisico. Ontvangt funding als die positief is, betaalt als die negatief is.
- Erin als de gemiddelde funding over 7 dagen > INSTAP_APR.
- Eruit als het 7-daags gemiddelde < 0 én de positie minstens MIN_HOUD_UUR open staat.
- Kosten: taker-fee op beide poten bij in- en uitstap.
- Kapitaal = spot-notional + perp-marge bij HEFBOOM (= notional × (1 + 1/HEFBOOM)).

Poort (config/experimenten.json, basis_traag): netto APR op kapitaal ≥ 6% over de
hele historie, en elk kalenderjaar ≥ 0.

Wat dit NIET modelleert (en waarom dat de uitslag kan kantelen):
- Basisbeweging spot vs perp bij in- en uitstap (slippage en premie).
- Liquidatierisico van de short-poot: bij 2x hefboom is een koersstijging van ~50%
  fataal TENZIJ spot als onderpand meetelt (unified/portfolio margin). Dat is
  de haalbaarheidsvraag die --spot en een aparte accountcheck moeten beantwoorden.
- Fee-tier: de basistarieven hieronder; de echte tier komt uit info `userFees`.
"""

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

HL_INFO = "https://api.hyperliquid.xyz/info"
MUNTEN = ("BTC", "ETH", "HYPE")
START = "2023-05-12"

INSTAP_APR = 0.05
MIN_HOUD_UUR = 7 * 24
VENSTER_UUR = 7 * 24
HEFBOOM = 2.0
FEE_PERP = 0.00045       # HL basis-taker perps
FEE_SPOT = 0.00070       # HL basis-taker spot
POORT_APR = 6.0

CACHE = os.path.join(tempfile.gettempdir(), "agent_trader_basis_funding.json")


def _post(body, pogingen=6):
    """POST naar de HL info-API, met oplopende wachttijd bij 429 (rate limit)."""
    wacht = 2.0
    for poging in range(pogingen):
        req = urllib.request.Request(HL_INFO, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code != 429 or poging == pogingen - 1:
                raise
            time.sleep(wacht)
            wacht *= 2


def haal_funding(munt, start_ms):
    rijen = []
    t = start_ms
    nu = int(time.time() * 1000)
    while True:
        r = _post({"type": "fundingHistory", "coin": munt, "startTime": t})
        if not r:
            break
        rijen += r
        laatst = r[-1]["time"]
        if len(r) < 500 or laatst >= nu - 3600 * 1000:
            break
        t = laatst + 1
        time.sleep(0.6)
    gezien, uit = set(), []
    for x in rijen:
        if x["time"] not in gezien:
            gezien.add(x["time"])
            uit.append((int(x["time"]), float(x["fundingRate"])))
    uit.sort()
    return uit


def laad(ververs=False):
    if not ververs and os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as fh:
            return {k: [tuple(p) for p in v] for k, v in json.load(fh).items()}
    start_ms = int(datetime.strptime(START, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    data = {m: haal_funding(m, start_ms) for m in MUNTEN}
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return data


def simuleer(reeks, instap_apr=INSTAP_APR, min_houd=MIN_HOUD_UUR, altijd_in=False):
    """Per uur: netto rendement op kapitaal. Geeft (lijst (ts, r), statistiek)."""
    kapitaal = 1.0 + 1.0 / HEFBOOM           # per 1 eenheid notional
    kosten_per_kant = FEE_PERP + FEE_SPOT
    uit, venster = [], []
    binnen, sinds, trades = altijd_in, 0, 0
    uren_binnen = 0
    if altijd_in:
        uit.append((reeks[0][0], -kosten_per_kant / kapitaal))
        trades = 1
    for ts, rate in reeks:
        venster.append(rate)
        if len(venster) > VENSTER_UUR:
            venster.pop(0)
        gem_apr = statistics.fmean(venster) * 24 * 365 if len(venster) == VENSTER_UUR else None
        r = 0.0
        if binnen:
            r += rate / kapitaal           # short perp ontvangt positieve funding
            uren_binnen += 1
            sinds += 1
            if not altijd_in and gem_apr is not None and gem_apr < 0 and sinds >= min_houd:
                binnen = False
                r -= kosten_per_kant / kapitaal
        elif gem_apr is not None and gem_apr > instap_apr:
            binnen, sinds = True, 0
            trades += 1
            r -= kosten_per_kant / kapitaal
        uit.append((ts, r))
    return uit, {"trades": trades, "tijd_in_markt_pct": round(100 * uren_binnen / max(len(reeks), 1), 1)}


def samenvatten(uur_rendementen):
    per_jaar, per_maand = defaultdict(list), defaultdict(float)
    for ts, r in uur_rendementen:
        d = datetime.fromtimestamp(ts / 1000, timezone.utc)
        per_jaar[d.year].append(r)
        per_maand["%04d-%02d" % (d.year, d.month)] += r
    jaren = {}
    for jaar, rs in sorted(per_jaar.items()):
        jaren[jaar] = round(sum(rs) / (len(rs) / (24 * 365)) * 100, 2)   # geannualiseerd
    totaal_uren = len(uur_rendementen)
    totaal_apr = sum(r for _, r in uur_rendementen) / (totaal_uren / (24 * 365)) * 100
    slechtste = min(per_maand.items(), key=lambda kv: kv[1])
    return {"apr_totaal_pct": round(totaal_apr, 2), "apr_per_jaar_pct": jaren,
            "slechtste_maand": (slechtste[0], round(slechtste[1] * 100, 3)),
            "maanden_negatief": sum(1 for v in per_maand.values() if v < 0),
            "maanden": len(per_maand)}


def backtest(ververs=False):
    data = laad(ververs)
    portefeuille = defaultdict(float)
    print("Trage basis — instap >%.0f%% APR (7d), uit <0 na min. %d dagen, hefboom %.0fx, "
          "fees %.3f%% per kant\n" % (INSTAP_APR * 100, MIN_HOUD_UUR // 24, HEFBOOM,
                                       (FEE_PERP + FEE_SPOT) * 100))
    for munt in MUNTEN:
        reeks = data[munt]
        eerste = datetime.fromtimestamp(reeks[0][0] / 1000, timezone.utc).date()
        for label, altijd in (("regel", False), ("altijd-in", True)):
            uren, stat = simuleer(reeks, altijd_in=altijd)
            s = samenvatten(uren)
            print("%-5s %-9s vanaf %s  APR %6.2f%%  per jaar %s  slechtste maand %s %.2f%%  "
                  "neg. maanden %d/%d  trades %d  in markt %.0f%%"
                  % (munt, label, eerste, s["apr_totaal_pct"], s["apr_per_jaar_pct"],
                     s["slechtste_maand"][0], s["slechtste_maand"][1], s["maanden_negatief"],
                     s["maanden"], stat["trades"], stat["tijd_in_markt_pct"]))
            if not altijd:
                for ts, r in uren:
                    portefeuille[ts] += r / len(MUNTEN)
    gezamenlijk = sorted(portefeuille.items())
    s = samenvatten(gezamenlijk)
    jaar_ok = all(v >= 0 for v in s["apr_per_jaar_pct"].values())
    print("\nPORTEFEUILLE (gelijk gewogen, regel): APR %.2f%%, per jaar %s, slechtste maand %s %.2f%%"
          % (s["apr_totaal_pct"], s["apr_per_jaar_pct"], s["slechtste_maand"][0], s["slechtste_maand"][1]))
    print("Poort: APR >= %.0f%% -> %s ; elk jaar >= 0 -> %s"
          % (POORT_APR, "JA" if s["apr_totaal_pct"] >= POORT_APR else "NEE",
             "JA" if jaar_ok else "NEE"))
    print("LET OP: gedeeltelijke jaren (%s) zijn geannualiseerd; HYPE bestaat pas sinds eind 2024."
          % ", ".join(str(j) for j in s["apr_per_jaar_pct"]))
    return s


def verifieer_spot():
    meta, ctxs = _post({"type": "spotMetaAndAssetCtxs"})
    tokens = {t["index"]: t["name"] for t in meta["tokens"]}
    ctx_per_coin = {c.get("coin"): c for c in ctxs}
    pmeta, pctxs = _post({"type": "metaAndAssetCtxs"})
    perp = {a["name"]: float(c["markPx"]) for a, c in zip(pmeta["universe"], pctxs) if c.get("markPx")}
    doelen = {"UBTC": "BTC", "UETH": "ETH", "HYPE": "HYPE"}
    print("Spot-poot (gekoppeld op coin-naam, niet op positie):")
    for paar in meta["universe"]:
        basis, quote = tokens.get(paar["tokens"][0]), tokens.get(paar["tokens"][1])
        if basis not in doelen or quote not in ("USDC", "USDH", "USDT0"):
            continue
        c = ctx_per_coin.get(paar["name"]) or {}
        mark = float(c.get("markPx") or 0)
        ref = perp.get(doelen[basis])
        afwijking = (mark / ref - 1) * 100 if mark and ref else None
        print("  %-5s/%-5s %-6s mark %-12s perp %-10s afwijking %s  24u-volume $%.2fM"
              % (basis, quote, paar["name"], c.get("markPx"), ref,
                 "%.3f%%" % afwijking if afwijking is not None else "?",
                 float(c.get("dayNtlVlm") or 0) / 1e6))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--spot", action="store_true")
    ap.add_argument("--ververs", action="store_true")
    a = ap.parse_args()
    if a.spot:
        verifieer_spot()
    else:
        backtest(a.ververs)
    sys.exit(0)
