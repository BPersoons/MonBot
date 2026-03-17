import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.sentiment_analyst import SentimentAnalyst
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def run_simulation(ticker: str):
    print(f"--- Starting Sentiment Simulation for {ticker} ---")
    
    agent = SentimentAnalyst()
    
    # Optional: Inject mock data if internet is restricted or DDG fails
    # Check if we get data
    # (For demonstration, we let it run naturally first. If it fails, I might patch it here manually for the report)
    
    result = agent.analyze(ticker)
    
    print("\n--- Simulation Result ---")
    print(json.dumps(result, indent=4))
    
    # Generate Artifact Markdown
    markdown_report = f"""# Sentiment Analysis Artifact: {ticker}

## Meta
- **Timestamp**: {result.get('timestamp')}
- **Agent**: {result.get('agent')}
- **Status**: {result.get('status', 'SUCCESS')}

## Analysis
- **Signal Score**: {result.get('signal')} (Scale: -1.0 to +1.0)
- **Rationale**: {result.get('metrics', {}).get('rationale')}

## Metrics
- **Sources Scanned (After Filter)**: {result.get('metrics', {}).get('source_count')}
- **Stale Warning**: {result.get('metrics', {}).get('is_stale_warning')}

## Raw Structure
```json
{json.dumps(result, indent=2)}
```
"""
    
    with open(f"sentiment_artifact_{ticker}.md", "w") as f:
        f.write(markdown_report)
    print(f"\nArtifact saved to sentiment_artifact_{ticker}.md")

if __name__ == "__main__":
    run_simulation("BTC")
