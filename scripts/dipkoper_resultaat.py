"""Resultaat van de dip-koper uit de bron: Hyperliquid-fills en funding, niet uit ons eigen boek.

    python scripts/dipkoper_resultaat.py [--vanaf 2026-07-20] [--adres 0x...]

Waarom (gemeten 21-09): het positiebestand houdt per ticker één vak bij. Een tweede ronde
in dezelfde naam overschrijft de eerste (CRCL, ORCL en TSLA verloren zo samen +$13), en
CRWV sloot vóór het resultaat per positie werd bijgehouden. trade_log.json mist dezelfde
rondes. Het totaalveld boekt tegen de markprijs, niet tegen de fillprijs, en telt geen fees
of funding. Voor elke evaluatie per naam is dit script de bron.

Let op: vóór de eigen wallet (tot ~22-07) liepen dip-trades via de hoofdwallet (MRVL -$0,99,
CRWV +$0,07). Die staan hier niet in, omdat de hoofdwallet ook andere handel bevat.
"""

import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

INFO = "https://api.hyperliquid.xyz/info"


def _post(body):
    req = urllib.request.Request(INFO, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _alles(soort, adres, start_ms, pagina):
    """Pagineert een info-endpoint dat maximaal `pagina` regels per keer geeft."""
    uit = []
    while True:
        r = _post({"type": soort, "user": adres, "startTime": start_ms})
        if not r:
            break
        uit.extend(r)
        if len(r) < pagina:
            break
        start_ms = max(x["time"] for x in r) + 1
    return uit


def per_munt(fills, funding):
    """{munt: {'gerealiseerd', 'fees', 'funding', 'sluitingen'}} plus een totaalregel."""
    per = defaultdict(lambda: {"gerealiseerd": 0.0, "fees": 0.0, "funding": 0.0, "sluitingen": 0})
    for f in fills:
        d = per[f["coin"]]
        pnl = float(f.get("closedPnl") or 0.0)
        d["gerealiseerd"] += pnl
        d["fees"] += float(f.get("fee") or 0.0)
        if pnl != 0.0:
            d["sluitingen"] += 1
    for x in funding:
        delta = x.get("delta") or {}
        if delta.get("type") == "funding":
            per[delta.get("coin")]["funding"] += float(delta.get("usdc") or 0.0)
    totaal = {k: sum(d[k] for d in per.values()) for k in ("gerealiseerd", "fees", "funding", "sluitingen")}
    return dict(per), totaal


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--vanaf", default="2026-07-20")
    ap.add_argument("--adres")
    a = ap.parse_args(argv)
    adres = a.adres
    if not adres:
        from utils.gcp_secrets import get_secret
        adres = get_secret("HL_THEMATIC_WALLET_ADDRESS")
    if not adres:
        print("ONMEETBAAR: geen adres voor de dip-koper-wallet")
        return 1
    start = int(datetime.fromisoformat(a.vanaf).replace(tzinfo=timezone.utc).timestamp() * 1000)
    fills = _alles("userFillsByTime", adres, start, 2000)
    funding = _alles("userFunding", adres, start, 500)
    per, t = per_munt(fills, funding)
    print("Dip-koper-wallet %s.. vanaf %s: %d fills, %d fundingregels"
          % (adres[:6], a.vanaf, len(fills), len(funding)))
    for munt, d in sorted(per.items(), key=lambda kv: -kv[1]["gerealiseerd"]):
        netto = d["gerealiseerd"] - d["fees"] + d["funding"]
        print("  %-12s gerealiseerd %+7.2f  fees %5.2f  funding %+6.2f  netto %+7.2f  (%d sluitende fills)"
              % (munt, d["gerealiseerd"], d["fees"], d["funding"], netto, d["sluitingen"]))
    netto = t["gerealiseerd"] - t["fees"] + t["funding"]
    print("  %-12s gerealiseerd %+7.2f  fees %5.2f  funding %+6.2f  netto %+7.2f"
          % ("TOTAAL", t["gerealiseerd"], t["fees"], t["funding"], netto))
    print("Open posities tellen hier alleen mee met hun fees en funding; hun koerswinst niet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
