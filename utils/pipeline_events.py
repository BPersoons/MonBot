"""
Pipeline Activity Feed — Structured Event Logger

Append-only JSON log that records every meaningful state transition
in the decision pipeline. Enables answering "why did ticker X change state?"

Events: DECISION, NARRATOR_CHECK, RISK_CHECK, EXECUTION, TRADE_EXIT,
        MONITOR_UPDATE, MONITOR_EXPIRED
"""

import json
import os
import logging
from datetime import datetime

logger = logging.getLogger("PipelineEvents")

EVENTS_FILE = "pipeline_events.json"
MAX_EVENTS = 500


def _load_events() -> list:
    if not os.path.exists(EVENTS_FILE):
        return []
    try:
        with open(EVENTS_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, Exception):
        return []


def _save_events(events: list):
    try:
        with open(EVENTS_FILE, "w") as f:
            json.dump(events, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save pipeline events: {e}")


def log_event(event_type: str, ticker: str, data: dict = None):
    """
    Append a structured event to the pipeline activity feed.

    Args:
        event_type: One of DECISION, NARRATOR_CHECK, RISK_CHECK,
                    EXECUTION, TRADE_EXIT, MONITOR_UPDATE, MONITOR_EXPIRED
        ticker: The ticker symbol (e.g. "PUMP/USDC")
        data: Dict of event-specific payload
    """
    event = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "ticker": ticker,
        "data": data or {}
    }

    try:
        events = _load_events()
        events.append(event)

        # Auto-prune to last MAX_EVENTS
        if len(events) > MAX_EVENTS:
            events = events[-MAX_EVENTS:]

        _save_events(events)
    except Exception as e:
        logger.error(f"Failed to log pipeline event [{event_type}] for {ticker}: {e}")


def get_events(limit: int = 100, ticker_filter: str = None, event_type_filter: str = None) -> list:
    """
    Read events from the log, optionally filtered.

    Args:
        limit: Max events to return (most recent first)
        ticker_filter: Only return events for this ticker
        event_type_filter: Only return events of this type
    """
    events = _load_events()

    if ticker_filter:
        events = [e for e in events if e.get("ticker") == ticker_filter]
    if event_type_filter:
        events = [e for e in events if e.get("event_type") == event_type_filter]

    # Return most recent first
    return list(reversed(events[-limit:]))


def get_previous_state(ticker: str) -> str:
    """
    Look up the most recent DECISION event for a ticker to determine its previous state.
    Returns the to_state from the last DECISION, or 'UNKNOWN' if none found.
    """
    events = _load_events()
    for event in reversed(events):
        if event.get("event_type") == "DECISION" and event.get("ticker") == ticker:
            return event.get("data", {}).get("to_state", "UNKNOWN")
    return "NEW"
