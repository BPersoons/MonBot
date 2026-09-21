"""Uitstapsignaal voor het wereldindexfonds (motor trede 2, schaduw).

    python research/uitstapsignaal.py meet      # na een maandslot: stand vastleggen
    python research/uitstapsignaal.py stand     # huidige stand tonen, niets schrijven

Besluit Bart 21-09: stabiel groeien, met een in- en uitstaplaag per bezit. De regel (slot
onder het 10-maandsgemiddelde -> uit, erboven -> in) slaagde op papier op brede markten:
VS 1927-2026, ontwikkeld buiten de VS en Europa 1991-2026 (research/uitstapregel*.py). Hij
zakte door op crypto en op losse industrieën, dus GEEN signaal voor GRID of de kern-crypto.

VOORAF VASTGELEGD (21-09):
- Instrument: WEBN.DE in euro's, precies wat we houden. IWDA.AS (MSCI World, euro's) staat
  ernaast als controle; verschillen ze van stand, dan staat dat in de melding.
- Alleen afgesloten maanden tellen: het slot van de lopende maand is nog geen maandslot.
- Onmeetbaar is geen 'in': zonder koers wordt er niets vastgelegd en niets gemeld.
- Een melding alleen als de stand omslaat (in -> uit of uit -> in). DeGiro heeft geen API,
  dus Bart voert uit. In de schaduwfase is het een advies, geen opdracht.
- Schaduwmeting: vanaf de eerste vooruit gemeten maand rendement regel tegen vasthouden.
  Teruggerekende maanden (vóór 2026-09) tellen daar niet in mee.
"""

import io
import json
import math
import os
import sys
from datetime import date

LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uitstap_signaal.json")
INSTRUMENT = "WEBN.DE"
CONTROLE = "IWDA.AS"
VENSTER = 10
EERSTE_VOORUIT = "2026-09"


def maandsloten(dagkoersen, vandaag):
    """{'JJJJ-MM': slot} van afgesloten maanden; de lopende maand valt weg."""
    loopt = "%04d-%02d" % (vandaag.year, vandaag.month)
    uit = {}
    for dag, koers in sorted(dagkoersen.items()):
        if koers is None or not math.isfinite(koers) or koers <= 0:
            continue
        maand = dag[:7]
        if maand < loopt:
            uit[maand] = koers
    return uit


def standen(sloten):
    """[(maand, slot, gemiddelde, 'in'/'uit')] vanaf de eerste maand met een vol venster."""
    maanden = sorted(sloten)
    rijen = []
    for i in range(VENSTER - 1, len(maanden)):
        venster = [sloten[m] for m in maanden[i - VENSTER + 1:i + 1]]
        gem = sum(venster) / VENSTER
        slot = sloten[maanden[i]]
        rijen.append((maanden[i], slot, gem, "in" if slot > gem else "uit"))
    return rijen


def schaduw(maanden):
    """Rendement regel tegen vasthouden over de vooruit gemeten maanden (fracties)."""
    vooruit = [m for m in maanden if not m.get("teruggerekend")]
    regel = vast = 1.0
    for vorige, nu in zip(vooruit, vooruit[1:]):
        r = nu["slot"] / vorige["slot"] - 1
        vast *= 1 + r
        if vorige["stand"] == "in":
            regel *= 1 + r
    return {"maanden": max(len(vooruit) - 1, 0), "regel": regel - 1, "vasthouden": vast - 1}


def _dagkoersen(ticker):
    try:
        import yfinance as yf
        d = yf.download(ticker, period="3y", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
        return {ts.strftime("%Y-%m-%d"): float(v) for ts, v in d.items()}
    except Exception as exc:
        print("%s niet uitgelezen: %s" % (ticker, exc))
        return {}


def _laad():
    if not os.path.exists(LEDGER):
        return {"_comment": "Schaduwreeks van het uitstapsignaal (research/uitstapsignaal.py). "
                            "Alleen toevoegen; teruggerekende maanden zijn gemarkeerd.",
                "instrument": INSTRUMENT, "venster_maanden": VENSTER, "maanden": []}
    with io.open(LEDGER, encoding="utf-8") as fh:
        return json.load(fh)


def _schrijf(d):
    with io.open(LEDGER, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def verwerk(ledger, rijen, controle_rijen):
    """Voegt nieuwe maanden toe. Geeft (melding of None) terug."""
    bekend = {m["maand"] for m in ledger["maanden"]}
    controle = {m: s for m, _, _, s in controle_rijen}
    melding = None
    for maand, slot, gem, stand in rijen:
        if maand in bekend:
            continue
        vorige = ledger["maanden"][-1] if ledger["maanden"] else None
        ledger["maanden"].append({
            "maand": maand, "slot": round(slot, 4), "gem10": round(gem, 4), "stand": stand,
            "controle_stand": controle.get(maand),
            "teruggerekend": maand < EERSTE_VOORUIT,
        })
        if vorige and vorige["stand"] != stand and maand >= EERSTE_VOORUIT:
            actie = ("verkoop WEBN en parkeer de euro's in een geldmarktfonds"
                     if stand == "uit" else "koop WEBN terug met het geparkeerde geld")
            melding = ("<b>Uitstapsignaal WEBN: %s</b>\nSlot %s €%.2f, 10-maandsgemiddelde €%.2f (%+.1f%%).\n"
                       "Regel: %s.\nControle MSCI World (IWDA): %s.\n"
                       "Schaduwfase: advies, jij beslist en voert uit bij DeGiro."
                       % (stand.upper(), maand, slot, gem, (slot / gem - 1) * 100, actie,
                          controle.get(maand) or "onbekend"))
    return melding


def _emit(melding):
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with io.open(out, "a", encoding="utf-8") as fh:
        fh.write("triggered=%s\n" % ("true" if melding else "false"))
        fh.write("message<<UITSTAP_EOF\n%s\nUITSTAP_EOF\n" % (melding or ""))


def main(argv):
    opdracht = argv[1] if len(argv) > 1 else "stand"
    vandaag = date.today()
    rijen = standen(maandsloten(_dagkoersen(INSTRUMENT), vandaag))
    controle_rijen = standen(maandsloten(_dagkoersen(CONTROLE), vandaag))
    if not rijen:
        print("ONMEETBAAR: geen maandsloten voor %s — niets vastgelegd, geen melding." % INSTRUMENT)
        _emit(None)
        return 0
    maand, slot, gem, stand = rijen[-1]
    print("%s slot %s: €%.2f, 10-maandsgemiddelde €%.2f (%+.1f%%) -> %s"
          % (INSTRUMENT, maand, slot, gem, (slot / gem - 1) * 100, stand.upper()))
    if controle_rijen:
        print("controle %s %s: %s" % (CONTROLE, controle_rijen[-1][0], controle_rijen[-1][3].upper()))
    if opdracht != "meet":
        return 0
    ledger = _laad()
    melding = verwerk(ledger, rijen, controle_rijen)
    _schrijf(ledger)
    s = schaduw(ledger["maanden"])
    print("schaduw over %d vooruit gemeten maand(en): regel %+.1f%%, vasthouden %+.1f%%"
          % (s["maanden"], s["regel"] * 100, s["vasthouden"] * 100))
    if melding:
        print(melding)
    _emit(melding)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
