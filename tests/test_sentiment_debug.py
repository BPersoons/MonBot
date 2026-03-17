import sys
import os
import logging

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestSentiment")

def debug_web_intelligence():
    print("\n--- Testing WebIntelligence ---")
    try:
        from utils.web_intelligence import WebIntelligence
        wi = WebIntelligence()
        
        ticker = "BTC/USDT"
        print(f"Scanning social for {ticker}...")
        social = wi.scan_social_media(ticker)
        print(f"Social Items Found: {len(social)}")
        if social:
            print(f"Sample: {social[0]}")
            
        print(f"Scanning news for {ticker}...")
        news = wi.scan_news(ticker)
        print(f"News Items Found: {len(news)}")
        if news:
            print(f"Sample: {news[0]}")
            
        return social + news
    except ImportError:
        print("WebIntelligence module not found or dependencies missing.")
        return []
    except Exception as e:
        print(f"WebIntelligence Error: {e}")
        return []

def debug_llm_analysis(data):
    print("\n--- Testing LLM Client ---")
    if not data:
        print("No data to analyze. Skipping LLM test.")
        return

    try:
        from utils.llm_client import LLMClient
        llm = LLMClient()
        
        combined_text = "\n".join([f"- [{d['source']}] {d.get('text', '')}" for d in data[:5]])
        
        prompt = f"""
        You are a quantitative sentiment analyst for a hedge fund.
        Analyze sentiment for 'BTC/USDT' based on these snippets.
        
        Data:
        {combined_text}
        
        Output format:
        SCORE: <float between -1.0 and +1.0>
        RATIONALE: <one sentence>
        """
        
        print("Sending prompt to LLM...")
        response = llm.analyze_text(prompt)
        print(f"LLM Response:\n{response}")
        
    except ImportError:
        print("LLMClient module not found.")
    except Exception as e:
        print(f"LLMClient Error: {e}")

if __name__ == "__main__":
    # data = debug_web_intelligence()
    # Mock data to test LLM only
    data = [
        {"source": "twitter", "text": "Bitcoin is looking bullish today! breaking 100k soon"},
        {"source": "news", "text": "BTC ETF inflows hit record high"},
        {"source": "reddit", "text": "I'm selling everything, crash incoming"}
    ]
    debug_llm_analysis(data)
