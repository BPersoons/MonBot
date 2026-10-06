"""Volledige fundinghistorie van Hyperliquid-perps (ook de xyz-dex), per maand.

De info-API geeft maximaal 500 uur per aanroep; dit script pagineert vanaf de notering
tot nu. Funding is per uur; positief = longs betalen shorts (wat een short-hedge ontvangt).

Gebruik:
  python scripts/funding_historie.py xyz:GOLD xyz:SILVER BTC
  python scripts/funding_historie.py xyz:GOLD --json data_uit.json
"""
import argparse
import json
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

API = "https://api.hyperliquid.xyz/info"


def _post(body):
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    for poging in range(5):
        try:
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception:
            time.sleep(1.5 * (poging + 1))
    raise RuntimeError("HL info-API onbereikbaar")


def historie(coin, vanaf_ms=0):
    """Alle uurregels [(ms, rate)] vanaf vanaf_ms, gepagineerd."""
    uit, start = [], vanaf_ms
    while True:
        blok = _post({"type": "fundingHistory", "coin": coin, "startTime": start})
        if not blok:
            break
        for r in blok:
            uit.append((int(r["time"]), float(r["fundingRate"])))
        laatste = int(blok[-1]["time"])
        if len(blok) < 500 or laatste <= start:
            break
        start = laatste + 1
        time.sleep(0.2)
    # ontdubbelen op tijd
    return sorted(dict(uit).items())


def per_maand(regels):
    m = defaultdict(list)
    for ms, r in regels:
        m[datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m")].append(r)
    return {k: {"uren": len(v), "apr_pct": sum(v) / len(v) * 24 * 365 * 100,
                "positief_pct": 100.0 * sum(1 for x in v if x > 0) / len(v)} for k, v in sorted(m.items())}


def samenvatting(coin, regels):
    if not regels:
        return {"coin": coin, "uren": 0}
    fr = [r for _, r in regels]
    maanden = per_maand(regels)
    hele = {k: v for k, v in maanden.items() if v["uren"] >= 24 * 25}
    return {
        "coin": coin,
        "vanaf": datetime.fromtimestamp(regels[0][0] / 1000, timezone.utc).strftime("%Y-%m-%d"),
        "uren": len(fr),
        "apr_pct": sum(fr) / len(fr) * 24 * 365 * 100,
        "positief_pct": 100.0 * sum(1 for x in fr if x > 0) / len(fr),
        "slechtste_maand": min(hele.items(), key=lambda kv: kv[1]["apr_pct"]) if hele else None,
        "maanden": maanden,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("coins", nargs="+")
    p.add_argument("--json", default=None)
    a = p.parse_args()
    alles = []
    for c in a.coins:
        s = samenvatting(c, historie(c))
        alles.append(s)
        if not s["uren"]:
            print(f"{c}: geen historie")
            continue
        sm = s["slechtste_maand"]
        print(f"\n{c}: sinds {s['vanaf']}, {s['uren']} uur, gemiddeld {s['apr_pct']:.1f}% per jaar, "
              f"{s['positief_pct']:.0f}% van de uren positief"
              + (f"; slechtste hele maand {sm[0]} {sm[1]['apr_pct']:.1f}%" if sm else ""))
        for k, v in s["maanden"].items():
            print(f"  {k}  {v['apr_pct']:7.1f}%  positief {v['positief_pct']:4.0f}%  ({v['uren']} u)")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(alles, fh, indent=1)


if __name__ == "__main__":
    main()
