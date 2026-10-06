"""Het HYPE-basispotje telt mee in sleeve_nav en nav: geen bestand = geen potje,
een bestand zonder waarde = onmeetbaar (nooit nul)."""
import json

from utils import basis_hype as bh
from utils import nav
from utils.sleeve_nav import SleeveNAV


def _schrijf(tmp_path, monkeypatch, inhoud):
    p = tmp_path / "basis.json"
    if inhoud is not None:
        p.write_text(json.dumps(inhoud))
    monkeypatch.setattr(bh, "STATE_FILE", str(p))


def test_zonder_bestand_nul_en_geen_regel(tmp_path, monkeypatch):
    _schrijf(tmp_path, monkeypatch, None)
    assert SleeveNAV._basis_value() == 0.0 and nav._basis() == []


def test_met_waarde(tmp_path, monkeypatch):
    _schrijf(tmp_path, monkeypatch, {"waarde_usd": 141.2, "inleg_usd": 140.0, "laatst": "2026-10-07T10:00:00+00:00"})
    assert SleeveNAV._basis_value() == 141.2
    assert nav._basis()[0]["waarde_usd"] == 141.2 and nav._basis()[0]["status"] == "ok"


def test_bestand_zonder_waarde_is_onmeetbaar(tmp_path, monkeypatch):
    _schrijf(tmp_path, monkeypatch, {"waarde_usd": None})
    assert SleeveNAV._basis_value() is None and nav._basis()[0]["status"] == "fout"


def test_kapot_bestand_is_onmeetbaar(tmp_path, monkeypatch):
    p = tmp_path / "basis.json"
    p.write_text("{kapot")
    monkeypatch.setattr(bh, "STATE_FILE", str(p))
    assert SleeveNAV._basis_value() is None and nav._basis()[0]["status"] == "fout"
