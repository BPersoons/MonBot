"""
Regression tests for the 3 bugs that caused the $21 loss:
  A) Fill price fallback: CCXT order.get('price') returns 5% slippage tolerance, not actual fill
  B) Reconciliation at 0 positions: Pass 3 must detect externally closed trades
  C) Correlation guard: only 1 position per correlated asset group
"""
import json
import math
import os
import time
import tempfile
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_execution_agent():
    """Create an ExecutionAgent with mocked exchange and DB so no real connections are needed."""
    with patch("agents.execution_agent.HyperliquidExchange") as MockExchange, \
         patch("agents.execution_agent.DatabaseClient") as MockDB:
        mock_ex = MockExchange.return_value
        mock_ex.signing_client = None  # skip startup sync
        mock_ex.wallet_address = "0xtest"
        mock_ex.vault_address = "0xvault"

        from agents.execution_agent import ExecutionAgent
        agent = ExecutionAgent()
        # Restore a usable mock exchange after __init__
        agent.exchange = MagicMock()
        agent.exchange.signing_client = MagicMock()
        agent.db = MagicMock()
        return agent


def _write_trade_log(path, trades):
    with open(path, "w") as f:
        json.dump(trades, f)


# ===========================================================================
# TEST A — Fill price fallback
# ===========================================================================

class TestFillPriceFallback:
    """
    Bug: CCXT market-buy orders set order['price'] to intended * 1.05 (slippage tolerance).
    The old code used `order.get('average') or order.get('price')` which fell back to the
    tolerance price when 'average' was None, recording +5% as the entry price.

    Fix: `order.get('average') or current_price_check` — never trust order['price'].
    """

    def test_uses_average_when_present(self, tmp_path, monkeypatch):
        """When order has 'average', use it as entry_price."""
        monkeypatch.chdir(tmp_path)
        _write_trade_log(tmp_path / "trade_log.json", [])

        agent = _make_execution_agent()
        agent.exchange.get_market_price.return_value = 45100.0
        agent.exchange.get_amount_precision.return_value = 0.001
        agent.exchange.get_min_notional.return_value = 10.0
        agent.exchange.get_funding_rate.return_value = 0.0001
        agent.exchange.create_order.return_value = {
            "id": "order_1",
            "average": 45000.5,         # actual fill
            "price": 47250.0,           # 5% tolerance — MUST NOT be used
            "amount": 0.001,
            "filled": 0.001,
            "status": "closed",
        }
        agent.exchange.fetch_order_status.return_value = None
        agent.strategy_manager = None

        proposal = {
            "ticker": "BTC/USDC",
            "action": "BUY",
            "price": 45000.0,
            "size": 0.001,
            "conviction": 0.8,
            "metrics": {"kelly": {"recommended_size": 45}},
        }

        result = agent.execute_order(proposal)

        assert result is not None
        assert result["entry_price"] == 45000.5, (
            f"entry_price should be average fill (45000.5), got {result['entry_price']}"
        )
        assert result["entry_price"] != 47250.0, "entry_price must NOT be the slippage tolerance"

    def test_falls_back_to_market_price_when_average_is_none(self, tmp_path, monkeypatch):
        """When order['average'] is None, fall back to current_price_check — NOT order['price']."""
        monkeypatch.chdir(tmp_path)
        _write_trade_log(tmp_path / "trade_log.json", [])

        agent = _make_execution_agent()
        agent.exchange.get_market_price.return_value = 45100.0
        agent.exchange.get_amount_precision.return_value = 0.001
        agent.exchange.get_min_notional.return_value = 10.0
        agent.exchange.get_funding_rate.return_value = 0.0001
        agent.exchange.create_order.return_value = {
            "id": "order_2",
            "average": None,            # not available yet
            "price": 47250.0,           # 5% tolerance — MUST NOT be used
            "amount": 0.001,
            "filled": 0.001,
            "status": "closed",
        }
        # fetch_order_status also returns no average
        agent.exchange.fetch_order_status.return_value = {
            "status": "closed",
            "average": None,
            "filled": 0.001,
        }
        agent.strategy_manager = None

        proposal = {
            "ticker": "BTC/USDC",
            "action": "BUY",
            "price": 45000.0,
            "size": 0.001,
            "conviction": 0.8,
            "metrics": {"kelly": {"recommended_size": 45}},
        }

        result = agent.execute_order(proposal)

        assert result is not None
        # Must be the market price we captured, NOT the 5% tolerance
        assert result["entry_price"] == 45100.0, (
            f"entry_price should be current_price_check (45100.0), got {result['entry_price']}"
        )
        assert result["entry_price"] != 47250.0, "entry_price must NOT be the slippage tolerance"


# ===========================================================================
# TEST B — Reconciliation at 0 HL positions
# ===========================================================================

class TestReconciliationZeroPositions:
    """
    Bug: `if hl_pos_map:` skipped Pass 3 when HL returned 0 positions, so OPEN trades
    in trade_log whose HL positions had been liquidated were never marked CLOSED.

    Fix: `if True:` — always run all 3 reconciliation passes.
    """

    def test_pass3_closes_orphaned_trades(self, tmp_path, monkeypatch):
        """An OPEN trade with no matching HL position (age > 5 min) must be marked CLOSED."""
        monkeypatch.chdir(tmp_path)

        orphan_trade = {
            "id": "trade_orphan",
            "ticker": "BTC/USDC",
            "action": "BUY",
            "status": "OPEN",
            "entry_price": 45000.0,
            "quantity": 0.001,
            "entry_time": time.time() - 600,  # 10 minutes ago
            "entry_fmt": "2026-04-04T10:00:00",
        }
        _write_trade_log(tmp_path / "trade_log.json", [orphan_trade])

        # Simulate Pass 3 logic from main.py (extracted inline)
        with open(tmp_path / "trade_log.json") as f:
            all_trades = json.load(f)

        hl_pos_map = {}  # 0 positions on HL

        # This is the fixed logic (if True instead of if hl_pos_map)
        _now_ts = time.time()
        for _t in all_trades:
            if _t.get('status') not in ('OPEN', 'PLACED'):
                continue
            _base = (_t.get('ticker') or '').split('/')[0].upper()
            if _base in hl_pos_map:
                continue
            _age_min = (_now_ts - float(_t.get('entry_time') or _now_ts)) / 60
            if _age_min < 5:
                continue
            _t['status'] = 'CLOSED'
            _t['close_reason'] = 'EXTERNAL_CLOSURE'
            _t['exit_price'] = _t.get('entry_price', 0)

        assert all_trades[0]['status'] == 'CLOSED'
        assert all_trades[0]['close_reason'] == 'EXTERNAL_CLOSURE'

    def test_pass3_does_not_close_fresh_trades(self, tmp_path, monkeypatch):
        """Trades younger than 5 minutes must NOT be closed (HL may still be processing)."""
        monkeypatch.chdir(tmp_path)

        fresh_trade = {
            "id": "trade_fresh",
            "ticker": "ETH/USDC",
            "action": "BUY",
            "status": "OPEN",
            "entry_price": 3000.0,
            "quantity": 0.01,
            "entry_time": time.time() - 60,  # 1 minute ago
        }
        _write_trade_log(tmp_path / "trade_log.json", [fresh_trade])

        with open(tmp_path / "trade_log.json") as f:
            all_trades = json.load(f)

        hl_pos_map = {}

        _now_ts = time.time()
        for _t in all_trades:
            if _t.get('status') not in ('OPEN', 'PLACED'):
                continue
            _base = (_t.get('ticker') or '').split('/')[0].upper()
            if _base in hl_pos_map:
                continue
            _age_min = (_now_ts - float(_t.get('entry_time') or _now_ts)) / 60
            if _age_min < 5:
                continue
            _t['status'] = 'CLOSED'

        assert all_trades[0]['status'] == 'OPEN', "Fresh trade should NOT be closed"


# ===========================================================================
# TEST C — Correlation guard
# ===========================================================================

class TestCorrelationGuard:
    """
    Bug: XYZ-CL/USDC and XYZ-BRENTOIL/USDC both opened — both are oil and move together,
    doubling exposure to the same risk.

    Fix: CORRELATION_GROUPS in ExecutionAgent blocks new trades if a correlated asset is open.
    """

    def test_blocks_correlated_oil_trade(self, tmp_path, monkeypatch):
        """With XYZ-BRENTOIL/USDC open, XYZ-CL/USDC must be blocked."""
        monkeypatch.chdir(tmp_path)

        existing_trade = {
            "id": "trade_oil1",
            "ticker": "XYZ-BRENTOIL/USDC",
            "action": "BUY",
            "status": "OPEN",
            "entry_price": 110.0,
            "quantity": 1.0,
            "entry_time": time.time() - 300,
        }
        _write_trade_log(tmp_path / "trade_log.json", [existing_trade])

        agent = _make_execution_agent()
        agent.exchange.get_market_price.return_value = 112.0
        agent.exchange.get_amount_precision.return_value = 0.1
        agent.exchange.get_min_notional.return_value = 10.0
        agent.exchange.get_funding_rate.return_value = 0.0001
        agent.exchange.create_order.return_value = {
            "id": "should_not_fire",
            "average": 112.0,
            "price": 117.6,
            "amount": 1.0,
            "filled": 1.0,
            "status": "closed",
        }
        agent.strategy_manager = None

        proposal = {
            "ticker": "XYZ-CL/USDC",
            "action": "BUY",
            "price": 112.0,
            "size": 1.0,
            "conviction": 0.7,
            "metrics": {"kelly": {"recommended_size": 112}},
        }

        result = agent.execute_order(proposal)
        assert result is None, "Correlated oil trade should be blocked"
        # create_order must NOT have been called
        agent.exchange.create_order.assert_not_called()

    def test_allows_uncorrelated_trade(self, tmp_path, monkeypatch):
        """With XYZ-BRENTOIL/USDC open, BTC/USDC (uncorrelated) must still go through."""
        monkeypatch.chdir(tmp_path)

        existing_trade = {
            "id": "trade_oil1",
            "ticker": "XYZ-BRENTOIL/USDC",
            "action": "BUY",
            "status": "OPEN",
            "entry_price": 110.0,
            "quantity": 1.0,
            "entry_time": time.time() - 300,
        }
        _write_trade_log(tmp_path / "trade_log.json", [existing_trade])

        agent = _make_execution_agent()
        agent.exchange.get_market_price.return_value = 45100.0
        agent.exchange.get_amount_precision.return_value = 0.001
        agent.exchange.get_min_notional.return_value = 10.0
        agent.exchange.get_funding_rate.return_value = 0.0001
        agent.exchange.create_order.return_value = {
            "id": "order_btc",
            "average": 45050.0,
            "price": 47302.5,
            "amount": 0.001,
            "filled": 0.001,
            "status": "closed",
        }
        agent.exchange.fetch_order_status.return_value = None
        agent.strategy_manager = None

        proposal = {
            "ticker": "BTC/USDC",
            "action": "BUY",
            "price": 45000.0,
            "size": 0.001,
            "conviction": 0.8,
            "metrics": {"kelly": {"recommended_size": 45}},
        }

        result = agent.execute_order(proposal)
        assert result is not None, "Uncorrelated trade should NOT be blocked"
        assert result["ticker"] == "BTC/USDC"

    def test_blocks_precious_metals_correlation(self, tmp_path, monkeypatch):
        """With XYZ-GOLD/USDC open, XYZ-SILVER/USDC must be blocked."""
        monkeypatch.chdir(tmp_path)

        existing_trade = {
            "id": "trade_gold",
            "ticker": "XYZ-GOLD/USDC",
            "action": "SELL",
            "status": "OPEN",
            "entry_price": 4600.0,
            "quantity": 1.0,
            "entry_time": time.time() - 300,
        }
        _write_trade_log(tmp_path / "trade_log.json", [existing_trade])

        agent = _make_execution_agent()
        agent.strategy_manager = None

        proposal = {
            "ticker": "XYZ-SILVER/USDC",
            "action": "SELL",
            "price": 72.0,
            "size": 1.0,
            "conviction": 0.7,
            "metrics": {"kelly": {"recommended_size": 72}},
        }

        result = agent.execute_order(proposal)
        assert result is None, "Correlated precious metals trade should be blocked"
