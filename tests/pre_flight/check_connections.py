import sys
import logging
from utils.db_client import DatabaseClient
from utils.exchange_client import HyperliquidExchange

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PreFlight-Connections")

def check_supabase():
    try:
        logger.info("📡 Checking Supabase connection...")
        db = DatabaseClient()
        status = db.test_connection()
        
        if status["connection_available"]:
            logger.info("✅ Supabase Connected")
            return True
        else:
            logger.error("❌ Supabase Connection Failed")
            logger.error(f"Details: {status}")
            return False
    except Exception as e:
        logger.error(f"❌ Supabase Check Exception: {e}")
        return False

def check_hyperliquid():
    try:
        logger.info("📡 Checking Hyperliquid connection...")
        # Initialize in View-Only mode (no signing needed for basic check) but standard init does both
        exchange = HyperliquidExchange(testnet=True)
        
        if not exchange.public_client:
             logger.error("❌ Hyperliquid Public Client failed to initialize")
             return False

        # Attempt to fetch BTC price as a simple "hello"
        price = exchange.get_market_price("BTC/USDC") # Hyperliquid symbols usually work with /USDC
        
        if price > 0:
            logger.info(f"✅ Hyperliquid Connected (BTC Price: {price})")
            return True
        else:
            # Try check local markets cache size
            if len(exchange.markets) > 0:
                 logger.info(f"✅ Hyperliquid Connected (Markets loaded: {len(exchange.markets)})")
                 return True
            
            logger.error("❌ Hyperliquid Connection Failed (Price=0, No Markets)")
            return False
            
    except Exception as e:
        logger.error(f"❌ Hyperliquid Check Exception: {e}")
        return False

if __name__ == "__main__":
    success = True
    
    if not check_supabase():
        success = False
        
    if not check_hyperliquid():
        # strict gating might be optional, but for "Continuous Integrity" we default to strict
        success = False
        
    if success:
        logger.info("✅ PRE-FLIGHT CONNECTION CHECK PASSED")
        sys.exit(0)
    else:
        logger.error("🛑 PRE-FLIGHT CONNECTION CHECK FAILED")
        sys.exit(1)
