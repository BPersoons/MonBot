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


def test_geld_onderweg_houdt_basislijn_en_meldt_als_het_te_lang_duurt(register):
    st = {"yield_saldo": {"usd": 1000.0, "ts": NU - 3600}}
    g, st = vb.evalueer(_basis(yield_totaal_usd=600.0, kasbeheer_onderweg=True), st, register, [], nu=NU)
    assert not g and st["yield_saldo"]["usd"] == 1000.0, "tijdens een transit blijft de basislijn staan"
    g, st = vb.evalueer(_basis(yield_totaal_usd=600.0, kasbeheer_onderweg=True), st, register, [],
                        nu=NU + 7 * 3600)
    assert "saldo_check_uit:alarm" in _sleutels(g), "een transit die blijft hangen moet opvallen"


def test_verlies_tijdens_transit_wordt_na_de_transit_gezien(register):
    """A1-audit ronde 2: een verlies tijdens een transit mag niet in de basislijn verdwijnen."""
    st = {"yield_saldo": {"usd": 1000.0, "ts": NU - 3600}}
    _, st = vb.evalueer(_basis(yield_totaal_usd=700.0, kasbeheer_onderweg=True), st, register, [], nu=NU)
    # Transit klaar: REBALANCE van $100 naar HL geboekt — maar het potje staat op $700, niet $900.
    stroom = [{"ts": NU + 60, "van": "yield_core", "naar": "swarm", "bedrag_usd": 100.0}]
    g, _ = vb.evalueer(_basis(yield_totaal_usd=700.0), st, register, stroom, nu=NU + 300)
    assert "yield_saldo:kill" in _sleutels(g)


def test_geen_valse_kill_na_deploy_yield_race(register):
    """A1-audit ronde 1: geld telt al mee vóór de stroom geboekt is."""
    st = {"yield_saldo": {"usd": 1000.0, "ts": NU - 7200}}
    # $300 staat al op de treasury-wallet, proposal BRIDGED.
    g1, st = vb.evalueer(_basis(yield_totaal_usd=1300.0, kasbeheer_onderweg=True), st, register, [],
                         nu=NU - 3500)
    # Proposal DEPLOYED, stroom geboekt.
    stroom = [{"ts": NU - 3000, "van": "swarm", "naar": "yield_core", "bedrag_usd": 300.0}]
    g2, st = vb.evalueer(_basis(yield_totaal_usd=1300.0), st, register, stroom, nu=NU - 2900)
    g3, st = vb.evalueer(_basis(yield_totaal_usd=1300.0), st, register, stroom, nu=NU + 60)
    assert not any(x["sleutel"] == "yield_saldo" for x in g1 + g2 + g3), "valse kill na DEPLOY_YIELD"
    # Daarna weer gewoon oordelen: 1,15% daling zonder stroom -> kill.
    g4, _ = vb.evalueer(_basis(yield_totaal_usd=1285.0), st, register, stroom, nu=NU + 3660)
    assert "yield_saldo:kill" in _sleutels(g4), "de bewaking moet na de stroom weer werken"


def test_leeggetrokken_protocol_is_een_kill_binnen_een_ronde(register):
    """A1-audit ronde 2: een geslaagde on-chain 0 is een echt verlies, geen 'onmeetbaar'."""
    st = {"yield_saldo": {"usd": 2490.0, "ts": NU - 300}}
    g, _ = vb.evalueer(_basis(yield_totaal_usd=0.0, yield_balances={"aave": 0.0}), st, register, [], nu=NU)
    assert "yield_saldo:kill" in _sleutels(g)


def test_mislukte_onchain_uitlezing_is_onmeetbaar_geen_nul(register):
    st = {"yield_saldo": {"usd": 2490.0, "ts": NU - 300}}
    g, st = vb.evalueer(_basis(yield_totaal_usd=None), st, register, [], nu=NU)
    assert not any(x["sleutel"] == "yield_saldo" for x in g), "RPC-fout gezien als verlies"
    assert st["yield_saldo"]["usd"] == 2490.0 and st["onmeetbaar"]["yield_totaal_usd"] == 1


def test_saldi_onchain_rekent_aave_vault_en_wallet(monkeypatch):
    import utils.treasury_yield_oracle as yo
    antwoorden = {
        ("0xatoken", "0x70a08231"): hex(2_490_150_079),
        ("0xvault", "0x70a08231"): hex(500 * 10 ** 18),
        ("0xvault", "0x07a2d13a"): hex(565_000_000),
        (vb.USDC_ARB, "0x70a08231"): hex(12_500_000),
    }
    monkeypatch.setattr(yo, "_eth_call", lambda to, data: antwoorden[(to, data[:10])])
    protocollen = [
        {"id": "aave", "type": "aave_v3", "automated": True, "receipt_token": "0xatoken"},
        {"id": "fluid", "type": "erc4626", "automated": True, "vault_address": "0xvault"},
        {"id": "uit", "type": "erc4626", "automated": False, "vault_address": "0xnooit"},
    ]
    saldi, wallet = vb._saldi_onchain(protocollen)
    assert saldi == {"aave": 2490.150079, "fluid": 565.0} and wallet == 12.5

    def kapot(to, data):
        raise RuntimeError("alle RPC's weg")
    monkeypatch.setattr(yo, "_eth_call", kapot)
    assert vb._veilig(vb._saldi_onchain, protocollen) is None, "een mislukte uitlezing is geen 0"


def test_dip_koper_stilstand(register):
    g, _ = vb.evalueer(_basis(dip_koper_stilstand_min=240.0), {}, register)
    assert "dip_koper_stilstand:alarm" in _sleutels(g)
    g, _ = vb.evalueer(_basis(dip_koper_stilstand_min=12.0), {}, register)
    assert "dip_koper_stilstand:alarm" not in _sleutels(g)


def test_share_price_rekent_met_decimalen():
    def nep_call(to, data):
        if data == "0x313ce567":
            return hex(18)
        assert data.startswith("0x07a2d13a") and int(data[10:], 16) == 10 ** 18
        return hex(1_050_000)   # 1,05 USDC per heel aandeel
    with patch("utils.treasury_yield_oracle._eth_call", nep_call):
        assert vb._erc4626_share_price("0xvault") == 1.05
    with patch("utils.treasury_yield_oracle._eth_call",
               lambda to, data: hex(18) if data == "0x313ce567" else "0x0"):
        assert vb._veilig(vb._erc4626_share_price, "0xvault") is None, "prijs 0 is onmeetbaar"


def test_hlp_niet_gevonden_is_onmeetbaar():
    with patch.object(vb, "_http_json", return_value=[]):
        assert vb._veilig(vb._hlp_equity, "0xuser", "0xvault") is None


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
