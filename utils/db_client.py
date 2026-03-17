"""
Enhanced Database Client - Supabase with Fallback Cache
Provides robust persistence layer with circuit breaker and local fallback.
"""

import logging
import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    logging.warning("Supabase library not installed. Database features will be limited.")

load_dotenv()

logger = logging.getLogger("DatabaseClient")


class CircuitBreaker:
    """Circuit breaker pattern for database connection management."""
    
    def __init__(self, failure_threshold: int = 3, timeout_seconds: int = 300):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def record_success(self):
        """Record successful operation."""
        self.failure_count = 0
        self.state = "CLOSED"
        logger.info("Circuit breaker: Connection restored")
    
    def record_failure(self):
        """Record failed operation."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit breaker OPEN: {self.failure_count} consecutive failures")
    
    def can_attempt(self) -> bool:
        """Check if we should attempt database operation."""
        if self.state == "CLOSED":
            return True
        
        if self.state == "OPEN":
            # Check if timeout has passed
            if self.last_failure_time:
                elapsed = (datetime.now() - self.last_failure_time).total_seconds()
                if elapsed > self.timeout_seconds:
                    self.state = "HALF_OPEN"
                    logger.info("Circuit breaker: Attempting reconnection (HALF_OPEN)")
                    return True
            return False
        
        # HALF_OPEN: Allow one attempt
        return True
    
    def get_status(self) -> Dict:
        """Get circuit breaker status."""
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None
        }


class DatabaseClient:
    """
    Enhanced database client with fallback cache and circuit breaker.
    Combines Supabase for persistence with local JSON cache for resilience.
    """
    
    def __init__(self):
        """Initialize database client with fallback mechanisms."""
        self.cache_file = "data_cache.json"
        self.circuit_breaker = CircuitBreaker(failure_threshold=3, timeout_seconds=300)
        self.client: Optional[Client] = None
        self.cache_mode = False
        
        # Initialize Supabase connection
        if SUPABASE_AVAILABLE:
            self._init_supabase()
        else:
            logger.error("Supabase not available - operating in cache-only mode")
            self.cache_mode = True
            
        # Agent metadata cache to prevent overwriting JSON fields during upserts
        self._agent_metadata_cache: Dict[str, Dict] = {}
        
        # Ensure cache file exists
        self._init_cache()
    
    def _init_supabase(self):
        """Initialize Supabase client."""
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_KEY")
        
        if not url or not key:
            logger.error("SUPABASE_URL or SUPABASE_KEY not configured")
            self.cache_mode = True
            return
        
        try:
            self.client = create_client(url, key)
            logger.info("✅ Supabase client initialized")
            
            # Validate schema
            if self.ensure_schema():
                logger.info("✅ Database schema validated")
            else:
                logger.warning("⚠️ Schema validation failed - some features may not work")
                
        except Exception as e:
            logger.error(f"Failed to initialize Supabase: {e}")
            self.cache_mode = True
    
    def _init_cache(self):
        """Initialize local cache file."""
        if not os.path.exists(self.cache_file):
            cache_data = {
                "pending_trades": [],
                "pending_performance_logs": [],
                "last_sync": None,
                "failed_writes": 0
            }
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            logger.info(f"Initialized cache file: {self.cache_file}")
    
    def _load_cache(self) -> Dict:
        """Load cache data."""
        try:
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
            return {
                "pending_trades": [],
                "pending_performance_logs": [],
                "last_sync": None,
                "failed_writes": 0
            }
    
    def _save_cache(self, cache_data: Dict):
        """Save cache data."""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving cache: {e}")
    
    def is_available(self) -> bool:
        """Check if database is available."""
        if not self.client or not self.circuit_breaker.can_attempt():
            return False
        
        try:
            # Simple ping query
            self.client.table("trades").select("id").limit(1).execute()
            self.circuit_breaker.record_success()
            return True
        except Exception as e:
            logger.debug(f"Database availability check failed: {e}")
            self.circuit_breaker.record_failure()
            return False
    
    def ensure_schema(self) -> bool:
        """
        Validate required tables exist.
        Note: Schema creation should be done manually in Supabase dashboard.
        """
        if not self.client:
            return False
        
        required_tables = ["trades", "agent_performance", "market_snapshots", "system_state"]
        
        try:
            for table in required_tables:
                self.client.table(table).select("*").limit(1).execute()
            return True
        except Exception as e:
            logger.error(f"Schema validation failed: {e}")
            logger.error("Please run supabase_schema.sql in your Supabase SQL editor")
            return False
    
    # ===== Trade Logging =====
    
    def log_trade_with_reasoning(self, trade_data: Dict, reasoning_trace: Dict) -> bool:
        """
        Log a trade with full ADK reasoning trace.
        
        Args:
            trade_data: Trade information (ticker, action, price, etc.)
            reasoning_trace: Full ADK decision chain
            
        Returns:
            True if successful
        """
        # Prepare complete record
        record = {
            "ticker": trade_data.get("ticker"),
            "action": trade_data.get("action"),
            "conviction": trade_data.get("conviction", 0.0),
            "entry_price": trade_data.get("price", 0.0),
            "quantity": trade_data.get("quantity", 0.0),
            "risk_metrics": trade_data.get("risk_metrics", {}),
            "analyst_signals": trade_data.get("analyst_signals", {}),
            "reasoning_trace": reasoning_trace,  # <-- NEW
            "status": "OPEN",
            "created_at": datetime.now().isoformat()
        }
        
        # Try database first
        if self.is_available():
            try:
                result = self.client.table("trades").insert(record).execute()
                logger.info(f"✅ Trade logged to Supabase: {record['ticker']} {record['action']}")
                
                # Sync any pending cache
                self._try_sync_cache()
                return True
            except Exception as e:
                logger.error(f"Failed to log trade to Supabase: {e}")
                self.circuit_breaker.record_failure()
        
        # Fallback to cache
        logger.warning(f"⚠️ Database unavailable - logging to cache")
        cache = self._load_cache()
        cache["pending_trades"].append(record)
        cache["failed_writes"] += 1
        self._save_cache(cache)
        return True
    
    def get_latest_trades(self, limit: int = 10, ticker: Optional[str] = None) -> List[Dict]:
        """
        Get most recent trades.
        
        Args:
            limit: Maximum number of trades
            ticker: Optional filter by ticker
            
        Returns:
            List of trade records
        """
        if not self.is_available():
            logger.warning("Database unavailable - returning empty list")
            return []
        
        try:
            query = self.client.table("trades")\
                .select("*")\
                .order("created_at", desc=True)\
                .limit(limit)
            
            if ticker:
                query = query.eq("ticker", ticker)
            
            result = query.execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error fetching trades: {e}")
            return []
    
    def get_open_trades(self, ticker: Optional[str] = None) -> List[Dict]:
        """Get all open trades."""
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
    
    def get_closed_trades(self, audited: bool = False, limit: int = 100) -> List[Dict]:
        """
        Get closed trades for auditing.
        
        Args:
            audited: If True, get audited trades. If False, get unaudited.
            limit: Maximum records
        """
        if not self.is_available():
            return []
        
        try:
            query = self.client.table("trades")\
                .select("*")\
                .eq("status", "CLOSED")\
                .order("closed_at", desc=True)\
                .limit(limit)
            
            # Note: audited flag should be added to schema
            result = query.execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error fetching closed trades: {e}")
            return []
    
    def update_trade_exit(self, trade_id: int, exit_price: float, pnl: float) -> bool:
        """Update trade with exit data."""
        if not self.is_available():
            logger.warning("Cannot update trade - database unavailable")
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
            logger.error(f"Error updating trade: {e}")
            return False
    
    # ===== Performance Tracking =====
    
    def log_agent_performance(self, analyst: str, ticker: str, prediction: float,
                              actual_outcome: float, metrics: Dict) -> bool:
        """Log analyst performance."""
        record = {
            "analyst": analyst,
            "ticker": ticker,
            "prediction": prediction,
            "actual_outcome": actual_outcome,
            "accuracy": 1.0 - abs(prediction - actual_outcome),
            "metrics": metrics,
            "timestamp": datetime.now().isoformat()
        }
        
        if self.is_available():
            try:
                self.client.table("agent_performance").insert(record).execute()
                return True
            except Exception as e:
                logger.error(f"Error logging performance: {e}")
                self.circuit_breaker.record_failure()
        
        # Fallback to cache
        cache = self._load_cache()
        cache["pending_performance_logs"].append(record)
        self._save_cache(cache)
        return True
    
    def get_agent_score(self, analyst: str, days: int = 30) -> Dict:
        """
        Get agent performance score.
        
        Returns:
            Dict with avg_accuracy, total_predictions, etc.
        """
        if not self.is_available():
            return {"analyst": analyst, "avg_accuracy": 0.0, "total_predictions": 0}
        
        try:
            threshold = (datetime.now() - timedelta(days=days)).isoformat()
            
            result = self.client.table("agent_performance")\
                .select("*")\
                .eq("analyst", analyst)\
                .gte("timestamp", threshold)\
                .execute()
            
            if not result.data:
                return {"analyst": analyst, "avg_accuracy": 0.0, "total_predictions": 0}
            
            records = result.data
            accuracies = [r["accuracy"] for r in records]
            
            return {
                "analyst": analyst,
                "avg_accuracy": sum(accuracies) / len(accuracies),
                "total_predictions": len(records),
                "period_days": days
            }
        except Exception as e:
            logger.error(f"Error fetching agent score: {e}")
            return {"analyst": analyst, "avg_accuracy": 0.0, "total_predictions": 0}
    
    # ===== System State =====
    
    def get_system_state(self, key: str, default: Any = None) -> Any:
        """Get system state value."""
        if not self.is_available():
            return default
        
        try:
            result = self.client.table("system_state")\
                .select("value")\
                .eq("key", key)\
                .execute()
            
            if result.data and len(result.data) > 0:
                return result.data[0]["value"]
            return default
        except Exception as e:
            logger.debug(f"Error fetching system state: {e}")
            return default
    
    def set_system_state(self, key: str, value: Any) -> bool:
        """Set system state value (upsert)."""
        if not self.is_available():
            return False
        
        try:
            record = {
                "key": key,
                "value": value,
                "updated_at": datetime.now().isoformat()
            }
            
            self.client.table("system_state").upsert(record, on_conflict="key").execute()
            return True
        except Exception as e:
            logger.error(f"Error setting system state: {e}")
            return False
            
    def get_agent_cache(self, key: str, ttl_hours: float) -> Optional[Any]:
        """Get cached analyst data if it hasn't expired based on TTL."""
        if not self.is_available():
            return None
            
        try:
            result = self.client.table("system_state").select("*").eq("key", key).execute()
                
            if result.data and len(result.data) > 0:
                record = result.data[0]
                updated_at_str = record.get("updated_at")
                if updated_at_str:
                    updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=timezone.utc)
                    
                    now = datetime.now(timezone.utc)
                    age_hours = (now - updated_at).total_seconds() / 3600
                    
                    if age_hours <= ttl_hours:
                        return record.get("value")
            return None
        except Exception as e:
            logger.debug(f"Error fetching cache for {key}: {e}")
            return None

    def set_agent_cache(self, key: str, value: Any) -> bool:
        """Set cached analyst data using system_state table."""
        return self.set_system_state(key, value)
    
    # ===== Swarm Health =====

    def update_swarm_health(self, agent_name: str, status: str, 
                           task: str = None, reasoning: str = None, 
                           meta: Dict = None, cycle_count: int = 0,
                           last_error: str = None) -> bool:
        """
        Update agent status in swarm_health table.
        """
        if not self.is_available():
            return False

        try:
            # Build metadata: merge task/reasoning into JSON column 
            # Retrieve existing metadata cache for the agent so we don't wipe previous keys (e.g. latest_decisions)
            merged_meta = self._agent_metadata_cache.get(agent_name, {}).copy()
            if meta:
                merged_meta.update(meta)
                
            if task is not None:
                merged_meta["current_task"] = task
            if reasoning is not None:
                merged_meta["current_reasoning_snippet"] = reasoning
                
            # Update cache
            self._agent_metadata_cache[agent_name] = merged_meta

            record = {
                "agent_name": agent_name,
                "status": status,
                "last_pulse": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "cycle_count": cycle_count,
                "metadata": merged_meta,
                "last_error": last_error
            }
            
            self.client.table("swarm_health").upsert(record, on_conflict="agent_name").execute()

            return True
        except Exception as e:
            logger.error(f"Error updating swarm health for {agent_name}: {e}")
            # Do not use circuit breaker for health checks to avoid noise
            return False

    def get_swarm_health(self) -> List[Dict]:
        """
        Get all agents' health status.
        """
        if not self.is_available():
            return []

        try:
            result = self.client.table("swarm_health").select("*").execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error fetching swarm health: {e}")
            return []
            
    # ===== System Backlog =====
    
    def get_system_backlog(self, limit: int = 50) -> List[Dict]:
        """
        Get the latest CPO system improvement ideas and executive summaries.
        """
        if not self.is_available():
            return []
            
        try:
            result = self.client.table("system_backlog").select("*").order("priority", desc=True).order("created_at", desc=True).limit(limit).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error fetching system backlog: {e}")
            return []
    
    # ===== Cache Sync =====
    
    def _try_sync_cache(self) -> bool:
        """Attempt to sync cached data to database."""
        cache = self._load_cache()
        
        pending_trades = cache.get("pending_trades", [])
        pending_performance = cache.get("pending_performance_logs", [])
        
        if not pending_trades and not pending_performance:
            return True  # Nothing to sync
        
        logger.info(f"Syncing cache: {len(pending_trades)} trades, {len(pending_performance)} performance logs")
        
        synced_trades = 0
        synced_performance = 0
        
        # Sync trades
        for trade in pending_trades[:]:
            try:
                self.client.table("trades").insert(trade).execute()
                pending_trades.remove(trade)
                synced_trades += 1
            except Exception as e:
                logger.warning(f"Failed to sync trade: {e}")
                break  # Stop syncing on first failure
        
        # Sync performance logs
        for log in pending_performance[:]:
            try:
                self.client.table("agent_performance").insert(log).execute()
                pending_performance.remove(log)
                synced_performance += 1
            except Exception as e:
                logger.warning(f"Failed to sync performance log: {e}")
                break
        
        # Update cache
        cache["pending_trades"] = pending_trades
        cache["pending_performance_logs"] = pending_performance
        cache["last_sync"] = datetime.now().isoformat()
        cache["failed_writes"] = len(pending_trades) + len(pending_performance)
        self._save_cache(cache)
        
        logger.info(f"✅ Cache sync complete: {synced_trades} trades, {synced_performance} logs")
        return len(pending_trades) == 0 and len(pending_performance) == 0
    
    def get_cache_status(self) -> Dict:
        """Get cache and circuit breaker status."""
        cache = self._load_cache()
        
        return {
            "circuit_breaker": self.circuit_breaker.get_status(),
            "cache_mode": self.cache_mode,
            "pending_trades": len(cache.get("pending_trades", [])),
            "pending_performance_logs": len(cache.get("pending_performance_logs", [])),
            "last_sync": cache.get("last_sync"),
            "database_available": self.is_available()
        }
    
    # ===== Testing =====
    
    def test_connection(self) -> Dict:
        """Test database connection and return diagnostic info."""
        result = {
            "supabase_configured": bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY")),
            "client_initialized": self.client is not None,
            "connection_available": False,
            "schema_valid": False,
            "circuit_breaker": self.circuit_breaker.get_status(),
            "cache_status": self._load_cache()
        }
        
        if self.client:
            result["connection_available"] = self.is_available()
            if result["connection_available"]:
                result["schema_valid"] = self.ensure_schema()
        
        return result


# CLI for testing
if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    db = DatabaseClient()
    
    if "--test-connection" in sys.argv:
        print("\n=== Database Connection Test ===\n")
        status = db.test_connection()
        
        for key, value in status.items():
            if isinstance(value, dict):
                print(f"{key}:")
                for k, v in value.items():
                    print(f"  {k}: {v}")
            else:
                icon = "✅" if value else "❌"
                print(f"{icon} {key}: {value}")
        
        print(f"\n{'='*40}\n")
        
        if status["connection_available"] and status["schema_valid"]:
            print("✅ Database is ready!")
        else:
            print("⚠️ Database setup incomplete. Please check configuration.")
    
    elif "--validate-schema" in sys.argv:
        if db.ensure_schema():
            print("✅ Schema validation passed")
        else:
            print("❌ Schema validation failed")
    
    elif "--sync-cache" in sys.argv:
        if db._try_sync_cache():
            print("✅ Cache synced successfully")
        else:
            print("⚠️ Cache sync incomplete")
    
    else:
        print("Usage:")
        print("  python -m utils.db_client --test-connection")
        print("  python -m utils.db_client --validate-schema")
        print("  python -m utils.db_client --sync-cache")
