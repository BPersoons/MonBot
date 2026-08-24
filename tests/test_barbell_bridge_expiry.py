"""Check 23: een tijdelijk instrument mag niet stilzwijgend permanent worden.

Slot 1 van de barbell draait voorlopig op XYZ-SMH (perp) omdat het broker-account
nog niet geactiveerd kon worden. Perps kosten funding en kennen liquidatierisico —
acceptabel voor weken, niet voor maanden. Dit systeem heeft een geschiedenis van
interim-maatregelen die permanent werden, dus de vervaldatum krijgt een alarm.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.swarm_monitor import SwarmMonitor


def _write_cfg(tmp_path, *, active=True, review_by="2020-01-01", instrument="XYZ-SMH"):
    cfgdir = tmp_path / "config"
    cfgdir.mkdir(exist_ok=True)
    (cfgdir / "barbell_targets.json").write_text(json.dumps({
        "themes": {
            "SEMIS": {
                "slot_order": 1,
                "bridge": {
                    "active": active,
                    "venue": "hyperliquid_xyz_dex",
                    "instrument": instrument,
                    "review_by": review_by,
                    "converts_to": "IE00BMC38736 (VVSM) bij DEGIRO",
                },
            },
            "DEFENSE": {"slot_order": 2},
        }
    }), encoding="utf-8")


@pytest.fixture
def monitor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m = SwarmMonitor.__new__(SwarmMonitor)
    m._bridge_alert_times = {}
    sent = []
    m._send_telegram = lambda msg: sent.append(msg)
    m.sent = sent
    return m


def test_alerts_when_past_review_date(monitor, tmp_path):
    _write_cfg(tmp_path, review_by="2020-01-01")
    monitor._check_barbell_bridge_expiry()

    assert len(monitor.sent) == 1
    msg = monitor.sent[0]
    assert "SEMIS" in msg and "XYZ-SMH" in msg
    assert "VVSM" in msg, "moet zeggen waar het naartoe moet"


def test_silent_before_review_date(monitor, tmp_path):
    _write_cfg(tmp_path, review_by="2099-01-01")
    monitor._check_barbell_bridge_expiry()
    assert monitor.sent == []


def test_silent_when_bridge_deactivated(monitor, tmp_path):
    """Na omzetting naar de ETF zet je active=false — dan hoort het stil te zijn."""
    _write_cfg(tmp_path, active=False, review_by="2020-01-01")
    monitor._check_barbell_bridge_expiry()
    assert monitor.sent == []


def test_cooldown_prevents_spam(monitor, tmp_path):
    _write_cfg(tmp_path, review_by="2020-01-01")
    monitor._check_barbell_bridge_expiry()
    monitor._check_barbell_bridge_expiry()
    monitor._check_barbell_bridge_expiry()
    assert len(monitor.sent) == 1, "max één alarm per cooldown-venster"


def test_missing_config_is_not_fatal(monitor):
    monitor._check_barbell_bridge_expiry()  # geen config in tmp_path
    assert monitor.sent == []


def test_malformed_date_is_not_fatal(monitor, tmp_path):
    _write_cfg(tmp_path, review_by="binnenkort")
    monitor._check_barbell_bridge_expiry()
    assert monitor.sent == []


def test_live_config_bridge_is_coherent():
    """De echte config moet coherent zijn — in BEIDE standen.

    Deze toets eiste eerst onvoorwaardelijk `active is True`, met als reden
    "zolang het broker-account nog niet open is". Dat is voorbij: het account
    is open (WEBN + GRID gekocht op 2026-08-20) en de brug-positie XYZ-SMH is
    op diezelfde dag gesloten, waarna `active` op false ging. De toets bewaakte
    daarmee een tijdelijke productiestand in plaats van een eigenschap, en viel
    om zodra het plan gewoon zijn beloop kreeg.

    Wat wél altijd moet gelden: een ACTIEVE brug is volledig ingevuld (anders is
    het vervaldatum-alarm een lege huls), en een GESLOTEN brug houdt zijn
    gegevens zodat er iets valt na te lezen. Zo blijft de toets betekenisvol
    wanneer er ooit een nieuwe brug wordt geopend.
    """
    import datetime as dt

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "config", "barbell_targets.json"), encoding="utf-8") as f:
        cfg = json.load(f)

    bridge = cfg["themes"]["SEMIS"]["bridge"]
    assert isinstance(bridge["active"], bool), "active moet een bool zijn, geen string"
    assert bridge["instrument"] == "XYZ-SMH"
    assert "VVSM" in bridge["converts_to"]

    if bridge["active"]:
        # Een actieve brug zonder geldige einddatum kan niet bewaakt worden.
        dt.datetime.strptime(bridge["review_by"], "%Y-%m-%d")
