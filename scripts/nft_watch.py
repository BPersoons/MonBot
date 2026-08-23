"""Bewaakt de drie NFT-collecties waar handel in zit, en meldt alleen bij een echte kans.

    python scripts/nft_watch.py            # meten, staat bijwerken, trigger bepalen
    python scripts/nft_watch.py --status   # alleen tonen, niets wegschrijven

Draait in GitHub Actions (`.github/workflows/nft_watch.yml`), NIET op de VM — net als
de scorekaart. De repo is de bron; een kopie op de VM zou de state-duplicatie
herhalen die dit project al drie keer heeft geraakt.

## Waarom maar drie collecties

`scripts/nft_wallet_scan.py` heeft de wallet op 2026-08-22 doorgemeten: van 109
collecties hadden er DRIE een 24u-volume boven $500. De rest heeft geen handel, en
daar is een floor-prijs geen koers maar een vraagprijs. Bewaken wat niet verhandeld
wordt levert alleen meldingen op.

## De regel: floor EN volume

Een trigger vraagt allebei tegelijk:
  * de floor staat >= `floor_stijging_pct` boven de vastgelegde basis, EN
  * het 24u-volume is >= `min_volume_24h_usd` EN >= `volume_stijging_pct` boven basis.

Een floor die stijgt zonder volume is één optimistische aanbieder. Bij deze
collecties is dat het normale geval, en precies het soort melding dat je leert
wegklikken — waarna je de echte mist. Zie de meldingen-opschoning van 2026-08-22.

## Onmeetbaar telt niet als nul

Lukt de uitlezing niet (rate limit, netwerk), dan wordt de collectie
OVERGESLAGEN — niet als "floor gedaald" geboekt en niet als trigger. Dat
onderscheid ging in de eerste versie van de scan mis: alle fouten werden "niet
gelist", waarna 107 van 109 collecties ten onrechte dood heetten.

## Wat het bewust NIET doet

Geen totale waarde uitrekenen. floor x stuks is een bovengrens die je bij verkoop
niet haalt, want je duwt je eigen floor omlaag zodra je meerdere stuks aanbiedt.
"""

import json
import os
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
CONFIG = os.path.join(WORTEL, "research", "nft_watch.json")
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
PAUZE_SEC = 6.0


def markt(contract):
    """("ok", dict) | ("niet_gelist", None) | ("onbekend", None)."""
    url = "https://api.coingecko.com/api/v3/nfts/ethereum/contract/%s" % contract
    for poging in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            d = json.load(urllib.request.urlopen(req, timeout=25))
            return "ok", {
                "floor_usd": (d.get("floor_price") or {}).get("usd"),
                "floor_eth": (d.get("floor_price") or {}).get("native_currency"),
                "vol24_usd": (d.get("volume_24h") or {}).get("usd"),
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


def _in_cooldown(staat, naam, dagen):
    laatst = (staat.get(naam) or {}).get("laatste_melding")
    if not laatst:
        return False
    try:
        t = datetime.fromisoformat(laatst)
    except Exception:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - t < timedelta(days=dagen)


def main():
    alleen_tonen = "--status" in sys.argv
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    dr = cfg["drempels"]
    staat = cfg.get("staat") or {}
    nu = datetime.now(timezone.utc)

    treffers, regels, overgeslagen = [], [], []
    for c in cfg["collecties"]:
        status, m = markt(c["contract"])
        time.sleep(PAUZE_SEC)
        if status != "ok" or not m or m.get("floor_usd") is None:
            overgeslagen.append("%s (%s)" % (c["naam"], status))
            continue

        floor, vol = float(m["floor_usd"]), float(m.get("vol24_usd") or 0.0)
        b_floor = float(c["basis_floor_usd"]) or 1.0
        b_vol = float(c["basis_volume_24h_usd"]) or 1.0
        d_floor = (floor / b_floor - 1) * 100
        d_vol = (vol / b_vol - 1) * 100

        regels.append("  %-20s floor $%9.2f (%+6.1f%%)  vol $%9.0f (%+7.1f%%)  x%d"
                      % (c["naam"], floor, d_floor, vol, d_vol, c["stuks"]))

        raakt = (d_floor >= dr["floor_stijging_pct"]
                 and vol >= dr["min_volume_24h_usd"]
                 and d_vol >= dr["volume_stijging_pct"])
        if raakt and not _in_cooldown(staat, c["naam"], dr["cooldown_dagen"]):
            treffers.append(
                "<b>%s</b> — floor $%.2f (%+.0f%% t.o.v. $%.2f), volume $%.0f (%+.0f%%). "
                "Je hebt er %d." % (c["naam"], floor, d_floor, b_floor, vol, d_vol, c["stuks"]))
            staat.setdefault(c["naam"], {})["laatste_melding"] = nu.isoformat(timespec="seconds")
        staat.setdefault(c["naam"], {}).update(
            {"floor_usd": floor, "vol24_usd": vol, "gemeten": nu.isoformat(timespec="seconds")})

    print("NFT-bewaking %s" % nu.strftime("%Y-%m-%d %H:%M UTC"))
    print("\n".join(regels) or "  (niets uitgelezen)")
    if overgeslagen:
        # Expliciet: dit is GEEN 'geen markt' en GEEN daling.
        print("  overgeslagen (niet uitgelezen, geen oordeel): %s" % ", ".join(overgeslagen))

    if not alleen_tonen:
        cfg["staat"] = staat
        cfg["laatst_gedraaid"] = nu.isoformat(timespec="seconds")
        with open(CONFIG, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    uit = os.getenv("GITHUB_OUTPUT")
    if treffers:
        bericht = ("🖼️ <b>NFT — mogelijke verkoopkans</b>\n\n" + "\n\n".join(treffers)
                   + "\n\nFloor x stuks is een bovengrens: meerdere stuks tegelijk "
                     "aanbieden duwt de floor omlaag.")
        print("\nTRIGGER:\n" + bericht)
        if uit:
            with open(uit, "a", encoding="utf-8") as fh:
                fh.write("triggered=true\n")
                fh.write("message<<NFT_EOF\n%s\nNFT_EOF\n" % bericht)
    else:
        print("\nGeen trigger.")
        if uit:
            with open(uit, "a", encoding="utf-8") as fh:
                fh.write("triggered=false\n")


if __name__ == "__main__":
    main()
