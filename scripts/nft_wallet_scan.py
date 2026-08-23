"""Welke NFT-collecties in een wallet hebben überhaupt een markt?

    python scripts/nft_wallet_scan.py [adres]

## Waarom dit bestaat

Een oude NFT-wallet bevat al snel honderd collecties, en voor vrijwel allemaal is
de genoteerde floor-prijs fictie: geen volume, geen bieders, niet te verkopen. Een
monitor die daar allemaal op let, produceert precies de meldingenstroom die in
augustus 2026 is weggehaald — 43 per dag terug naar 2, met als reden dat een
melding die je leert wegklikken je de echte kost.

Dit script beantwoordt daarom eerst de voorvraag: **waar is handel?** Pas wat die
toets doorstaat, is het bewaken waard.

## Wat "een markt" hier betekent

Niet de floor-prijs maar het **volume**. Een floor van 2 ETH zonder omzet is een
vraagprijs waar niemand op ingaat. De rangschikking gaat daarom op 24-uursvolume,
met de floor er als tweede kolom naast.

⚠️ Twee dingen die dit script NIET doet, bewust:
 - Het rekent geen totale portefeuillewaarde uit. floor x aantal is een bovengrens
   die je bij verkoop nooit haalt: je duwt je eigen floor omlaag.
 - Het kijkt niet naar ERC-404-tokens. Die rapporteren hun "aantal" in
   token-eenheden, niet in stuks, en geven onzinnige tellingen.

Bron collecties: Blockscout (gratis, geen sleutel). Bron prijzen: CoinGecko NFT
API (gratis tier, ~10-30 calls/min — vandaar de vertraging tussen aanroepen).
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

STANDAARD_ADRES = "0x75a70b3f24eb6f32e75b53fbe9315111d05851d0"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
PAUZE_SEC = 6.0          # CoinGecko gratis tier is strenger dan hij documenteert
VOLUME_DREMPEL_USD = 500  # daaronder noemen we het geen markt


def _haal(url, timeout=30):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout))


def collecties(adres):
    """Alle NFT-collecties in het adres, via Blockscout."""
    basis = ("https://eth.blockscout.com/api/v2/addresses/%s/nft/collections"
             "?type=ERC-721%%2CERC-1155" % adres)
    uit, nxt = [], None
    for _ in range(20):
        url = basis + ("&" + urllib.parse.urlencode(nxt) if nxt else "")
        d = _haal(url)
        uit += d.get("items", [])
        nxt = d.get("next_page_params")
        if not nxt:
            break
        time.sleep(0.4)
    return uit


def markt(contract):
    """Geeft ("ok", dict) / ("niet_gelist", None) / ("onbekend", None).

    Dat onderscheid is het halve script. De eerste versie ving ALLE fouten af en
    boekte ze als "niet gelist" — waarna een rate limit van CoinGecko 107 van de 109
    collecties als "geen markt" bestempelde, inclusief er een met $4.591 dagvolume.
    Onmeetbaar telt niet als nul; het is een eigen categorie.
    """
    url = "https://api.coingecko.com/api/v3/nfts/ethereum/contract/%s" % contract
    for poging in range(4):
        try:
            d = _haal(url, 25)
            return "ok", {
                "floor_usd": (d.get("floor_price") or {}).get("usd"),
                "floor_eth": (d.get("floor_price") or {}).get("native_currency"),
                "vol24_usd": (d.get("volume_24h") or {}).get("usd"),
                "houders": d.get("number_of_unique_addresses"),
                "naam": d.get("name"),
            }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "niet_gelist", None
            if e.code in (429, 503):
                time.sleep(20 * (poging + 1))
                continue
            return "onbekend", None
        except Exception:
            time.sleep(5)
    return "onbekend", None


def main():
    adres = sys.argv[1] if len(sys.argv) > 1 else STANDAARD_ADRES
    print("Wallet: %s\n" % adres)
    items = collecties(adres)
    print("Collecties gevonden: %d — nu prijzen ophalen (~%d min)\n"
          % (len(items), int(len(items) * PAUZE_SEC / 60) + 1))

    rijen = []
    for i, c in enumerate(items, 1):
        t = c.get("token", {}) or {}
        typ = t.get("type")
        naam = (t.get("name") or "?")[:38]
        adr = t.get("address_hash")
        # ERC-404 telt in token-eenheden, niet in stuks — buiten beschouwing
        if typ == "ERC-404":
            rijen.append((None, naam, typ, None, None, "ERC-404, aantal onbruikbaar"))
            continue
        n = int(c.get("amount") or 0)
        status, m = markt(adr)
        time.sleep(PAUZE_SEC)
        if status == "ok":
            rijen.append((m["vol24_usd"] or 0.0, naam, typ, n, m, "ok"))
        elif status == "niet_gelist":
            rijen.append((0.0, naam, typ, n, None, "niet_gelist"))
        else:
            rijen.append((None, naam, typ, n, None, "onbekend"))
        if i % 20 == 0:
            print("   ... %d/%d" % (i, len(items)))

    echt = [r for r in rijen if r[5] == "ok" and (r[0] or 0) >= VOLUME_DREMPEL_USD]
    dun = [r for r in rijen if r[5] == "ok" and 0 < (r[0] or 0) < VOLUME_DREMPEL_USD]
    dood = [r for r in rijen if r[5] in ("ok", "niet_gelist") and (r[0] or 0) == 0]
    onbekend = [r for r in rijen if r[5] == "onbekend"]
    n404 = [r for r in rijen if str(r[5]).startswith("ERC-404")]

    print("\n" + "=" * 92)
    print("HEEFT EEN MARKT — 24u-volume >= $%d" % VOLUME_DREMPEL_USD)
    print("=" * 92)
    print("  %-38s %5s %11s %12s %10s" % ("collectie", "stuks", "floor $", "24u vol $", "houders"))
    for vol, naam, typ, n, m, _ in sorted(echt, key=lambda r: -r[0]):
        print("  %-38s %5s %11.2f %12.0f %10s"
              % (naam, n, m["floor_usd"] or 0, vol, m["houders"] or "?"))

    print("\n" + "=" * 92)
    print("DUNNE MARKT — volume onder $%d: floor is hier een vraagprijs, geen koers" % VOLUME_DREMPEL_USD)
    print("=" * 92)
    for vol, naam, typ, n, m, _ in sorted(dun, key=lambda r: -r[0]):
        print("  %-38s %5s  floor $%-9.2f vol $%.0f" % (naam, n, m["floor_usd"] or 0, vol))

    print("\n" + "=" * 92)
    print("GEEN MARKT — %d collecties, niet gelist of nul volume" % len(dood))
    print("=" * 92)
    print("  " + ", ".join(sorted(r[1] for r in dood))[:1500])
    if n404:
        print("\nERC-404 (aantal niet uit te lezen): " + ", ".join(r[1] for r in n404))

    if onbekend:
        print("")
        print("=" * 92)
        print("NIET UITGELEZEN — %d collecties. GEEN oordeel: dit is geen 'geen markt'." % len(onbekend))
        print("=" * 92)
        print("  " + ", ".join(sorted(x[1] for x in onbekend))[:900])

    print("")
    print("SAMENVATTING: %d met markt | %d dun | %d zonder markt | %d NIET UITGELEZEN | %d ERC-404"
          % (len(echt), len(dun), len(dood), len(onbekend), len(n404)))
    print("Alleen de eerste groep is het bewaken waard.")


if __name__ == "__main__":
    main()
