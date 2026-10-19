"""Zoekt naast HYPE munten waarop een basis-trade op Hyperliquid de lat haalt (basis_scan_hl).

Kandidaten: munten met spot én perp op Hyperliquid, spot-dagvolume >= $1 mln. Een spottoken
heet vaak anders dan de perp (UBTC -> BTC, ONEAR -> NEAR, XMR1 -> XMR); de koppeling telt
alleen als de spotkoers binnen 3% van de perpkoers ligt, anders is het een andere munt.

Per kandidaat draait `basis_sim.simuleer` met de parameters van het LIVE potje (hefboom 1,5,
band 1,0-2,0, geen staking): binnen het kader van 2x. De vooruitmeting van de HYPE-basis
(hefboom 2, band 1,4-3) gaat tot 3x en sloot daardoor NEAR ten onrechte uit (A4 19-10).
Door als (register, 12-10):
- >= 5,2% per jaar op kapitaal (Aave + 2pp) in ELK halfjaar met >= 120 dagen data;
- geen verliesmaand (hele maanden, funding + staking);
- niet gedragen door één maand: zonder de beste maand nog steeds >= 5,2% over de hele periode;
- geen liquidatie in welk venster ook.

Wat het papier NIET meet (zelfde gaten als de HYPE-basis): spot- vs perpkoers (de simulatie
gebruikt de perpkoers voor beide), slippage op de spot, ADL, venuerisico. Een munt met een
dun spotboek haalt het papier en verliest live op de spread.

Gebruik:
  python scripts/basis_scan.py               # alle kandidaten
  python scripts/basis_scan.py --json uit.json
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from basis_sim import _post, dagcandles, funding_per_dag, jaar_pct, simuleer  # noqa: E402

LAT_PCT = 5.2
MIN_VOLUME_USD = 1_000_000
MAX_KOERSAFWIJKING = 0.03
LIVE = {"lev": 1.5, "lev_min": 1.0, "lev_max": 2.0}   # utils/basis_hype.py, kader <= 2x


def kandidaten(min_volume=MIN_VOLUME_USD):
    """[(perp, spotnaam, volume)] voor spotparen tegen USDC met een perp van dezelfde munt."""
    meta, ctxs = _post({"type": "spotMetaAndAssetCtxs"})
    tokens = {t["index"]: t["name"] for t in meta["tokens"]}
    ctx = {c["coin"]: c for c in ctxs}          # koppelen op coin, niet op volgorde
    pmeta, pctxs = _post({"type": "metaAndAssetCtxs"})
    perp_px = {u["name"]: float(c["markPx"]) for u, c in zip(pmeta["universe"], pctxs)
               if c.get("markPx") and not u.get("isDelisted")}
    uit = []
    for paar in meta["universe"]:
        c = ctx.get(paar["name"])
        basis, quote = tokens[paar["tokens"][0]], tokens[paar["tokens"][1]]
        if not c or quote != "USDC" or not c.get("markPx"):
            continue
        vol = float(c.get("dayNtlVlm") or 0)
        if vol < min_volume:
            continue
        spot_px = float(c["markPx"])
        kaal = re.sub(r"\d+$", "", basis)
        for naam in (basis, kaal, kaal[1:], "k" + kaal[1:]):
            px = perp_px.get(naam)
            if px and abs(spot_px / px - 1) <= MAX_KOERSAFWIJKING:
                uit.append((naam, basis, vol))
                break
        else:
            uit.append((None, basis, vol))
    return uit


def halfjaren(dagen):
    vensters = {}
    for d in dagen:
        vensters.setdefault(d[:4] + ("-H1" if d[5:7] <= "06" else "-H2"), []).append(d)
    return {k: v for k, v in vensters.items() if len(v) >= 120}


def beoordeel(coin):
    px, fund = dagcandles(coin), funding_per_dag(coin)
    alle = sorted(d for d in px if d in fund)
    if len(alle) < 120:
        return {"coin": coin, "oordeel": "te kort", "dagen": len(alle)}
    heel = simuleer(px, fund, dagen=alle, **LIVE)
    r = {"coin": coin, "van": alle[0], "tot": alle[-1], "dagen": len(alle),
         "liquidatie": heel["liquidatie"], "halfjaren": {}, "redenen": []}
    if heel["liquidatie"]:
        r["redenen"].append("liquidatie op %s" % heel["liquidatie"])
    else:
        r["netto_pct"] = round(jaar_pct(heel), 1)
        maanden = sorted(heel["maand"].items())[1:-1]
        r["slechtste_maand"] = min(maanden, key=lambda kv: kv[1]) if maanden else None
        if r["slechtste_maand"] and r["slechtste_maand"][1] < 0:
            r["redenen"].append("verliesmaand %s ($%.1f op $1000)" % r["slechtste_maand"])
        if maanden:
            beste = max(maanden, key=lambda kv: kv[1])
            jaren = (len(alle) - 1) / 365
            zonder = ((heel["eind"] - beste[1]) / 1000) ** (1 / jaren) * 100 - 100
            r["zonder_beste_maand_pct"] = round(zonder, 1)
            if zonder < LAT_PCT:
                r["redenen"].append("gedragen door %s (zonder: %.1f%%)" % (beste[0], zonder))
        if r["netto_pct"] < LAT_PCT:
            r["redenen"].append("hele periode %.1f%% < %.1f%%" % (r["netto_pct"], LAT_PCT))
    for naam, v in sorted(halfjaren(alle).items()):
        u = simuleer(px, fund, dagen=v, **LIVE)
        pct = None if u["liquidatie"] else round(jaar_pct(u), 1)
        r["halfjaren"][naam] = pct
        if pct is None:
            r["redenen"].append("%s liquidatie" % naam)
        elif pct < LAT_PCT:
            r["redenen"].append("%s %.1f%%" % (naam, pct))
    r["oordeel"] = "door" if not r["redenen"] else "valt af"
    return r


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    a = argparse.ArgumentParser()
    a.add_argument("--json", default=None)
    a.add_argument("--min-volume", type=float, default=MIN_VOLUME_USD)
    args = a.parse_args()
    uit = []
    for perp, spot, vol in kandidaten(args.min_volume):
        if perp is None:
            print(f"{spot:>8}  spot ${vol/1e6:5.1f} mln  geen perp van dezelfde munt")
            uit.append({"spot": spot, "volume": vol, "oordeel": "geen perp"})
            continue
        r = beoordeel(perp)
        r.update({"spot": spot, "volume": vol})
        uit.append(r)
        hj = " ".join(f"{k} {'LIQ' if v is None else f'{v:.1f}'}" for k, v in r.get("halfjaren", {}).items())
        print(f"{perp:>8}  spot ${vol/1e6:5.1f} mln  {r.get('van', '')}..{r.get('tot', '')}  "
              f"netto {r.get('netto_pct', '-')}%  | {hj}  -> {r['oordeel'].upper()}"
              + (f"  ({'; '.join(r.get('redenen', []))})" if r.get("redenen") else ""))
        time.sleep(0.5)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(uit, fh, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
