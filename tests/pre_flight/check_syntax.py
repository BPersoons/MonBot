"""Parseert ELK Python-bestand in de repo. Geen imports, dus geen neveneffecten.

    python -m tests.pre_flight.check_syntax

## Waarom dit naast check_imports bestaat

`check_imports` importeert alleen `agents/`, `core/`, `utils/` en `integrations/`,
en dat is een verstandige keuze: een top-level script importeren voert het uit.
Maar daardoor werd `scripts/` en `research/` door niets gecontroleerd.

Op 2026-08-22 en 2026-08-23 is twee keer een Python-bestand met een syntaxfout in
`main` gepusht — `scripts/overzicht.py` en `scripts/wallet_inventaris.py`, beide
keren doordat een escape in een shell-heredoc een echte newline werd. De CI meldde
allebei de keren SUCCESS, want de check keek daar niet.

`ast.parse()` voert niets uit. Er is dus geen reden om ook maar één bestand over te
slaan, en dat maakt dit de goedkoopste vangnet die er is: het vangt precies de
fout die twee keer door de mazen glipte.
"""

import ast
import io
import os
import sys

OVERSLAAN = {".git", ".venv", "venv", "__pycache__", "node_modules", ".claude"}


def main(wortel=None):
    wortel = wortel or os.getcwd()
    fouten, geteld = [], 0

    for pad, mappen, bestanden in os.walk(wortel):
        mappen[:] = [m for m in mappen if m not in OVERSLAAN and not m.startswith(".")]
        for naam in bestanden:
            if not naam.endswith(".py"):
                continue
            vol = os.path.join(pad, naam)
            rel = os.path.relpath(vol, wortel)
            try:
                bron = io.open(vol, encoding="utf-8").read()
            except Exception as e:
                # Niet kunnen lezen is GEEN "geen fout" — apart melden.
                fouten.append((rel, "niet leesbaar: %s" % str(e)[:80]))
                continue
            try:
                ast.parse(bron, filename=rel)
                geteld += 1
            except SyntaxError as e:
                fouten.append((rel, "regel %s: %s" % (e.lineno, e.msg)))

    print("Syntaxcheck: %d bestanden geparseerd" % geteld)
    if fouten:
        print("\n%d BESTAND(EN) KAPOT:" % len(fouten))
        for rel, msg in fouten:
            print("  %-52s %s" % (rel, msg))
        return 1
    print("Alles parseert.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
