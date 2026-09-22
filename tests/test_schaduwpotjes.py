"""Schaduwpotjes (research/schaduwpotjes.py): de regels van een uitschieterpotje, op papier."""

import copy
import math

import pandas as pd

from research import schaduwpotjes as sp

REGELS = {"stop_verlies_pct": 40, "laten_lopen_tot_winst_pct": 100, "trailing_vanaf_top_pct": 30,
          "oogst_boven_x": 2.0, "kosten_per_order_eur": 0.0, "kosten_pct": 0.0, "funding_pct_per_jaar": 0.0}


def _pot(**regels):
    r = dict(REGELS, **regels)
    return {"instrumenten": {"A": "EUR", "B": "EUR"}, "inleg_eur": 100, "regels": r, "thema_fonds": "T",
            "start": "2026-01-01", "status": "loopt", "gestart_op": None}


def _gestart(**regels):
    return sp.start(_pot(**regels), {"A": 10.0, "B": 10.0}, "2026-01-01", 1.0)


def test_start_gelijk_gewogen_met_kosten():
    pot = sp.start(_pot(kosten_per_order_eur=3.0), {"A": 10.0, "B": 20.0}, "2026-01-01", 1.0)
    assert math.isclose(pot["posities"]["A"]["stuks"], 4.7) and math.isclose(pot["posities"]["B"]["stuks"], 2.35)
    assert math.isclose(sp.waarde(pot, {"A": 10.0, "B": 20.0}, 1.0), 94.0)


def test_stop_bij_min_40_procent():
    pot = _gestart()
    sp.verwerk_dag(pot, {"A": 6.1, "B": 10.0}, "2026-01-02", 1.0, 1)      # -39%: blijft
    assert pot["posities"]["A"]["open"]
    sp.verwerk_dag(pot, {"A": 5.9, "B": 10.0}, "2026-01-03", 1.0, 1)      # -41%: stop
    assert not pot["posities"]["A"]["open"] and math.isclose(pot["kas_eur"], 29.5)


def test_geen_trailing_voor_verdubbeling():
    pot = _gestart()
    sp.verwerk_dag(pot, {"A": 19.0, "B": 10.0}, "2026-01-02", 1.0, 1)     # +90%
    sp.verwerk_dag(pot, {"A": 12.0, "B": 10.0}, "2026-01-03", 1.0, 1)     # -37% onder de top
    assert pot["posities"]["A"]["open"], "winst laten lopen tot +100%"


def test_trailing_na_verdubbeling():
    pot = _gestart(oogst_boven_x=0)
    sp.verwerk_dag(pot, {"A": 22.0, "B": 10.0}, "2026-01-02", 1.0, 1)     # +120%
    sp.verwerk_dag(pot, {"A": 15.6, "B": 10.0}, "2026-01-03", 1.0, 1)     # -29% onder de top: blijft
    assert pot["posities"]["A"]["open"]
    sp.verwerk_dag(pot, {"A": 15.3, "B": 10.0}, "2026-01-04", 1.0, 1)     # -30,5%: trailing
    assert not pot["posities"]["A"]["open"]


def test_oogst_boven_twee_keer_de_inleg_naar_de_kern():
    pot = _gestart()
    sp.verwerk_dag(pot, {"A": 40.0, "B": 10.0}, "2026-01-02", 1.0, 1)     # potje 250 = 2,5x
    assert math.isclose(pot["kern_stuks"], 50.0)                           # overschot 50 tegen kern-koers 1
    assert math.isclose(sp.waarde(pot, {"A": 40.0, "B": 10.0}, 1.0), 250.0)
    zonder_kern = sp.waarde(pot, {"A": 40.0, "B": 10.0}, 1.0) - pot["kern_stuks"] * 1.0
    assert math.isclose(zonder_kern, 200.0)


def test_funding_kost_per_kalenderdag():
    pot = _gestart(funding_pct_per_jaar=5.5)
    sp.verwerk_dag(pot, {"A": 10.0, "B": 10.0}, "2026-01-04", 1.0, 3)      # weekend: 3 dagen
    assert math.isclose(pot["kas_eur"], -100 * 0.055 * 3 / 365)


def _koersen(rijen):
    return pd.DataFrame(rijen).set_index("dag")


def test_bijwerken_wacht_tot_alle_koersen_er_zijn_en_is_herhaalbaar():
    d = {"potjes": {"p": _pot()}}
    k = _koersen([
        {"dag": "2026-01-01", "A": 10.0, "B": float("nan"), sp.KERN: 1.0, "T": 1.0},
        {"dag": "2026-01-02", "A": 10.0, "B": 10.0, sp.KERN: 1.0, "T": 1.0},
        {"dag": "2026-01-05", "A": 11.0, "B": 10.0, sp.KERN: 1.1, "T": 1.2},
    ])
    sp.bijwerken(d, k)
    pot = d["potjes"]["p"]
    assert pot["gestart_op"] == "2026-01-02"
    assert len(pot["reeks"]) == 1 and math.isclose(pot["reeks"][0]["waarde_eur"], 105.0)
    assert math.isclose(pot["reeks"][0]["kern_eur"], 110.0) and math.isclose(pot["reeks"][0]["thema_eur"], 120.0)
    eerst = copy.deepcopy(pot)
    sp.bijwerken(d, k)
    assert pot == eerst, "nog een keer draaien mag niets veranderen"


def test_ontbrekende_koers_zet_het_potje_stil():
    d = {"potjes": {"p": _pot()}}
    k = _koersen([
        {"dag": "2026-01-02", "A": 10.0, "B": 10.0, sp.KERN: 1.0, "T": 1.0},
        {"dag": "2026-01-05", "A": float("nan"), "B": 10.0, sp.KERN: 1.0, "T": 1.0},
        {"dag": "2026-01-06", "A": 12.0, "B": 10.0, sp.KERN: 1.0, "T": 1.0},
    ])
    meldingen = sp.bijwerken(d, k)
    assert any("ONMEETBAAR op 2026-01-05" in m for m in meldingen)
    assert d["potjes"]["p"]["laatste_dag"] == "2026-01-02", "geen verzonnen waarde, geen sprong eroverheen"
