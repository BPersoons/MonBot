"""NAV-koersen: een NaN-rij van yfinance mag nooit als $0 in de potjesreeks belanden.

Gevonden door de A1-audit van 2026-09-15: `nav._koers` miste de guard die dezelfde dag
in research/track.py was gerepareerd, en SleeveNAV neemt zijn snapshot precies rond
00:05 UTC — wanneer yfinance een lege rij voor vandaag meegeeft.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import nav  # noqa: E402

pd = pytest.importorskip("pandas")


def _nep_yfinance():
    def ticker(symbool):
        def history(period=None, **kw):
            if symbool == "LEEG":
                return pd.DataFrame({"Close": [float("nan")]})
            return pd.DataFrame({"Close": [12.7, 12.8, float("nan")]})
        return types.SimpleNamespace(history=history)
    module = types.ModuleType("yfinance")
    module.Ticker = ticker
    return module


def test_koers_slaat_nan_laatste_rij_over(monkeypatch):
    monkeypatch.setitem(sys.modules, "yfinance", _nep_yfinance())
    assert nav._koers("WEBN.DE") == 12.8
    assert nav._koers("LEEG") is None


def test_tradfi_waarde_weigert_nan_en_fouten(monkeypatch):
    from utils.sleeve_nav import SleeveNAV
    monkeypatch.setattr(nav, "_broker", lambda: [{"status": "ok", "waarde_usd": float("nan")}])
    assert SleeveNAV._tradfi_value() is None
    monkeypatch.setattr(nav, "_broker", lambda: [{"status": "fout", "waarde_usd": None},
                                                 {"status": "ok", "waarde_usd": 5.0}])
    assert SleeveNAV._tradfi_value() is None
    monkeypatch.setattr(nav, "_broker", lambda: [{"status": "ok", "waarde_usd": 10.0},
                                                 {"status": "ok", "waarde_usd": 5.5}])
    assert SleeveNAV._tradfi_value() == 15.5
    monkeypatch.setattr(nav, "_broker", lambda: [])
    assert SleeveNAV._tradfi_value() == 0.0
