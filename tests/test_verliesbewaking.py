"""Verliesbewaking: elke drempel vuurt, overboekingen geven geen vals alarm, en de
brandoefening bewijst het hele pad inclusief detectietijd."""
import json
import os
import sys
from unittest.mock import patch

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from utils import verliesbewaking as vb  # noqa: E402

NU = 1789500000.0


@pytest.fixture(scope="module")
def register():
    """Het ECHTE register — de toets bewaakt daarmee ook het schema."""
    with open(os.path.join(REPO, "config", "experimenten.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _basis(**extra):
    m = {"ts": NU, "aave_liquidity_index": 1.10, "yield_totaal_usd": 1000.0, "yield_ts": NU,
         "kasbeheer_onderweg": False, "share_prices": {}, "usdc_prijs": 1.0,
         "snapshot_leeftijd_uur": 1.0, "kpi_onmeetbaar": []}
    m.update(extra)
    return m


def _sleutels(gebeurtenissen):
    return {"%s:%s" % (g["sleutel"], g["niveau"]) for g in gebeurtenissen}


def test_gezonde_toestand_geeft_niets(register):
    st = {"aave_liquidity_index": 1.09, "yield_saldo": {"usd": 999.0, "ts": NU - 3600}}
    g, _ = vb.evalueer(_basis(), st, register)
    assert g == []


def test_dalende_liquidity_index_en_share_price(register):
    st = {"aave_liquidity_index": 1.11, "share_prices": {"fluid": 1.13}}
    g, nieuw = vb.evalueer(_basis(share_prices={"fluid": 1.12}), st, register)
    assert {"aave_liquidity_index:alarm", "share_price:fluid:alarm"} <= _sleutels(g)
    assert nieuw["aave_liquidity_index"] == 1.11, "basislijn mag niet mee omlaag"


def test_saldo_daling_na_flowcorrectie(register):
    st = {"yield_saldo": {"usd": 1000.0, "ts": NU - 3600}}
    # 0,5% lager zonder stroom -> alarm; 1,5% -> kill
    g, _ = vb.evalueer(_basis(yield_totaal_usd=995.0), st, register)
    assert "yield_saldo:alarm" in _sleutels(g)
    g, _ = vb.evalueer(_basis(yield_totaal_usd=985.0), st, register)
    assert "yield_saldo:kill" in _sleutels(g)
    # Dezelfde 985 na een REBALANCE van $15 eruit is GEEN verlies.
    stroom = [{"ts": NU - 1800, "van": "yield_core", "naar": "swarm", "bedrag_usd": 15.0}]
    g, _ = vb.evalueer(_basis(yield_totaal_usd=985.0), st, register, stroom)
    assert not any(x["sleutel"] == "yield_saldo" for x in g), "overboeking gezien als verlies"


def test_geld_onderweg_geeft_geen_oordeel_en_houdt_basislijn(register):
    st = {"yield_saldo": {"usd": 1000.0, "ts": NU - 3600}}
    g, nieuw = vb.evalueer(_basis(yield_totaal_usd=600.0, kasbeheer_onderweg=True), st, register)
    assert not any(x["sleutel"] == "yield_saldo" for x in g)
    assert nieuw["yield_saldo"]["usd"] == 1000.0


def test_usdc_peg(register):
    g, _ = vb.evalueer(_basis(usdc_prijs=0.99), {}, register)
    assert "usdc_peg:alarm" in _sleutels(g)
    g, _ = vb.evalueer(_basis(usdc_prijs=0.97), {}, register)
    assert "usdc_peg:kill" in _sleutels(g)


def test_hlp_drawdown_is_robuust_tegen_stortingen(register):
    g, st = vb.evalueer(_basis(hlp_inleg_usd=500.0, hlp_equity_usd=500.0), {}, register)
    assert not g
    g, st = vb.evalueer(_basis(hlp_inleg_usd=1000.0, hlp_equity_usd=1000.0), st, register)
    assert not g, "een extra storting is geen drawdown"
    g, _ = vb.evalueer(_basis(hlp_inleg_usd=1000.0, hlp_equity_usd=955.0), st, register)
    assert "hlp_drawdown:alarm" in _sleutels(g)
    g, _ = vb.evalueer(_basis(hlp_inleg_usd=1000.0, hlp_equity_usd=910.0), st, register)
    assert "hlp_drawdown:kill" in _sleutels(g)


def test_verliesbudget(register):
    g, st = vb.evalueer(_basis(hlp_inleg_usd=500.0, hlp_equity_usd=360.0), {}, register)
    assert "experimentbudget:alarm" in _sleutels(g) and st["experimentverlies_usd"] == 140.0
    g, _ = vb.evalueer(_basis(hlp_inleg_usd=500.0, hlp_equity_usd=200.0,
                              basis_verlies_usd=5.0), {}, register)
    assert "experimentbudget:kill" in _sleutels(g)


def test_onmeetbaar_wordt_na_drie_rondes_een_alarm(register):
    st = {}
    for ronde in range(1, 4):
        g, st = vb.evalueer(_basis(usdc_prijs=None), st, register)
        gevuurd = "usdc_prijs_onmeetbaar:alarm" in _sleutels(g)
        assert gevuurd is (ronde == 3), "ronde %d" % ronde
    g, st = vb.evalueer(_basis(), st, register)
    assert "usdc_prijs" not in st.get("onmeetbaar", {}), "teller moet resetten na een meting"


def test_meting_zelf_wordt_bewaakt(register):
    g, _ = vb.evalueer(_basis(snapshot_leeftijd_uur=30.0, kpi_onmeetbaar=["flows"]), {}, register)
    assert {"meting_snapshot:alarm", "meting_kpi:alarm"} <= _sleutels(g)
    g, _ = vb.evalueer(_basis(snapshot_leeftijd_uur=None), {}, register)
    assert "meting_snapshot:alarm" in _sleutels(g)


def test_cooldown_meldt_hetzelfde_niet_twee_keer(tmp_path, register):
    verstuurd = []
    pad_reg = os.path.join(REPO, "config", "experimenten.json")
    with patch.object(vb, "lees_metingen", return_value=_basis(usdc_prijs=0.97)), \
         patch.object(vb.flows, "laad_flows", return_value=[]):
        eerste = vb.run_check(verstuurd.append, nu=NU, register_pad=pad_reg,
                              state_pad=str(tmp_path / "st.json"),
                              oefening_pad=str(tmp_path / "vlag.json"))
        tweede = vb.run_check(verstuurd.append, nu=NU + 300, register_pad=pad_reg,
                              state_pad=str(tmp_path / "st.json"),
                              oefening_pad=str(tmp_path / "vlag.json"))
    assert eerste and not tweede
    assert len(verstuurd) == len(eerste)


def test_ontbrekend_register_is_zelf_een_alarm(tmp_path):
    verstuurd = []
    vb.run_check(verstuurd.append, nu=NU, register_pad=str(tmp_path / "nee.json"),
                 state_pad=str(tmp_path / "st.json"), oefening_pad=str(tmp_path / "vlag.json"))
    assert verstuurd and "NIETS bewaakt" in verstuurd[0]


def test_brandoefening_end_to_end(tmp_path):
    vlag = str(tmp_path / "vlag.json")
    staat = str(tmp_path / "st.json")
    vb.maak_oefening(pad=vlag, nu=NU)
    verstuurd = []
    with patch.object(vb, "lees_metingen", side_effect=AssertionError("oefening mag niet echt meten")):
        g = vb.run_check(verstuurd.append, nu=NU + 240,
                         register_pad=os.path.join(REPO, "config", "experimenten.json"),
                         state_pad=staat, oefening_pad=vlag)
    assert len(verstuurd) == 1 and "OEFENING" in verstuurd[0]
    assert not os.path.exists(vlag), "vlag moet na verwerking weg zijn"
    with open(staat, encoding="utf-8") as fh:
        oef = json.load(fh)["laatste_oefening"]
    assert oef["alles_gevonden"] is True, "gemist: %s" % (set(oef["verwacht"]) - set(oef["gevonden"]))
    assert oef["detectie_min"] == 4.0
    assert all(x.get("oefening") for x in g)
