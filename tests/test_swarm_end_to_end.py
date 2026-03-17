import unittest
import time
import json
import os
import sys

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.project_lead import ProjectLead
from agents.execution_agent import ExecutionAgent
from utils.exchange_client import PaperExchange

class TestSwarmEndToEnd(unittest.TestCase):
    def setUp(self):
        print("\n--- Setting up Swarm Test ---")
        self.project_lead = ProjectLead()
        # Ensure we are using PaperExchange
        self.assertIsInstance(self.project_lead.execution_agent.exchange, PaperExchange)
        print("PaperExchange validated.")

    def test_full_flow_btc(self):
        print("\n--- Testing Full Flow for BTC/USDT ---")
        ticker = "BTC/USDT"
        
        # 1. Scout / Analysis (Real Data)
        print(f"1. Scout analyzing {ticker}...")
        result = self.project_lead.process_opportunity(ticker)
        
        print(f"Analysis Result: {result.get('status')}")
        print(f"Combined Score: {result.get('combined_score')}")
        
        # Check integrity of result
        self.assertIn('combined_score', result)
        self.assertIn('analysis', result)
        
        # 2. Check if Business Case was generated (if Score > 1.5)
        if result['combined_score'] > 1.5:
             payload = result.get('payload_sent', {})
             business_case = payload.get('business_case', {})
             print("2. Business Case Generated:")
             print(json.dumps(business_case, indent=2))
             
             if result['status'] == 'BUY':
                 print("3. Execution Triggered (Paper Trading)")
                 # We can check trade log
                 with open("trade_log.json", "r") as f:
                     trades = json.load(f)
                     last_trade = trades[-1]
                     print(f"Last Trade Status: {last_trade['status']}")
                     if last_trade['status'] in ['OPEN', 'PLACED']:
                         print(f"Execution Latency: {last_trade.get('execution_latency', 'N/A')}s")
                         print(f"Realized Slippage: {last_trade.get('realized_slippage', 'N/A')}")
        else:
            print("Score too low for Execution test. Simulating high score force-run...")
            # We can force execution to test that part if natural flow didn't trigger
            trade_proposal = {
                "ticker": ticker,
                "action": "BUY",
                "conviction": 2.0,
                "size": 0.001, # Small amount
                "price": self.project_lead.execution_agent.exchange.get_market_price(ticker),
                "metrics": {"recommended_size": 0.001}
            }
            if trade_proposal['price'] > 0:
                print("Force-Executing Trade Proposal...")
                exec_result = self.project_lead.execution_agent.execute_order(trade_proposal)
                if exec_result:
                    print(f"Force Execution Status: {exec_result['status']}")
                    print(f"Latency: {exec_result.get('execution_latency')}")
                else:
                    print("Force Execution Failed (likely API keys missing or network issue).")
            else:
                print("Could not fetch price for Force Execution.")

if __name__ == '__main__':
    unittest.main()
