"""
Dashboard Query Layer - Supabase Integration with Fallback
Provides data fetching for dashboard with automatic fallback to StateManager.
"""

import logging
from typing import Dict, List, Optional
from utils.db_client import DatabaseClient

logger = logging.getLogger("DashboardQueryLayer")


class DashboardDataProvider:
    """
    Centralized data provider for dashboard.
    Fetches from Supabase with automatic fallback to Redis StateManager.
    """
    
    def __init__(self, db_client: Optional[DatabaseClient] = None):
        """
        Initialize dashboard data provider.
        
        Args:
            db_client: Optional DatabaseClient instance
        """
        self.db = db_client or DatabaseClient()
        self.using_fallback = False
    
    def get_latest_trades(self, limit: int = 10) -> List[Dict]:
        """
        Get most recent trades.
        
        Args:
            limit: Maximum number of trades
            
        Returns:
            List of trade records
        """
        trades = self.db.get_latest_trades(limit=limit)
        
        if not trades:
            logger.warning("Database unavailable - no trade history available")
            self.using_fallback = True
            return []
        
        return trades
    
    def get_agent_scores(self, days: int = 30) -> Dict[str, Dict]:
        """
        Get performance scores for all analysts.
        
        Args:
            days: Number of days to look back
            
        Returns:
            Dict of {analyst_name: score_data}
        """
        analysts = ["technical", "fundamental", "sentiment"]
        scores = {}
        
        for analyst in analysts:
            score = self.db.get_agent_score(analyst, days=days)
            scores[analyst] = score
        
        # If database unavailable, return default weights
        if not any(s.get("total_predictions", 0) > 0 for s in scores.values()):
            logger.warning("No performance data available yet")
        
        return scores
    
    def get_open_positions(self) -> List[Dict]:
        """
        Get all open trading positions.
        
        Returns:
            List of open trades
        """
        positions = self.db.get_open_trades()
        
        return positions
    
    def get_system_status(self) -> Dict:
        """
        Get system status and health.
        
        Returns:
            System status dict
        """
        # Check database health
        cache_status = self.db.get_cache_status()
        
        # Get StateManager status if available
        state_status = "UNKNOWN"
        return {
            "database_available": cache_status.get("database_available", False),
            "circuit_breaker": cache_status.get("circuit_breaker", {}),
            "cache_mode": cache_status.get("cache_mode", False),
            "pending_writes": (
                cache_status.get("pending_trades", 0) + 
                cache_status.get("pending_performance_logs", 0)
            ),
            "system_status": state_status,
            "using_fallback": self.using_fallback
        }
    
    def is_healthy(self) -> bool:
        """Check if data provider is healthy."""
        return self.db.is_available()

    # ===== Swarm Health =====

    def get_swarm_health(self) -> List[Dict]:
        """
        Get current status of all agents.
        """
        agents = self.db.get_swarm_health()
            
        return agents

    def update_agent_status(self, agent_name: str, status: str, 
                           task: str = None, reasoning: str = None, 
                           meta: Dict = None, cycle_count: int = 0,
                           last_error: str = None) -> bool:
        """
        Update an agent's status.
        """
        return self.db.update_swarm_health(agent_name, status, task, reasoning, meta, cycle_count, last_error)
