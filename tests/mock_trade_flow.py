import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.project_lead import ProjectLead

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def test_trade_flow():
    print("\n--- Starting Mock Trade Flow ---\n")
    
    lead = ProjectLead()
    ticker = "BTC/USD"
    
    # Mocking analysts to force a trade for demonstration
    lead.technical_analyst.analyze = lambda x: {'agent': 'Tech', 'signal': 0.8, 'ticker': x}
    lead.fundamental_analyst.analyze = lambda x: {'agent': 'Fund', 'signal': 0.8, 'ticker': x}
    lead.sentiment_analyst.analyze = lambda x: {'agent': 'Sent', 'signal': 0.8, 'ticker': x}
    
    result = lead.process_opportunity(ticker)
    
    print(f"\nFinal Result for {ticker}: {result['status']}")
    if 'risk' in result:
        print(f"Risk Decision: {result['risk']}")
    if 'analysis' in result:
        print(f"Combined Score: {result['analysis']['combined_score']}")
        
    print("\n--- End Mock Trade Flow ---")

if __name__ == "__main__":
    test_trade_flow()
