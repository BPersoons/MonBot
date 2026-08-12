#!/usr/bin/env python3
"""PostToolUse-hook: herinner aan het vastleggen van learnings na een git commit.

## Waarom een commit de trigger is

Elke echte les uit de sessie van 2026-08-11/12 eindigde in een commitbericht: de
ccxt-spotprijsval, de self.logger-bug, de state-drift, de requirements-resolutie.
Een commit markeert het moment waarop iets is uitgezocht en afgerond — precies
waar een les ontstaat. Bij een willekeurige bewerking is dat niet zo.

## Wat deze hook NIET doet

Hij schrijft niets. Het knelpunt is niet het opschrijven maar het *oordelen*: een
script kan niet bepalen of iets een niet-triviale, sessie-overstijgende les is.
Automatisch memory vullen zou hem binnen een week vol ruis zetten, en dat is
precies wat de memory-instructies verbieden ("niet opslaan wat uit de code
afleidbaar is, of wat alleen deze conversatie raakt").

Daarom: alleen een herinnering, met "niets doen" als expliciet geldige uitkomst.
Een reminder die tot schrijven dwingt, produceert ruis in plaats van kennis.

Nooit blokkerend: faalt deze hook, dan gaat de commit gewoon door.
"""
import json
import re
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

if data.get("tool_name") != "Bash":
    sys.exit(0)

commando = (data.get("tool_input") or {}).get("command", "") or ""

# Alleen een ECHTE commit. `git commit --dry-run`, `git log`-regels die het woord
# bevatten, en `--amend --no-edit` op een al gemelde commit vallen af.
if not re.search(r"\bgit\s+commit\b", commando) or "--dry-run" in commando:
    sys.exit(0)

# Was het een lege commit (niets te committen)? Dan geen herinnering.
uitvoer = (data.get("tool_response") or {}).get("stdout", "") or ""
if "nothing to commit" in uitvoer or "no changes added" in uitvoer:
    sys.exit(0)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": (
            "Er is zojuist gecommit. Beoordeel — kort — of hier iets in zit dat "
            "vastgelegd moet worden, en waar:\n"
            "  • memory — een niet-triviale les die een VOLGENDE sessie zonder deze "
            "context niet kan afleiden (een valkuil, een gecorrigeerde aanname, een "
            "beslissing met reden). Bestaat er al een memory over? Werk die dan bij "
            "in plaats van een tweede te maken.\n"
            "  • CLAUDE.md — een valkuil of conventie die bij het werken in deze repo "
            "steeds opnieuw opspeelt.\n"
            "  • een skill in .claude/commands/ — een werkwijze die herhaald wordt.\n"
            "  • docs/ — een besluit of route die het plan raakt.\n\n"
            "GEEN van bovenstaande is een prima uitkomst en de meest voorkomende: een "
            "bugfix die uit de code zelf blijkt, of iets dat alleen deze conversatie "
            "raakt, hoort NIET in memory. Schrijf in dat geval niets en ga door — "
            "meld het niet eens. Alleen melden als je iets vastlegt."
        ),
    }
}))
sys.exit(0)
