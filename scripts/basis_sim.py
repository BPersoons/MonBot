"""Simuleert een basis-trade op Hyperliquid: spot long + perp short, gelijke grootte.

Rendement op kapitaal = funding die de short ontvangt, min kosten. Het kapitaal staat
deels in spot en deels als marge voor de short (hefboom op de short = `lev`). Stijgt de
koers, dan krimpt de marge; zakt de hefboom buiten [lev_min, lev_max], dan wordt er
op dezelfde venue bijgestuurd: spot verkopen en de short evenredig verkleinen (of
omgekeerd). Dat kost spot- en perpkosten, geen brug.

Meetregels (CLAUDE.md, feedback_scorecard_meetregels):
- uurfunding uit de API, opgeteld per dag; koersen = dagcandles van de perp;
- liquidatie getoetst op de dag-HIGH (niet het slot): komt de marge op de high onder de
  onderhoudsmarge, dan telt de dag als liquidatie en stopt de simulatie met dat verlies;
- kosten op elke handeling, ook in- en uitstap.

Gebruik:
  python scripts/basis_sim.py HYPE
  python scripts/basis_sim.py HYPE --lev 2 --lev-max 3 --staking 2.0
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from funding_historie import historie  # noqa: E402

API = "https://api.hyperliquid.xyz/info"


def _post(body):
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def dagcandles(coin):
    eind = int(time.time() * 1000)
    c = _post({"type": "candleSnapshot",
               "req": {"coin": coin, "interval": "1d", "startTime": 0, "endTime": eind}})
    return {time.strftime("%Y-%m-%d", time.gmtime(k["t"] / 1000)):
            (float(k["h"]), float(k["c"])) for k in c}


def funding_per_dag(coin):
    dag = defaultdict(float)
    for ms, r in historie(coin):
        dag[time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))] += r
    return dag


def simuleer(px, fund, lev=2.0, lev_min=1.4, lev_max=3.0, perp_fee=0.00045,
             spot_fee=0.0007, staking_pct=0.0, onderhoud=0.05, C=1000.0, dagen=None):
    """px: {dag: (high, close)}, fund: {dag: som uurfunding}. Geeft een dict met uitkomst."""
    dagen = dagen or sorted(d for d in px if d in fund)
    p0 = px[dagen[0]][1]
    N = C * lev / (1 + lev)                # spot = N, marge = N / lev
    q = N * (1 - spot_fee) / p0            # HYPE gekocht na spotkosten
    marge = C - N - q * p0 * perp_fee      # short openen kost perp-fee
    kosten = N * spot_fee + q * p0 * perp_fee
    funding = staking = 0.0
    n_bij = 0
    vorig = p0
    maand = defaultdict(float)
    for d in dagen[1:]:
        high, p = px[d]
        # liquidatietoets op de high, vóór het bijsturen van vandaag
        marge_high = marge - q * (high - vorig)
        if marge_high <= onderhoud * q * high:
            waarde = max(marge_high, 0) + q * high
            return {"liquidatie": d, "eind": waarde, "dagen": dagen, "n_bij": n_bij,
                    "kosten": kosten, "funding": funding, "maand": dict(maand)}
        f = q * p * fund[d]
        s = q * p * staking_pct / 100 / 365
        marge += -q * (p - vorig) + f
        q_spot_extra = s / p                 # staking komt als HYPE bij
        funding += f
        staking += s
        maand[d[:7]] += f + s
        vorig = p
        h = q * p / marge if marge > 0 else 99
        if h > lev_max or h < lev_min:
            # herverdeel totale waarde naar spot = N', marge = N'/lev
            totaal = marge + q * p
            n_nieuw = totaal * lev / (1 + lev)
            dq = n_nieuw / p - q               # >0: bijkopen + short groter
            k = abs(dq) * p * (spot_fee + perp_fee)
            kosten += k
            q = q + dq
            marge = totaal - q * p - k
            n_bij += 1
        q += q_spot_extra
    p = px[dagen[-1]][1]
    eind = marge + q * p - q * p * (spot_fee + perp_fee)
    kosten += q * p * (spot_fee + perp_fee)
    return {"liquidatie": None, "eind": eind, "dagen": dagen, "n_bij": n_bij,
            "kosten": kosten, "funding": funding, "staking": staking, "maand": dict(maand)}


def jaar_pct(uit, C=1000.0):
    jaren = (len(uit["dagen"]) - 1) / 365
    return ((uit["eind"] / C) ** (1 / jaren) - 1) * 100 if jaren > 0 and uit["eind"] > 0 else -100.0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    a = argparse.ArgumentParser()
    a.add_argument("coin")
    a.add_argument("--lev", type=float, default=2.0)
    a.add_argument("--lev-min", type=float, default=1.4)
    a.add_argument("--lev-max", type=float, default=3.0)
    a.add_argument("--staking", type=float, default=0.0, help="%% per jaar extra op de spot (kHYPE)")
    a.add_argument("--vanaf", default=None, help="JJJJ-MM-DD: alleen dit venster (vooruitmeting)")
    args = a.parse_args()
    px, fund = dagcandles(args.coin), funding_per_dag(args.coin)
    alle = sorted(d for d in px if d in fund and (not args.vanaf or d >= args.vanaf))
    print(f"{args.coin}: {alle[0]}..{alle[-1]}, koers {px[alle[0]][1]:.2f} -> {px[alle[-1]][1]:.2f}")
    vensters = [("hele periode", alle)]
    if args.vanaf:
        vensters = vensters[:1]
    for jaar in ([] if args.vanaf else sorted({d[:4] for d in alle})):
        v = [d for d in alle if d[:4] == jaar]
        if len(v) > 60:
            vensters.append((jaar, v))
    if not args.vanaf:
        vensters.append(("laatste 6 maanden", alle[-183:]))
    for naam, v in vensters:
        u = simuleer(px, fund, args.lev, args.lev_min, args.lev_max, staking_pct=args.staking, dagen=v)
        if u["liquidatie"]:
            print(f"  {naam:18} LIQUIDATIE op {u['liquidatie']}")
            continue
        # alleen hele maanden: de eerste en de lopende zijn onvolledig
        maanden = sorted(u["maand"].items())[1:-1]
        slechtste = min(maanden, key=lambda kv: kv[1]) if maanden else None
        print(f"  {naam:18} netto {jaar_pct(u):6.1f}% per jaar op kapitaal | funding ${u['funding']:.0f}"
              f" kosten ${u['kosten']:.0f} op $1000 | {u['n_bij']}x bijgestuurd"
              + (f" | slechtste maand {slechtste[0]} ${slechtste[1]:.1f}" if slechtste else ""))


if __name__ == "__main__":
    main()
