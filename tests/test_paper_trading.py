import sys
import os
import json
import logging
import unittest
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.project_lead import ProjectLead
from utils.performance import PerformanceTracker
from agents.execution_agent import TRADE_LOG_FILE

# Setup logging
logging.basicConfig(level=logging.INFO)

class TestPaperTrading(unittest.TestCase):
    def setUp(self):
        # Clear trade log before test
        if os.path.exists(TRADE_LOG_FILE):
             os.remove(TRADE_LOG_FILE)
             
        self.lead = ProjectLead()
        
        # Mock Analysts to force a BUY
        self.lead.technical_analyst.analyze = MagicMock(return_value={'signal': 1.0, 'reason': 'Mock Bull', 'price': 50000.0})
        self.lead.fundamental_analyst.analyze = MagicMock(return_value={'signal': 1.0, 'reason': 'Mock Bull'})
        self.lead.sentiment_analyst.analyze = MagicMock(return_value={'signal': 1.0, 'reason': 'Mock Bull'})
        
        # Mock Risk Manager to Approve
        self.lead.risk_manager.validate_trade_proposal = MagicMock(return_value={
            "approved": True, 
            "metrics": {"recommended_size": 0.5},
            "reason": "Mock Approval"
        })
        
        # Mock LLM strictly for Paper Trading test to enforce BUILD_CASE
        self.lead.llm = MagicMock()
        self.lead.llm.available = True
        self.lead.llm.analyze_text.return_value = '''{
            "bull_case": "Mock Bull",
            "bear_case": "Mock Bear",
            "synthesis": "Mock",
            "final_score": 1.0,
            "rrr": "1:2",
            "stop_loss_pct": 5.0,
            "next_step": "BUILD_CASE",
            "target_entry_price": 50000.0,
            "monitoring_rationale": "N/A"
        }'''

    def test_end_to_end_execution(self):
        print("Running End-to-End Paper Trading Test...")
        
        # 1. Trigger Opportunity
        result = self.lead.process_opportunity("BTC")
        
        self.assertEqual(result['status'], "BUY")
        print("Trade Status: BUY confirmed.")
        
        # 2. Verify Log File
        self.assertTrue(os.path.exists(TRADE_LOG_FILE))
        
        with open(TRADE_LOG_FILE, 'r') as f:
            trades = json.load(f)
            
        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual(trade['ticker'], "BTC")
        self.assertEqual(trade['action'], "BUY")
        self.assertEqual(trade['quantity'], 0.5)
        # Check Slippage logic (Price should be slightly higher than 50000)
        self.assertGreater(trade['entry_price'], 50000.0) 
        
        print(f"Trade Logged Successfully: {trade}")
        
        # 3. Verify Performance Tracker Reading
        tracker = PerformanceTracker()
        metrics = tracker.calculate_metrics()
        
        self.assertEqual(metrics['open_positions'], 1)
        print("Performance Tracker saw the open position.")

if __name__ == '__main__':
    unittest.main()
