"""Saldi van rendementsprotocollen: `automated` zegt waar geld HEEN mag, niet waar het LIGT.

A2-audit 2026-09-15, bevinding 6: Fluid terugzetten op `automated: false` terwijl er geld in
staat liet dat geld uit alle totalen verdwijnen — een valse drawdown en een verkeerde
concentratie. Gerepareerd 2026-09-19.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import treasury_agent as ta  # noqa: E402
from utils import treasury_executor as te  # noqa: E402

CONFIG = [
    {"id": "aave-v3-arbitrum-usdc", "type": "aave_v3", "automated": True},
    {"id": "fluid-fusdc-arbitrum", "type": "erc4626", "automated": False,
     "vault_address": "0x1A996cb54bb95462040408c06122D45D6Cdb6096"},
    {"id": "compound-v3-arbitrum-usdc", "type": "compound_v3", "automated": False},
    {"id": "kapot-zonder-vault", "type": "erc4626", "automated": True},
]


def _agent(monkeypatch, aave=None, erc=None):
    agent = object.__new__(ta.TreasuryAgent)
    agent._load_protocol_config = MagicMock(return_value=CONFIG)
    monkeypatch.setattr(te, "lees_aave_saldo", aave or (lambda w: 2490.35))
    monkeypatch.setattr(te, "lees_erc4626_saldo", erc or (lambda v, w: 871.0))
    return agent


def test_geld_in_een_niet_automated_protocol_telt_gewoon_mee(monkeypatch):
    saldi = _agent(monkeypatch)._get_yield_balances()
    assert saldi["fluid-fusdc-arbitrum"] == 871.0
    assert saldi["aave-v3-arbitrum-usdc"] == 2490.35


def test_terugdraaien_naar_automated_false_geeft_geen_valse_drawdown(monkeypatch):
    """Het scenario uit de audit: de vlag gaat uit, het geld blijft staan."""
    aan = list(CONFIG)
    aan[1] = dict(aan[1], automated=True)
    agent = _agent(monkeypatch)
    agent._load_protocol_config = MagicMock(return_value=aan)
    voor = sum(agent._get_yield_balances().values())
    agent._load_protocol_config = MagicMock(return_value=CONFIG)   # vlag weer uit
    na = sum(agent._get_yield_balances().values())
    assert voor == na == pytest.approx(3361.35)


def test_onleesbaar_saldo_telt_niet_als_nul(monkeypatch):
    def kapot(v, w):
        raise RuntimeError("RPC weg")

    saldi = _agent(monkeypatch, erc=kapot)._get_yield_balances()
    assert "fluid-fusdc-arbitrum" not in saldi, "onmeetbaar is geen nul"
    assert saldi["aave-v3-arbitrum-usdc"] == 2490.35, "de rest blijft gewoon meetellen"


def test_onbekend_type_telt_niet_als_nul(monkeypatch):
    saldi = _agent(monkeypatch)._get_yield_balances()
    assert "compound-v3-arbitrum-usdc" not in saldi


def test_erc4626_zonder_vaultadres_telt_niet_als_nul(monkeypatch):
    saldi = _agent(monkeypatch)._get_yield_balances()
    assert "kapot-zonder-vault" not in saldi


def test_concentratie_rekent_met_het_echte_totaal(monkeypatch):
    """Zonder de fix zou Aave 100% lijken terwijl het 74% is — en dan verplaatst
    diversificatie een bedrag dat nergens op slaat."""
    saldi = _agent(monkeypatch)._get_yield_balances()
    totaal = sum(saldi.values())
    assert saldi["aave-v3-arbitrum-usdc"] / totaal == pytest.approx(0.741, abs=0.01)


def test_strikte_lezer_gooit_door_waar_de_milde_nul_teruggeeft(monkeypatch):
    def kapot(*a, **k):
        raise RuntimeError("RPC weg")

    monkeypatch.setattr(te, "_rpc", kapot)
    with pytest.raises(RuntimeError):
        te.lees_aave_saldo(te._TREASURY_WALLET)
    with pytest.raises(RuntimeError):
        te.lees_erc4626_saldo("0x" + "a" * 40, te._TREASURY_WALLET)
    assert te.get_aave_balance(te._TREASURY_WALLET) == 0.0
    assert te.get_erc4626_balance("0x" + "a" * 40, te._TREASURY_WALLET) == 0.0


def test_leeg_antwoord_is_een_storing_geen_nul(monkeypatch):
    """A1-audit 19-09, bevinding 5: `"0x"` is geen nul maar een call die niet is uitgevoerd.

    Een echte nul komt terug als 32 nulbytes. Deze toets legde eerder het verkeerde gedrag
    vast (0.0 bij `"0x"`), en juist dat voedde de spookbeweging uit bevinding 4.
    """
    monkeypatch.setattr(te, "_rpc", lambda m, p: "0x")
    with pytest.raises(RuntimeError, match="onmeetbaar"):
        te.lees_aave_saldo(te._TREASURY_WALLET)
    with pytest.raises(RuntimeError, match="onmeetbaar"):
        te.lees_erc4626_saldo("0x" + "a" * 40, te._TREASURY_WALLET)


def test_echte_nul_is_gewoon_nul(monkeypatch):
    """32 nulbytes = de wallet heeft niets in dit protocol. Dat is een meting."""
    monkeypatch.setattr(te, "_rpc", lambda m, p: "0x" + "0" * 64)
    assert te.lees_aave_saldo(te._TREASURY_WALLET) == 0.0
    assert te.lees_erc4626_saldo("0x" + "a" * 40, te._TREASURY_WALLET) == 0.0


def test_aandelen_zonder_waarde_is_een_storing_geen_nul(monkeypatch):
    """Wél aandelen, maar convertToAssets geeft niets terug: dat is onmeetbaar."""
    antwoorden = {"0x70a08231": hex(5_000_000), "0x07a2d13a": "0x"}
    monkeypatch.setattr(te, "_rpc", lambda m, p: antwoorden[p[0]["data"][:10]])
    with pytest.raises(RuntimeError, match="onmeetbaar"):
        te.lees_erc4626_saldo("0x" + "a" * 40, te._TREASURY_WALLET)


# ── Dezelfde fout zat op DRIE plekken; tel ze in de code (guard-dekking) ──────

PROTOCOLLEN = [
    {"id": "aave-v3-arbitrum-usdc", "type": "aave_v3", "automated": True,
     "receipt_token": "0x724dc807b04555b71ed48a6896b6F41593b8C637"},
    {"id": "fluid-fusdc-arbitrum", "type": "erc4626", "automated": False,
     "vault_address": "0x1A996cb54bb95462040408c06122D45D6Cdb6096"},
    {"id": "compound-v3-arbitrum-usdc", "type": "compound_v3", "automated": False},
]


def test_verliesbewaking_ziet_geld_in_een_niet_automated_protocol(monkeypatch):
    from utils import verliesbewaking as vb

    def nep_eth_call(to, data):
        if data.startswith("0x07a2d13a"):
            return hex(871_000_000)                 # convertToAssets → $871
        return hex(1_000_000_000)                   # balanceOf → aandelen/saldo

    monkeypatch.setattr("utils.treasury_yield_oracle._eth_call", nep_eth_call)
    saldi, wallet = vb._saldi_onchain(PROTOCOLLEN)
    assert "fluid-fusdc-arbitrum" in saldi and saldi["fluid-fusdc-arbitrum"] == pytest.approx(871.0)
    assert wallet == pytest.approx(1000.0)


def test_verliesbewaking_gooit_door_bij_een_mislukte_uitlezing(monkeypatch):
    from utils import verliesbewaking as vb

    monkeypatch.setattr("utils.treasury_yield_oracle._eth_call", lambda to, data: "0x")
    with pytest.raises(ValueError):
        vb._saldi_onchain(PROTOCOLLEN)


def test_totaalsom_in_de_executor_telt_niet_automated_ook_mee(monkeypatch, tmp_path):
    import json as _json
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "treasury_protocols.json").write_text(
        _json.dumps({"protocols": PROTOCOLLEN}), encoding="utf-8")
    monkeypatch.setattr(te, "get_aave_balance", lambda w: 2490.0)
    monkeypatch.setattr(te, "get_erc4626_balance", lambda v, w: 871.0)
    assert te.get_total_yield_balance(te._TREASURY_WALLET) == pytest.approx(3361.0)


def test_geen_enkele_saldo_lus_filtert_nog_op_automated():
    """Guard-dekking: drie plekken lazen saldi en sloegen niet-automated protocollen over."""
    import inspect
    for functie in (ta.TreasuryAgent._get_yield_balances,
                    te.get_total_yield_balance):
        bron = inspect.getsource(functie)
        assert 'if not cfg.get("automated")' not in bron, functie.__name__
    from utils import verliesbewaking as vb
    assert 'if not p.get("automated")' not in inspect.getsource(vb._saldi_onchain)


# ── Beslissen gebeurt op de STRIKTE saldi (audit 19-09, bevinding 4) ─────────

def _beslis_agent(strikt, mild=None):
    agent = object.__new__(ta.TreasuryAgent)
    agent._deploy_geblokkeerd = MagicMock(return_value=False)
    agent._strikte_yield_saldi = MagicMock(return_value=strikt)
    agent._check_yield_switch = MagicMock(side_effect=lambda o, b, p: (p + [("switch", b)], ["s"]))
    agent._check_yield_diversification = MagicMock(side_effect=lambda o, b, p: (p + [("div", b)], ["d"]))
    return agent


def test_onleesbare_saldi_geven_geen_enkele_beweging():
    agent = _beslis_agent(None)
    voorstellen, s, d = agent._switch_en_diversificatie([], {"aave": 2490.0}, [])
    assert voorstellen == [] and s == [] and d == []
    agent._check_yield_switch.assert_not_called()


def test_een_protocol_dat_alleen_in_het_milde_dict_staat_blokkeert_de_ronde():
    """Het spookscenario: Fluid ontbreekt strikt, Aave lijkt dan 100% en er vuurt een switch."""
    agent = _beslis_agent({"aave": 2490.0})
    voorstellen, s, d = agent._switch_en_diversificatie([], {"aave": 2490.0, "fluid": 871.0}, [])
    assert voorstellen == [] and s == [] and d == []


def test_beslissing_gebruikt_de_strikte_bedragen_niet_de_milde():
    agent = _beslis_agent({"aave": 2490.0, "fluid": 871.0})
    voorstellen, _, _ = agent._switch_en_diversificatie([], {"aave": 2490.0, "fluid": 0.0}, [])
    gebruikt = [b for naam, b in voorstellen]
    assert all(b["fluid"] == 871.0 for b in gebruikt), "milde nul mag niet doorwerken"


def test_diversificatiedoel_ligt_nooit_boven_de_cap_uit_het_register(monkeypatch):
    """Zet het register op 50% en de diversificatie mag niet op 65% blijven mikken."""
    import inspect
    bron = inspect.getsource(ta.TreasuryAgent._check_yield_diversification)
    assert "min(_DIVERSIFY_TARGET_PCT, cap_pct)" in bron
    monkeypatch.setattr(ta, "_max_aandeel_per_protocol", lambda: (0.50, "aave-v3-arbitrum-usdc"))
    assert min(ta._DIVERSIFY_TARGET_PCT, ta._max_aandeel_per_protocol()[0] * 100) == 50.0


# ── verliesbewaking: adres zonder leesroute is een storing, geen nul ─────────

def test_protocol_met_adres_maar_zonder_leesroute_is_een_storing(monkeypatch):
    from utils import verliesbewaking as vb
    monkeypatch.setattr("utils.treasury_yield_oracle._eth_call", lambda to, data: hex(10 ** 9))
    with pytest.raises(ValueError, match="geen leesroute"):
        vb._saldi_onchain([{"id": "raar", "type": "compound_v3", "automated": True,
                            "comet_address": "0xc0ffee"}])


def test_protocol_zonder_adres_is_gewoon_uit(monkeypatch):
    """compound-v3 staat bewust zonder adres in de config: geen alarm, geen logruis."""
    from utils import verliesbewaking as vb
    monkeypatch.setattr("utils.treasury_yield_oracle._eth_call", lambda to, data: hex(10 ** 9))
    saldi, wallet = vb._saldi_onchain([{"id": "compound-v3-arbitrum-usdc", "type": "compound_v3",
                                        "automated": False, "comet_address": None}])
    assert saldi == {} and wallet == 1000.0


# ── Eén werkende RPC: opnieuw proberen is de echte buffer (19-09) ────────────

def test_eth_call_probeert_opnieuw_na_een_hapering(monkeypatch):
    from utils import treasury_yield_oracle as yo

    pogingen = []

    class _Antwoord:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"jsonrpc":"2.0","id":1,"result":"0x2a"}'

    def nep_urlopen(req, timeout=None):
        pogingen.append(req.full_url)
        if len(pogingen) <= len(yo._ARB_RPCS):      # eerste ronde faalt overal
            raise OSError("HTTP Error 403: Forbidden")
        return _Antwoord()

    monkeypatch.setattr(yo.urllib.request, "urlopen", nep_urlopen)
    monkeypatch.setattr(yo.time, "sleep", lambda s: None)
    assert yo._eth_call("0xdead", "0xbeef") == "0x2a"
    assert len(pogingen) == len(yo._ARB_RPCS) + 1, "tweede ronde begint weer bovenaan"


def test_eth_call_gooit_door_als_alles_blijft_falen(monkeypatch):
    from utils import treasury_yield_oracle as yo

    n = []

    def nep_urlopen(req, timeout=None):
        n.append(1)
        raise OSError("HTTP Error 403: Forbidden")

    monkeypatch.setattr(yo.urllib.request, "urlopen", nep_urlopen)
    monkeypatch.setattr(yo.time, "sleep", lambda s: None)
    with pytest.raises(OSError):
        yo._eth_call("0xdead", "0xbeef")
    assert len(n) == len(yo._ARB_RPCS) * yo._POGINGEN, "elke ronde alle endpoints"


def test_een_protocol_zonder_adres_geeft_geen_waarschuwing(monkeypatch, caplog):
    """Compound staat bewust zonder adres in de config; elke ronde waarschuwen is ruis."""
    import logging
    with caplog.at_level(logging.WARNING, logger="TreasuryAgent"):
        _agent(monkeypatch)._get_yield_balances()
    assert not [r for r in caplog.records if "compound" in r.getMessage()]
