import sys
import os
import json
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.execution_agent import ExecutionAgent, TRADE_LOG_FILE

if __name__ == "__main__":
    print("Running Isolated Execution Agent Test...")
    if os.path.exists(TRADE_LOG_FILE):
        os.remove(TRADE_LOG_FILE)
        
    agent = ExecutionAgent()
    
    proposal = {
        "ticker": "TEST_BTC",
        "action": "BUY",
        "size": 1.0,
        "price": 1000.0,
        "metrics": {"recommended_size": 1.0}
    }
    
    agent.execute_order(proposal)
    
    if os.path.exists(TRADE_LOG_FILE):
        print("SUCCESS: Log file created.")
        with open(TRADE_LOG_FILE, 'r') as f:
            print(json.load(f))
    else:
        print("FAILURE: Log file not found.")
