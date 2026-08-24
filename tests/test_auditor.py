import unittest
from unittest.mock import MagicMock, patch
import time
from datetime import datetime, timedelta
from agents.execution_agent import ExecutionAgent

class TestPreFlightAuditor(unittest.TestCase):
    def setUp(self):
        # Patch dependencies before Init
        with patch('agents.execution_agent.DatabaseClient'), \
             patch('agents.execution_agent.HyperliquidExchange'):
             
            self.agent = ExecutionAgent()
            # Mock logger to avoid clutter
            self.agent.logger = MagicMock()

    def test_auditor_pass_base_case(self):
        """Test ideal scenario: Immediate execution, no slippage."""
        trade_data = {
            "action": "BUY",
            "approved_at_price": 50000.0,
            "max_slippage_allowed": 0.005,
            "approval_time": datetime.now().isoformat()
        }
        current_price = 50000.0
        
        result = self.agent.perform_pre_flight_check(trade_data, current_price)
        self.assertTrue(result['passed'])
        print(f"\n✓ Base Case Passed: {result['reason']}")

    def test_tien_minuten_oud_is_niet_verlopen(self):
        """Tien minuten oud mag gewoon door — de grens ligt op 60 minuten.

        Deze toets eiste eerst een harde afwijzing met "Stale Data" bij >5
        minuten. Dat gedrag bestaat niet meer: de drempel staat op 60 minuten
        en daarboven volgt geen afwijzing maar een LLM-hertoets (zie de
        docstring van perform_pre_flight_check). De toets legde dus een
        vervangen ontwerp vast en faalde op de vervanging.
        """
        tien_min = (datetime.now() - timedelta(minutes=10)).isoformat()
        result = self.agent.perform_pre_flight_check({
            "action": "BUY", "approved_at_price": 50000.0, "approval_time": tien_min,
        }, 50000.0)
        self.assertTrue(result['passed'], result['reason'])

    def test_late_goedkeuring_gaat_naar_de_llm_hertoets(self):
        """Boven de 60 minuten beslist de LLM-hertoets, in beide richtingen.

        Dat pad had geen enkele toets, terwijl het de laatste horde is vóór een
        echte order.
        """
        laat = (datetime.now() - timedelta(minutes=90)).isoformat()
        trade = {
            "action": "BUY", "ticker": "BTC/USDC",
            "approved_at_price": 50000.0, "approval_time": laat,
        }

        with patch.object(self.agent, '_revalidate_thesis',
                          return_value=(False, "these achterhaald")) as afwijzen:
            result = self.agent.perform_pre_flight_check(trade, 50000.0)
        afwijzen.assert_called_once()
        self.assertFalse(result['passed'])
        self.assertIn("LLM Rejection", result['reason'])

        with patch.object(self.agent, '_revalidate_thesis',
                          return_value=(True, "these staat nog")):
            result = self.agent.perform_pre_flight_check(trade, 50000.0)
        self.assertTrue(result['passed'])
        self.assertIn("LLM Validated", result['reason'])

    def test_auditor_reject_slippage_buy(self):
        """Test excessive slippage on BUY (Price goes UP)."""
        trade_data = {
            "action": "BUY",
            "approved_at_price": 50000.0,
            "max_slippage_allowed": 0.005 # 0.5%
        }
        # Price moves up 1% (Bad for BUY)
        current_price = 50500.0 
        
        result = self.agent.perform_pre_flight_check(trade_data, current_price)
        self.assertFalse(result['passed'])
        self.assertIn("Excessive Slippage", result['reason'])
        print(f"✓ Slippage (Buy) Case Passed (Rejected as expected): {result['reason']}")

    def test_auditor_accept_favorable_move(self):
        """Test favorable price movement (Price drops for BUY)."""
        trade_data = {
            "action": "BUY",
            "approved_at_price": 50000.0,
            "max_slippage_allowed": 0.005
        }
        # Price moves DOWN 1% (Good for BUY)
        current_price = 49500.0
        
        result = self.agent.perform_pre_flight_check(trade_data, current_price)
        self.assertTrue(result['passed'])
        print(f"✓ Favorable Move Logic Passed: {result['reason']}")

    def test_auditor_reject_slippage_sell(self):
        """Test excessive slippage on SELL (Price goes DOWN)."""
        trade_data = {
            "action": "SELL",
            "approved_at_price": 50000.0,
            "max_slippage_allowed": 0.005
        }
        # Price moves DOWN 1% (Bad for SELL)
        current_price = 49500.0
        
        result = self.agent.perform_pre_flight_check(trade_data, current_price)
        self.assertFalse(result['passed'])
        self.assertIn("Excessive Slippage", result['reason'])
        print(f"✓ Slippage (Sell) Case Passed (Rejected as expected): {result['reason']}")

if __name__ == '__main__':
    unittest.main()
