"""Conviction Core (barbell groei-been) + de treasury-earmark die het beschermt.

De kern die hier bewaakt wordt: treasury en conviction-core zijn twee allocators op
DEZELFDE wallet. Zonder de earmark sweept de treasury het DCA-kapitaal naar Aave
(auto-APPROVED) en is terughalen een handmatige bridge-stap.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.conviction_core import ConvictionCore


CFG = {
    "enabled": False,
    "target_usd": 650,
    "split_pct": {"BTC": 80, "ETH": 20},
    "bands": {"rebalance_drift_pp": 8, "min_trade_usd": 11, "cooldown_days": 7},
    "dca": {"max_deploy_per_run_usd": 82},
    "reserve_spot_usdc": 150,
}
PRICES = {"BTC": 63000.0, "ETH": 3000.0}


def _plan(values, free_usdc, state=None, cfg=None):
    return ConvictionCore().plan(cfg or CFG, values, PRICES, free_usdc, state or {})


def test_first_tranche_respects_dca_cap_and_split():
    """Eerste run met het $12,68-zaadje: deploy exact de tranche, 80/20 verdeeld."""
    trades = _plan({"BTC": 12.68, "ETH": 0.0}, free_usdc=653.0)

    assert {t["asset"] for t in trades} == {"BTC", "ETH"}
    total = sum(t["usd"] for t in trades)
    assert total == pytest.approx(82.0, abs=0.01), "DCA-cap overschreden"
    assert all(t["side"] == "buy" for t in trades)

    pool = 12.68 + 82.0
    btc = next(t for t in trades if t["asset"] == "BTC")
    eth = next(t for t in trades if t["asset"] == "ETH")
    assert btc["usd"] == pytest.approx(0.80 * pool - 12.68, abs=0.01)
    assert eth["usd"] == pytest.approx(0.20 * pool, abs=0.01)


def test_never_deploys_beyond_target():
    """Sleeve op target => geen nieuwe inzet, ook al staat er cash klaar."""
    assert _plan({"BTC": 520.0, "ETH": 130.0}, free_usdc=500.0) == []


def test_dca_stops_at_target_not_at_cash():
    """Laatste tranche is begrensd door het target ($30 resterend), niet door de
    DCA-cap ($82) of de beschikbare cash ($500). De ETH-poot is dan $6 en valt
    onder min_trade_usd — die wordt overgeslagen i.p.v. als stoforder geplaatst."""
    trades = _plan({"BTC": 496.0, "ETH": 124.0}, free_usdc=500.0)

    assert sum(t["usd"] for t in trades) <= 30.0 + 0.01
    assert [t["asset"] for t in trades] == ["BTC"]
    assert trades[0]["usd"] == pytest.approx(24.0, abs=0.01)


def test_no_free_cash_means_no_trades():
    assert _plan({"BTC": 12.68, "ETH": 0.0}, free_usdc=0.0) == []


def test_band_rebalance_only_outside_drift():
    """Zonder DCA vuurt alleen een échte drift (>8pp) — binnen de band niets."""
    on_target = _plan({"BTC": 520.0, "ETH": 130.0}, free_usdc=0.0, cfg={**CFG, "target_usd": 650})
    assert on_target == []

    # BTC 90% / ETH 10% => 10pp drift, buiten de band
    skewed = _plan({"BTC": 585.0, "ETH": 65.0}, free_usdc=0.0)
    assert {t["asset"]: t["side"] for t in skewed} == {"BTC": "sell", "ETH": "buy"}


def test_cooldown_is_reported_so_run_can_skip():
    """Na een verse trade draagt het plan een cooldown — run() slaat die over."""
    import datetime as dt

    today = dt.date.today().isoformat()
    trades = _plan({"BTC": 12.68, "ETH": 0.0}, free_usdc=653.0,
                   state={"last_action": {"BTC": today}})
    btc = next(t for t in trades if t["asset"] == "BTC")
    assert btc["cooldown"] is not None and btc["cooldown"] > 0
    eth = next(t for t in trades if t["asset"] == "ETH")
    assert eth["cooldown"] is None


# ── treasury-earmark ──────────────────────────────────────────────────────────

class _FakeExchange:
    def __init__(self, holdings):
        self._holdings = holdings

    def get_spot_holdings(self):
        return self._holdings

    def get_spot_price(self, asset):
        return PRICES[asset]


def _treasury(monkeypatch, tmp_path, holdings, target_usd=650):
    from agents.treasury_agent import TreasuryAgent

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "conviction_core.json").write_text(json.dumps({"target_usd": target_usd}))
    monkeypatch.chdir(tmp_path)
    return TreasuryAgent(exchange_client=_FakeExchange(holdings))


def test_earmark_reserves_full_target_before_dca(monkeypatch, tmp_path):
    agent = _treasury(monkeypatch, tmp_path, holdings={})
    assert agent._conviction_reserved_usd() == pytest.approx(650.0)


def test_earmark_shrinks_as_dca_deploys(monkeypatch, tmp_path):
    # ~$315 aan UBTC + ~$150 aan UETH is ingezet
    agent = _treasury(monkeypatch, tmp_path,
                      holdings={"UBTC": 0.005, "UETH": 0.05})
    assert agent._conviction_reserved_usd() == pytest.approx(650.0 - 465.0, abs=0.5)


def test_earmark_is_zero_when_sleeve_is_full(monkeypatch, tmp_path):
    agent = _treasury(monkeypatch, tmp_path, holdings={"UBTC": 0.02})
    assert agent._conviction_reserved_usd() == 0.0


def test_earmark_is_zero_when_sleeve_unfunded(monkeypatch, tmp_path):
    """target_usd=0 => geen reservering, treasury gedraagt zich als voorheen."""
    agent = _treasury(monkeypatch, tmp_path, holdings={}, target_usd=0)
    assert agent._conviction_reserved_usd() == 0.0


def test_earmark_fails_safe_when_holdings_unreadable(monkeypatch, tmp_path):
    """Onleesbare holdings => volledig target reserveren (nooit per ongeluk sweepen)."""
    class _Broken:
        def get_spot_holdings(self):
            raise RuntimeError("HL down")

    from agents.treasury_agent import TreasuryAgent

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "conviction_core.json").write_text(json.dumps({"target_usd": 650}))
    monkeypatch.chdir(tmp_path)
    agent = TreasuryAgent(exchange_client=_Broken())
    assert agent._conviction_reserved_usd() == pytest.approx(650.0)
