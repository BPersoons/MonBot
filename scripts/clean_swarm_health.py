
import logging
import os
from dotenv import load_dotenv

# Load .env.adk explicitly for local scripts
load_dotenv(".env.adk")

from utils.db_client import DatabaseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Cleanup")

def clean_swarm_health():
    db = DatabaseClient()
    if not db.is_available():
        logger.error("Database unavailable.")
        return

    logger.info("Cleaning up swarm_health table...")
    
    # 1. Fetch all rows
    try:
        response = db.client.table("swarm_health").select("*").execute()
        rows = response.data
        
        logger.info(f"Found {len(rows)} rows.")
        
        # 2. Identify duplicates / unwanted names
        # We want to keep: "Scout", "ProjectLead", "Risk Manager", "PerformanceAuditor", "ProductOwner", "Heartbeat"
        # plus analysts: "Technical Analyst", "Fundamental Analyst", "Sentiment Analyst", "Execution Agent", "Narrator"
        
        # If we see "ResearchAgent", we delete it (since we are moving to "Scout")
        
        for row in rows:
            name = row['agent_name']
            logger.info(f"Checking agent: {name}")
            
            if name == "ResearchAgent":
                logger.info(f"Deleting deprecated agent: {name}")
                db.client.table("swarm_health").delete().eq("agent_name", name).execute()
            
            # Remove any with empty names or weird chars if any
            if not name or name.strip() == "":
                 logger.info(f"Deleting invalid agent name: '{name}'")
                 db.client.table("swarm_health").delete().eq("agent_name", name).execute()
                 
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")

if __name__ == "__main__":
    clean_swarm_health()
