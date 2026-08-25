"""
Unit tests for SwarmMonitor health checks.

Prevents regressions like:
- NoneType comparison errors when Supabase returns null cycle_count
- Crashes in _check_supabase_health / _check_pipeline_output on unexpected None values
"""
import sys
import os
from datetime import datetime, timezone, timedelta
import tempfile
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.swarm_monitor import SwarmMonitor


def _make_monitor():
    """Return a SwarmMonitor with a mocked db client.

    Gebruikt bewust de ECHTE constructor. Hiervoor stond hier
    `SwarmMonitor.__new__(SwarmMonitor)` met een handmatige opsomming van zes
    attributen — dat omzeilt `__init__`, dus elk attribuut dat er later bij kwam
    ontbrak. Toen `_cycle_last_advance` werd toegevoegd (cumulatieve
    freeze-timer) braken vier toetsen met een AttributeError, en omdat pytest
    niet in CI draait bleef dat staan. `__init__` zet er inmiddels negentien;
    die met de hand bijhouden is een gegarandeerde herhaling.

    De constructor is hier veilig: hij start geen thread (dat doet `start()`)
    en doet verder alleen veldinitialisatie. Het enige I/O-punt is
    `_load_alert_state()`, en dat wijzen we naar een niet-bestaand pad in temp
    zodat een toets nooit de echte alarmstate van deze machine inleest.
    """
    state_file = os.path.join(tempfile.gettempdir(), "monitor_alert_state_TEST_ONLY.json")
    with patch.object(SwarmMonitor, "ALERT_STATE_FILE", state_file):
        monitor = SwarmMonitor(db_client=MagicMock())
    monitor.logger = MagicMock()
    monitor._check_count = 1
    monitor._last_alert_time = None
    return monitor


def test_fixture_dekt_alle_velden_van_de_constructor():
    """Struikeldraad: de fixture mag niet achterlopen op `__init__`.

    Deze toets bestaat omdat precies dat vier toetsen sloopte. Hij faalt zodra
    de fixture een veld mist dat de echte constructor wel zet.
    """
    echt = SwarmMonitor(db_client=MagicMock())
    ontbreekt = set(vars(echt)) - set(vars(_make_monitor()))
    assert not ontbreekt, "fixture mist veld(en) uit __init__: %s" % sorted(ontbreekt)


def _agent(name, cycle_count=1, status="IDLE", meta=None, last_pulse=None):
    """Build a fake swarm_health row."""
    if last_pulse is None:
        last_pulse = datetime.now(tz=timezone.utc).isoformat()
    return {
        "agent_name": name,
        "cycle_count": cycle_count,
        "status": status,
        "last_pulse": last_pulse,
        "metadata": meta or {},
        "last_error": None,
    }


def _mock_db_with_agents(monitor, rows):
    """Wire monitor.db so that swarm_health queries return `rows`."""
    result_mock = MagicMock()
    result_mock.data = rows
    monitor.db.client.table.return_value.select.return_value.execute.return_value = result_mock
    # Also handle chained queries (order/limit) used by ProductOwner backlog check
    monitor.db.client.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])


# ---------------------------------------------------------------------------
# Test: null cycle_count from Supabase must not crash comparisons
# ---------------------------------------------------------------------------

def test_check_supabase_health_null_cycle_count_does_not_crash():
    """_check_supabase_health must not raise TypeError when cycle_count is None (Supabase null)."""
    monitor = _make_monitor()
    now = datetime.now(tz=timezone.utc)
    _mock_db_with_agents(monitor, [_agent("Heartbeat", cycle_count=None, status="IDLE")])
    # Should not raise
    issues = monitor._check_supabase_health(now)
    assert isinstance(issues, list)


def test_check_pipeline_output_null_cycle_count_does_not_crash():
    """_check_pipeline_output must not raise TypeError when cycle_count is None."""
    monitor = _make_monitor()
    now = datetime.now(tz=timezone.utc)
    rows = [
        _agent("Scout", cycle_count=None, meta={"scanned_count": 0, "approved_count": 0, "total_universe": 0}),
        _agent("ProjectLead", cycle_count=None, status="IDLE", meta={"latest_decisions": []}),
        _agent("PerformanceAuditor", cycle_count=None),
        _agent("ProductOwner", cycle_count=None),
        _agent("Heartbeat", cycle_count=None),
    ]
    _mock_db_with_agents(monitor, rows)
    issues = monitor._check_pipeline_output(now)
    assert isinstance(issues, list)


def test_frozen_cycle_detection_with_null_count():
    """Second check with null cycle_count must not crash frozen-cycle detection."""
    monitor = _make_monitor()
    now = datetime.now(tz=timezone.utc)
    # Seed previous state
    monitor._prev_check_time = now - timedelta(minutes=20)
    monitor._prev_cycle_counts["Heartbeat"] = 0
    _mock_db_with_agents(monitor, [_agent("Heartbeat", cycle_count=None)])
    issues = monitor._check_supabase_health(now)
    assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# Test: normal operation still works
# ---------------------------------------------------------------------------

def test_healthy_agents_produce_no_agent_errors():
    """Agents with recent pulses and IDLE status produce no AGENT_ERROR/AGENT_STALE issues."""
    monitor = _make_monitor()
    now = datetime.now(tz=timezone.utc)
    _mock_db_with_agents(monitor, [
        _agent("Heartbeat", cycle_count=5, status="ACTIVE"),
        _agent("ProjectLead", cycle_count=5, status="IDLE"),
    ])
    issues = monitor._check_supabase_health(now)
    assert not any(i["type"] in ("AGENT_ERROR", "AGENT_STALE") for i in issues)


def test_stale_heartbeat_flagged():
    """Heartbeat with a pulse > 30 min old must be flagged as AGENT_STALE."""
    monitor = _make_monitor()
    now = datetime.now(tz=timezone.utc)
    old_pulse = (now - timedelta(minutes=45)).isoformat()
    _mock_db_with_agents(monitor, [_agent("Heartbeat", cycle_count=3, status="IDLE", last_pulse=old_pulse)])
    issues = monitor._check_supabase_health(now)
    stale = [i for i in issues if i["type"] == "AGENT_STALE" and i["agent"] == "Heartbeat"]
    assert stale, "Expected AGENT_STALE for Heartbeat with 45-min-old pulse"


# ──────────────────────────────────────────────────────────────────────
# Alarmen die aankomen, en guards die op ELKE plek staan
#
# Twee bugs uit dezelfde meting (2026-08-25):
#   1. 8 van 51 Telegram-verzendingen faalden met HTTP 400 omdat de
#      alarmnaam (DB_ERROR) een ongepaarde underscore is voor Telegram's
#      Markdown. Eén slechte naam wist het HELE bericht, inclusief de
#      gezonde meldingen die ernaast gebundeld zaten.
#   2. Twee checks lazen trade_log.json zonder de sleeve/oogst-uitsluiting.
#      Dat is de zesde keer dat die guard ergens ontbrak; deze toetsen
#      maken van "tel de plekken in de code" iets dat vanzelf faalt.
# ──────────────────────────────────────────────────────────────────────

import json as _json

from agents.swarm_monitor import _md_escape


def _sleeve_trade(ticker, entry_epoch, action="BUY"):
    return {
        "id": f"T_{ticker}", "ticker": ticker, "action": action, "status": "OPEN",
        "entry_time": entry_epoch, "quantity": 1.0, "entry_price": 10.0,
        "thematic_exposure": True,
    }


def test_alarmnaam_met_underscore_breekt_het_bericht_niet():
    """Elke opgemaakte regel moet een even aantal ongeëscapete _ overhouden."""
    for naam in ("DB_ERROR", "NO_OUTPUT", "AGENT_STALE", "PIPELINE_BLOCKED"):
        regel = f"*{_md_escape(naam)}*"
        kaal = regel.replace(r"\_", "")
        assert "_" not in kaal, f"{naam} laat een ongepaarde underscore achter"


def test_composer_escapet_type_bericht_en_agent():
    """Het samengestelde alarm bevat geen losse Markdown-tekens meer."""
    monitor = _make_monitor()
    verzonden = []
    monitor._send_telegram = lambda tekst: verzonden.append(tekst)
    monitor._sent_alerts = {}
    with patch("agents.swarm_monitor._telegram_token", return_value="x"), \
         patch("agents.swarm_monitor._telegram_chat_id", return_value="y"):
        monitor._maybe_send_telegram_alert([{
            "type": "DB_ERROR", "severity": "HIGH", "agent": "SwarmMonitor",
            "message": "kon trade_log.json niet lezen (a*b)",
        }])
    assert verzonden, "alarm werd niet samengesteld"
    kaal = verzonden[0].replace(r"\_", "").replace(r"\*", "")
    # Alleen de opmaak die de composer zelf zet blijft over: *Swarm Monitor
    # Alert*, _Detected at .._ en de severity-regel. Die zijn allemaal gepaard.
    assert kaal.count("_") % 2 == 0
    assert kaal.count("*") % 2 == 0


def test_telegram_valt_terug_op_platte_tekst_bij_400():
    """Een 400 mag geen verloren alarm zijn — hij gaat opnieuw, zonder opmaak."""
    import urllib.error
    monitor = _make_monitor()
    pogingen = []

    def _nep_urlopen(req, timeout=10):
        pogingen.append(req.data.decode())
        if len(pogingen) == 1:
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, None)
        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return _Resp()

    with patch("agents.swarm_monitor._telegram_token", return_value="x"), \
         patch("agents.swarm_monitor._telegram_chat_id", return_value="y"), \
         patch("urllib.request.urlopen", _nep_urlopen):
        monitor._send_telegram("*DB_ERROR* kapot")

    assert len(pogingen) == 2, "geen tweede poging na een 400"
    assert "parse_mode" in pogingen[0]
    assert "parse_mode" not in pogingen[1], "de herkansing moet ZONDER opmaak gaan"


def test_richting_eenzijdigheid_negeert_de_dip_koper(tmp_path, monkeypatch):
    """De dip-koper is per ontwerp alleen LONG — dat is geen scheefstand."""
    monitor = _make_monitor()
    verzonden = []
    monitor._send_telegram = lambda tekst: verzonden.append(tekst)

    basis = datetime(2026, 8, 25, 8, 0).timestamp()
    trades = [_sleeve_trade(f"XYZ-T{i}", basis + i * 60) for i in range(12)]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "trade_log.json").write_text(_json.dumps(trades), encoding="utf-8")

    monitor._check_directional_pathology(datetime.now())
    assert not verzonden, f"vals alarm op sleeve-posities: {verzonden}"


def test_position_sync_sluit_geen_posities_van_een_andere_wallet(tmp_path):
    """Fix 3 mag de sleeve niet als spookpositie wegschrijven.

    De sleeve draait op wallet 0xBd6c; hl_open_bases komt van de hoofdwallet.
    Zolang die hoofdwallet leeg was hield de veiligheidsrem dit tegen — maar
    zodra daar één positie staat sloeg de rem niet meer aan en sloot deze lus
    de hele sleeve-boekhouding. Dezelfde fout als main.py's Pass 3.

    De opstelling is bewust het scherpst mogelijke geval: er is een ECHTE
    spookpositie (BTC staat OPEN in trade_log maar niet op de beurs), zodat de
    schrijvende lus daadwerkelijk draait. Alleen filteren bij het inlezen is
    hier niet genoeg — die lus itereert over álle trades.
    """
    monitor = _make_monitor()
    monitor._send_telegram = lambda tekst: None

    basis = datetime(2026, 8, 25, 8, 0).timestamp()
    eigen = {"id": "T_BTC", "ticker": "BTC/USDC", "action": "BUY", "status": "OPEN",
             "entry_time": basis, "quantity": 0.01, "entry_price": 60000.0}
    trades = [eigen, _sleeve_trade("XYZ-BABA/USDC", basis + 10),
              _sleeve_trade("XYZ-CRCL/USDC", basis + 20)]

    trade_log = tmp_path / "trade_log.json"
    actief = tmp_path / "active_assets.json"
    trade_log.write_text(_json.dumps(trades), encoding="utf-8")
    actief.write_text(_json.dumps(["BTC/USDC"]), encoding="utf-8")

    # De hoofdwallet houdt ETH aan: niet leeg (dus geen veiligheidsrem), maar
    # ook geen BTC — die is dus een echt spook en de opruimlus gaat draaien.
    exchange = MagicMock()
    exchange.vault_address = "0x92D4"
    exchange.signing_client = MagicMock()
    exchange.fetch_all_positions.return_value = [
        {"symbol": "ETH/USDC:USDC", "contracts": 1.0}
    ]
    exchange._xyz_fetch_ok = True
    monitor.exchange_client = exchange
    monitor._sent_alerts = {}

    with patch.object(SwarmMonitor, "TRADE_LOG_FILE", str(trade_log)), \
         patch.object(SwarmMonitor, "ACTIVE_ASSETS_FILE", str(actief)), \
         patch("agents.swarm_monitor._telegram_token", return_value=""), \
         patch("agents.swarm_monitor._telegram_chat_id", return_value=""):
        monitor._check_position_sync(datetime.now())

    na = {t["ticker"]: t["status"] for t in _json.loads(trade_log.read_text(encoding="utf-8"))}
    assert na["XYZ-BABA/USDC"] == "OPEN", "sleeve-positie als spook gesloten"
    assert na["XYZ-CRCL/USDC"] == "OPEN", "sleeve-positie als spook gesloten"
    # Controle op de opstelling zelf: het echte spook MOET zijn opgeruimd,
    # anders bewijst deze toets niets (dan draaide de lus gewoon niet).
    assert na["BTC/USDC"] == "CLOSED", "de opruimlus draaide niet — toets is leeg"
