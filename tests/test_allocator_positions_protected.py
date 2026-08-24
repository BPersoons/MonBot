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


def test_live_config_beschermt_precies_de_actieve_bruggen():
    """De bescherming moet exact de ACTIEVE bruggen dekken — niet meer, niet minder.

    Deze toets eiste eerst onvoorwaardelijk dat XYZ-SMH beschermd werd, "zolang
    de positie open staat". Die positie is op 2026-08-20 gesloten en de brug op
    `active: false` gezet, waarna de toets omviel op een volstrekt normale gang
    van zaken. Een toets die een tijdelijke stand vastlegt, gaat gegarandeerd
    rood — en leert je daarna niets meer.

    De eigenschap die wél altijd geldt, en die scherper is dan het origineel:
    de allocator beschermt precies de bruggen die aanstaan. Dat vangt zowel een
    half-afgesloten brug (uit, maar nog wél afgeschermd) als een nieuwe brug die
    aanstaat zonder bescherming.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "config", "barbell_targets.json"), encoding="utf-8") as f:
        cfg = json.load(f)

    verwacht = {
        b["instrument"].split("/")[0]
        for t in cfg.get("themes", {}).values()
        if (b := t.get("bridge")) and b.get("active")
    }

    cwd = os.getcwd()
    try:
        os.chdir(root)
        assert _barbell_bridge_bases() == verwacht
    finally:
        os.chdir(cwd)
