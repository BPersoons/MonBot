"""Posities van de ALLOCATOR mogen niet door de TRADER geadopteerd worden.

De ghost-reconcile in main.py neemt elke HL-positie die niet in trade_log staat op
als RECOVERED_-trade met een standaard 5% stop-loss. Voor de barbell-brug (een
buy-and-hold-drager) zou dat betekenen dat StrategyManager hem bij de eerste
normale dip sluit. Zelfde klasse fout als de twee orphan-shorts: twee systemen die
dezelfde wallet beheren zonder van elkaar te weten.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.allocator_positions import barbell_bridge_bases as _barbell_bridge_bases


def _cfg(tmp_path, themes):
    d = tmp_path / "config"
    d.mkdir(exist_ok=True)
    (d / "barbell_targets.json").write_text(json.dumps({"themes": themes}), encoding="utf-8")


def test_active_bridge_is_protected(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _cfg(tmp_path, {"SEMIS": {"bridge": {"active": True, "instrument": "XYZ-SMH"}}})
    assert _barbell_bridge_bases() == {"XYZ-SMH"}


def test_inactive_bridge_is_not_protected(tmp_path, monkeypatch):
    """Na omzetting naar de ETF (active=false) mag de reconcile weer normaal doen."""
    monkeypatch.chdir(tmp_path)
    _cfg(tmp_path, {"SEMIS": {"bridge": {"active": False, "instrument": "XYZ-SMH"}}})
    assert _barbell_bridge_bases() == set()


def test_multiple_bridges(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _cfg(tmp_path, {
        "SEMIS": {"bridge": {"active": True, "instrument": "XYZ-SMH"}},
        "GOLD": {"bridge": {"active": True, "instrument": "XYZ-GOLD/USDC"}},
        "DEFENSE": {"slot_order": 2},
    })
    assert _barbell_bridge_bases() == {"XYZ-SMH", "XYZ-GOLD"}


def test_missing_config_is_not_fatal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _barbell_bridge_bases() == set()


def test_live_config_protects_the_open_position():
    """De ECHTE config moet de brug beschermen zolang de positie open staat."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cwd = os.getcwd()
    try:
        os.chdir(root)
        assert "XYZ-SMH" in _barbell_bridge_bases()
    finally:
        os.chdir(cwd)
