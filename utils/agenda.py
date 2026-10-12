"""Herinnering aan wat alleen Bart kan doen (besluit 2026-10-12, Q2).

Werk op de VM kan zelf doorlopen, maar een sessie, een overboeking of een besluit wacht op
Bart. Op 2026-10-10 viel daardoor de geplande verkleining van de VM weg: niemand startte
de sessie. Daarom een vaste werkronde op zaterdag, en een bericht op de dag dat iets
vervalt.

Bron: `config/agenda.json` (zit in de image). Dezelfde lijst voedt de overzichtspagina.
- zaterdag: werkronde-bericht met alles wat binnen 7 dagen vervalt of achterstallig is;
- andere dagen: alleen wat vandaag vervalt, anders niets.

`main.py` roept dit aan direct na de dagelijkse potjes-snapshot, dus hooguit één bericht
per UTC-dag, ook na een herstart.
"""
import json
import logging
import os
from datetime import date, timedelta

logger = logging.getLogger("Agenda")

AGENDA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "config", "agenda.json")
ZATERDAG = 5


def laad_items(pad=AGENDA_FILE) -> list:
    """Items met een geldige datum, gesorteerd. Een onleesbare agenda is een fout, geen lege lijst."""
    with open(pad, encoding="utf-8") as fh:
        ruw = json.load(fh)
    items = []
    for it in ruw.get("items") or []:
        items.append({"datum": date.fromisoformat(it["datum"]), "vraag": it["vraag"],
                      "uitleg": it.get("uitleg", "")})
    return sorted(items, key=lambda i: i["datum"])


def herinnering(vandaag: date, items: list):
    """Tekst voor Telegram, of None als er vandaag niets te melden is."""
    if vandaag.weekday() == ZATERDAG:
        grens = vandaag + timedelta(days=7)
        relevant = [i for i in items if i["datum"] <= grens]
        regels = ["*Werkronde vandaag* — start een sessie en zeg \"werkronde\"."]
        if relevant:
            regels.append("Op de agenda:")
        for i in relevant:
            if i["datum"] < vandaag:
                wanneer = "achterstallig sinds %s" % i["datum"].strftime("%d-%m")
            elif i["datum"] == vandaag:
                regels.append("• %s (vandaag) — %s" % (i["vraag"], i["uitleg"]))
                continue
            else:
                wanneer = i["datum"].strftime("%d-%m")
            regels.append("• %s (%s)" % (i["vraag"], wanneer))
        return "\n".join(regels)
    vandaag_items = [i for i in items if i["datum"] == vandaag]
    if not vandaag_items:
        return None
    regels = ["*Vandaag voor jou:*"]
    for i in vandaag_items:
        regels.append("• %s — %s" % (i["vraag"], i["uitleg"]))
    return "\n".join(regels)


def herinnering_vandaag(vandaag: date, pad=AGENDA_FILE):
    """Zoals `herinnering`, maar leest de agenda. Een leesfout wordt luid gelogd én gemeld:
    een stille agenda zou eruitzien als 'niets te doen'."""
    try:
        items = laad_items(pad)
    except Exception as e:
        logger.error(f"Agenda onleesbaar ({pad}): {e}")
        return "*Agenda onleesbaar* — de herinneringen staan stil: %s" % str(e)[:120]
    return herinnering(vandaag, items)
