"""Gas bijvullen tussen eigen wallets — het enige pad dat waarde verstuurt.

De treasury-wallet heeft ~0,000124 ETH en de code weigert al onder 0,0001, dus er past
één Fluid-switch en daarna stopt kasbeheer. De hoofdwallet heeft 0,000497 ETH op Arbitrum;
een interne overboeking lost dat op zonder nieuw geld.

Wat hier wordt vastgelegd is vooral wat dit pad NIET mag doen. Twee dingen kwamen uit de
A1-audit van 2026-09-16 en waren in de eerste versie fout:
- 21.000 gas is een L1-getal; op Arbitrum weigert de keten de transactie ("intrinsic gas
  too low", gemeten schatting 22.599). De gaslimiet komt nu uit een schatting mét `value`.
- Zonder receipt-controle ziet een mislukte overboeking eruit als geslaagd, terwijl het gas
  wél weg is.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import treasury_executor as te  # noqa: E402

VAULT = "0x92D4D9D4c0371D10F3d62194ECD7d43eB9E4F445"


def _rpc_mock(saldo_eth=0.000497, schatting=22_599, gezien=None):
    def rpc(methode, params):
        if methode == "eth_getBalance":
            return hex(int(round(saldo_eth * 10 ** 18)))
        if methode == "eth_estimateGas":
            if gezien is not None:
                gezien.append(params[0])
            return hex(schatting)
        raise AssertionError("onverwachte RPC-aanroep: %s" % methode)
    return rpc


def _account(adres=VAULT):
    acc = MagicMock()
    acc.from_key.return_value.address = adres
    return acc


def _omgeving(saldo_eth=0.000497, schatting=22_599, status="0x1", gezien=None, afzender=VAULT):
    """Alle patches voor een geslaagde aanroep; `verstuurd` vangt wat _send_tx kreeg."""
    verstuurd = {}

    def send_tx(to, data, pk, gas, value=0):
        verstuurd.update({"to": to, "data": data, "gas": gas, "value": value})
        return "0xhash"

    patches = [
        patch.object(te, "_rpc", _rpc_mock(saldo_eth, schatting, gezien)),
        patch.object(te, "_send_tx", send_tx),
        patch.object(te, "_wait_receipt", lambda h, **kw: ({"status": status} if status else None)),
        patch.object(te, "_EthAccount", _account(afzender)),
        patch.object(te, "_vault_adres", lambda: VAULT),
    ]
    return patches, verstuurd


def _met(patches, fn):
    import contextlib
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return fn()


def test_stuurt_het_bedrag_met_een_gaslimiet_uit_de_schatting():
    gezien = []
    patches, verstuurd = _omgeving(gezien=gezien)
    h = _met(patches, lambda: te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.00035, "0xkey"))
    assert h == "0xhash"
    assert verstuurd["to"] == te._TREASURY_WALLET and verstuurd["data"] == "0x"
    assert verstuurd["value"] == 350_000_000_000_000, "0,00035 ETH in wei"
    assert verstuurd["gas"] >= 22_599, "moet boven de gemeten schatting liggen"
    assert verstuurd["gas"] >= 40_000, "ondergrens vastgepind, niet via de constante zelf"
    assert gezien and "value" in gezien[0], "de schatting moet de waarde meesturen"


def test_weigert_boven_de_bovengrens():
    patches, verstuurd = _omgeving(saldo_eth=5.0)
    with pytest.raises(RuntimeError, match="buiten de toegestane grens"):
        _met(patches, lambda: te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.01, "0xkey"))
    assert not verstuurd


def test_weigert_nul_en_negatief():
    for bedrag in (0.0, -0.0005):
        patches, verstuurd = _omgeving()
        with pytest.raises(RuntimeError, match="buiten de toegestane grens"):
            _met(patches, lambda: te.stuur_eth_voor_gas(te._TREASURY_WALLET, bedrag, "0xkey"))
        assert not verstuurd


def test_weigert_een_andere_bestemming():
    """Ook een eigen wallet is niet goed genoeg: alleen de treasury-wallet."""
    patches, verstuurd = _omgeving()
    with pytest.raises(RuntimeError, match="alleen naar de treasury-wallet"):
        _met(patches, lambda: te.stuur_eth_voor_gas(
            "0xBd6c7F3D15C86f745170c34A692B22F7706683cC", 0.0003, "0xkey"))
    assert not verstuurd


def test_weigert_een_andere_afzender():
    """A1-audit: alleen de bestemming was vastgezet, de sleutel niet."""
    patches, verstuurd = _omgeving(afzender="0xE18F1961000000000000000000000000000000AA")
    with pytest.raises(RuntimeError, match="alleen vanaf de vault-wallet"):
        _met(patches, lambda: te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.00035, "0xkey"))
    assert not verstuurd


def test_weigert_als_het_vault_adres_onbekend_is():
    patches, verstuurd = _omgeving()
    patches[-1] = patch.object(te, "_vault_adres", lambda: "")
    with pytest.raises(RuntimeError, match="Vault-adres onbekend"):
        _met(patches, lambda: te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.00035, "0xkey"))
    assert not verstuurd


def test_weigert_als_de_afzender_te_weinig_overhoudt():
    """0,00045 sturen vanaf 0,000497 laat te weinig over voor de eigen gasmarge."""
    patches, verstuurd = _omgeving(saldo_eth=0.000497)
    with pytest.raises(RuntimeError, match="nodig"):
        _met(patches, lambda: te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.00045, "0xkey"))
    assert not verstuurd


def test_mislukte_transactie_is_geen_succes():
    """A1-audit: zonder receipt-controle ziet een mislukking eruit als geslaagd."""
    patches, verstuurd = _omgeving(status="0x0")
    with pytest.raises(RuntimeError, match="MISLUKT"):
        _met(patches, lambda: te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.00035, "0xkey"))
    assert verstuurd, "hij is wél verstuurd — daarom moet de fout luid zijn"


def test_geen_receipt_is_onbekend_en_zegt_niet_opnieuw_starten():
    """Geen receipt ≠ mislukt: de transactie kan alsnog landen. Opnieuw starten = dubbel."""
    patches, _ = _omgeving(status=None)
    with pytest.raises(RuntimeError, match="ONBEKEND") as fout:
        _met(patches, lambda: te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.00035, "0xkey"))
    assert "NIET opnieuw starten" in str(fout.value)


def test_haperende_hermeting_maakt_een_gelukte_overboeking_geen_fout():
    """De receipt (0x1) is het bewijs; de hermeting erna is alleen informatie."""
    patches, verstuurd = _omgeving()
    telling = {"n": 0}

    def rpc(methode, params):
        if methode == "eth_estimateGas":
            return hex(22_599)
        if methode == "eth_getBalance":
            telling["n"] += 1
            if telling["n"] > 1:                       # de hermeting ná de receipt
                raise RuntimeError("All Arbitrum RPCs failed")
            return hex(int(0.000497 * 10 ** 18))
        raise AssertionError(methode)

    patches[0] = patch.object(te, "_rpc", rpc)
    h = _met(patches, lambda: te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.00035, "0xkey"))
    assert h == "0xhash" and verstuurd, "geslaagd blijft geslaagd"


# ── `_vault_adres`: één definitie, direct getoetst ──────────────────────────────
# A1-audit 2026-09-17: de functie zelf werd door geen enkele toets geraakt (de toetsen
# hierboven vervangen hem). Drie mutaties bleven daardoor groen.

AGENT = "0xE18F1961000000000000000000000000000000AA"


def test_vault_adres_valt_nooit_terug_op_de_agent_wallet(monkeypatch):
    monkeypatch.delenv("HL_VAULT_ADDRESS", raising=False)
    monkeypatch.setenv("HL_WALLET_ADDRESS", AGENT)
    with patch("utils.gcp_secrets.get_secret", return_value=""), \
         patch.object(te, "_fetch_secret_rest", lambda naam: ""):
        assert te._vault_adres() == "", "de agent-wallet is een ander account"


def test_vault_adres_gebruikt_de_rest_weg_als_de_sdk_leeg_is(monkeypatch):
    monkeypatch.delenv("HL_VAULT_ADDRESS", raising=False)
    gevraagd = []

    def rest(naam):
        gevraagd.append(naam)
        return VAULT if naam == "HL_VAULT_ADDRESS" else ""

    with patch("utils.gcp_secrets.get_secret", return_value=""), \
         patch.object(te, "_fetch_secret_rest", rest):
        assert te._vault_adres() == VAULT
    assert gevraagd == ["HL_VAULT_ADDRESS"], "nooit om HL_WALLET_ADDRESS vragen"


def test_vault_adres_neemt_de_sdk_als_die_hem_heeft(monkeypatch):
    monkeypatch.delenv("HL_VAULT_ADDRESS", raising=False)
    rest = MagicMock(return_value="")
    with patch("utils.gcp_secrets.get_secret", return_value=VAULT), \
         patch.object(te, "_fetch_secret_rest", rest):
        assert te._vault_adres() == VAULT
    assert not rest.called, "REST is de laatste weg, niet de eerste"


def test_opname_client_komt_niet_uit_op_de_agent_wallet(monkeypatch):
    """Sleutel wél, vault-adres níét: dan geen client — zeker niet een voor de agent-wallet."""
    monkeypatch.setenv("HL_VAULT_PRIVATE_KEY", "0x" + "1" * 64)
    monkeypatch.setenv("HL_WALLET_ADDRESS", AGENT)
    with patch.object(te, "_vault_adres", lambda: ""):
        assert te._create_vault_withdrawal_client() is None


def test_send_tx_stuurt_standaard_geen_waarde():
    """Elke bestaande aanroeper doet een contract-aanroep; die moet value 0 houden."""
    ondertekend = {}

    class _Acc:
        @staticmethod
        def from_key(pk):
            return MagicMock(address=VAULT)

        @staticmethod
        def sign_transaction(tx, pk):
            ondertekend.update(tx)
            return MagicMock(raw_transaction=b"\x01")

    def rpc(methode, params):
        return {"eth_getTransactionCount": "0x1", "eth_gasPrice": hex(100_000_000),
                "eth_sendRawTransaction": "0xhash"}[methode]

    with patch.object(te, "_rpc", rpc), patch.object(te, "_EthAccount", _Acc):
        te._send_tx("0xdoel", "0xdata", "0xkey", 100_000)
    assert ondertekend["value"] == 0

    with patch.object(te, "_rpc", rpc), patch.object(te, "_EthAccount", _Acc):
        te._send_tx("0xdoel", "0x", "0xkey", 40_000, value=123)
    assert ondertekend["value"] == 123


def test_afzender_houdt_de_reserve_van_de_hoofdwallet_over():
    """A1-audit 2026-09-17: met alleen _MIN_ETH_FOR_GAS kon een toegestane bijvulling de
    REBALANCE blokkeren en Check 26 laten afgaan. Nu één reserve voor alle drie."""
    net_te_weinig = 0.0002 + te._HOOFDWALLET_RESERVE_ETH - 1e-9
    patches, verstuurd = _omgeving(saldo_eth=net_te_weinig)
    with pytest.raises(RuntimeError, match="reserve"):
        _met(patches, lambda: te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.0002, "0xkey"))
    assert not verstuurd
    assert net_te_weinig > 0.0002 + te._MIN_ETH_FOR_GAS, "de oude grens had dit doorgelaten"


def test_bijvulling_van_vanavond_past_binnen_de_reserve():
    """0,00035 vanaf 0,000497046 (gemeten 17-09) laat ~0,000147 over: boven de reserve."""
    assert 0.000497046 >= 0.00035 + te._HOOFDWALLET_RESERVE_ETH



def test_reserve_rekent_de_kosten_van_de_overboeking_mee():
    """A1-audit r2: precies op de grens eindigde de hoofdwallet ~4,6e-7 onder de reserve."""
    op_de_grens = 0.0002 + te._HOOFDWALLET_RESERVE_ETH + 1e-9
    patches, verstuurd = _omgeving(saldo_eth=op_de_grens)
    with pytest.raises(RuntimeError, match="reserve"):
        _met(patches, lambda: te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.0002, "0xkey"))
    assert not verstuurd
    assert te._GAS_KOSTEN_OVERBOEKING_ETH >= 4.3e-7
