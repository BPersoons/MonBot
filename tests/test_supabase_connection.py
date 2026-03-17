"""
Supabase Connection Test & Schema Validation
Run this after configuring SUPABASE_URL and SUPABASE_KEY in .env.adk
"""

import logging
import sys
import os
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.db_client import DatabaseClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("SupabaseTest")


def test_connection():
    """Test Supabase connection and configuration."""
    print("\n" + "="*60)
    print("SUPABASE CONNECTION TEST")
    print("="*60 + "\n")
    
    # Load environment
    load_dotenv(".env.adk")
    
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    
    # Check configuration
    print("1. Configuration Check")
    print("-" * 40)
    
    if not url or url == "https://your-project.supabase.co":
        print("❌ SUPABASE_URL not configured")
        print("   Please set SUPABASE_URL in .env.adk")
        return False
    else:
        print(f"✅ SUPABASE_URL: {url[:30]}...")
    
    if not key or key == "your-supabase-anon-key":
        print("❌ SUPABASE_KEY not configured")
        print("   Please set SUPABASE_KEY in .env.adk")
        return False
    else:
        print(f"✅ SUPABASE_KEY: {key[:20]}...")
    
    print()
    
    # Initialize client
    print("2. Client Initialization")
    print("-" * 40)
    
    try:
        db = DatabaseClient()
        print("✅ DatabaseClient initialized")
    except Exception as e:
        print(f"❌ Failed to initialize client: {e}")
        return False
    
    print()
    
    # Test connection
    print("3. Connection Test")
    print("-" * 40)
    
    if db.is_available():
        print("✅ Connection successful")
    else:
        print("❌ Connection failed")
        print("   Check your SUPABASE_URL and KEY")
        print("   Circuit breaker state:", db.circuit_breaker.get_status())
        return False
    
    print()
    
    # Validate schema
    print("4. Schema Validation")
    print("-" * 40)
    
    if db.ensure_schema():
        print("✅ All required tables exist:")
        print("   - trades")
        print("   - agent_performance")
        print("   - market_snapshots")
        print("   - system_state")
    else:
        print("❌ Schema validation failed")
        print("\n   Action required:")
        print("   1. Go to your Supabase dashboard")
        print("   2. Navigate to SQL Editor")
        print("   3. Run the script: integrations/supabase_schema.sql")
        return False
    
    print()
    
    # Test write operation
    print("5. Test Write Operation")
    print("-" * 40)
    
    test_data = {
        "ticker": "TEST/USD",
        "action": "BUY",
        "conviction": 1.5,
        "price": 100.0,
        "quantity": 0.1,
        "risk_metrics": {"kelly": 0.1},
        "analyst_signals": {"technical": 0.8}
    }
    
    test_reasoning = {
        "test": True,
        "timestamp": "2026-02-03T16:00:00"
    }
    
    try:
        success = db.log_trade_with_reasoning(test_data, test_reasoning)
        if success:
            print("✅ Write test successful")
            print("   Test trade logged successfully")
        else:
            print("❌ Write test failed")
            return False
    except Exception as e:
        print(f"❌ Write test failed: {e}")
        return False
    
    print()
    
    # Test read operation
    print("6. Test Read Operation")
    print("-" * 40)
    
    try:
        trades = db.get_latest_trades(limit=5)
        print(f"✅ Read test successful")
        print(f"   Retrieved {len(trades)} trades")
    except Exception as e:
        print(f"❌ Read test failed: {e}")
        return False
    
    print()
    print("="*60)
    print("🎉 ALL TESTS PASSED!")
    print("="*60)
    print("\nYour Supabase connection is ready for production use.")
    print()
    
    return True


def print_sql_command():
    """Print the SQL command for creating the trades table."""
    print("\n" + "="*60)
    print("SQL SCHEMA FOR TRADES TABLE")
    print("="*60 + "\n")
    
    sql = """
-- Trades Table with ADK Reasoning Trace
CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL CHECK (action IN ('BUY', 'SELL', 'HOLD')),
    conviction DECIMAL(5, 2),
    entry_price DECIMAL(15, 2),
    exit_price DECIMAL(15, 2),
    quantity DECIMAL(15, 8),
    pnl DECIMAL(15, 2),
    status VARCHAR(10) DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED')),
    risk_metrics JSONB,
    analyst_signals JSONB,
    reasoning_trace JSONB,  -- Full ADK decision chain
    audited BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trades_ticker_status ON trades(ticker, status);
CREATE INDEX IF NOT EXISTS idx_trades_audited ON trades(audited) WHERE status = 'CLOSED';
"""
    
    print(sql)
    print("\n" + "="*60)
    print("Copy the full schema from: integrations/supabase_schema.sql")
    print("="*60 + "\n")


if __name__ == "__main__":
    if "--sql" in sys.argv:
        print_sql_command()
    else:
        success = test_connection()
        
        if not success:
            print("\n💡 TIP: Run with --sql flag to see the schema SQL:")
            print("   python tests/test_supabase_connection.py --sql")
            sys.exit(1)
        
        sys.exit(0)
