"""Agenda-herinnering (besluit 2026-10-12): zaterdag werkronde, anders alleen de vervaldag."""
import json
import os
import sys
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from utils import agenda  # noqa: E402

ITEMS = [
    {"datum": date(2026, 10, 3), "vraag": "Oud", "uitleg": "u0"},
    {"datum": date(2026, 10, 14), "vraag": "Woensdag", "uitleg": "u1"},
    {"datum": date(2026, 10, 17), "vraag": "Zaterdag", "uitleg": "u2"},
    {"datum": date(2026, 10, 24), "vraag": "Volgende zaterdag", "uitleg": "u3"},
    {"datum": date(2026, 11, 3), "vraag": "Ver weg", "uitleg": "u4"},
]


def test_zaterdag_geeft_werkronde_met_week_en_achterstand():
    tekst = agenda.herinnering(date(2026, 10, 17), ITEMS)
    assert date(2026, 10, 17).weekday() == agenda.ZATERDAG
    assert "Werkronde vandaag" in tekst
    assert "Oud (achterstallig sinds 03-10)" in tekst
    assert "Woensdag (achterstallig sinds 14-10)" in tekst
    assert "Zaterdag (vandaag) — u2" in tekst, "wat vandaag vervalt krijgt de uitleg erbij"
    assert "u1" not in tekst and "u3" not in tekst
    assert "Volgende zaterdag (24-10)" in tekst, "7 dagen vooruit telt mee"
    assert "Ver weg" not in tekst


def test_zaterdag_zonder_items_meldt_toch_de_werkronde():
    assert "Werkronde vandaag" in agenda.herinnering(date(2026, 10, 17), [])


def test_doordeweeks_alleen_de_vervaldag():
    tekst = agenda.herinnering(date(2026, 10, 14), ITEMS)
    assert tekst.startswith("*Vandaag voor jou:*") and "Woensdag — u1" in tekst
    assert "Oud" not in tekst and "Zaterdag" not in tekst
    assert agenda.herinnering(date(2026, 10, 15), ITEMS) is None, "niets te melden = stil"


def test_echte_agenda_is_leesbaar():
    items = agenda.laad_items()
    assert items and all(isinstance(i["datum"], date) for i in items)


def test_onleesbare_agenda_is_een_melding_geen_stilte(tmp_path):
    pad = tmp_path / "agenda.json"
    pad.write_text("{kapot", encoding="utf-8")
    tekst = agenda.herinnering_vandaag(date(2026, 10, 15), str(pad))
    assert tekst and "onleesbaar" in tekst
    pad.write_text(json.dumps({"items": [{"datum": "2026-13-01", "vraag": "x"}]}), encoding="utf-8")
    assert "onleesbaar" in agenda.herinnering_vandaag(date(2026, 10, 15), str(pad))
