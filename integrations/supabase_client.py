"""
Supabase Client - PostgreSQL Integration
Replaces trade_log.json with persistent database storage.
"""

import logging
import os
from typing import Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    logging.warning("Supabase library not installed. Trade logging will fall back to local storage.")

load_dotenv()

logger = logging.getLogger("SupabaseClient")


class SupabaseClient:
    """
    Client for interacting with Supabase PostgreSQL database.
    Handles trade logging, performance tracking, and market data storage.
    """
    
    def __init__(self):
        """Initialize Supabase client."""
        if not SUPABASE_AVAILABLE:
            logger.error("Supabase library not available. Cannot initialize client.")
            self.client = None
            return
        
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        
        if not url or not key:
            logger.error("SUPABASE_URL or SUPABASE_KEY not set. Client will not function.")
            self.client = None
            return
        
        try:
            self.client: Client = create_client(url, key)
            logger.info("Supabase client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            self.client = None
    
    def is_available(self) -> bool:
        """Check if Supabase client is ready."""
        return self.client is not None
    
    # ===== Trade Logging =====
    
    def log_trade(self, trade_data: Dict) -> bool:
        """
        Log a trade to the database.
        
        Args:
            trade_data: Trade information including:
                - ticker: str
                - action: str (BUY/SELL/HOLD)
                - conviction: float
                - price: float
                - quantity: float
                - risk_metrics: dict
                - analyst_signals: dict
                
        Returns:
            True if successful
        """
        if not self.is_available():
            logger.error("Supabase client not available. Cannot log trade.")
            return False
        
        try:
            # Prepare record
            record = {
                "ticker": trade_data.get("ticker"),
                "action": trade_data.get("action"),
                "conviction": trade_data.get("conviction", 0.0),
                "entry_price": trade_data.get("price", 0.0),
                "quantity": trade_data.get("quantity", 0.0),
                "risk_metrics": trade_data.get("risk_metrics", {}),
                "analyst_signals": trade_data.get("analyst_signals", {}),
                "status": "OPEN",
                "created_at": datetime.now().isoformat()
            }
            
            # Insert into trades table
            result = self.client.table("trades").insert(record).execute()
            
            logger.info(f"Trade logged for {trade_data.get('ticker')}: {trade_data.get('action')}")
            return True
            
        except Exception as e:
            logger.error(f"Error logging trade: {e}")
            return False
    
    def update_trade_exit(self, trade_id: int, exit_price: float, pnl: float) -> bool:
        """
        Update a trade with exit information.
        
        Args:
            trade_id: Database ID of the trade
            exit_price: Exit price
            pnl: Profit/Loss amount
            
        Returns:
            True if successful
        """
        if not self.is_available():
            return False
        
        try:
            update_data = {
                "exit_price": exit_price,
                "pnl": pnl,
                "status": "CLOSED",
                "closed_at": datetime.now().isoformat()
            }
            
            self.client.table("trades").update(update_data).eq("id", trade_id).execute()
            logger.info(f"Updated trade {trade_id} with exit data")
            return True
            
        except Exception as e:
            logger.error(f"Error updating trade exit: {e}")
            return False
    
    def get_open_trades(self, ticker: Optional[str] = None) -> List[Dict]:
        """
        Get all open trades.
        
        Args:
            ticker: Optional filter by ticker
            
        Returns:
            List of open trade records
        """
        if not self.is_available():
            return []
        
        try:
            query = self.client.table("trades").select("*").eq("status", "OPEN")
            
            if ticker:
                query = query.eq("ticker", ticker)
            
            result = query.execute()
            return result.data if result.data else []
            
        except Exception as e:
            logger.error(f"Error fetching open trades: {e}")
            return []
    
    def get_trade_history(self, ticker: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """
        Get trade history.
        
        Args:
            ticker: Optional filter by ticker
            limit: Maximum number of records
            
        Returns:
            List of trade records
        """
        if not self.is_available():
            return []
        
        try:
            query = self.client.table("trades").select("*").order("created_at", desc=True).limit(limit)
            
            if ticker:
                query = query.eq("ticker", ticker)
            
            result = query.execute()
            return result.data if result.data else []
            
        except Exception as e:
            logger.error(f"Error fetching trade history: {e}")
            return []
    
    # ===== Performance Tracking =====
    
    def log_agent_performance(self, analyst: str, ticker: str, prediction: float, 
                             actual_outcome: float, metrics: Dict) -> bool:
        """
        Log analyst performance for a prediction.
        
        Args:
            analyst: Analyst name
            ticker: Asset ticker
            prediction: Predicted signal (-1 to +1)
            actual_outcome: Actual market outcome (-1 to +1)
            metrics: Additional performance metrics
            
        Returns:
            True if successful
        """
        if not self.is_available():
            return False
        
        try:
            record = {
                "analyst": analyst,
                "ticker": ticker,
                "prediction": prediction,
                "actual_outcome": actual_outcome,
                "accuracy": 1.0 - abs(prediction - actual_outcome),
                "metrics": metrics,
                "timestamp": datetime.now().isoformat()
            }
            
            self.client.table("agent_performance").insert(record).execute()
            logger.info(f"Logged performance for {analyst} on {ticker}")
            return True
            
        except Exception as e:
            logger.error(f"Error logging agent performance: {e}")
            return False
    
    def get_agent_performance_stats(self, analyst: str, days: int = 30) -> Dict:
        """
        Get performance statistics for an analyst.
        
        Args:
            analyst: Analyst name
            days: Number of days to look back
            
        Returns:
            Performance statistics
        """
        if not self.is_available():
            return {}
        
        try:
            # Calculate date threshold
            from datetime import timedelta
            threshold = (datetime.now() - timedelta(days=days)).isoformat()
            
            # Query performance records
            result = self.client.table("agent_performance")\
                .select("*")\
                .eq("analyst", analyst)\
                .gte("timestamp", threshold)\
                .execute()
            
            if not result.data:
                return {"analyst": analyst, "record_count": 0}
            
            records = result.data
            accuracies = [r["accuracy"] for r in records]
            
            stats = {
                "analyst": analyst,
                "record_count": len(records),
                "avg_accuracy": sum(accuracies) / len(accuracies),
                "min_accuracy": min(accuracies),
                "max_accuracy": max(accuracies),
                "period_days": days
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error fetching agent performance: {e}")
            return {}
    
    # ===== Market Snapshots =====
    
    def save_market_snapshot(self, ticker: str, snapshot_data: Dict) -> bool:
        """
        Save a market data snapshot.
        
        Args:
            ticker: Asset ticker
            snapshot_data: Market data (price, volume, indicators, etc.)
            
        Returns:
            True if successful
        """
        if not self.is_available():
            return False
        
        try:
            record = {
                "ticker": ticker,
                "snapshot_data": snapshot_data,
                "timestamp": datetime.now().isoformat()
            }
            
            self.client.table("market_snapshots").insert(record).execute()
            return True
            
        except Exception as e:
            logger.error(f"Error saving market snapshot: {e}")
            return False
    
    # ===== Schema Management =====
    
    def check_schema(self) -> bool:
        """
        Check if required tables exist.
        
        Returns:
            True if schema is ready
        """
        if not self.is_available():
            return False
        
        required_tables = ["trades", "agent_performance", "market_snapshots"]
        
        try:
            for table in required_tables:
                # Attempt a simple query to check table existence
                self.client.table(table).select("*").limit(1).execute()
            
            logger.info("Database schema validated")
            return True
            
        except Exception as e:
            logger.error(f"Schema validation failed: {e}")
            logger.error("Please run the migration script to create required tables")
            return False
