"""
Trade Log Migration Script
Migrates trade_log.json to Supabase PostgreSQL.
"""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

# Add parent directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from integrations.supabase_client import SupabaseClient
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("TradeMigration")


def backup_file(file_path: str) -> bool:
    """Create backup of trade log."""
    if not os.path.exists(file_path):
        logger.warning(f"File not found: {file_path}")
        return False
    
    backup_path = f"{file_path}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        shutil.copy2(file_path, backup_path)
        logger.info(f"✓ Backup created: {backup_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to backup {file_path}: {e}")
        return False


def migrate_trades(supabase_client: SupabaseClient, trades_data: list) -> tuple:
    """
    Migrate trade records to Supabase.
    
    Args:
        supabase_client: SupabaseClient instance
        trades_data: List of trade records
        
    Returns:
        Tuple of (success_count, error_count)
    """
    success_count = 0
    error_count = 0
    
    for trade in trades_data:
        try:
            # Transform to expected format
            trade_record = {
                "ticker": trade.get("ticker"),
                "action": trade.get("action", "BUY"),
                "conviction": trade.get("conviction", 0.0),
                "entry_price": trade.get("price") or trade.get("entry_price", 0.0),
                "exit_price": trade.get("exit_price"),
                "quantity": trade.get("quantity", 0.0),
                "pnl": trade.get("pnl"),
                "status": trade.get("status", "CLOSED"),
                "risk_metrics": trade.get("metrics") or trade.get("risk_metrics", {}),
                "analyst_signals": trade.get("analyst_signals", {}),
                "created_at": trade.get("timestamp") or trade.get("created_at"),
                "closed_at": trade.get("closed_at")
            }
            
            success = supabase_client.log_trade(trade_record)
            if success:
                success_count += 1
            else:
                error_count += 1
                logger.warning(f"Failed to migrate trade: {trade.get('ticker')}")
                
        except Exception as e:
            error_count += 1
            logger.error(f"Error migrating trade: {e}")
    
    return success_count, error_count


def main():
    """Main migration function."""
    logger.info("="*60)
    logger.info("TRADE LOG MIGRATION")
    logger.info("="*60)
    logger.info("This script migrates trade_log.json to Supabase")
    logger.info("="*60)
    
    # Initialize Supabase client
    supabase = SupabaseClient()
    
    if not supabase.is_available():
        logger.error("Supabase client not available")
        logger.error("Please check your SUPABASE_URL and SUPABASE_KEY environment variables")
        return 1
    
    # Check schema
    if not supabase.check_schema():
        logger.error("Supabase schema not ready")
        logger.error("Please run the SQL schema file in your Supabase dashboard:")
        logger.error("  integrations/supabase_schema.sql")
        return 1
    
    logger.info("✓ Supabase client ready")
    
    # Load trade log
    trade_log_path = "trade_log.json"
    
    if not os.path.exists(trade_log_path):
        logger.warning(f"No {trade_log_path} found. Nothing to migrate.")
        return 0
    
    try:
        with open(trade_log_path, 'r') as f:
            trades = json.load(f)
        
        if not isinstance(trades, list):
            logger.error("trade_log.json is not a list of trades")
            return 1
        
        logger.info(f"Loaded {len(trades)} trade records from {trade_log_path}")
        
    except Exception as e:
        logger.error(f"Error loading trade log: {e}")
        return 1
    
    # Confirm migration
    print(f"\nFound {len(trades)} trade records to migrate")
    print("\nA backup will be created automatically.")
    
    response = input("\nProceed with migration? (yes/no): ").strip().lower()
    if response != "yes":
        logger.info("Migration cancelled by user")
        return 0
    
    # Backup
    if not backup_file(trade_log_path):
        logger.error("Backup failed. Migration aborted.")
        return 1
    
    # Migrate
    logger.info("\nMigrating trades to Supabase...")
    success_count, error_count = migrate_trades(supabase, trades)
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("MIGRATION SUMMARY")
    logger.info("="*60)
    logger.info(f"Total records: {len(trades)}")
    logger.info(f"✓ Successfully migrated: {success_count}")
    logger.info(f"✗ Errors: {error_count}")
    logger.info("="*60)
    
    if error_count == 0:
        logger.info("\n🎉 Migration completed successfully!")
        logger.info("\nNext steps:")
        logger.info("  1. Verify data in Supabase dashboard")
        logger.info("  2. Test trade logging: python -c 'from integrations.supabase_client import SupabaseClient; c = SupabaseClient(); print(c.get_trade_history(limit=5))'")
        return 0
    else:
        logger.warning(f"\n⚠️ Migration completed with {error_count} errors")
        logger.warning("Some trades may not have been migrated. Please review the errors above.")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
