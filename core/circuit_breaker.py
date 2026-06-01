import os
import json
import logging
import time

_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "cb_state.json")
_STATE_FILE = os.path.normpath(_STATE_FILE)

class CircuitBreaker:
    def __init__(self, **_kwargs):
        self.logger = logging.getLogger("CircuitBreaker")

    def _read_state(self) -> dict:
        try:
            with open(_STATE_FILE) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"paused": False}

    def _write_state(self, state: dict):
        try:
            with open(_STATE_FILE, "w") as f:
                json.dump(state, f)
        except Exception as e:
            self.logger.error(f"CircuitBreaker: failed to write state file: {e}")

    def can_trade(self) -> bool:
        state = self._read_state()
        if state.get("paused"):
            reason = state.get("reason", "unknown")
            self.logger.warning(f"Circuit breaker OPEN — trading paused: {reason}")
            return False
        return True

    def pause_system(self, reason: str = "manual"):
        self.logger.critical(f"CircuitBreaker: pausing system — {reason}")
        self._write_state({"paused": True, "reason": reason, "paused_at": time.time()})

    def resume_system(self):
        self.logger.info("CircuitBreaker: resuming system")
        self._write_state({"paused": False})
