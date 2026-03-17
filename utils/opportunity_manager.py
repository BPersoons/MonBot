import json
import os
import logging
from datetime import datetime
from utils.pipeline_events import log_event as log_pipeline_event

class OpportunityManager:
    """
    Manages the persistent state of opportunities identified by the Scout (Macro Thesis)
    that are waiting for the right entry point from the Technical Analyst (Micro Thesis).
    """
    def __init__(self, storage_file: str = "monitoring_watchlist.json"):
        self.storage_file = storage_file
        self.logger = logging.getLogger("OpportunityManager")
        self.opportunities = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.storage_file):
            return {}
        try:
            with open(self.storage_file, "r") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            self.logger.error(f"Error loading {self.storage_file}: {e}")
            return {}

    def _save(self):
        try:
            with open(self.storage_file, "w") as f:
                json.dump(self.opportunities, f, indent=4)
        except Exception as e:
            self.logger.error(f"Error saving {self.storage_file}: {e}")

    def add_or_update(self, ticker: str, score: float, details: dict, next_step: str, reason: str,
                      target_entry_price: float = 0.0, direction: str = "LONG",
                      current_price: float = 0.0, monitoring_rationale: str = "",
                      rrr: str = "1:1.5", stop_loss_pct: float = 5.0, timeframe: str = "1h"):
        """Adds a setup to the watchlist or updates its current state."""
        setup_id = f"{ticker}_{timeframe}"
        
        # Initialize if new
        if setup_id not in self.opportunities:
            self.opportunities[setup_id] = {
                "setup_id": setup_id,
                "ticker": ticker,
                "timeframe": timeframe,
                "first_spotted": datetime.now().isoformat(),
                "duration_hours": 0.0,
                "original_reason": reason,
                "status": "MONITORING",
                "price_history": [],
                "target_entry_price": target_entry_price, # Set it initially
            }
        
        # Track rolling price history for momentum (last 5 checks)
        price_history = self.opportunities[setup_id].get("price_history", [])
        if current_price > 0:
            price_history.append(round(current_price, 6))
            if len(price_history) > 5:
                price_history = price_history[-5:]
                
        # --- TARGET FREEZE LOGIC ---
        # If we already have a locked-in target (>0), DO NOT overwrite it.
        # This prevents Zeno's Paradox where the target keeps dropping endlessly.
        existing_target = self.opportunities[setup_id].get("target_entry_price", 0.0)
        final_target = existing_target if existing_target > 0 else target_entry_price
        
        # Update dynamic fields
        self.opportunities[setup_id].update({
            "last_updated": datetime.now().isoformat(),
            "ticker": ticker,
            "timeframe": timeframe,
            "current_score": score,
            "next_step": next_step,
            "latest_reason": reason,
            "details": details,
            "target_entry_price": final_target,
            "direction": direction,
            "current_price": current_price,
            "monitoring_rationale": monitoring_rationale,
            "rrr": rrr,
            "stop_loss_pct": stop_loss_pct,
            "price_history": price_history
        })
        
        self.logger.info(f"Opportunity {setup_id} added/updated in Watchlist (Score: {score:.2f})")
        self._save()

    def remove(self, setup_id: str, reason: str = "Unknown"):
        """Removes an asset from monitoring (e.g., if trade executed or thesis invalidated)."""
        if setup_id in self.opportunities:
            del self.opportunities[setup_id]
            self.logger.info(f"Removed {setup_id} from Monitoring Watchlist. Reason: {reason}")
            self._save()

    def review_opportunities(self) -> list:
        """
        Calculates time open and ranks the active monitored opportunities by current score.
        Drops opportunities that are too weak or older than a specific threshold (e.g., 48 hours).
        """
        now = datetime.now()
        to_remove = []
        
        for ticker, data in self.opportunities.items():
            # Calculate duration
            try:
                first_spotted = datetime.fromisoformat(data["first_spotted"])
                duration_hours = (now - first_spotted).total_seconds() / 3600
                data["duration_hours"] = round(duration_hours, 1)
            except Exception:
                data["duration_hours"] = 0.0
                
            # Discard criteria
            if data["duration_hours"] > 48.0:
                self.logger.info(f"Discarding {ticker} from Monitoring: Time limit exceeded (48h).")
                to_remove.append((ticker, "Time Limit Exceeded (48h)"))
                try:
                    log_pipeline_event("MONITOR_EXPIRED", data.get("ticker", ticker), {
                        "reason": "Time Limit Exceeded (48h)",
                        "duration_hours": data["duration_hours"],
                        "last_score": data.get("current_score", 0),
                    })
                except Exception:
                    pass
            elif data.get("current_score", 0) < 0.0:
                # If score drops below 0 entirely, the macro thesis is likely invalidated
                self.logger.info(f"Discarding {ticker} from Monitoring: Thesis invalidated (Score < 0).")
                to_remove.append((ticker, "Macro Thesis Invalidated (Score < 0)"))
                try:
                    log_pipeline_event("MONITOR_EXPIRED", data.get("ticker", ticker), {
                        "reason": "Macro Thesis Invalidated (Score < 0)",
                        "duration_hours": data.get("duration_hours", 0),
                        "last_score": data.get("current_score", 0),
                    })
                except Exception:
                    pass

        # Execute removals
        for setup_id, reason in to_remove:
            self.remove(setup_id, reason)
            
        # Return ranked list
        active_list = list(self.opportunities.values())
        active_list.sort(key=lambda x: x.get("current_score", 0), reverse=True)
        return active_list

    def get_monitoring_setups(self) -> list:
        """Returns a list of dicts representing the setups currently being monitored."""
        return [
            {
                "setup_id": k, 
                "ticker": v["ticker"], 
                "timeframe": v.get("timeframe", "1h")
            } 
            for k, v in self.opportunities.items()
        ]
