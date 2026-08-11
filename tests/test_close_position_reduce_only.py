"""Sluit-orders mogen NOOIT een positie kunnen openen.

Regressie op de bug die twee orphan-shorts maakte (2026-07-24 $2.107 notional,
2026-07-28 $128): close_position() stuurde een gewone market-order zonder
reduceOnly. Stond er in trade_log een positie die de beurs niet had, dan was die
"sluit"-SELL gewoon een verkoop — en die opende een short. Daarna werd de trade
als CLOSED geboekt met winst berekend tegen entry_price: fictieve PnL die ook nog
de weight-learning voedde.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agents.execution_agent as ea_mod
from agents.execution_agent import ExecutionAgent, PHANTOM_CLOSE_REASON


class _FakeExchange:
    """Legt vast waarmee create_order is aangeroepen; simuleert HL's reduceOnly."""

    def __init__(self, positions=None, fill=True, positions_raise=False):
        self.calls = []
        self._positions = positions if positions is not None else []
        self._fill = fill
        self._positions_raise = positions_raise
        self.signing_client = object()

    def create_order(self, ticker, action, quantity, price=None, order_type='market',
                     leverage=None, margin_mode=None, reduce_only=False):
        self.calls.append({"ticker": ticker, "action": action, "quantity": quantity,
                           "reduce_only": reduce_only})
        if not self._fill:
            return None
        return {"id": "1", "average": 100.0}

    def fetch_all_positions(self):
        if self._positions_raise:
            raise RuntimeError("HL unreachable")
        return self._positions

    def get_amount_precision(self, ticker):
        return 0.001

    def get_market_price(self, ticker):
        return 100.0

    def get_trade_costs(self, ticker, since_ms):
        return {"fees": 0.0, "funding_received": 0.0}


def _pos(symbol, size):
    return {"symbol": symbol, "contracts": size, "info": {"szi": str(size), "coin": symbol.split("/")[0]}}


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ea_mod, "_send_telegram", lambda *a, **k: None)
    return ExecutionAgent


def _write_log(trade):
    with open("trade_log.json", "w") as f:
        json.dump([trade], f)


def _open_trade(**over):
    t = {"id": "T1", "ticker": "BTC/USDC", "action": "BUY", "quantity": 0.01,
         "entry_price": 100.0, "status": "OPEN"}
    t.update(over)
    return t


def _make(agent_cls, exchange):
    a = agent_cls.__new__(agent_cls)
    a.exchange = exchange
    import logging
    a.logger = logging.getLogger("test")
    return a


# ── de kern: reduceOnly ───────────────────────────────────────────────────────

def test_close_sends_reduce_only(agent, tmp_path):
    ex = _FakeExchange(positions=[_pos("BTC/USDC:USDC", -0.01)])
    a = _make(agent, ex)
    _write_log(_open_trade())

    a.close_position("T1", reason="TAKE_PROFIT")

    assert len(ex.calls) == 1
    assert ex.calls[0]["reduce_only"] is True, "sluit-order zonder reduceOnly kan een positie OPENEN"


def test_partial_exit_sends_reduce_only(agent):
    """De partial-exit-tak deelt hetzelfde risico als de volledige sluiting."""
    import inspect
    src = inspect.getsource(ea_mod.ExecutionAgent)
    assert src.count("reduce_only=True") >= 2, (
        "zowel close_position() als de partial exit moeten reduce_only=True meesturen")


def test_opening_orders_stay_normal():
    """Openende orders mogen NOOIT reduceOnly krijgen — dan opent er niets meer."""
    import inspect
    src = inspect.getsource(ea_mod.ExecutionAgent)
    for line in src.splitlines():
        if "create_order(trade['ticker'], trade['action']" in line:
            assert "reduce_only" not in line


# ── spookpositie-afhandeling ─────────────────────────────────────────────────

def test_phantom_is_booked_flat_without_order(agent):
    """Beurs zegt expliciet 'geen positie' => wegboeken met PnL 0, niet blijven hertesten."""
    ex = _FakeExchange(positions=[], fill=False)
    a = _make(agent, ex)
    _write_log(_open_trade())

    assert a.close_position("T1", reason="TIME_EXIT_72H") is True

    with open("trade_log.json") as f:
        t = json.load(f)[0]
    assert t["status"] == "CLOSED"
    assert t["close_reason"] == PHANTOM_CLOSE_REASON
    assert t["pnl"] == 0.0 and t["pnl_net"] == 0.0


def test_real_position_that_fails_to_close_stays_open(agent):
    """Order mislukt maar de positie bestaat WEL => niet wegboeken."""
    ex = _FakeExchange(positions=[_pos("BTC/USDC:USDC", -0.01)], fill=False)
    a = _make(agent, ex)
    _write_log(_open_trade())

    assert a.close_position("T1", reason="STOP_LOSS") is False

    with open("trade_log.json") as f:
        assert json.load(f)[0]["status"] == "OPEN"


def test_unknown_position_state_stays_open(agent):
    """Fetch mislukt => onbepaald => NIET wegboeken (een echte positie stil sluiten is erger)."""
    ex = _FakeExchange(fill=False, positions_raise=True)
    a = _make(agent, ex)
    _write_log(_open_trade())

    assert a.close_position("T1", reason="STOP_LOSS") is False

    with open("trade_log.json") as f:
        assert json.load(f)[0]["status"] == "OPEN"


def test_has_live_position_tristate(agent):
    a = _make(agent, _FakeExchange(positions=[_pos("BTC/USDC:USDC", -0.01)]))
    assert a._has_live_position("BTC/USDC") is True
    assert a._has_live_position("ETH/USDC") is False

    a2 = _make(agent, _FakeExchange(positions=[_pos("BTC/USDC:USDC", 0.0)]))
    assert a2._has_live_position("BTC/USDC") is False, "size 0 telt niet als open positie"

    a3 = _make(agent, _FakeExchange(positions_raise=True))
    assert a3._has_live_position("BTC/USDC") is None


# ── auditor leert niet van boekhoudkundige sluitingen ────────────────────────

def test_auditor_skips_non_strategy_closures(tmp_path, monkeypatch):
    from utils.auditor import _NON_STRATEGY_CLOSE_REASONS

    assert PHANTOM_CLOSE_REASON in _NON_STRATEGY_CLOSE_REASONS
    assert "ORPHAN_CLEANUP" in _NON_STRATEGY_CLOSE_REASONS
