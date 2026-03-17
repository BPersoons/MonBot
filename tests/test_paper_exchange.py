import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.exchange_client import PaperExchange

class TestPaperExchange(unittest.TestCase):
    def test_init(self):
        print("Testing PaperExchange Init...")
        try:
            exchange = PaperExchange(testnet=True)
            print("PaperExchange initialized.")
            if exchange.public_client:
                print("Public client initialized.")
                
                # Fetch Ticker
                print("Fetching Ticker BTC/USDT...")
                price = exchange.get_market_price("BTC/USDT")
                print(f"Price: {price}")
                self.assertGreater(price, 0)
            else:
                print("Exchange init failed (check logs).")
        except Exception as e:
            print(f"Exception: {e}")
            raise e

if __name__ == '__main__':
    unittest.main()
