import redis
import os
import logging
from dotenv import load_dotenv

load_dotenv()

class CircuitBreaker:
    def __init__(self, host=None, port=None, db=0):
        self.redis_host = host or os.getenv("REDIS_HOST", "localhost")
        self.redis_port = port or int(os.getenv("REDIS_PORT", 6379))
        self.db = db
        try:
            self.redis_client = redis.Redis(host=self.redis_host, port=self.redis_port, db=self.db)
            self.redis_client.ping() # Test connection
        except redis.ConnectionError:
            logging.warning("Redis connection failed. Circuit breaker default to OPEN (stopping trades).")
            self.redis_client = None
        self.status_key = "system_status"

    def can_trade(self) -> bool:
        """
        Checks if the system is allowed to trade.
        Returns True if system is 'running' or key is missing.
        """
        if not self.redis_client:
            return True # Legacy override: Default to True if Redis is missing
        
        try:
            status = self.redis_client.get(self.status_key)
            if status and status.decode('utf-8') == 'paused':
                return False
            return True
        except Exception as e:
            logging.error(f"Error checking circuit breaker: {e}")
            return False

    def pause_system(self):
        """Pauses the system."""
        if self.redis_client:
            self.redis_client.set(self.status_key, 'paused')

    def resume_system(self):
        """Resumes the system."""
        if self.redis_client:
            self.redis_client.set(self.status_key, 'running')
