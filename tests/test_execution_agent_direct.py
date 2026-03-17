import unittest
import time
import json
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.execution_agent import ExecutionAgent
from utils.exchange_client import PaperExchange

class TestExecutionAgentDirect(unittest.TestCase):
    def setUp(self):
        print("\n--- Setting up Execution Agent Test ---")
        # Initialize Agent
        self.agent = ExecutionAgent()
        # Ensure we are using testnet exchange
        self.agent.exchange = PaperExchange(testnet=True)
        
        # Reset log file for clean test
        with open("trade_log.json", "w") as f:
            json.dump([], f)

    def test_paper_trade_execution(self):
        print("\n--- Testing Direct Paper Trade Execution ---")
        ticker = "BTC/USDT"
        
        # 1. Get Live Price
        self.agent.exchange.get_market_price = lambda t: 50000.0
        price = self.agent.exchange.get_market_price(ticker)
        print(f"Current Market Price: {price}")
        
        # 2. Create Trade Proposal
        trade_proposal = {
            "ticker": ticker,
            "action": "BUY",
            "size": 0.001, # Small size
            "price": price, 
            "conviction": 2.0,
            "analyst_signals": {"technical": 0.8},
            "synthesis_report": "Test Trade",
            "metrics": {"recommended_size": 0.001}
        }
        
        # 3. Mock Exchange Order Placement (since we lack API Keys)
        original_create_order = self.agent.exchange.create_order
        original_fetch_status = self.agent.exchange.fetch_order_status
        
        def mock_create_order(ticker, action, quantity, price=None, order_type='market'):
            print(f"MOCKED: Creating {action} order for {ticker}")
            return {'id': 'mock_order_123', 'price': price, 'amount': quantity, 'status': 'open'}
            
        def mock_fetch_status(order_id, ticker):
            print(f"MOCKED: Fetching status for {order_id}")
            return {'id': order_id, 'status': 'closed', 'average': price, 'filled': 0.001, 'fee': {'cost': 0.0001}}

        # Apply Mocks
        self.agent.exchange.create_order = mock_create_order
        self.agent.exchange.fetch_order_status = mock_fetch_status

        # 4. Execute Order
        print("Executing Order...")
        try:
            result = self.agent.execute_order(trade_proposal)
        finally:
             # Restore mocks
             self.agent.exchange.create_order = original_create_order
             self.agent.exchange.fetch_order_status = original_fetch_status
        
        # 5. Assertions
        self.assertIsNotNone(result)
        print(f"Trade Result Status: {result['status']}")
        
        self.assertIn(result['status'], ['OPEN', 'PLACED'])
        self.assertIn('execution_latency', result)
        self.assertIn('realized_slippage', result)
        
        print(f"Execution Latency: {result.get('execution_latency')}s")
        print(f"Realized Slippage: {result.get('realized_slippage')}")
        
        # 5. Verify Log File
        with open("trade_log.json", "r") as f:
            logs = json.load(f)
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]['id'], result['id'])
            print("Trade logged successfully.")

if __name__ == '__main__':
    unittest.main()
