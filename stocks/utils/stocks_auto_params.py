"""
stocks_auto_params.py — AutoParams subclass for the stocks department.

Uses config/stocks_auto_params.json instead of config/auto_params.json.
All logic is inherited from AutoParams; only the file path and defaults differ.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("StocksAutoParams")

STOCKS_PARAMS_FILE = "config/stocks_auto_params.json"

DEFAULTS: Dict[str, Any] = {
    "score_threshold_propose": 0.65,
    "score_threshold_monitor": 0.50,
    "fast_score_threshold": 0.45,
    "w_growth": 0.30,
    "w_multiple": 0.30,
    "w_management": 0.20,
    "w_moat": 0.10,
    "w_sentiment": 0.10,
    "max_position_pct": 0.05,
    "stop_loss_pct": 0.10,
    "trailing_stop_activation_pct": 0.15,
    "trailing_stop_distance_pct": 0.25,
    "max_portfolio_positions": 10,
    "sector_concentration_limit": 0.20,
    "earnings_blackout_days": 5,
    "fmp_daily_calls_budget": 200,
    "portfolio_cash_usd": 20000,
}

BOUNDS: Dict[str, tuple] = {
    "score_threshold_propose":      (0.50, 0.80),
    "score_threshold_monitor":      (0.35, 0.65),
    "fast_score_threshold":         (0.30, 0.60),
    "w_growth":                     (0.10, 0.60),
    "w_multiple":                   (0.10, 0.60),
    "w_management":                 (0.05, 0.40),
    "w_moat":                       (0.02, 0.30),
    "w_sentiment":                  (0.02, 0.30),
    "max_position_pct":             (0.02, 0.10),
    "stop_loss_pct":                (0.05, 0.20),
    "trailing_stop_activation_pct": (0.08, 0.30),
    "trailing_stop_distance_pct":   (0.10, 0.40),
    "max_portfolio_positions":      (3,    20),
    "sector_concentration_limit":   (0.10, 0.40),
    "earnings_blackout_days":       (2,    14),
    "fmp_daily_calls_budget":       (50,   250),
    "portfolio_cash_usd":           (1000, 1_000_000),
}

MAX_DRIFT_FRACTION = 0.30


class StocksAutoParams:
    """Thread-safe reader/writer for config/stocks_auto_params.json."""

    def __init__(self):
        self._ensure_file()

    def get(self, key: str, fallback: Any = None) -> Any:
        data = self._load()
        default = DEFAULTS.get(key, fallback)
        return data.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        data = self._load()
        return {k: v for k, v in data.items() if not k.startswith("_")}

    def update(self, key: str, new_value: Any, changed_by: str, reason: str) -> Optional[Any]:
        if key not in DEFAULTS:
            logger.warning(f"StocksAutoParams.update: unknown key '{key}' — rejected")
            return None

        if key in BOUNDS:
            lo, hi = BOUNDS[key]
            if not (lo <= new_value <= hi):
                logger.warning(f"StocksAutoParams: {key}={new_value} out of bounds [{lo},{hi}] — rejected")
                return None

        data = self._load()
        old_value = data.get(key, DEFAULTS[key])
        if old_value == new_value:
            return old_value

        # Drift guard
        initial = data.get("_initial", {}).get(key, DEFAULTS.get(key))
        if initial not in (None, 0):
            drift = abs(new_value - initial) / abs(initial)
            if drift > MAX_DRIFT_FRACTION:
                logger.warning(
                    f"StocksAutoParams: {key} drift {drift:.0%} exceeds {MAX_DRIFT_FRACTION:.0%} "
                    f"— human review required"
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
        logger.info(f"StocksAutoParams: {key} {old_value} → {new_value} by {changed_by} ({reason})")
        return old_value

    def _ensure_file(self):
        os.makedirs("config", exist_ok=True)
        if not os.path.exists(STOCKS_PARAMS_FILE):
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
            with open(STOCKS_PARAMS_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"StocksAutoParams: failed to load {STOCKS_PARAMS_FILE}: {e}")
            return dict(DEFAULTS)

    def _write(self, data: dict):
        try:
            with open(STOCKS_PARAMS_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"StocksAutoParams: failed to write {STOCKS_PARAMS_FILE}: {e}")
