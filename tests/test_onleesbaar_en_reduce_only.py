"""Audit 21-09 (A1, dip-koper): onmeetbaar is geen nul, en sluitende orders zijn reduceOnly.

- sleeve_nav: een onleesbaar positiebestand van de dip-koper gaf 0,0 (een valse daling van
  ~$255 in de dagsnapshot). Nu None -> snapshot uitgesteld, zoals bij Conviction Core en broker.
- kasbeheer: het sluiten van de harvest-short (BUY) ging zonder reduceOnly; bestaat de short
  niet meer, dan opent zo'n order een long.
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import sleeve_nav as sn  # noqa: E402


def test_sleeve_nav_dip_koper_ontbrekend_nul_onleesbaar_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert sn.SleeveNAV._thematic_exposure_value() == 0.0          # bestaat nog niet
    # kapotte JSON, en geldige JSON die niet te waarderen is (audit ronde 2, bev. b)
    for tekst in ("", '{"cash_usd": 12.7, "positions": {"XYZ', "[]", '{"positions": [1]}'):
        (tmp_path / sn.THEMATIC_EXPOSURE_FILE).write_text(tekst)
        assert sn.SleeveNAV._thematic_exposure_value() is None, repr(tekst)
    (tmp_path / sn.THEMATIC_EXPOSURE_FILE).write_text('{"cash_usd": 12.7, "positions": {}}')
    assert sn.SleeveNAV._thematic_exposure_value() == 12.7


def test_sleeve_nav_stelt_snapshot_uit_bij_onleesbare_dip_koper(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / sn.TREASURY_STATE_FILE).write_text("{}")         # vers, dus niet staal
    nav = sn.SleeveNAV.__new__(sn.SleeveNAV)
    nav.config = {"sleeves": ["yield_core", "thematic_exposure"], "source_map": {},
                  "default_yield_sleeve": "yield_core"}
    monkeypatch.setattr(sn.SleeveNAV, "_conviction_value", staticmethod(lambda: 0.0))
    monkeypatch.setattr(sn.SleeveNAV, "_tradfi_value", staticmethod(lambda: 0.0))
    monkeypatch.setattr(sn.SleeveNAV, "_thematic_wallet_is_segregated", staticmethod(lambda: True))

    monkeypatch.setattr(sn.SleeveNAV, "_thematic_exposure_value", staticmethod(lambda: 5.0))
    sleeves, _ = nav.compute_sleeves()                               # controle: de opzet werkt
    assert sleeves["thematic_exposure"] == 5.0

    monkeypatch.setattr(sn.SleeveNAV, "_thematic_exposure_value", staticmethod(lambda: None))
    assert nav.compute_sleeves() is None, "onleesbare dip-koper moet de snapshot uitstellen"


def test_harvest_sluiten_is_reduce_only():
    from agents.treasury_agent import TreasuryAgent
    ex = MagicMock()
    ex.create_order.return_value = {"average": 100.0}
    zelf = SimpleNamespace(exchange_client=ex, _save_harvest_state=lambda s: None,
                           _send_telegram=lambda t: None)
    assert TreasuryAgent._close_harvest_position(
        zelf, {"asset": "ETH", "size": 0.01, "entry_price": 101.0}, "toets") is True
    args, kwargs = ex.create_order.call_args
    assert args[1] == "BUY" and kwargs.get("reduce_only") is True
