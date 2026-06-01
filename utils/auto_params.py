"""
auto_params.py — Centralized auto-tunable parameter store.

All tunable numeric parameters live in config/auto_params.json.
Agents call get() to read live values; the Auditor calls update()
to record a tuned value with audit metadata.

Usage:
    from utils.auto_params import AutoParams
    params = AutoParams()
    threshold = params.get("tech_prefilter_min", 0.15)
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("AutoParams")

AUTO_PARAMS_FILE = "config/auto_params.json"

DEFAULTS: Dict[str, Any] = {
    "score_threshold": 0.08,
    "tech_prefilter_min": 0.02,
    "scan_universe_size": 16,
    "consecutive_loss_offboard": 3,
    "drawdown_offboard_pct": 5.0,
}

BOUNDS: Dict[str, tuple] = {
    "score_threshold":          (0.05, 0.20),   # must stay within actual score range
    "tech_prefilter_min":       (0.02, 0.15),   # low floor to ensure fund+sent always run
    "scan_universe_size":       (6,    20),
    "consecutive_loss_offboard":(2,    5),
    "drawdown_offboard_pct":    (2.0,  10.0),
}

# Drift guard: warn if param moves more than this fraction from its initial value
MAX_DRIFT_FRACTION = 0.30


class AutoParams:
    """Thread-safe reader/writer for config/auto_params.json."""

    def __init__(self):
        self._ensure_file()

    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────

    def get(self, key: str, fallback: Any = None) -> Any:
        """Read a single param value. Falls back to DEFAULTS then fallback arg."""
        data = self._load()
        default = DEFAULTS.get(key, fallback)
        return data.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        """Return all non-meta/shadow params as a flat dict."""
        data = self._load()
        return {k: v for k, v in data.items() if not k.startswith("_") and k != "shadow_mode"}

    # ─────────────────────────────────────────────────────────────────
    # Shadow test helpers
    # ─────────────────────────────────────────────────────────────────

    def start_shadow_test(self, key: str, new_value: Any, old_value: Any,
                          reason: str, duration_hours: float = 4.0):
        """Start a time-bounded shadow test for a proposed param change."""
        from datetime import timedelta
        data = self._load()
        now  = datetime.now(timezone.utc)
        end  = (now + timedelta(hours=duration_hours)).isoformat()
        data["shadow_mode"] = True
        data["_shadow"] = {
            "candidate_param":  key,
            "candidate_value":  new_value,
            "old_value":        old_value,
            "end_at":           end,
            "started_at":       now.isoformat(),
            "triggered_by":     reason,
        }
        data["_meta"] = {
            "last_changed_by": "PerformanceAuditor",
            "last_changed_at": now.isoformat(),
            "change_reason":   f"Shadow test started: {key} {old_value} -> {new_value}",
            "param":           "shadow_mode",
            "old_value":       False,
            "new_value":       True,
        }
        self._write(data)
        logger.info(
            f"AutoParams: shadow test started — {key} {old_value} -> {new_value} "
            f"for {duration_hours}h (ends {end})"
        )

    def get_shadow_state(self) -> dict:
        """Return the active _shadow dict, or {} if none."""
        return self._load().get("_shadow", {})

    def is_shadow_mode(self) -> bool:
        """Return True if shadow mode is currently active."""
        return bool(self._load().get("shadow_mode", False))

    def is_shadow_expired(self) -> bool:
        """Return True if the shadow test duration has elapsed."""
        shadow = self.get_shadow_state()
        end_at = shadow.get("end_at")
        if not end_at:
            return False
        try:
            return datetime.now(timezone.utc) >= datetime.fromisoformat(end_at)
        except Exception:
            return False

    def get_candidate_value(self, key: str) -> Any:
        """
        If a shadow test is active for `key`, return the candidate value.
        Otherwise return the live value (or default).
        """
        data = self._load()
        if data.get("shadow_mode"):
            shadow = data.get("_shadow", {})
            if shadow.get("candidate_param") == key:
                return shadow.get("candidate_value", data.get(key, DEFAULTS.get(key)))
        return data.get(key, DEFAULTS.get(key))

    def end_shadow_test(self):
        """Clear shadow mode and state."""
        data = self._load()
        data["shadow_mode"] = False
        data["_shadow"] = {}
        data["_meta"] = {
            "last_changed_by": "ShadowTest",
            "last_changed_at": datetime.now(timezone.utc).isoformat(),
            "change_reason":   "Shadow test ended",
        }
        self._write(data)
        logger.info("AutoParams: shadow mode cleared")

    def update(self, key: str, new_value: Any, changed_by: str, reason: str) -> Optional[Any]:
        """
        Write a new value for key with audit metadata.
        Enforces bounds and drift guard.
        Returns old value on success, None if update was rejected.
        """
        if key not in DEFAULTS:
            logger.warning(f"AutoParams.update: unknown key '{key}' — rejected")
            return None

        # Bounds check
        if key in BOUNDS:
            lo, hi = BOUNDS[key]
            if not (lo <= new_value <= hi):
                logger.warning(
                    f"AutoParams: {key}={new_value} out of bounds [{lo}, {hi}] — rejected"
                )
                return None

        data = self._load()
        old_value = data.get(key, DEFAULTS[key])

        if old_value == new_value:
            return old_value  # Nothing to do

        # Drift guard
        initial = data.get("_initial", {}).get(key, DEFAULTS.get(key))
        if initial not in (None, 0):
            drift = abs(new_value - initial) / abs(initial)
            if drift > MAX_DRIFT_FRACTION:
                logger.warning(
                    f"AutoParams: {key} drift {drift:.0%} exceeds {MAX_DRIFT_FRACTION:.0%} "
                    f"from initial {initial} — skipping autonomous update, human review required"
                )
                return None

        data[key] = new_value
        data["_meta"] = {
            "last_changed_by": changed_by,
            "last_changed_at": datetime.now(timezone.utc).isoformat(),
            "change_reason": reason,
            "param": key,
            "old_value": old_value,
            "new_value": new_value,
        }
        self._write(data)
        logger.info(
            f"AutoParams: {key} {old_value} -> {new_value} "
            f"by {changed_by} ({reason})"
        )
        return old_value

    # ─────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────

    def _ensure_file(self):
        os.makedirs("config", exist_ok=True)
        if not os.path.exists(AUTO_PARAMS_FILE):
            self._write({
                **DEFAULTS,
                "_meta": {
                    "last_changed_by": "init",
                    "last_changed_at": datetime.now(timezone.utc).isoformat(),
                    "change_reason": "Initial config",
                },
                "_bounds": {k: list(v) for k, v in BOUNDS.items()},
                "_initial": dict(DEFAULTS),
            })

    def _load(self) -> dict:
        try:
            with open(AUTO_PARAMS_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"AutoParams: failed to load {AUTO_PARAMS_FILE}: {e}")
            return dict(DEFAULTS)

    def _write(self, data: dict):
        try:
            with open(AUTO_PARAMS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"AutoParams: failed to write {AUTO_PARAMS_FILE}: {e}")
