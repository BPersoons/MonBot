"""Uitstapsignaal voor het wereldindexfonds (motor trede 2, schaduw).

    python research/uitstapsignaal.py meet      # na een maandslot: stand vastleggen
    python research/uitstapsignaal.py stand     # huidige stand tonen, niets schrijven

Besluit Bart 21-09: stabiel groeien, met een in- en uitstaplaag per bezit. De regel (slot
onder het 10-maandsgemiddelde -> uit, erboven -> in) is op papier een VERZEKERING TEGEN
TRAGE, DIEPE DALINGEN (1929, 2000-02, 2008), geen beter beleggen. Met 2008 erin verlaagt hij
de diepste daling met een kwart tot ruim de helft, ook tegen een vaste mix met dezelfde
blootstelling (2007-2026: x0,44 VS tot x0,74 Europa). Zonder zo'n daling (2010-2026) kost hij
1,4-2,9pp per jaar tegen die mix, bij een ongeveer gelijke daling. De enige toets in EURO'S,
op het soort fonds dat we houden (IWDA 2010-2026), haalt criterium 1 niet: rendement 9,0%
tegen 12,4% per jaar, daling x0,65 (grens x0,60). De VS-toets
haalde zijn eigen vooraf vastgelegde rendementsgrens niet (-1,8pp, grens -1,5pp). Buiten de VS
lag 1973-2005 al in Fabers steekproef (EAFE), dus echt nieuw is alleen 2007+, en daarin
beslist 2008 (audit 21-09, docs/audits/2026-09-21-uitstaplaag.md). Op crypto en losse
industrieën zakte hij door: GEEN signaal voor GRID of de kern-crypto.

VOORAF VASTGELEGD (21-09, bijgesteld na de audit):
- Instrument: WEBN.DE in euro's, precies wat we houden. IWDA.AS (MSCI World, euro's) staat
  ernaast als controle; verschillen ze van stand, dan staat dat in de melding.
- Alleen afgesloten maanden tellen: het slot van de lopende maand is nog geen maandslot.
- Onmeetbaar is geen 'in': zonder koers wordt er niets vastgelegd, en ontbreekt het slot van
  vorige maand op de 5e nog, dan volgt één luide melding.
- Een melding bij elke omslag. Zolang ADVIES False is (tot de poort van 03-11 en een besluit
  van Bart) staat er SCHADUW — GEEN ACTIE in, zonder koop- of verkoopinstructie.
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
# Pas True na de poort van 03-11 en een expliciet besluit van Bart (docs/besluiten.md).
# Tot dan is een omslag informatie over de schaduwmeting, geen opdracht.
ADVIES = False
ONMEETBAAR_NA_DAG = 5


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


def _omslag_tekst(maand, slot, gem, stand, controle_stand):
    kop = "Uitstapsignaal WEBN: %s" % stand.upper()
    regels = ["<b>%s</b>" % kop,
              "Slot %s €%.2f, 10-maandsgemiddelde €%.2f (%+.1f%%)." % (maand, slot, gem, (slot / gem - 1) * 100),
              "Controle MSCI World (IWDA): %s." % (controle_stand or "onbekend")]
    if ADVIES:
        regels.append("Regel: %s. Jij beslist en voert uit bij DeGiro."
                      % ("verkoop WEBN en parkeer de euro's in een geldmarktfonds" if stand == "uit"
                         else "koop WEBN terug met het geparkeerde geld"))
    else:
        regels.append("SCHADUW — GEEN ACTIE. Dit meet alleen of het signaal werkt; het wordt pas "
                      "advies na de poort van 03-11 en jouw besluit.")
    return "\n".join(regels)


def verwerk(ledger, rijen, controle_rijen):
    """Voegt nieuwe maanden toe (ook te laat binnengekomen, op volgorde) en geeft de
    meldingen van ALLE omslagen in deze run terug, samengevoegd, of None."""
    bekend = {m["maand"] for m in ledger["maanden"]}
    controle = {m: s for m, _, _, s in controle_rijen}
    nieuw = []
    for maand, slot, gem, stand in rijen:
        if maand in bekend:
            continue
        ledger["maanden"].append({
            "maand": maand, "slot": round(slot, 4), "gem10": round(gem, 4), "stand": stand,
            "controle_stand": controle.get(maand),
            "teruggerekend": maand < EERSTE_VOORUIT,
        })
        nieuw.append(maand)
    ledger["maanden"].sort(key=lambda m: m["maand"])
    meldingen = []
    for i, m in enumerate(ledger["maanden"]):
        if m["maand"] not in nieuw or i == 0 or m["maand"] < EERSTE_VOORUIT:
            continue
        if ledger["maanden"][i - 1]["stand"] != m["stand"]:
            meldingen.append(_omslag_tekst(m["maand"], m["slot"], m["gem10"], m["stand"],
                                           m.get("controle_stand")))
    return "\n\n".join(meldingen) or None


def _vorige_maand(vandaag):
    j, m = (vandaag.year, vandaag.month - 1) if vandaag.month > 1 else (vandaag.year - 1, 12)
    return "%04d-%02d" % (j, m)


def controleer_volledigheid(ledger, rijen, vandaag):
    """Stilte mag er niet uitzien als 'blijf in'. Ontbreekt het slot van vorige maand op
    dag ONMEETBAAR_NA_DAG nog, dan één melding per ontbrekende maand."""
    vorige = _vorige_maand(vandaag)
    # Al vastgelegd in een eerdere run telt ook: een lege yfinance-dag daarna is geen gat.
    bekend = {r[0] for r in rijen} | {m["maand"] for m in ledger.get("maanden", [])}
    if vandaag.day < ONMEETBAAR_NA_DAG or vorige in bekend:
        return None
    if ledger.get("onmeetbaar_gemeld") == vorige:
        return None
    ledger["onmeetbaar_gemeld"] = vorige
    return ("<b>Uitstapsignaal WEBN: ONMEETBAAR</b>\nHet maandslot van %s ontbreekt op %s nog "
            "(yfinance). De stand is onbekend — niet 'nog in'." % (vorige, vandaag.isoformat()))


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
        print("ONMEETBAAR: geen maandsloten voor %s — niets vastgelegd." % INSTRUMENT)
        melding = None
        if opdracht == "meet":
            ledger = _laad()
            melding = controleer_volledigheid(ledger, rijen, vandaag)
            if melding:
                _schrijf(ledger)
                print(melding)
        _emit(melding)
        return 0
    maand, slot, gem, stand = rijen[-1]
    print("%s slot %s: €%.2f, 10-maandsgemiddelde €%.2f (%+.1f%%) -> %s"
          % (INSTRUMENT, maand, slot, gem, (slot / gem - 1) * 100, stand.upper()))
    if controle_rijen:
        print("controle %s %s: %s" % (CONTROLE, controle_rijen[-1][0], controle_rijen[-1][3].upper()))
    if opdracht != "meet":
        return 0
    ledger = _laad()
    melding = "\n\n".join(x for x in (verwerk(ledger, rijen, controle_rijen),
                                      controleer_volledigheid(ledger, rijen, vandaag)) if x) or None
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
