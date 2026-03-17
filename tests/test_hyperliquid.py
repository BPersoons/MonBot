import unittest
import time
import json
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.execution_agent import ExecutionAgent
from utils.exchange_client import HyperliquidExchange

class TestHyperliquidExecution(unittest.TestCase):
    def setUp(self):
        print("\n--- Setting up Hyperliquid Execution Test ---")
        
        # We must mock ccxt before ExecutionAgent initializes HyperliquidExchange
        from unittest.mock import patch, MagicMock
        self.patcher = patch('utils.exchange_client.ccxt.hyperliquid')
        self.mock_ccxt = self.patcher.start()
        
        # Setup mock ccxt client
        mock_client = MagicMock()
        mock_client.load_markets.return_value = {"BTC/USDC:USDC": {}}
        mock_client.fetch_ticker.return_value = {'last': 50000.0}
        mock_client.fetch_order_book.return_value = {'bids': [[49999, 1]], 'asks': [[50001, 1]]}
        mock_client.fetch_funding_rate.return_value = {'fundingRate': 0.01}
        self.mock_ccxt.return_value = mock_client
        
        self.agent = ExecutionAgent()
        # Verify Exchange is Hyperliquid
        self.assertIsInstance(self.agent.exchange, HyperliquidExchange)

    def tearDown(self):
        self.patcher.stop()

    def test_credentials_loaded(self):
        print("\n--- Testing Credential Loading ---")
        exchange = self.agent.exchange
        
        print(f"Wallet Address in Config: {exchange.wallet_address}")
        
        if exchange.signing_client:
            print("✅ Signing Client: INITIALIZED")
        else:
            print("❌ Signing Client: NOT INITIALIZED (Missing Keys?)")
            
        self.assertIsNotNone(exchange.wallet_address, "Wallet Address should not be None")
        self.assertIsNotNone(exchange.signing_client, "Signing Client should be initialized")

        print("Testing Public L1 Data Fetching...")
        
        # Debug symbols
        if hasattr(self.agent.exchange, 'markets'):
             print(f"Available markets: {list(self.agent.exchange.markets.keys())[:5]}...")
        
        ticker = "BTC/USDC:USDC" # Try the specific CCXT format for HL Perps
        if ticker not in self.agent.exchange.markets:
             ticker = "BTC/USD:USDC" # Alternate
             if ticker not in self.agent.exchange.markets:
                 ticker = "BTC/USDT" # Standard fallback
        
        # Mock public client data for deterministic tests handled by MagicMock in setUp
            
        print(f"Using Ticker: {ticker}")
        
        # 1. Price
        price = self.agent.exchange.get_market_price(ticker)
        print(f"L1 Price for {ticker}: {price}")
        self.assertGreater(price, 0)
        
        # 2. Orderbook
        ob = self.agent.exchange.get_l1_orderbook(ticker)
        print(f"L1 Orderbook: {ob}")
        self.assertIsNotNone(ob)
        self.assertGreater(ob['bid'], 0)
        self.assertGreater(ob['ask'], 0)
        
        # 3. Funding
        funding = self.agent.exchange.get_funding_rate(ticker)
        print(f"Funding Rate: {funding}")
        
    def test_mock_on_chain_execution(self):
        print("\n--- Testing Mocked On-Chain Execution ---")
        
        # Mock Signing Logic to pass without keys
        original_create = self.agent.exchange.create_order
        original_status = self.agent.exchange.fetch_order_status
        original_signing_client = self.agent.exchange.signing_client
        
        # Inject Mock Client just to pass check "if not self.signing_client"
        self.agent.exchange.signing_client = "MOCKED_CLIENT" # Dummy truthy value
        
        def mock_create(ticker, action, quantity, price=None, order_type='market'):
            print(f"MOCKED SIGNATURE: {action} {quantity} {ticker}")
            return {'id': '0xhash123', 'status': 'open'}
            
        def mock_status(order_id, ticker):
            # Return closed status immediately for test
            return {'id': order_id, 'status': 'closed', 'average': 60000.0, 'filled': 0.001, 'fee': {'cost': 0.5}} # 0.5 USDC gas/fees

        self.agent.exchange.create_order = mock_create
        self.agent.exchange.fetch_order_status = mock_status
        
        try:
            trade_proposal = {
                "ticker": "BTC/USDT", "action": "BUY", "size": 0.001, 
                "price": 60000.0, "conviction": 2.0, "metrics": {}
            }
            
            result = self.agent.execute_order(trade_proposal)
            
            print(json.dumps(result, indent=2))
            
            self.assertEqual(result['status'], 'OPEN')
            self.assertIn('funding_rate', result)
            self.assertEqual(result['fees'], 0.5)
            
        finally:
             self.agent.exchange.create_order = original_create
             self.agent.exchange.fetch_order_status = original_status
             self.agent.exchange.signing_client = original_signing_client

if __name__ == '__main__':
    unittest.main()
