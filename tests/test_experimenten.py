"""De gedeelde definitie van experimentverlies (utils/experimenten.py).

Eigen toetsen, want dit is de module waar kpi.py (H3) en verliesbewaking.py (verliesbudget)
allebei op leunen: gaat hier iets stil fout, dan meten beide hetzelfde verkeerde getal.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import experimenten as exp  # noqa: E402


def test_alleen_live_en_meetellend_belast_het_budget():
    assert exp.telt_mee_voor_budget({"status": "live", "verliesbudget_telt_mee": True}) is True
    assert exp.telt_mee_voor_budget({"status": "gepland", "verliesbudget_telt_mee": True}) is False
    assert exp.telt_mee_voor_budget({"status": "live", "verliesbudget_telt_mee": False}) is False
    assert exp.telt_mee_voor_budget({"status": "wacht_op_regime", "verliesbudget_telt_mee": True}) is False
    for rommel in (None, "live", 42, {}):
        assert exp.telt_mee_voor_budget(rommel) is False


def test_verlies_is_inleg_min_waarde_en_nooit_negatief():
    assert exp.verlies_usd(500.0, 480.0) == 20.0
    assert exp.verlies_usd(500.0, 650.0) == 0.0, "winst is geen negatief verlies"
    assert exp.verlies_usd(0.0, 0.0) == 0.0


def test_onmeetbaar_geeft_none_en_niet_nul():
    assert exp.verlies_usd(None, 100.0) is None
    assert exp.verlies_usd(100.0, None) is None
    assert exp.verlies_usd(float("nan"), 100.0) is None
    assert exp.verlies_usd(100.0, math.inf) is None
    assert exp.verlies_usd("", 100.0) is None


def test_startdatum_wordt_als_utc_gelezen():
    naive = exp.meet_vanaf({"verlies_meten_vanaf": "2026-09-16T00:00:00"})
    met_zone = exp.meet_vanaf({"verlies_meten_vanaf": "2026-09-16T00:00:00+00:00"})
    assert naive == met_zone, "naive tijd moet als UTC gelden, net als elders in de meting"
    assert exp.meet_vanaf({}) is None
    assert exp.meet_vanaf({"verlies_meten_vanaf": None}) is None
    assert exp.meet_vanaf({"verlies_meten_vanaf": "gisteren"}) is None


def test_het_echte_register_voldoet_aan_de_regels():
    """Struikeldraad: een experiment op live zonder startdatum is onmeetbaar, geen getal."""
    import json
    pad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config", "experimenten.json")
    with open(pad, encoding="utf-8") as fh:
        register = json.load(fh)
    for naam, e in (register.get("experimenten") or {}).items():
        # Sinds de motor (docs/MOTOR.md, 21-09): een potje is verplicht zodra een experiment
        # geld KAN houden (proeftuin of schalen, of gepland met een doelpotje). Een idee op
        # trede 0 mag er juist geen hebben; een papiertoets of een gestopte tweak die nooit
        # geld hield, heeft er geen nodig.
        if e.get("trede") == 0:
            assert not e.get("sleeve"), "%s is een idee maar heeft een potje" % naam
            continue
        kan_geld_houden = (e.get("trede", 0) >= 3
                           or e.get("status") in ("live", "gepland", "wacht_op_regime"))
        if kan_geld_houden:
            assert e.get("sleeve"), "%s kan geld houden maar heeft geen potje" % naam
        if exp.telt_mee_voor_budget(e):
            assert exp.meet_vanaf(e) is not None, (
                "%s staat live en telt mee, maar heeft geen verlies_meten_vanaf" % naam)


def _echt_register():
    import json
    pad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config", "experimenten.json")
    with open(pad, encoding="utf-8") as fh:
        return json.load(fh)


def test_hooguit_een_meetellend_experiment_per_potje():
    """A1 2026-10-12: basis_traag en basis_hype deelden potje `basis`. Dat gaf een valse H5,
    en bij geld op beide had basis_hype vals verlies gezien (inleg = alle stromen naar het
    potje, waarde = alleen zijn eigen state) — met een echte afbouw via de 50%-regel."""
    gezien = {}
    for naam, e in (_echt_register().get("experimenten") or {}).items():
        if e.get("sleeve") and e.get("verliesbudget_telt_mee"):
            assert e["sleeve"] not in gezien, "%s en %s delen potje %s" % (
                gezien.get(e["sleeve"]), naam, e["sleeve"])
            gezien[e["sleeve"]] = naam


def test_startdatum_ligt_niet_in_de_toekomst():
    """Een tikfout (2027) zou H3 stil op 0,0 zetten: geen meetbare periode."""
    import time
    for naam, e in (_echt_register().get("experimenten") or {}).items():
        vanaf = exp.meet_vanaf(e)
        if vanaf is not None:
            assert vanaf <= time.time(), "%s: verlies_meten_vanaf ligt in de toekomst" % naam
