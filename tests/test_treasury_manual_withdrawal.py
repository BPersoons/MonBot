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


VAULT_ADR = "0x92D4D9D4c0371D10F3d62194ECD7d43eB9E4F445"


def _saldi(per_adres):
    """Nep-_rpc die balanceOf per adres een eigen bedrag geeft."""
    def rpc(methode, params):
        data = str(params[0].get("data", "")).lower()
        for adres, bedrag in per_adres.items():
            if adres.lower()[2:] in data:
                return hex(int(round(bedrag * 10 ** 6)))
        return "0x0"
    return rpc


def _saldo(usdc):
    return lambda methode, params: hex(int(round(usdc * 10 ** 6)))


def test_monitor_meldt_de_gebeurtenis_ook_als_de_wallet_al_leeg_is(tmp_path, monkeypatch):
    """A1-audit: op 23-07 stond het geld binnen een minuut al terug in Aave.

    Een drempel op het wallet-saldo had dat incident gemist — daarom melden we op de
    gebeurtenis en is het saldo alleen een veld.
    """
    monkeypatch.chdir(tmp_path)
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand()])
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert monitor._send_telegram.called, "lege wallet is juist het echte geval"
    tekst = monitor._send_telegram.call_args[0][0]
    assert "267" in tekst and "$0.00" in tekst
    assert "niet bevestigd" in tekst, "niet claimen dat het geld nog op de wallet staat"
    assert "op HL zijn aangekomen" in tekst, "de bevestiging kan verlopen zijn"

    monitor._send_telegram.reset_mock()
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert not monitor._send_telegram.called, "geen tweede melding binnen 24 uur"


def test_monitor_meldt_beide_adressen(tmp_path, monkeypatch):
    """Bij een mislukte bridge-stap-2 staat het geld op het vault-Arb-adres, niet op de wallet."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HL_VAULT_ADDRESS", VAULT_ADR)
    from utils.treasury_executor import _TREASURY_WALLET
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand()])
    with patch("utils.treasury_executor._rpc", _saldi({_TREASURY_WALLET: 0.0, VAULT_ADR: 267.28})):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    tekst = monitor._send_telegram.call_args[0][0]
    assert "Treasury wallet: $0.00" in tekst and "vault-Arb-adres: $267.28" in tekst


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


def test_monitor_zwijgt_bij_oud_scheef_en_opgelost(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    nu = datetime.now(timezone.utc)

    # het echte record van 23-07: 55 dagen oud
    sm, oud = _monitor(tmp_path, [_rebalance_gestrand(uren_geleden=55 * 24)])
    with patch("utils.treasury_executor._rpc", _saldo(1600.0)):
        oud._check_gestrand_rebalance_geld(nu)
    assert not oud._send_telegram.called, "dood record mag geen vers geld claimen"

    # tijdstempel in de toekomst (klokscheefheid) — nooit melden, ook al wint hij de min()
    sm, scheef = _monitor(tmp_path, [_rebalance_gestrand(uren_geleden=-120)])
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        scheef._check_gestrand_rebalance_geld(nu)
    assert not scheef._send_telegram.called

    # een latere GESLAAGDE rebalance loste het margeprobleem op
    sm, klaar = _monitor(tmp_path, [
        _rebalance_gestrand(uren_geleden=5),
        {"id": "TRR_later", "type": "REBALANCE", "status": "COMPLETED", "amount_usd": 401.83,
         "aave_withdrawn_at": _iso(4), "completed_at": _iso(3)},
    ])
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        klaar._check_gestrand_rebalance_geld(nu)
    assert not klaar._send_telegram.called, "opgelost = geen melding meer"


def test_monitor_kiest_de_meest_recente_en_meldt_hoogstens_twee_keer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    nu = datetime.now(timezone.utc)
    sm, monitor = _monitor(tmp_path, [
        _rebalance_gestrand(uren_geleden=13 * 24, id="TRR_OUD", amount_usd=50.0),
        _rebalance_gestrand(uren_geleden=1, id="TRR_VERS", amount_usd=267.28),
    ])
    with patch("utils.treasury_executor._rpc", _saldo(267.28)):
        monitor._check_gestrand_rebalance_geld(nu)
    tekst = monitor._send_telegram.call_args[0][0]
    assert "TRR_VERS" in tekst and "TRR_OUD" not in tekst
    assert "267" in tekst and "$50" not in tekst, "geen bedrag noemen dat nergens bij hoort"

    # tweede melding pas na 24 uur, en daarna nooit meer
    monitor._send_telegram.reset_mock()
    with patch("utils.treasury_executor._rpc", _saldo(267.28)):
        monitor._check_gestrand_rebalance_geld(nu + timedelta(hours=25))
    assert monitor._send_telegram.called and "herinnering" in monitor._send_telegram.call_args[0][0]
    monitor._send_telegram.reset_mock()
    with patch("utils.treasury_executor._rpc", _saldo(267.28)):
        monitor._check_gestrand_rebalance_geld(nu + timedelta(hours=50))
    assert not monitor._send_telegram.called, "hooguit twee meldingen per geval"


def test_mislukte_melding_geeft_geen_stilte(tmp_path, monkeypatch):
    """A1-audit ronde 2: `_send_telegram` slikte fouten in, dus stempelen ná de melding
    betekende niets. Nu geeft hij False terug en blijft de melding openstaan."""
    monkeypatch.chdir(tmp_path)
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand()])
    monitor._send_telegram = MagicMock(return_value=False)
    for _ in range(2):
        with patch("utils.treasury_executor._rpc", _saldo(0.0)):
            monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert monitor._send_telegram.call_count == 2, "mislukte melding mag niet stempelen"


def test_twee_verschillende_strandingen_melden_allebei(tmp_path, monkeypatch):
    """De cooldown hangt aan het voorstel-id, niet aan de check."""
    monkeypatch.chdir(tmp_path)
    nu = datetime.now(timezone.utc)
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand(uren_geleden=6, id="TRR_EEN")])
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        monitor._check_gestrand_rebalance_geld(nu)
    assert "TRR_EEN" in monitor._send_telegram.call_args[0][0]

    (tmp_path / "treasury_proposals.json").write_text(json.dumps([
        _rebalance_gestrand(uren_geleden=6, id="TRR_EEN"),
        _rebalance_gestrand(uren_geleden=1, id="TRR_TWEE"),
    ]), encoding="utf-8")
    monitor._send_telegram.reset_mock()
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        monitor._check_gestrand_rebalance_geld(nu + timedelta(minutes=5))
    assert monitor._send_telegram.called, "een nieuwe stranding moet wél melden"
    assert "TRR_TWEE" in monitor._send_telegram.call_args[0][0]


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
