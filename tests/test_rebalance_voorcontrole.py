"""REBALANCE controleert de hele keten vóór de Aave-opname (M3-voorwaarde, 2026-09-17).

Keten: Aave-opname (treasury) → USDC naar de vault (treasury) → bridge (vault). Een
tekort op de vault bleek eerder pas ná de opname, en dan bleef het geld op Arbitrum
liggen (18-07, 23-07). En zonder vault-sleutel viel de code terug op de agent-wallet:
een ander HL-account.
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import treasury_executor as te  # noqa: E402

VAULT = "0x92D4D9D4c0371D10F3d62194ECD7d43eB9E4F445"
AGENT = "0xE18F196100000000000000000000000000000001"
ADRES_VAN = {"TKEY": te._TREASURY_WALLET, "VKEY": VAULT, "AKEY": AGENT}

T_MIN = te._MIN_ETH_FOR_GAS + te._GAS_MARGE_FACTOR * 2 * te._GAS_KOSTEN_AAVE_ETH
V_MIN = te._MIN_ETH_FOR_GAS + te._GAS_MARGE_FACTOR * te._GAS_KOSTEN_BRIDGE_ETH


class _NepAccount:
    @staticmethod
    def from_key(sleutel):
        return MagicMock(address=ADRES_VAN[sleutel])


@pytest.fixture(autouse=True)
def omgeving(monkeypatch):
    monkeypatch.setenv("HL_VAULT_ADDRESS", VAULT)
    monkeypatch.delenv("HL_WALLET_ADDRESS", raising=False)
    monkeypatch.setattr(te, "_fetch_secret_rest", lambda naam: "")
    monkeypatch.setattr(te, "_EthAccount", _NepAccount)
    monkeypatch.setattr(te, "get_vault_private_key", lambda: "VKEY")
    # Niets mag een echte transactie sturen.
    monkeypatch.setattr(te, "_send_tx", MagicMock(side_effect=AssertionError("geen tx in deze toets")))


def _saldi(monkeypatch, treasury, vault):
    vragen = []

    def nep_rpc(methode, params):
        assert methode == "eth_getBalance"
        vragen.append(params[0])
        waarde = {te._TREASURY_WALLET.lower(): treasury, VAULT.lower(): vault}[params[0].lower()]
        if isinstance(waarde, Exception):
            raise waarde
        return hex(int(round(waarde * 10 ** 18)))

    monkeypatch.setattr(te, "_rpc", nep_rpc)
    return vragen


def _rebalance(monkeypatch):
    opname = MagicMock(return_value="0xabc")
    monkeypatch.setattr(te, "withdraw_aave_to_wallet", opname)
    meldingen = []
    p = {"id": "TRR_t", "type": "REBALANCE", "status": "APPROVED", "amount_usd": 250.0}
    uit = te.advance_proposal(p, private_key="TKEY", telegram_fn=meldingen.append)
    return uit, opname, meldingen


def test_stand_na_de_bijvulling_van_vanavond_mag_rebalancen(monkeypatch):
    _saldi(monkeypatch, treasury=0.000474, vault=0.000147)
    uit, opname, _ = _rebalance(monkeypatch)
    assert uit["status"] == "REBALANCING"
    opname.assert_called_once_with(250.0, "TKEY")


def test_te_weinig_gas_op_de_vault_neemt_niets_op(monkeypatch):
    _saldi(monkeypatch, treasury=0.001, vault=0.000101)
    uit, opname, meldingen = _rebalance(monkeypatch)
    opname.assert_not_called()
    assert uit["status"] == "FAILED"
    assert "vault" in uit["error"] and "Niets opgenomen" in uit["error"]
    assert "aave_withdrawn_at" not in uit, "anders meldt Check 25 gestrand geld dat er niet is"
    assert meldingen, "Bart hoort dat de rebalance niet doorging"


def test_treasury_met_gas_voor_een_stap_maar_niet_voor_de_keten(monkeypatch):
    """0,000105 ETH haalt de per-stap-controle van de opname, maar niet de overboeking erna."""
    _saldi(monkeypatch, treasury=0.000105, vault=0.001)
    uit, opname, _ = _rebalance(monkeypatch)
    opname.assert_not_called()
    assert "treasury" in uit["error"]


@pytest.mark.parametrize("rol", ["treasury", "vault"])
def test_de_grens_ligt_precies_op_het_minimum(monkeypatch, rol):
    ruim = {"treasury": 0.001, "vault": 0.001}
    minimum = {"treasury": T_MIN, "vault": V_MIN}[rol]
    _saldi(monkeypatch, **dict(ruim, **{rol: minimum * 1.0001}))
    te._rebalance_kan_afmaken("TKEY")
    _saldi(monkeypatch, **dict(ruim, **{rol: minimum * 0.999}))
    with pytest.raises(RuntimeError, match=rol):
        te._rebalance_kan_afmaken("TKEY")


def test_marge_is_ruimer_dan_een_losse_transactie():
    assert T_MIN >= te._MIN_ETH_FOR_GAS + 2 * te._GAS_KOSTEN_AAVE_ETH * 2
    assert V_MIN >= te._MIN_ETH_FOR_GAS + te._GAS_KOSTEN_BRIDGE_ETH * 2


def test_geen_vaultsleutel_neemt_niets_op(monkeypatch):
    _saldi(monkeypatch, treasury=0.001, vault=0.001)
    monkeypatch.setattr(te, "get_vault_private_key", lambda: "")
    uit, opname, _ = _rebalance(monkeypatch)
    opname.assert_not_called()
    assert "vault-sleutel" in uit["error"]


def test_terugvalsleutel_van_de_agent_wallet_wordt_geweigerd(monkeypatch):
    """get_vault_private_key valt terug op HL_PRIVATE_KEY: dat is een ander HL-account."""
    vragen = _saldi(monkeypatch, treasury=0.001, vault=0.001)
    monkeypatch.setattr(te, "get_vault_private_key", lambda: "AKEY")
    uit, opname, _ = _rebalance(monkeypatch)
    opname.assert_not_called()
    assert "ander HL-account" in uit["error"]
    assert vragen == [], "eerst het adres, dan pas saldi lezen"


def test_onbekend_vaultadres_neemt_niets_op(monkeypatch):
    _saldi(monkeypatch, treasury=0.001, vault=0.001)
    monkeypatch.delenv("HL_VAULT_ADDRESS", raising=False)
    monkeypatch.setattr("utils.gcp_secrets.get_secret", lambda *a, **k: None)
    uit, opname, _ = _rebalance(monkeypatch)
    opname.assert_not_called()
    assert "onbekend" in uit["error"]


def test_onleesbaar_saldo_neemt_niets_op(monkeypatch):
    _saldi(monkeypatch, treasury=0.001, vault=RuntimeError("rpc weg"))
    uit, opname, _ = _rebalance(monkeypatch)
    opname.assert_not_called()
    assert "onleesbaar" in uit["error"]


def test_bridge_weigert_een_vaultsleutel_van_een_ander_account(monkeypatch):
    """Ook voor voorstellen die al ná de opname staan (BRIDGE_BACK_NEEDED van vóór deze wijziging)."""
    monkeypatch.setattr(te, "_verify_is_contract", MagicMock(return_value=True))
    monkeypatch.setattr(te, "get_arb_usdc_balance", MagicMock(return_value=250.0))
    with pytest.raises(RuntimeError, match="another HL account"):
        te._bridge_usdc_to_hl(250.0, "TKEY", "AKEY")
    te._send_tx.assert_not_called()


def test_bridge_weigert_als_het_vaultadres_onbekend_is(monkeypatch):
    monkeypatch.delenv("HL_VAULT_ADDRESS", raising=False)
    monkeypatch.setattr("utils.gcp_secrets.get_secret", lambda *a, **k: None)
    monkeypatch.setattr(te, "_verify_is_contract", MagicMock(return_value=True))
    with pytest.raises(RuntimeError, match="onbekend"):
        te._bridge_usdc_to_hl(250.0, "TKEY", "VKEY")
    te._send_tx.assert_not_called()


def test_bridge_met_de_juiste_vaultsleutel_gaat_voorbij_de_adrescontrole(monkeypatch):
    monkeypatch.setattr(te, "_verify_is_contract", MagicMock(return_value=True))
    monkeypatch.setattr(te, "_check_eth_gas", MagicMock(side_effect=RuntimeError("stop hier")))
    with pytest.raises(RuntimeError, match="stop hier"):
        te._bridge_usdc_to_hl(250.0, "TKEY", "VKEY")


def test_overboeking_in_de_bridge_gebruikt_een_schatting_met_ondergrens(monkeypatch):
    """A1-audit: de vaste 80k werd tot 78% gebruikt; een tekort daar valt ná de opname."""
    monkeypatch.setattr(te, "_verify_is_contract", MagicMock(return_value=True))
    monkeypatch.setattr(te, "_check_eth_gas", MagicMock())
    monkeypatch.setattr(te, "get_arb_usdc_balance", MagicMock(return_value=250.0))
    schatting = MagicMock(return_value=123_456)
    monkeypatch.setattr(te, "_estimate_gas", schatting)
    verstuurd = []

    def nep_send(to, data, pk, gas, value=0):
        verstuurd.append((to, gas))
        raise RuntimeError("stop na de overboeking")

    monkeypatch.setattr(te, "_send_tx", nep_send)
    with pytest.raises(RuntimeError, match="stop na de overboeking"):
        te._bridge_usdc_to_hl(250.0, "TKEY", "VKEY")
    assert verstuurd == [(te._USDC_ARB, 123_456)]
    args = schatting.call_args.args
    assert args[0] == te._USDC_ARB and args[2] == te._TREASURY_WALLET and args[3] == te._GAS_TRANSFER


def test_bridge_back_wacht_als_het_vaultadres_even_onbekend_is(monkeypatch):
    """A1-audit: dat gaf FAILED ná de opname; bij een ontbrekende sleutel wachtte hij al."""
    monkeypatch.delenv("HL_VAULT_ADDRESS", raising=False)
    monkeypatch.setattr("utils.gcp_secrets.get_secret", lambda *a, **k: None)
    brug = MagicMock()
    monkeypatch.setattr(te, "_bridge_usdc_to_hl", brug)
    p = {"id": "TRR_w", "type": "REBALANCE", "status": "BRIDGE_BACK_NEEDED", "amount_usd": 250.0,
         "aave_withdrawn_at": "2026-09-17T20:00:00+00:00"}
    uit = te.advance_proposal(dict(p), private_key="TKEY", telegram_fn=lambda m: None)
    assert uit["status"] == "BRIDGE_BACK_NEEDED"
    brug.assert_not_called()
