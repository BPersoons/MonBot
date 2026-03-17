import json
import logging
from unittest.mock import MagicMock
from agents.project_lead import ProjectLead

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def generate_dashboard_data():
    print("--- Starting Dashboard Data Generation ---")
    
    # Initialize Project Lead
    lead = ProjectLead()
    
    # MOCKING Analyst Scores based on user request:
    # Sentiment: +0.75 (Bullish)
    # Technical: -0.30 (Bearish/Warning)
    # Fundamental: Let's stand at 0.0 (Neutral) for simplicity
    
    lead.sentiment_analyst.analyze = MagicMock(return_value={
        "ticker": "BTC", "signal": 0.75, "reason": "High social volume"
    })
    
    lead.technical_analyst.analyze = MagicMock(return_value={
        "ticker": "BTC", "signal": -0.30, "reason": "RSI Divergence"
    })
    
    lead.fundamental_analyst.analyze = MagicMock(return_value={
        "ticker": "BTC", "signal": 0.0, "reason": "No major news"
    })

    # Run the process
    result = lead.process_opportunity("BTC")
    
    # Save to JSON
    with open("dashboard.json", "w") as f:
        json.dump(result, f, indent=4)
        
    print("\n--- Dashboard Data Saved to dashboard.json ---")
    print(f"File content preview:")
    print(json.dumps(result, indent=2))
    
    print("\n--- Generated Directieverslag (Executive Summary) ---")
    print(result['payload_sent']['executive_summary'])
    print("-----------------------------------------------------")

if __name__ == "__main__":
    generate_dashboard_data()
