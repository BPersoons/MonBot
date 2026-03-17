"""
Swarm Health Manager - Real-time agent health monitoring
Reports agent status to Supabase swarm_health table for dashboard visibility.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional
from utils.db_client import DatabaseClient

logger = logging.getLogger("SwarmHealth")


class SwarmHealthManager:
    """
    Manages real-time health reporting for all agents in the trading swarm.
    Data is persisted to Supabase swarm_health table.
    """
    
    def __init__(self, db_client: Optional[DatabaseClient] = None):
        self.db = db_client or DatabaseClient()
        self._table = "swarm_health"
        
    def report_health(
        self, 
        agent_name: str, 
        status: str,
        cycle_count: int = 0,
        last_error: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        Report/update agent health status (upsert).
        
        Args:
            agent_name: Name of the agent (e.g., "ProjectLead", "Heartbeat")
            status: One of ACTIVE, IDLE, ERROR, STARTING
            cycle_count: Number of completed cycles
            last_error: Most recent error message if any
            metadata: Additional context (JSON)
            
        Returns:
            True if successful
        """
        if not self.db.is_available():
            logger.warning(f"Database unavailable - health not reported for {agent_name}")
            return False
            
        try:
            # Delegate directly to the DatabaseClient to leverage the _agent_metadata_cache
            # This prevents upserting a raw blob that wipes previously injected metadata keys 
            # like ProjectLead's `latest_decisions` array.
            
            # The method signature for update_swarm_health is:
            # def update_swarm_health(self, agent_name: str, status: str, 
            #                        task: str = None, reasoning: str = None, 
            #                        meta: Dict = None, cycle_count: int = 0,
            #                        last_error: str = None) -> bool:
            
            # We must map the current arguments down:
            
            # Extract task and reasoning if present in metadata (which was the old format)
            task = metadata.pop("current_task", None) if metadata else None
            reasoning = metadata.pop("current_reasoning_snippet", None) if metadata else None
            
            result = self.db.update_swarm_health(
                agent_name=agent_name,
                status=status,
                task=task,
                reasoning=reasoning,
                meta=metadata or {},
                cycle_count=cycle_count,
                last_error=last_error
            )
            
            logger.debug(f"Health reported via DB Cache: {agent_name} = {status}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to report health for {agent_name}: {e}")
            return False
    
    def get_dashboard(self) -> List[Dict]:
        """
        Get all agent statuses for dashboard display.
        
        Returns:
            List of agent health records
        """
        if not self.db.is_available():
            return []
            
        try:
            # Ensure we select metadata explicitly if * doesn't cover it cleanly in all adapters, 
            # but * is usually fine. Just ensuring it returns list of dicts.
            result = self.db.client.table(self._table).select("*").order('last_pulse', desc=True).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Failed to fetch dashboard: {e}")
            return []
    
    def get_agent_status(self, agent_name: str) -> Optional[Dict]:
        """Get status for a specific agent."""
        if not self.db.is_available():
            return None
            
        try:
            result = self.db.client.table(self._table).select("*").eq(
                "agent_name", agent_name
            ).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Failed to fetch status for {agent_name}: {e}")
            return None
    
    def mark_error(self, agent_name: str, error_message: str) -> bool:
        """Quick method to mark an agent as ERROR with message."""
        return self.report_health(
            agent_name=agent_name,
            status="ERROR",
            last_error=error_message
        )
    
    def clear_error(self, agent_name: str) -> bool:
        """Clear error status for an agent."""
        return self.report_health(
            agent_name=agent_name,
            status="ACTIVE",
            last_error=None
        )
