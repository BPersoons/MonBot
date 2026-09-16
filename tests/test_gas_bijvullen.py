"""Gas bijvullen tussen eigen wallets — het enige pad dat waarde verstuurt.

De treasury-wallet heeft ~0,000124 ETH en de code weigert al onder 0,0001, dus er past
één Fluid-switch en daarna stopt kasbeheer. De hoofdwallet heeft 0,000497 ETH op Arbitrum;
een interne overboeking lost dat op zonder nieuw geld. Omdat `_send_tx` daarvoor voor het
eerst een `value` meekrijgt, staat hier wat dat pad NIET mag doen.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import treasury_executor as te  # noqa: E402

AFZENDER = "0x92D4D9D4c0371D10F3d62194ECD7d43eB9E4F445"


def _mocks(saldo_eth=0.000497):
    """(_rpc-mock, _send_tx-mock) met een afzender die `saldo_eth` heeft."""
    verstuurd = {}

    def rpc(methode, params):
        if methode == "eth_getBalance":
            return hex(int(round(saldo_eth * 10 ** 18)))
        raise AssertionError("onverwachte RPC-aanroep: %s" % methode)

    def send_tx(to, data, pk, gas, value=0):
        verstuurd.update({"to": to, "data": data, "gas": gas, "value": value})
        return "0xhash"

    return rpc, send_tx, verstuurd


def _account_mock():
    acc = MagicMock()
    acc.from_key.return_value.address = AFZENDER
    return acc


def test_stuurt_het_bedrag_naar_de_treasury_wallet():
    rpc, send_tx, verstuurd = _mocks()
    with patch.object(te, "_rpc", rpc), patch.object(te, "_send_tx", send_tx), \
         patch.object(te, "_EthAccount", _account_mock()):
        h = te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.00035, "0xkey")
    assert h == "0xhash"
    assert verstuurd["to"] == te._TREASURY_WALLET
    assert verstuurd["value"] == 350_000_000_000_000, "0,00035 ETH in wei"
    assert verstuurd["gas"] == 21_000 and verstuurd["data"] == "0x", "kale overboeking"


def test_weigert_boven_de_bovengrens():
    rpc, send_tx, verstuurd = _mocks(saldo_eth=5.0)
    with patch.object(te, "_rpc", rpc), patch.object(te, "_send_tx", send_tx), \
         patch.object(te, "_EthAccount", _account_mock()):
        with pytest.raises(RuntimeError, match="buiten de toegestane grens"):
            te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.01, "0xkey")
    assert not verstuurd, "er mag niets verstuurd zijn"


def test_weigert_nul_en_negatief():
    rpc, send_tx, verstuurd = _mocks()
    with patch.object(te, "_rpc", rpc), patch.object(te, "_send_tx", send_tx), \
         patch.object(te, "_EthAccount", _account_mock()):
        for bedrag in (0.0, -0.0005):
            with pytest.raises(RuntimeError, match="buiten de toegestane grens"):
                te.stuur_eth_voor_gas(te._TREASURY_WALLET, bedrag, "0xkey")
    assert not verstuurd


def test_weigert_een_andere_bestemming():
    """Ook een eigen wallet is niet goed genoeg: alleen de treasury-wallet."""
    rpc, send_tx, verstuurd = _mocks()
    with patch.object(te, "_rpc", rpc), patch.object(te, "_send_tx", send_tx), \
         patch.object(te, "_EthAccount", _account_mock()):
        with pytest.raises(RuntimeError, match="alleen naar de treasury-wallet"):
            te.stuur_eth_voor_gas("0xBd6c7F3D15C86f745170c34A692B22F7706683cC", 0.0003, "0xkey")
    assert not verstuurd


def test_weigert_als_de_afzender_te_weinig_overhoudt():
    """0,0004 sturen vanaf 0,000497 laat te weinig over voor de eigen gasmarge."""
    rpc, send_tx, verstuurd = _mocks(saldo_eth=0.000497)
    with patch.object(te, "_rpc", rpc), patch.object(te, "_send_tx", send_tx), \
         patch.object(te, "_EthAccount", _account_mock()):
        with pytest.raises(RuntimeError, match="nodig"):
            te.stuur_eth_voor_gas(te._TREASURY_WALLET, 0.00045, "0xkey")
    assert not verstuurd


def test_send_tx_stuurt_standaard_geen_waarde():
    """Elke bestaande aanroeper doet een contract-aanroep; die moet value 0 houden."""
    ondertekend = {}

    class _Acc:
        @staticmethod
        def from_key(pk):
            return MagicMock(address=AFZENDER)

        @staticmethod
        def sign_transaction(tx, pk):
            ondertekend.update(tx)
            return MagicMock(raw_transaction=b"\x01")

    def rpc(methode, params):
        if methode == "eth_getTransactionCount":
            return "0x1"
        if methode == "eth_gasPrice":
            return hex(100_000_000)
        if methode == "eth_sendRawTransaction":
            return "0xhash"
        raise AssertionError(methode)

    with patch.object(te, "_rpc", rpc), patch.object(te, "_EthAccount", _Acc):
        te._send_tx("0xdoel", "0xdata", "0xkey", 100_000)
    assert ondertekend["value"] == 0

    with patch.object(te, "_rpc", rpc), patch.object(te, "_EthAccount", _Acc):
        te._send_tx("0xdoel", "0x", "0xkey", 21_000, value=123)
    assert ondertekend["value"] == 123
