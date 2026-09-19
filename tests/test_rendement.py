"""De meter achter de M3-poort: APR per protocol uit de share price.

A2-audit 2026-09-19, bevinding 1: de poortcriteria stonden in het register, maar geen code
las ze. Een poort die niet te meten is, kan niet gehaald worden.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import rendement as r  # noqa: E402
from utils import verliesbewaking as vb  # noqa: E402

DAG = 86400.0
NU = 1_800_000_000.0

REGISTER = {
    "experimenten": {
        "fluid_rente": {
            "protocol_id": "fluid-fusdc-arbitrum",
            "poort": {"min_apr_pct": 4.0, "max_afwijking_defillama_pp": 1.0, "min_dagen": 14},
            "kill": {"dagen_onder_benchmark": 30},
        }
    }
}


def _reeks(koers0, koers1, dagen, eind=NU):
    return {"eerste": {"koers": koers0, "ts": eind - dagen * DAG},
            "laatste": {"koers": koers1, "ts": eind}}


def test_apr_van_een_bekende_groei():
    """1% in 30 dagen ≈ 12,9% per jaar (samengesteld)."""
    m = r.apr_uit_reeks(_reeks(1.0, 1.01, 30), NU)
    assert m["apr_pct"] == pytest.approx(12.91, abs=0.05) and m["dagen"] == 30.0


def test_storten_en_opnemen_veranderen_de_meting_niet():
    """Share price is per definitie flow-gecorrigeerd: dezelfde koersen, ander kapitaal."""
    a = r.apr_uit_reeks(_reeks(1.05, 1.0605, 14), NU)
    b = r.apr_uit_reeks(_reeks(1.05, 1.0605, 14), NU)
    assert a == b and a["apr_pct"] > 0


def test_te_kort_gemeten_is_onmeetbaar_geen_nul():
    assert r.apr_uit_reeks(_reeks(1.0, 1.0001, 0.2), NU) is None


def test_lege_of_kapotte_reeks_is_onmeetbaar():
    for reeks in ({}, None, {"eerste": {}}, {"eerste": {"koers": 0, "ts": 1}, "laatste": {"koers": 1, "ts": 2}}):
        assert r.apr_uit_reeks(reeks, NU) is None


def _state(fluid, aave, dagelijks=None):
    st = {"rendement_reeks": {"fluid-fusdc-arbitrum": dict(fluid), r.BENCHMARK_ID: dict(aave)}}
    if dagelijks:
        for pid, punten in dagelijks.items():
            st["rendement_reeks"][pid]["dagelijks"] = punten
    return st


def test_poort_is_onmeetbaar_zolang_de_veertien_dagen_niet_vol_zijn():
    p = r.poort("fluid-fusdc-arbitrum", _state(_reeks(1.0, 1.002, 5), _reeks(1.0, 1.0004, 5)),
                REGISTER, defillama_apr_pct=4.3, nu=NU)
    assert p["gehaald"] is None and "5.0 van de 14" in " ".join(p["redenen"])


def test_poort_gehaald_met_apr_boven_de_eis_en_dicht_bij_defillama():
    p = r.poort("fluid-fusdc-arbitrum", _state(_reeks(1.0, 1.0017, 14), _reeks(1.0, 1.0011, 14)),
                REGISTER, defillama_apr_pct=4.5, nu=NU)
    assert p["gehaald"] is True
    assert p["gemeten"]["apr_pct"] == pytest.approx(4.53, abs=0.1)
    assert p["spread_pp"] == pytest.approx(1.6, abs=0.15), "spread tegen Aave over hetzelfde venster"


def test_poort_zakt_onder_de_vier_procent():
    p = r.poort("fluid-fusdc-arbitrum", _state(_reeks(1.0, 1.0014, 14), _reeks(1.0, 1.0011, 14)),
                REGISTER, defillama_apr_pct=3.7, nu=NU)
    assert p["gehaald"] is False and "onder de eis" in " ".join(p["redenen"])


def test_poort_zonder_defillama_is_onmeetbaar_niet_gehaald():
    """De eis staat in het register; zonder vergelijking mag hij niet stil wegvallen."""
    p = r.poort("fluid-fusdc-arbitrum", _state(_reeks(1.0, 1.0017, 14), _reeks(1.0, 1.0011, 14)),
                REGISTER, defillama_apr_pct=None, nu=NU)
    assert p["gehaald"] is None and "DeFiLlama" in " ".join(p["redenen"])


def test_poort_zakt_op_een_te_grote_afwijking_van_defillama():
    p = r.poort("fluid-fusdc-arbitrum", _state(_reeks(1.0, 1.0017, 14), _reeks(1.0, 1.0011, 14)),
                REGISTER, defillama_apr_pct=8.0, nu=NU)
    assert p["gehaald"] is False and "wijkt" in " ".join(p["redenen"])


def _dagpunten(start, groei_per_dag, n, eind=NU):
    return [{"koers": start * (groei_per_dag ** i), "ts": eind - (n - 1 - i) * DAG} for i in range(n)]


def test_kill_regel_telt_dagen_onder_de_benchmark():
    st = _state(_reeks(1.0, 1.0014, 31), _reeks(1.0, 1.0011, 31),
                dagelijks={"fluid-fusdc-arbitrum": _dagpunten(1.0, 1.00005, 32),
                           r.BENCHMARK_ID: _dagpunten(1.0, 1.00010, 32)})
    assert r.dagen_onder_benchmark(st, "fluid-fusdc-arbitrum") == 31
    p = r.poort("fluid-fusdc-arbitrum", st, REGISTER, defillama_apr_pct=1.8, nu=NU)
    assert p["gehaald"] is False and "KILL-regel" in " ".join(p["redenen"])


def test_kill_regel_is_onmeetbaar_met_een_te_korte_reeks():
    st = _state(_reeks(1.0, 1.0017, 14), _reeks(1.0, 1.0011, 14))
    assert r.dagen_onder_benchmark(st, "fluid-fusdc-arbitrum") is None


def test_check24_bewaart_de_eerste_meting_en_een_punt_per_dag():
    st = {}
    vb._boek_rendementsmeting(st, "fluid-fusdc-arbitrum", 1.0, NU)
    vb._boek_rendementsmeting(st, "fluid-fusdc-arbitrum", 1.001, NU + 300)      # zelfde dag
    vb._boek_rendementsmeting(st, "fluid-fusdc-arbitrum", 1.002, NU + DAG + 60)
    reeks = st["rendement_reeks"]["fluid-fusdc-arbitrum"]
    assert reeks["eerste"] == {"koers": 1.0, "ts": NU}, "de eerste meting blijft staan"
    assert reeks["laatste"]["koers"] == 1.002
    assert len(reeks["dagelijks"]) == 2, "hooguit één punt per dag"


def test_check24_negeert_een_onbruikbare_koers():
    st = {}
    for slecht in (0, None, -1.0):
        vb._boek_rendementsmeting(st, "x", slecht, NU)
    assert st == {}


def test_de_reeks_staat_los_van_het_lopende_maximum():
    """`share_prices` is een maximum voor dalingsdetectie; een maximum is geen meetreeks."""
    st = {"share_prices": {"fluid-fusdc-arbitrum": 9.99}}
    vb._boek_rendementsmeting(st, "fluid-fusdc-arbitrum", 1.0, NU)
    assert st["share_prices"]["fluid-fusdc-arbitrum"] == 9.99
    assert st["rendement_reeks"]["fluid-fusdc-arbitrum"]["eerste"]["koers"] == 1.0


def test_het_register_koppelt_het_experiment_aan_het_protocol():
    """Zonder protocol_id vindt de meter de poortcriteria niet terug."""
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "config", "experimenten.json"), encoding="utf-8") as fh:
        reg = json.load(fh)
    assert reg["experimenten"]["fluid_rente"]["protocol_id"] == "fluid-fusdc-arbitrum"
