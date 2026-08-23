"""Meldt wanneer een dode token in de wallet weer verhandelbaar wordt.

    python scripts/token_watch.py            # meten, staat bijwerken, trigger bepalen
    python scripts/token_watch.py --status   # alleen tonen, niets wegschrijven

## De vraag die dit beantwoordt

De wallet houdt ~167 tokens waar geen enkele handel in zit: echte projecten
(Wolf Game WOOL, Kylin, Vertex, Tapmydata, Compounding LOOKS) waarvan de
liquiditeit is verdampt. WOOL heeft op dit moment geen enkel handelspaar; KYL
heeft een pool van $244.

Zoiets kan opleven — een relaunch, een migratie, een hype die terugkomt. Dan is
er kort wél diepte om eruit te stappen. Dit script kijkt dagelijks of dat gebeurt.

## Waarom LIQUIDITEIT en niet de koers

Een koers die verdubbelt op een pool van $244 levert je $0,30 op. De vraag is niet
"is het meer waard" maar **"kan ik eruit"**. Een trigger vraagt daarom drie dingen
tegelijk:

  1. je positie is minstens `min_waarde_usd` waard          — anders niet de moeite
  2. de pool is minstens `pool_factor` x je positie          — anders duw je hem zelf omlaag
  3. er is 24-uursvolume                                     — anders is de pool een etalage
  4. en het token was bij de EERSTE meting NIET verhandelbaar

Die vierde is wat het een verandering maakt in plaats van een toestand. USDC en
WETH voldoen altijd aan 1 tot 3; daar een melding over krijgen is zinloos. Bij de
eerste run wordt per token vastgelegd of het toen al leefde (`basis_levend`), en
alleen wat toen dood was kan later alarm slaan.

Alle vier, of geen melding. Dat is streng, en dat hoort: op 2026-08-22 zijn de
meldingen van ~43 naar ~2 per dag gebracht omdat een melding die je leert
wegklikken je de echte kost.

## Lokaas-tokens doen NOOIT mee

Tokens waarvan de NAAM een URL of een claim-instructie is, zijn neergezet om je
naar een kwaadaardig contract te lokken zodra je ze probeert te verkopen. Er zijn
er 101 in deze wallet. Een melding erover zou je precies de kant op duwen die je
niet op moet — ze worden daarom hard uitgesloten, ongeacht wat DexScreener zegt.

## Saldi worden LIVE gelezen

Niet uit een vastgelegde lijst. Verkoop je iets, dan verdwijnt het vanzelf uit de
bewaking; koop je iets bij, dan telt het mee. Kost één aanroep per keten.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

WORTEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAAT_BESTAND = os.path.join(WORTEL, "research", "token_watch.json")
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
RPC_UA = dict(UA, **{"Content-Type": "application/json"})

ADRES = "0x75a70b3f24eb6f32e75b53fbe9315111d05851d0"
MIN_WAARDE_USD = 150.0     # onder dit bedrag is uitstappen de moeite niet waard
POOL_FACTOR = 10.0         # pool moet minstens 10x je positie zijn
COOLDOWN_DAGEN = 14
BATCH = 30                 # DexScreener neemt maximaal 30 adressen per aanroep

LOKAAS = re.compile(
    r"(https?://|www\.|\.(io|com|net|xyz|site|fi|org|club|pro|finance|gifts?)\b"
    r"|visit |claim |airdrop|reward|voucher|gift|free )", re.I)

INDEXERS = [
    ("Ethereum", "https://eth.blockscout.com"),
    ("Base", "https://base.blockscout.com"),
    ("Polygon", "https://polygon.blockscout.com"),
    ("Optimism", "https://optimism.blockscout.com"),
    ("Arbitrum", "https://arbitrum.blockscout.com"),
    ("Gnosis", "https://gnosis.blockscout.com"),
]


def _get(url, timeout=40):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout))


def posities():
    """Live saldi per keten. Lokaas eruit, nulsaldi eruit."""
    uit, mislukt = [], []
    for keten, bs in INDEXERS:
        try:
            d = _get("%s/api/v2/addresses/%s/token-balances" % (bs, ADRES))
        except Exception as e:
            mislukt.append("%s (%s)" % (keten, str(e)[:30]))
            continue
        for x in d:
            t = x.get("token") or {}
            if t.get("type") != "ERC-20":
                continue
            nm, sym = t.get("name") or "", t.get("symbol") or "?"
            if LOKAAS.search(nm + " " + sym):
                continue
            bal = int(x["value"]) / (10 ** int(t.get("decimals") or 0)) if x.get("value") else 0.0
            if bal <= 0:
                continue
            uit.append({"keten": keten, "sym": sym, "contract": t.get("address_hash"), "saldo": bal})
    return uit, mislukt


def markten(contracten):
    """DexScreener in batches. Per token het DIEPSTE paar — daar kun je echt uit."""
    beste = {}
    for i in range(0, len(contracten), BATCH):
        stuk = contracten[i:i + BATCH]
        try:
            d = _get("https://api.dexscreener.com/latest/dex/tokens/%s" % ",".join(stuk), 30)
        except Exception:
            continue          # mislukt = geen oordeel, niet 'geen markt'
        for p in d.get("pairs") or []:
            adr = ((p.get("baseToken") or {}).get("address") or "").lower()
            liq = float((p.get("liquidity") or {}).get("usd") or 0)
            if adr and (adr not in beste or liq > beste[adr]["liq"]):
                beste[adr] = {"liq": liq,
                              "usd": float(p.get("priceUsd") or 0),
                              "vol24": float((p.get("volume") or {}).get("h24") or 0)}
        time.sleep(1.0)
    return beste


def _in_cooldown(staat, sleutel):
    laatst = (staat.get(sleutel) or {}).get("laatste_melding")
    if not laatst:
        return False
    try:
        t = datetime.fromisoformat(laatst)
    except Exception:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - t < timedelta(days=COOLDOWN_DAGEN)


def main():
    alleen_tonen = "--status" in sys.argv
    nu = datetime.now(timezone.utc)
    try:
        staat = json.load(open(STAAT_BESTAND, encoding="utf-8"))
    except Exception:
        staat = {"tokens": {}, "laatst_gedraaid": None}

    pos, mislukt = posities()
    markt = markten([p["contract"] for p in pos if p["contract"]])

    treffers, top = [], []
    for p in pos:
        sleutel = "%s/%s" % (p["keten"], p["sym"])
        m = markt.get((p["contract"] or "").lower())

        # Een token ZONDER handelspaar krijgt hier bewust wél een basisregel, met
        # basis_levend=False. Dat is precies het geval waar dit script voor bestaat:
        # WOOL heeft vandaag geen enkel paar. Zonder deze regel zou hij pas opduiken
        # op de dag dat hij een pool krijgt — en dan als "nieuw en meteen levend"
        # worden weggeschreven, waarna er nooit een melding komt.
        if not m or not m["usd"]:
            rij = staat["tokens"].setdefault(sleutel, {})
            rij.setdefault("basis_levend", False)
            rij.setdefault("basis_op", nu.isoformat(timespec="seconds"))
            rij.update({"waarde_usd": 0.0, "pool_usd": 0, "geen_paar": True,
                        "gemeten": nu.isoformat(timespec="seconds")})
            continue

        waarde = p["saldo"] * m["usd"]
        top.append((waarde, p, m))
        raakt = (waarde >= MIN_WAARDE_USD
                 and m["liq"] >= POOL_FACTOR * waarde
                 and m["vol24"] > 0)

        # Dit is een VERANDERINGS-detector, geen toestandsdetector. Bij de eerste
        # waarneming leggen we vast of een token toen al verhandelbaar was. USDC en
        # WETH zijn dat altijd; daar een melding over sturen is precies de ruis die
        # we op 2026-08-22 hebben weggehaald. Alleen wat DOOD was en opleeft telt.
        rij = staat["tokens"].setdefault(sleutel, {})
        if "basis_levend" not in rij:
            rij["basis_levend"] = bool(raakt)
            rij["basis_op"] = nu.isoformat(timespec="seconds")

        if raakt and not rij["basis_levend"] and not _in_cooldown(staat["tokens"], sleutel):
            treffers.append(
                "<b>%s</b> (%s) — je %.4f stuks zijn $%.0f waard. Pool $%.0f "
                "(%.0fx je positie), 24u-volume $%.0f."
                % (p["sym"], p["keten"], p["saldo"], waarde, m["liq"], m["liq"] / waarde, m["vol24"]))
            rij["laatste_melding"] = nu.isoformat(timespec="seconds")
        rij.update({"waarde_usd": round(waarde, 2), "pool_usd": round(m["liq"]),
                    "geen_paar": False, "gemeten": nu.isoformat(timespec="seconds")})

    top.sort(key=lambda r: -r[0])
    print("Token-bewaking %s — %d posities, %d met een handelspaar"
          % (nu.strftime("%Y-%m-%d %H:%M UTC"), len(pos), len(top)))
    print("  drempel: waarde >= $%.0f, pool >= %.0fx, volume > 0\n" % (MIN_WAARDE_USD, POOL_FACTOR))
    print("  %-10s %-12s %14s %12s %13s %12s" % ("keten", "token", "waarde $", "pool $", "pool/positie", "24u vol $"))
    for waarde, p, m in top[:12]:
        verh = (m["liq"] / waarde) if waarde else 0
        print("  %-10s %-12s %14.2f %12.0f %12.1fx %12.0f"
              % (p["keten"], str(p["sym"])[:12], waarde, m["liq"], verh, m["vol24"]))
    if mislukt:
        print("\n  NIET UITGELEZEN (geen oordeel): %s" % ", ".join(mislukt))

    if not alleen_tonen:
        staat["laatst_gedraaid"] = nu.isoformat(timespec="seconds")
        with open(STAAT_BESTAND, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(staat, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    uit = os.getenv("GITHUB_OUTPUT")
    if treffers:
        bericht = ("💧 <b>Token weer verhandelbaar</b>\n\n" + "\n\n".join(treffers)
                   + "\n\nLiquiditeit in dit soort tokens is vaak tijdelijk. "
                     "Controleer de pool zelf voor je iets doet.")
        print("\nTRIGGER:\n" + bericht)
        if uit:
            with open(uit, "a", encoding="utf-8") as fh:
                fh.write("token_triggered=true\n")
                fh.write("token_message<<TOK_EOF\n%s\nTOK_EOF\n" % bericht)
    else:
        print("\nGeen trigger.")
        if uit:
            with open(uit, "a", encoding="utf-8") as fh:
                fh.write("token_triggered=false\n")


if __name__ == "__main__":
    main()
