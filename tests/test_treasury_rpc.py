"""Kasbeheer-RPC: een revert is een antwoord, geen storing (A2-audit 2026-09-15).

Vóór de fix probeerde `_rpc` na een JSON-RPC-fout de volgende RPC, en die gaf een 403.
De revert verdween dan achter "All Arbitrum RPCs failed: 403", `_simulate_tx` las dat
als "RPC unavailable", en de echte transactie ging toch de deur uit — en revert, met gas.
"""
import io
import json
import os
import sys
import urllib.error
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import treasury_executor as te  # noqa: E402

REVERT = {"jsonrpc": "2.0", "id": 1,
          "error": {"code": 3, "message": "execution reverted", "data": "0x47bc4b2c"}}


class _Antwoord(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _nep_urlopen(volgorde):
    """Elke aanroep pakt het volgende antwoord: dict = JSON-body, int = HTTP-fout."""
    pogingen = []

    def urlopen(req, timeout=15):
        stap = volgorde[min(len(pogingen), len(volgorde) - 1)]
        pogingen.append(req.full_url)
        if isinstance(stap, int):
            raise urllib.error.HTTPError(req.full_url, stap, "fout", {}, None)
        return _Antwoord(json.dumps(stap).encode())
    return urlopen, pogingen


def test_revert_verdwijnt_niet_achter_een_transportfout():
    urlopen, _ = _nep_urlopen([REVERT, 403, 403])
    with patch.object(te, "_ARB_RPCS", ["https://a", "https://b", "https://c"]), \
         patch("urllib.request.urlopen", urlopen):
        with pytest.raises(RuntimeError) as fout:
            te._rpc("eth_call", [{}, "latest"])
    assert "reverted" in str(fout.value), "de revert moet de fout zijn, niet de 403"


UNAUTHORIZED = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "Unauthorized: key required"}}


def test_echte_rpc_volgorde_revert_wint_van_een_latere_json_fout():
    """A1-audit: Tenderly revert, zan.top 429, ankr JSON 'Unauthorized', 1rpc 403."""
    urlopen, pogingen = _nep_urlopen([REVERT, UNAUTHORIZED, 403, 403])
    with patch.object(te, "_ARB_RPCS", ["https://tenderly", "https://ankr", "https://1rpc", "https://arb1"]), \
         patch("urllib.request.urlopen", urlopen):
        with pytest.raises(RuntimeError) as fout:
            te._rpc("eth_call", [{}, "latest"])
    assert "reverted" in str(fout.value)
    assert pogingen == ["https://tenderly"], "na een revert geen andere RPC's meer proberen"


def test_json_fout_eerst_en_dan_revert_geeft_ook_de_revert():
    urlopen, _ = _nep_urlopen([UNAUTHORIZED, REVERT])
    with patch.object(te, "_ARB_RPCS", ["https://ankr", "https://tenderly"]), \
         patch("urllib.request.urlopen", urlopen):
        with pytest.raises(RuntimeError, match="reverted"):
            te._rpc("eth_call", [{}, "latest"])


def _deposit_mocks(volgorde, simulatie_faalt=False):
    """Patches voor _deposit_aave die elke transactie en dry-run in volgorde loggen."""
    def send(to, data, pk, gas):
        volgorde.append(("send", data[:10], int(data[-64:], 16) if data.startswith("0x095ea7b3") else None))
        return "0xtx%d" % len(volgorde)

    def sim(to, data, from_addr=""):
        volgorde.append(("sim", data[:10], None))
        if simulatie_faalt:
            raise RuntimeError("Dry-run reverted — TX NIET verstuurd: execution reverted")

    acc = patch.object(te, "_EthAccount")
    return [
        patch.object(te, "_verify_is_contract", return_value=True),
        patch.object(te, "_check_eth_gas"),
        patch.object(te, "get_aave_balance", side_effect=[1000.0, 1100.0]),
        patch.object(te, "_send_tx", side_effect=send),
        patch.object(te, "_simulate_tx", side_effect=sim),
        patch.object(te, "_wait_receipt", return_value={"status": "0x1"}),
        patch.object(te, "_read_usdc_allowance", return_value=10 ** 12),
        patch.object(te.time, "sleep"),
        acc,
    ]


def _met(patches, fn):
    import contextlib
    with contextlib.ExitStack() as stack:
        mocks = [stack.enter_context(p) for p in patches]
        mocks[-1].from_key.return_value.address = te._TREASURY_WALLET
        return fn()


def test_deposit_dry_run_komt_na_de_approve():
    """A1-audit: een supply-dry-run vóór de approve revert altijd op de allowance."""
    volgorde = []
    _met(_deposit_mocks(volgorde), lambda: te._deposit_aave(100.0, "0xkey"))
    soorten = [(s, sel) for s, sel, _ in volgorde]
    assert soorten[0] == ("send", "0x095ea7b3"), "eerst de approve"
    assert soorten.index(("sim", soorten[1][1])) < len(soorten) - 1
    assert soorten[1][0] == "sim" and soorten[2][0] == "send", "dry-run tussen approve en supply"


def test_revert_in_dry_run_trekt_de_approve_in_en_stort_niet():
    volgorde = []
    with pytest.raises(RuntimeError, match="NIET verstuurd"):
        _met(_deposit_mocks(volgorde, simulatie_faalt=True), lambda: te._deposit_aave(100.0, "0xkey"))
    sends = [(sel, bedrag) for s, sel, bedrag in volgorde if s == "send"]
    assert sends[0][0] == "0x095ea7b3" and sends[0][1] > 0, "approve"
    assert sends[-1] == ("0x095ea7b3", 0), "approve moet weer op 0"
    assert all(sel == "0x095ea7b3" for sel, _ in sends), "er mag geen supply verstuurd zijn"


def test_dry_run_stopt_bij_een_revert():
    urlopen, _ = _nep_urlopen([REVERT, 403, 403])
    with patch.object(te, "_ARB_RPCS", ["https://a", "https://b", "https://c"]), \
         patch("urllib.request.urlopen", urlopen):
        with pytest.raises(RuntimeError, match="NIET verstuurd"):
            te._simulate_tx("0x" + "1" * 40, "0xdeadbeef", from_addr="0x" + "2" * 40)


def test_dry_run_slaat_over_bij_een_echte_storing():
    urlopen, _ = _nep_urlopen([403, 403, 403])
    with patch.object(te, "_ARB_RPCS", ["https://a", "https://b"]), \
         patch("urllib.request.urlopen", urlopen):
        assert te._simulate_tx("0x" + "1" * 40, "0xdeadbeef") is None


def test_geslaagd_antwoord_komt_gewoon_terug():
    urlopen, _ = _nep_urlopen([{"jsonrpc": "2.0", "id": 1, "result": "0x2a"}])
    with patch.object(te, "_ARB_RPCS", ["https://a"]), patch("urllib.request.urlopen", urlopen):
        assert te._rpc("eth_blockNumber", []) == "0x2a"


def test_volledige_aave_opname_vraagt_uint256_max():
    verstuurd = {}
    with patch.object(te, "_EthAccount") as acc, \
         patch.object(te, "_check_eth_gas"), \
         patch.object(te, "_simulate_tx"), \
         patch.object(te, "get_arb_usdc_balance", side_effect=[0.0, 2490.13]), \
         patch.object(te, "_send_tx", side_effect=lambda to, data, pk, gas: verstuurd.update(data=data) or "0xtx"), \
         patch.object(te, "_wait_receipt", return_value={"status": "0x1"}):
        acc.from_key.return_value.address = te._TREASURY_WALLET
        te.withdraw_aave_to_wallet(2490.137054, "0xkey", volledig=True)
    # withdraw(asset, amount, to): het amount-veld is het tweede 32-byte-woord
    amount_hex = verstuurd["data"][10 + 64:10 + 128]
    assert amount_hex == "f" * 64, "volledige opname moet type(uint256).max gebruiken"
