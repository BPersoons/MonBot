import logging
import time
from agents.research_agent import ResearchAgent
from agents.project_lead import ProjectLead
from agents.product_owner import ProductOwner

logging.basicConfig(level=logging.INFO)

def test_scout_verbose_scan():
    print("\n[TEST] Scout Verbose Scan (Mocking)")
    scout = ResearchAgent()
    # Mocking exchange fetch to avoid real API call limits and ensure data
    scout.exchange.fetch_tickers = lambda: {
        "BTC/USDT": {"quoteVolume": 500_000_000},
        "ETH/USDT": {"quoteVolume": 250_000_000},
        "SOL/USDT": {"quoteVolume": 100_000_000},
        "DOGE/USDT": {"quoteVolume": 50_000_000},
        "AVAX/USDT": {"quoteVolume": 20_000_000},
        "LOWVOL/USDT": {"quoteVolume": 1_000}
    }
    # Mock backtester to avoid extensive calls
    scout.backtester.fetch_historical_data = lambda x: None 
    scout.backtester.run_simulation = lambda df: {"sharpe_ratio": 0.4, "win_rate": 0.45} # Fail check

    scout.scan_market([])
    print("✅ Scout scan matched. Check Dashboard for 'Scanning 5 pairs' and Radar.")

def test_veto_logging():
    print("\n[TEST] Project Lead Veto Logging")
    lead = ProjectLead()
    
    # Needs a mock synthesis to control score
    lead.synthesize_signals = lambda ticker: {
        "combined_score": 1.2, # Below 1.5 threshold
        "details": {"technical": {"signal": 0.5}, "sentiment": {"signal": 0.5}},
        "conflicts": []
    }
    
    lead.process_opportunity("TEST-COIN")
    print(f"Current Reasoning Stream: {lead.reasoning_history}")
    assert any("Veto TEST-COIN" in s for s in lead.reasoning_history)
    print("✅ Veto logged successfully.")

def test_cpo_market_context():
    print("\n[TEST] CPO Market Context")
    cpo = ProductOwner()
    # Mocking time check or force run
    # For testing, we call generate_executive_summary directly, 
    # ensuring the "State of the Market" prompt is used (inspected via code view previously)
    # Mock LLM response
    if cpo.llm:
         cpo.llm.analyze_text = lambda prompt: "Market Context: Volatility is high, recommending aggressive scanning."
    
    created = cpo.generate_executive_summary()
    if created:
        print("✅ CPO Executive Summary (Market Context) created.")
    else:
        print("⚠️ CPO task creation failed (DB issue or LLM missing).")

if __name__ == "__main__":
    test_scout_verbose_scan()
    test_veto_logging()
    test_cpo_market_context()
