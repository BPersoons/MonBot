"""
auto_executor.py — Autonomous execution of AUTO_PARAM backlog items.

The CPO classifies improvement ideas and calls queue() for AUTO_PARAM items.
SwarmMonitor calls check_pending() every 5 minutes.

Flow:
  CPO generates AUTO_PARAM idea
    -> queue(): validates bounds, writes to auto_exec_pending.json, sends Telegram veto msg
    -> SwarmMonitor calls check_pending() every 5 min
       -> polls Telegram getUpdates for "VETO" replies
       -> if VETO received: discard all pending changes
       -> if 1h elapsed, no VETO: apply via auto_params.update()
"""

import json
import logging
import os
import threading
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("AutoExecutor")

PENDING_FILE       = "auto_exec_pending.json"
VETO_WINDOW_HOURS  = 1.0

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")


class AutoExecutor:
    """Manages autonomous execution of AUTO_PARAM changes with Telegram veto window."""

    def __init__(self):
        self._lock = threading.Lock()

    # ─────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────

    def queue(self, param_key: str, proposed_value, old_value, reason: str, source: str = "CPO") -> bool:
        """
        Queue an AUTO_PARAM change for autonomous execution after a 1-hour veto window.
        Returns True if queued successfully, False if rejected/duplicate.
        """
        try:
            from utils.auto_params import AutoParams
            ap = AutoParams()
            data = ap._load()
            bounds = data.get("_bounds", {}).get(param_key)
            if not bounds:
                logger.warning(f"AutoExecutor: {param_key} has no bounds — not queueable")
                return False
            lo, hi = bounds[0], bounds[1]
            try:
                proposed_value = float(proposed_value)
            except (TypeError, ValueError):
                logger.warning(f"AutoExecutor: proposed_value {proposed_value!r} is not numeric")
                return False
            if not (lo <= proposed_value <= hi):
                logger.warning(
                    f"AutoExecutor: {proposed_value} out of bounds [{lo}, {hi}] for {param_key}"
                )
                return False
            if ap.is_shadow_mode():
                logger.info("AutoExecutor: shadow test active — deferring queue until test completes")
                return False
        except Exception as e:
            logger.warning(f"AutoExecutor: validation failed: {e}")
            return False

        deadline = (datetime.now(timezone.utc) + timedelta(hours=VETO_WINDOW_HOURS)).isoformat()
        item = {
            "id": f"{param_key}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
            "param_key": param_key,
            "proposed_value": proposed_value,
            "old_value": old_value,
            "reason": reason,
            "source": source,
            "veto_deadline": deadline,
            "status": "PENDING_VETO",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            state = self._load_state()
            # Deduplicate: skip if same param already pending
            for existing in state["pending"]:
                if existing["param_key"] == param_key and existing["status"] == "PENDING_VETO":
                    logger.info(f"AutoExecutor: {param_key} already in veto queue — skipping duplicate")
                    return False
            state["pending"].append(item)
            self._save_state(state)

        logger.info(f"AutoExecutor: queued {param_key} {old_value} -> {proposed_value} (veto deadline: {deadline})")
        self._send_telegram(
            f"[CPO AutoExec] Proposing: `{param_key}` {old_value} -> {proposed_value}\n"
            f"Reason: {reason}\n"
            f"Source: {source}\n"
            f"Change applies in 1h unless you reply *VETO*"
        )
        return True

    def check_pending(self):
        """
        Called by SwarmMonitor every check cycle.
        Polls Telegram for VETO messages, then applies or discards expired items.
        """
        with self._lock:
            state = self._load_state()

        if not state.get("pending"):
            return

        # Poll Telegram outside the lock (network call)
        vetoed = self._poll_veto_messages(state)  # updates state["telegram_offset"] in-place

        now = datetime.now(timezone.utc)
        still_pending = []

        for item in state["pending"]:
            if item.get("status") != "PENDING_VETO":
                continue  # Already resolved — drop from list

            if vetoed:
                logger.info(f"AutoExecutor: {item['param_key']} VETOED by user")
                self._send_telegram(
                    f"[CPO AutoExec] Vetoed: `{item['param_key']}` change discarded."
                )
                self._append_audit_log(
                    f"[AutoExecutor] VETOED {item['param_key']}: {item['old_value']} -> {item['proposed_value']} | {item['reason']}"
                )
                continue  # Drop from pending

            try:
                deadline = datetime.fromisoformat(item["veto_deadline"])
            except Exception:
                still_pending.append(item)
                continue

            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)

            if now >= deadline:
                self._apply(item)  # Sends Telegram internally
                continue  # Drop from pending

            still_pending.append(item)

        state["pending"] = still_pending
        with self._lock:
            self._save_state(state)

    def get_pending_count(self) -> int:
        """Return number of items currently in the veto queue."""
        state = self._load_state()
        return sum(1 for i in state.get("pending", []) if i.get("status") == "PENDING_VETO")

    # ─────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────

    def _apply(self, item: dict):
        """Apply a param change after the veto window expires without a VETO."""
        try:
            from utils.auto_params import AutoParams
            ap = AutoParams()
            success = ap.update(
                item["param_key"],
                item["proposed_value"],
                "AutoExecutor",
                f"CPO proposal (no veto) | {item['reason']}",
            )
            if success:
                logger.info(
                    f"AutoExecutor: APPLIED {item['param_key']} "
                    f"{item['old_value']} -> {item['proposed_value']}"
                )
                self._append_audit_log(
                    f"[AutoExecutor] APPLIED {item['param_key']}: "
                    f"{item['old_value']} -> {item['proposed_value']} | {item['reason']}"
                )
                self._send_telegram(
                    f"[CPO AutoExec] Applied: `{item['param_key']}` "
                    f"{item['old_value']} -> {item['proposed_value']}"
                )
            else:
                logger.warning(
                    f"AutoExecutor: auto_params.update() rejected {item['param_key']} "
                    f"(drift guard or bounds)"
                )
                self._send_telegram(
                    f"[CPO AutoExec] Rejected by drift guard: `{item['param_key']}` "
                    f"{item['old_value']} -> {item['proposed_value']}"
                )
        except Exception as e:
            logger.error(f"AutoExecutor: failed to apply {item['param_key']}: {e}")

    def _poll_veto_messages(self, state: dict) -> bool:
        """
        Poll Telegram getUpdates for new VETO messages from the configured chat.
        Updates state["telegram_offset"] in-place to avoid reprocessing.
        Returns True if any VETO message found.
        """
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return False

        offset = state.get("telegram_offset", 0)

        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = urllib.parse.urlencode({"offset": offset, "limit": 20, "timeout": 0})
            req = urllib.request.Request(f"{url}?{params}", method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            updates = data.get("result", [])
            vetoed = False

            for update in updates:
                update_id = update.get("update_id", 0)
                # Always advance offset so we don't re-read old messages
                state["telegram_offset"] = max(state.get("telegram_offset", 0), update_id + 1)

                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = (msg.get("text") or "").strip().upper()

                if chat_id == str(TELEGRAM_CHAT_ID) and text == "VETO":
                    vetoed = True
                    logger.info(f"AutoExecutor: VETO received (update_id={update_id})")

            return vetoed

        except Exception as e:
            logger.debug(f"AutoExecutor: Telegram poll failed: {e}")
            return False

    def _load_state(self) -> dict:
        try:
            with open(PENDING_FILE) as f:
                return json.load(f)
        except Exception:
            return {"pending": [], "telegram_offset": 0}

    def _save_state(self, state: dict):
        try:
            with open(PENDING_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"AutoExecutor: failed to save {PENDING_FILE}: {e}")

    def _append_audit_log(self, message: str):
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open("audit_log.txt", "a") as f:
                f.write(f"[{ts}] {message}\n")
        except Exception:
            pass

    def _send_telegram(self, text: str):
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.info(f"AutoExecutor (no Telegram): {text}")
            return
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            params = urllib.parse.urlencode({
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
            }).encode()
            req = urllib.request.Request(url, data=params, method="POST")
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as e:
            logger.warning(f"AutoExecutor: Telegram send failed: {e}")
