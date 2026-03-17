
import logging
import time
from utils.db_client import DatabaseClient
from agents.product_owner import ProductOwner
from agents.project_lead import ProjectLead
from agents.research_agent import ResearchAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("VerifyDashboard")

def verify():
    db = DatabaseClient()
    if not db.test_connection()['connection_available']:
        logger.error("Database not connected")
        return

    logger.info("1. Testing Product Owner (Executive Summary)...")
    cpo = ProductOwner()
    # Mock LLM response by injecting it or just running it if LLM is active
    # We'll just create a manual backlog item to test the DB
    task = {
        "title": "Strategic Verification",
        "description": "System verified. Volatility radar active. Monitoring for breakouts.",
        "priority": "INFO",
        "category": "EXECUTIVE_SUMMARY"
    }
    cpo._create_backlog_task(task, allow_duplicates=True)
    
    logger.info("2. Testing Project Lead (Reasoning Stream)...")
    lead = ProjectLead()
    # Simulate a debate
    lead._update_reasoning_stream("Analyzing BTC volatility...")
    lead._update_reasoning_stream("Sentiment is Neutral (0.5)")
    lead._update_reasoning_stream("Technical Signal: BULLISH")
    
    # Push to DB
    lead.dashboard_provider.update_agent_status(
        "Project Lead", "WORKING", 
        task="Verifying Dashboard", 
        reasoning="Testing Reasoning Stream",
        meta={"reasoning_history": lead.reasoning_history}
    )

    logger.info("3. Testing Scout (Radar)...")
    # Manually update Scout status with mock Radar
    radar = [
        {"ticker": "SOL/USDT", "volatility": 4.5, "volume_m": 120},
        {"ticker": "PEPE/USDT", "volatility": 8.2, "volume_m": 45},
        {"ticker": "BTC/USDT", "volatility": 1.2, "volume_m": 800}
    ]
    db.update_swarm_health(
        "Scout", "WORKING", 
        task="Market Scan", 
        reasoning="Updating Radar", 
        meta={"radar_list": radar}
    )

    logger.info("4. Testing Trade Metrics (Mock Trade)...")
    # Log a dummy closed trade
    db.client.table("trades").insert({
        "ticker": "TEST/USDT",
        "action": "BUY",
        "status": "CLOSED",
        "entry_price": 100,
        "exit_price": 110,
        "pnl": 10.0,
        "quantity": 1,
        "conviction": 0.9
    }).execute()

    logger.info("✅ Verification Data Pushed to Supabase.")
    logger.info("Please check Swarm Pulse Dashboard to see:")
    logger.info("- CPO Strategic Update banner")
    logger.info("- Project Lead history in card")
    logger.info("- Scout Radar list in card")
    logger.info("- Win Rate / Profit Factor updated")

if __name__ == "__main__":
    verify()
