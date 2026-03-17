import sys
import os
import pandas as pd

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.fundamental_analyst import FundamentalAnalyst

def debug_fundamental_analyst():
    print("Initializing Fundamental Analyst...")
    agent = FundamentalAnalyst()
    
    ticker = "BTC"
    print(f"Analyzing {ticker}...")
    result = agent.analyze(ticker)
    
    print("\n--- FUNDAMENTAL ANALYSIS REPORT ---")
    print(f"Ticker: {result['ticker']}")
    print(f"Signal Score: {result['signal']} ({result['status']})")
    
    print("\n[Reasoning Engine]")
    for reason in result['reasoning']:
        print(f"- {reason}")
        
    print("\n[Raw Data Points]")
    print(f"Source Count: {result['data_points']['source_count']}")
    print(f"Is Stale Warning: {result['data_points']['is_stale_warning']}")

    return result

if __name__ == "__main__":
    debug_fundamental_analyst()
