"""Een vastgelopen handmatige HL-opname mag kasbeheer niet stil en voor altijd blokkeren.

A1-hertoets kasbeheer 2026-09-15: een DEPLOY_YIELD in NEEDS_MANUAL_WITHDRAWAL hield
generate, HL-overschot, switch en diversificatie tegen, zonder verlooptijd, en de monitor
kende de status niet. Bovendien zette willekeurige USDC die later op de wallet kwam hem
alsnog naar BRIDGED.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import treasury_executor as te  # noqa: E402


def _iso(uren_geleden):
    return (datetime.now(timezone.utc) - timedelta(hours=uren_geleden)).isoformat()


def _voorstel(status="NEEDS_MANUAL_WITHDRAWAL", **extra):
    p = {"id": "TRP_x", "type": "DEPLOY_YIELD", "status": status, "amount_usd": 500.0,
         "source": "hl", "withdrawal_destination": te._TREASURY_WALLET}
    p.update(extra)
    return p


def test_handmatige_opname_verloopt_na_48u_als_het_geld_er_niet_is():
    with patch.object(te, "get_arb_usdc_balance", return_value=0.0):
        uit = te.advance_proposal(_voorstel(manual_withdrawal_since=_iso(49)))
    assert uit["status"] == "EXPIRED"


def test_geld_dat_net_op_tijd_aankomt_wint_van_de_verlooptijd():
    """A1-audit bevinding 6: de verlooptak stond vóór de saldo-poll (venster ~5 min)."""
    with patch.object(te, "get_arb_usdc_balance", return_value=1000.0):
        uit = te.advance_proposal(_voorstel(manual_withdrawal_since=_iso(49)))
    assert uit["status"] == "BRIDGED", "aangekomen geld mag niet alsnog verlopen"


def test_binnen_48u_gaat_hij_gewoon_door_als_het_geld_er_is():
    with patch.object(te, "get_arb_usdc_balance", return_value=1000.0):
        uit = te.advance_proposal(_voorstel(manual_withdrawal_since=_iso(1)))
    assert uit["status"] == "BRIDGED"


def test_oud_voorstel_zonder_eigen_veld_valt_terug_op_updated_at():
    with patch.object(te, "get_arb_usdc_balance", return_value=0.0):
        uit = te.advance_proposal(_voorstel(updated_at=_iso(60)))
    assert uit["status"] == "EXPIRED"


def test_automatische_bridge_verloopt_niet():
    with patch.object(te, "get_arb_usdc_balance", return_value=0.0):
        uit = te.advance_proposal(_voorstel("WITHDRAWING", updated_at=_iso(60)))
    assert uit["status"] == "WITHDRAWING"


def test_onleesbare_tijd_verloopt_niet_stil():
    with patch.object(te, "get_arb_usdc_balance", return_value=0.0):
        uit = te.advance_proposal(_voorstel(manual_withdrawal_since="gisteren"))
    assert uit["status"] == "NEEDS_MANUAL_WITHDRAWAL"


def _monitor(tmp_path, proposals):
    from agents import swarm_monitor as sm
    (tmp_path / "treasury_proposals.json").write_text(json.dumps(proposals), encoding="utf-8")
    state_file = os.path.join(tempfile.gettempdir(), "monitor_alert_state_TEST_ONLY.json")
    with patch.object(sm.SwarmMonitor, "ALERT_STATE_FILE", state_file):
        monitor = sm.SwarmMonitor(db_client=MagicMock())
    monitor._send_telegram = MagicMock()
    return sm, monitor


def _rebalance_gestrand(uren_geleden=2, **extra):
    p = {"id": "TRR_x", "type": "REBALANCE", "status": "FAILED", "amount_usd": 267.28,
         "aave_withdrawn_at": _iso(uren_geleden), "error": "bridge minimum"}
    p.update(extra)
    return p


def _saldo(usdc):
    """Nep-_rpc die balanceOf beantwoordt met dit bedrag."""
    return lambda methode, params: hex(int(usdc * 10 ** 6))


def test_monitor_meldt_de_gebeurtenis_ook_als_de_wallet_al_leeg_is(tmp_path, monkeypatch):
    """A1-audit: op 18-07 en 23-07 was het geld binnen een minuut terug in Aave.

    Een drempel op het wallet-saldo had beide incidenten gemist — daarom melden we op de
    gebeurtenis en is het saldo alleen een veld.
    """
    monkeypatch.chdir(tmp_path)
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand()])
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert monitor._send_telegram.called, "lege wallet is juist het echte geval"
    tekst = monitor._send_telegram.call_args[0][0]
    assert "267" in tekst and "$0.00" in tekst
    assert "terug in Aave" in tekst, "de melding moet die mogelijkheid noemen"

    monitor._send_telegram.reset_mock()
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert not monitor._send_telegram.called, "tweede ronde binnen de cooldown: stil"


def test_monitor_onderscheidt_nul_van_onmeetbaar(tmp_path, monkeypatch):
    """`get_arb_usdc_balance` slikt RPC-fouten in als 0.0 — hier mag dat niet gebeuren."""
    monkeypatch.chdir(tmp_path)
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand()])

    def kapot(methode, params):
        raise RuntimeError("All Arbitrum RPCs failed")

    with patch("utils.treasury_executor._rpc", kapot):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert monitor._send_telegram.called
    assert "onmeetbaar" in monitor._send_telegram.call_args[0][0]


def test_monitor_zwijgt_bij_een_oud_record_en_kiest_anders_de_verste(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # het echte record van 23-07: 55 dagen oud, mag nooit meer melden
    sm, oud = _monitor(tmp_path, [_rebalance_gestrand(uren_geleden=55 * 24)])
    with patch("utils.treasury_executor._rpc", _saldo(1600.0)):
        oud._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert not oud._send_telegram.called, "dood record mag geen vers geld claimen"

    # twee kandidaten: de melding moet over de MEEST RECENTE gaan
    sm2, twee = _monitor(tmp_path, [
        _rebalance_gestrand(uren_geleden=13 * 24, id="TRR_OUD", amount_usd=50.0),
        _rebalance_gestrand(uren_geleden=1, id="TRR_VERS", amount_usd=267.28),
    ])
    with patch("utils.treasury_executor._rpc", _saldo(267.28)):
        twee._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    tekst = twee._send_telegram.call_args[0][0]
    assert "TRR_VERS" in tekst and "TRR_OUD" not in tekst
    assert "267" in tekst and "$50" not in tekst, "geen bedrag noemen dat nergens bij hoort"


def test_monitor_meldt_een_hangende_handmatige_opname(tmp_path, monkeypatch):
    from agents import swarm_monitor as sm
    monkeypatch.chdir(tmp_path)
    (tmp_path / "treasury_proposals.json").write_text(json.dumps(
        [dict(_voorstel(), created_at=_iso(7), title="HL excess")]), encoding="utf-8")
    state_file = os.path.join(tempfile.gettempdir(), "monitor_alert_state_TEST_ONLY.json")
    with patch.object(sm.SwarmMonitor, "ALERT_STATE_FILE", state_file):
        monitor = sm.SwarmMonitor(db_client=MagicMock())
    monitor._send_telegram = MagicMock()
    with patch.object(sm, "_telegram_token", return_value="t"), \
         patch.object(sm, "_telegram_chat_id", return_value="c"):
        monitor._check_stuck_proposals(datetime.now(timezone.utc))
    assert monitor._send_telegram.called
    assert "NEEDS_MANUAL_WITHDRAWAL" in monitor._send_telegram.call_args[0][0]
