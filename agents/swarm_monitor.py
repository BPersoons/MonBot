"""
SwarmMonitor Agent - Proactive Health Watchdog
Runs as a background thread inside the swarm container.

Checks every 5 minutes:
1. Supabase swarm_health: stale agents, ERROR status, frozen cycle counts
2. Docker logs (from within the container): ERROR/CRITICAL/Traceback patterns
3. Telegram alerts for issues (with deduplication)

Writes findings back to Supabase (swarm_health table as 'SwarmMonitor' agent)
so the dashboard can display them.
"""

import json
import logging
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("SwarmMonitor")

# ──────────────────────────────────────────────
# Configuration (from env vars with defaults)
# ──────────────────────────────────────────────
CHECK_INTERVAL_SEC = int(os.getenv("MONITOR_CHECK_INTERVAL_MINUTES", "5")) * 60
ALERT_COOLDOWN_SEC = int(os.getenv("MONITOR_ALERT_COOLDOWN_MINUTES", "30")) * 60
STALE_THRESHOLD_MIN = int(os.getenv("MONITOR_STALE_AGENT_MINUTES", "10"))
# Heartbeat cycles legitimately take 6-19 min (heavy convergence cycles stack
# TreasuryAgent + SwarmLearner + a full scout/sentiment scan). Only alert on a
# TRUE hang: cycle_count not advancing for longer than the legit max.
CYCLE_FROZEN_THRESHOLD_MIN = int(os.getenv("MONITOR_CYCLE_FROZEN_MINUTES", "25"))
DRAWDOWN_ALERT_USD = float(os.getenv("PORTFOLIO_DRAWDOWN_ALERT_USD", "-10"))
DRAWDOWN_ALERT_COOLDOWN_SEC = 4 * 3600  # 4 hours
def _telegram_token() -> str:
    v = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not v:
        try:
            from utils.gcp_secrets import get_secret
            v = get_secret("TELEGRAM_BOT_TOKEN") or ""
        except Exception:
            pass
    return v

def _telegram_chat_id() -> str:
    v = os.getenv("TELEGRAM_CHAT_ID", "")
    if not v:
        try:
            from utils.gcp_secrets import get_secret
            v = get_secret("TELEGRAM_CHAT_ID") or ""
        except Exception:
            pass
    return v
CONTAINER_NAME = os.getenv("DOCKER_CONTAINER_NAME", "agent_trader_swarm")
LOG_TAIL_LINES = 100  # how many recent log lines to scan
LOG_ERROR_PATTERNS = [
    r" - ERROR - ",
    r" - CRITICAL - ",
    r"Traceback \(most recent call last\)",
    r"Exception:",
    r"\bquota\b",
    r"HTTP(?:/1\.[01])?\s*429",
    r"\b429 Too Many Requests\b",
    r"Connection refused",
    r"\bFATAL\b",
]

EXPECTED_AGENTS = ["Heartbeat", "ProjectLead", "Scout", "PerformanceAuditor", "ProductOwner"]


class SwarmMonitor:
    """
    Proactive health watchdog that runs inside the swarm as a daemon thread.
    It monitors other agents and reports issues to the dashboard via Supabase.
    """

    AUTO_PARAMS_FILE = "config/auto_params.json"
    ALERT_STATE_FILE = "monitor_alert_state.json"

    def __init__(self, db_client=None, exchange_client=None):
        self.db = db_client
        self.exchange_client = exchange_client
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # Alert deduplication: maps alert_key -> last_sent_timestamp
        self._sent_alerts: Dict[str, datetime] = {}
        self._load_alert_state()
        # Snapshot of previous cycle counts for freeze detection
        self._prev_cycle_counts: Dict[str, int] = {}
        # Timestamp when each agent's cycle_count last advanced (cumulative freeze timer)
        self._cycle_last_advance: Dict[str, datetime] = {}
        self._prev_check_time: Optional[datetime] = None
        self._check_count = 0
        # Pipeline output snapshots for stale detection
        self._prev_output_snapshots: Dict[str, str] = {}
        # Last known auto_params snapshot for change detection
        self._prev_auto_params: Dict = {}
        # Wallet empty alert cooldown timestamp
        self._wallet_empty_alert_time: float = 0
        self._wallet_zero_streak: int = 0  # consecutive 0-readings before alert (debounce HL API blips)
        # AutoExecutor for pending veto checks
        try:
            from utils.auto_executor import AutoExecutor
            self._auto_executor = AutoExecutor()
        except Exception as e:
            logger.warning(f"SwarmMonitor: AutoExecutor unavailable: {e}")
            self._auto_executor = None

    # ──────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────

    def start(self):
        """Start the monitoring loop in a background daemon thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="SwarmMonitor")
        self._thread.start()
        self._start_telegram_poll_thread()
        logger.info(f"🔍 SwarmMonitor started (interval={CHECK_INTERVAL_SEC}s)")

    def stop(self):
        """Stop the monitoring loop."""
        self._running = False
        logger.info("🔍 SwarmMonitor stopped")

    def run_once(self) -> Dict:
        """Run a single check cycle and return results dict (for testing)."""
        return self._run_checks()

    # ──────────────────────────────────────────
    # Internal loop
    # ──────────────────────────────────────────

    def _loop(self):
        """Main monitoring loop."""
        # Stagger first check by 60s to allow agents to initialize
        time.sleep(60)
        while self._running:
            try:
                self._run_checks()
            except Exception as e:
                logger.error(f"SwarmMonitor check failed: {e}", exc_info=True)
            time.sleep(CHECK_INTERVAL_SEC)

    def _safe_check(self, fn, *args):
        """Run a single check in isolation.

        Previously an exception in any one check (e.g. a NoneType in
        _check_supabase_health) propagated out of _run_checks, skipping every
        remaining check AND the prev_check_time update at the end — which in turn
        corrupted freeze detection. Isolating each check keeps the round complete.
        """
        try:
            return fn(*args)
        except Exception as e:
            logger.error(f"SwarmMonitor: check {fn.__name__} failed: {e}", exc_info=True)
            return None

    def _run_checks(self) -> Dict:
        """Run all checks and return consolidated findings."""
        self._check_count += 1
        now = datetime.now(timezone.utc)
        findings = []  # list of issue dicts
        all_ok = True

        logger.info(f"🔍 SwarmMonitor: running check #{self._check_count}")

        # ── Check 1: Supabase swarm_health ──────────
        db_issues = self._safe_check(self._check_supabase_health, now) or []
        findings.extend(db_issues)
        if db_issues:
            all_ok = False

        # ── Check 2: Docker log errors ───────────────
        log_issues = self._safe_check(self._check_docker_logs) or []
        findings.extend(log_issues)
        if log_issues:
            all_ok = False

        # ── Check 3: Pipeline output analysis ────────
        pipeline_issues = self._safe_check(self._check_pipeline_output, now) or []
        findings.extend(pipeline_issues)
        if pipeline_issues:
            all_ok = False

        # ── Check 4: Portfolio drawdown ───────────────
        self._safe_check(self._check_portfolio_health, now)

        # ── Check 5: Auto-param changes ───────────────
        self._safe_check(self._check_auto_param_changes)

        # ── Check 6: AutoExecutor pending veto windows ────
        self._safe_check(self._check_auto_executor)

        # ── Check 7: Pipeline null-signal detection ───────
        self._safe_check(self._check_signal_health, now)

        # ── Check 8: Wallet balance ────────────────────
        self._safe_check(self._check_wallet_balance)

        # ── Check 9: Threshold deadlock ────────────────
        self._safe_check(self._check_threshold_deadlock, now)

        # ── Check 10: HL position sync ─────────────────
        self._safe_check(self._check_position_sync, now)

        # ── Check 11: BUILD_CASE orphan detection ──────
        self._safe_check(self._check_build_case_orphan, now)

        # ── Check 12: 3-day P&L digest ─────────────────
        self._safe_check(self._check_pnl_digest, now)

        # ── Check 13: Health heartbeat ──────────────────
        self._safe_check(self._check_heartbeat, now)

        # ── Check 14: Stuck treasury proposals ─────────
        self._safe_check(self._check_stuck_proposals, now)

        # ── Check 15: MONITOR deadlock per ticker ──────
        self._safe_check(self._check_monitor_deadlock, now)

        # ── Check 16: XYZ zero-execute detection ───────
        self._safe_check(self._check_xyz_zero_execute, now)

        # ── Check 17: Treasury state staleness ─────────
        self._safe_check(self._check_treasury_staleness, now)

        # Check 18: trade drought — silent funnel halt, threshold-independent
        self._safe_check(self._check_trade_drought, now)

        # Add detected_at timestamp to all findings
        now_str = now.strftime("%H:%M:%S UTC")
        for f in findings:
            if "detected_at" not in f:
                f["detected_at"] = now_str

        # ── Summarize and persist ────────────────────
        status = "ACTIVE" if all_ok else "ERROR"
        issue_count = len(findings)
        summary = f"All {len(EXPECTED_AGENTS)} agents healthy" if all_ok else f"{issue_count} issue(s) detected"

        # Build metadata for dashboard
        meta = {
            "check_count": self._check_count,
            "last_checked": now.isoformat(),
            "check_interval_min": CHECK_INTERVAL_SEC // 60,
            "issues": findings,
            "all_ok": all_ok,
            "current_task": "Monitoring swarm health" if all_ok else f"⚠️ {issue_count} issues detected",
            "last_activity": summary,
        }

        # Write to swarm_health so dashboard shows it
        self._report_to_supabase(status, meta, error_summary=None if all_ok else summary)

        # ── Send Telegram alerts for new issues ──────
        if findings:
            self._maybe_send_telegram_alert(findings)

        # Store snapshot for next freeze-detection round
        self._prev_check_time = now
        self._save_alert_state()
        return {"ok": all_ok, "issues": findings, "check_count": self._check_count}

    # ──────────────────────────────────────────
    # Check 1: Supabase swarm_health
    # ──────────────────────────────────────────

    def _check_supabase_health(self, now: datetime) -> List[Dict]:
        """Check swarm_health table for stale/erroring agents."""
        issues = []
        if not self.db:
            return [{"type": "DB_UNAVAILABLE", "severity": "HIGH",
                     "message": "Cannot check swarm health – database client not available",
                     "agent": "SwarmMonitor"}]

        # Only query if DB is accessible (use raw client directly to avoid circuit breaker noise)
        try:
            result = self.db.client.table("swarm_health").select("*").execute()
            agents = result.data or []
        except Exception as e:
            return [{"type": "DB_ERROR", "severity": "HIGH",
                     "message": f"Failed to read swarm_health: {e}",
                     "agent": "SwarmMonitor"}]

        agent_map = {a["agent_name"]: a for a in agents}

        # Check each expected agent
        for agent_name in EXPECTED_AGENTS:
            if agent_name == "SwarmMonitor":
                continue  # Don't check ourselves
            if agent_name == "ProductOwner":
                continue  # Disabled to reduce Gemini API costs — no pulse expected

            agent = agent_map.get(agent_name)

            # Missing entirely (never reported)
            if not agent:
                issues.append({
                    "type": "AGENT_MISSING",
                    "severity": "HIGH",
                    "agent": agent_name,
                    "message": f"Agent '{agent_name}' has no health record – never started or crashed at init",
                })
                continue

            # Status ERROR
            if agent.get("status") == "ERROR":
                # .get(key, default) returns None when the key exists but is null,
                # so the default is NOT applied — guard with `or` to avoid None[:200].
                error_msg = agent.get("last_error") or "No details"
                issues.append({
                    "type": "AGENT_ERROR",
                    "severity": "HIGH",
                    "agent": agent_name,
                    "message": f"Agent is in ERROR state: {error_msg[:200]}",
                    "last_pulse": agent.get("last_pulse"),
                })

            # Stale pulse (agent silently died)
            pulse_raw = agent.get("last_pulse")
            if pulse_raw:
                try:
                    pulse_dt = datetime.fromisoformat(pulse_raw.replace("Z", "+00:00").replace("+00:00+00:00", "+00:00"))
                    if pulse_dt.tzinfo is None:
                        pulse_dt = pulse_dt.replace(tzinfo=timezone.utc)
                    age_min = (now - pulse_dt).total_seconds() / 60
                    
                    # Agent-specific thresholds
                    threshold = STALE_THRESHOLD_MIN
                    if agent_name == "Scout": threshold = 45 # Runs every 30m
                    elif agent_name == "ProductOwner": threshold = 4 * 60 # CPO runs every 10 cycles, can be hours
                    elif agent_name == "PerformanceAuditor": threshold = 2 * 60
                    elif agent_name == "Heartbeat": threshold = 30 # Main loop can take 15-20 minutes
                    elif agent_name in ["Auditor", "Judge", "ExecutionAgent", "RiskManager"]: threshold = 999999 # Often idle for long times
                    
                    if age_min > threshold:
                        issues.append({
                            "type": "AGENT_STALE",
                            "severity": "HIGH" if age_min > (threshold * 3) else "MEDIUM",
                            "agent": agent_name,
                            "message": f"No pulse for {age_min:.0f} min (threshold: {threshold} min)",
                            "last_pulse": pulse_raw,
                        })
                except Exception:
                    pass  # Bad timestamp, skip

            # Frozen cycle count — cumulative time since cycle_count last advanced.
            # Only Heartbeat is expected to advance every cycle; Scout / auditors
            # cycle irregularly by design, so freeze-checking them here would false-
            # positive (the stale-pulse check above already covers a truly dead agent).
            curr_count = int(agent.get("cycle_count") or 0)
            prev_count = self._prev_cycle_counts.get(agent_name)
            if prev_count is None or curr_count != prev_count:
                # First sighting or counter advanced → reset the freeze timer.
                self._cycle_last_advance[agent_name] = now
            elif agent_name == "Heartbeat":
                frozen_min = (now - self._cycle_last_advance.get(agent_name, now)).total_seconds() / 60
                if frozen_min > CYCLE_FROZEN_THRESHOLD_MIN:
                    issues.append({
                        "type": "CYCLE_FROZEN",
                        "severity": "HIGH" if frozen_min > CYCLE_FROZEN_THRESHOLD_MIN * 2 else "MEDIUM",
                        "agent": agent_name,
                        "message": f"Cycle count frozen at {curr_count} for {frozen_min:.0f} min "
                                   f"(threshold {CYCLE_FROZEN_THRESHOLD_MIN} min)",
                        "last_pulse": pulse_raw,
                    })

            # Update snapshot
            self._prev_cycle_counts[agent_name] = curr_count

        return issues

    # ──────────────────────────────────────────
    # Check 2: Docker log inspection
    # ──────────────────────────────────────────

    def _check_docker_logs(self) -> List[Dict]:
        """
        Reads our own container's logs via 'docker logs' command.
        Since we run inside the container, we use docker CLI if available,
        otherwise fall back to reading the heartbeat.log file written by main.py.
        """
        issues = []

        # ── Strategy A: Read heartbeat.log (always available inside container) ──
        log_content = self._read_log_file("heartbeat.log")
        if not log_content:
            log_content = self._read_log_file("swarm_vm.log")

        if not log_content:
            # ── Strategy B: Try docker logs (if docker CLI is available) ──
            log_content = self._run_docker_logs()

        if not log_content:
            return []  # Can't check logs, skip silently

        lines = log_content.splitlines()
        # Take last N lines only
        recent_lines = lines[-LOG_TAIL_LINES:]

        matched_lines = []
        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in LOG_ERROR_PATTERNS]

        for line in recent_lines:
            for pattern in compiled_patterns:
                if pattern.search(line):
                    matched_lines.append(line.strip())
                    break  # Don't double-count

        if matched_lines:
            # Group into a single finding, keep last 10
            snippet = "\n".join(matched_lines[-10:])
            issues.append({
                "type": "LOG_ERRORS",
                "severity": "HIGH" if len(matched_lines) > 3 else "MEDIUM",
                "agent": "Container",
                "message": f"{len(matched_lines)} error-pattern lines found in recent logs",
                "detail": snippet,
            })

        return issues

    def _read_log_file(self, filename: str) -> Optional[str]:
        """Read last N bytes of a log file."""
        try:
            if not os.path.exists(filename):
                return None
            size = os.path.getsize(filename)
            read_bytes = min(size, 50000)  # last 50KB
            with open(filename, "r", encoding="utf-8", errors="replace") as f:
                if size > read_bytes:
                    f.seek(size - read_bytes)
                return f.read()
        except Exception:
            return None

    def _run_docker_logs(self) -> Optional[str]:
        """Try to run 'docker logs' on the swarm container."""
        try:
            result = subprocess.run(
                ["docker", "logs", "--tail", str(LOG_TAIL_LINES), CONTAINER_NAME],
                capture_output=True, text=True, timeout=10
            )
            return (result.stdout or "") + (result.stderr or "")
        except Exception:
            return None

    # ──────────────────────────────────────────
    # Check 3: Pipeline output analysis
    # ──────────────────────────────────────────

    # Define the expected pipeline flow and what output each agent should produce
    PIPELINE_EXPECTATIONS = {
        "Scout": {
            "output_keys": ["tickers_scanned", "universe_size", "approved_count", "proposals_count"],
            "downstream": "ProjectLead",
            "output_label": "approved tickers",
            "min_output": 0,  # Scout finding 0 is valid if market is quiet
        },
        "ProjectLead": {
            "output_keys": ["latest_decisions"],
            "downstream": None,  # End of decision pipeline
            "output_label": "decisions",
            "min_output": 0,
        },
        "ProductOwner": {
            "output_keys": [],  # Checked via system_backlog table instead
            "downstream": None,
            "output_label": "improvement ideas",
            "min_output": 0,
        },
    }

    def _check_pipeline_output(self, now: datetime) -> List[Dict]:
        """Check if agents are producing output and if the pipeline flows correctly."""
        issues = []
        if not self.db:
            return []

        try:
            result = self.db.client.table("swarm_health").select("*").execute()
            agents = result.data or []
        except Exception:
            return []  # Can't check, skip silently

        agent_map = {}
        for a in agents:
            if isinstance(a, dict):
                agent_map[a.get("agent_name", "")] = a

        # ── Check each pipeline agent for output ──
        scout_approved = 0
        pl_decisions_count = 0

        for agent_name, expect in self.PIPELINE_EXPECTATIONS.items():
            agent = agent_map.get(agent_name)
            if not agent:
                continue  # Missing agents are caught by Check 1

            status = agent.get("status", "")
            meta = agent.get("metadata") or {}
            if not isinstance(meta, dict):
                meta = {}
            cycle = int(agent.get("cycle_count") or 0)

            # Skip agents that haven't started yet (cycle 0)
            if cycle == 0:
                continue

            # ── NO_OUTPUT: Agent is active but has no output in metadata ──
            if agent_name == "Scout":
                scanned = meta.get("scanned_count", meta.get("universe_size", 0))
                scout_approved = meta.get("approved_count", meta.get("proposals_count", 0))
                if cycle >= 2 and not scanned and meta.get("total_universe", 0) == 0:
                    issues.append({
                        "type": "NO_OUTPUT",
                        "severity": "MEDIUM",
                        "agent": "Scout",
                        "message": f"Scout has run {cycle} cycles but reports 0 tickers scanned — possible data source issue",
                    })

            elif agent_name == "ProjectLead":
                decisions = meta.get("latest_decisions", [])
                if isinstance(decisions, list):
                    pl_decisions_count = len(decisions)
                else:
                    pl_decisions_count = 0
                    
                pl_task_meta = meta.get("current_task", "")
                pl_task_db = agent.get("task", "") or ""
                is_scouting = "Scouting" in str(pl_task_meta) or "Scouting" in str(pl_task_db) or "Research" in str(pl_task_meta)
                
                if cycle >= 2 and pl_decisions_count == 0 and status == "IDLE" and not is_scouting:
                    issues.append({
                        "type": "NO_OUTPUT",
                        "severity": "MEDIUM",
                        "agent": "ProjectLead",
                        "message": f"ProjectLead has run {cycle} cycles but made 0 decisions — possible analysis failure",
                    })

            elif agent_name == "ProductOwner":
                # Check system_backlog for recent entries
                try:
                    backlog = self.db.client.table("system_backlog").select("created_at").order("created_at", desc=True).limit(1).execute()
                    if backlog.data:
                        last_idea_time = backlog.data[0].get("created_at", "")
                        try:
                            last_dt = datetime.fromisoformat(last_idea_time.replace("Z", "+00:00"))
                            if last_dt.tzinfo is None:
                                last_dt = last_dt.replace(tzinfo=timezone.utc)
                            days_since = (now - last_dt).total_seconds() / 86400
                            if cycle >= 11 and days_since > 7:
                                issues.append({
                                    "type": "STALE_OUTPUT",
                                    "severity": "MEDIUM",
                                    "agent": "ProductOwner",
                                    "message": f"CPO hasn't produced new ideas in {days_since:.0f} days — possible data source issue",
                                })
                        except Exception:
                            pass
                    elif cycle >= 11:
                        issues.append({
                            "type": "NO_OUTPUT",
                            "severity": "MEDIUM",
                            "agent": "ProductOwner",
                            "message": "CPO has no entries in system_backlog — never produced any ideas",
                        })
                except Exception:
                    pass

            # ── STALE_OUTPUT: Output hash hasn't changed between checks ──
            output_hash = str(meta.get("last_activity", "")) + str(cycle)
            prev_hash = self._prev_output_snapshots.get(agent_name)
            if prev_hash and output_hash == prev_hash and self._prev_check_time:
                elapsed = (now - self._prev_check_time).total_seconds() / 60
                if elapsed > 30:
                    issues.append({
                        "type": "STALE_OUTPUT",
                        "severity": "LOW",
                        "agent": agent_name,
                        "message": f"Output unchanged for {elapsed:.0f}min (same activity + cycle count)",
                    })
            self._prev_output_snapshots[agent_name] = output_hash

        # ── PIPELINE_BLOCKED: Scout produces but ProjectLead doesn't consume ──
        if scout_approved > 0 and pl_decisions_count == 0:
            scout_agent = agent_map.get("Scout", {})
            pl_agent = agent_map.get("ProjectLead", {})
            
            scout_cycle = int(scout_agent.get("cycle_count") or 0) if isinstance(scout_agent, dict) else 0
            pl_cycle = int(pl_agent.get("cycle_count") or 0) if isinstance(pl_agent, dict) else 0
            pl_status = pl_agent.get("status", "") if isinstance(pl_agent, dict) else ""
            
            pl_meta = pl_agent.get("metadata", {}) if isinstance(pl_agent, dict) else {}
            pl_task_meta = pl_meta.get("current_task", "") if isinstance(pl_meta, dict) else ""
            pl_task_db = pl_agent.get("task", "") if isinstance(pl_agent, dict) else ""
            is_scouting = "Scouting" in str(pl_task_meta) or "Scouting" in str(pl_task_db) or "Research" in str(pl_task_meta)
            
            # Only flag if both have run at least 1 cycle, and PL finished its cycle but produced 0 decisions
            if scout_cycle >= 1 and pl_cycle >= 1 and pl_status == "IDLE" and not is_scouting:
                issues.append({
                    "type": "PIPELINE_BLOCKED",
                    "severity": "HIGH",
                    "agent": "ProjectLead",
                    "message": f"Scout approved {scout_approved} tickers but ProjectLead made 0 decisions (status: {pl_status})",
                })

        return issues

    # ──────────────────────────────────────────
    # Check 4: Portfolio drawdown alert
    # ──────────────────────────────────────────

    def _check_portfolio_health(self, now: datetime):
        """Sum P&L of OPEN trades from trade_log.json and alert if below threshold."""
        try:
            if not os.path.exists("trade_log.json"):
                return
            with open("trade_log.json", "r", encoding="utf-8") as f:
                trades = json.load(f)
        except Exception as e:
            logger.debug(f"SwarmMonitor: could not read trade_log.json: {e}")
            return

        open_trades = [t for t in trades if t.get("status") == "OPEN"]
        if not open_trades:
            return

        total_pnl = sum(float(t.get("pnl") or 0) for t in open_trades)
        underwater = sum(1 for t in open_trades if float(t.get("pnl") or 0) < 0)

        if total_pnl >= DRAWDOWN_ALERT_USD:
            return  # Within acceptable range

        alert_key = "portfolio_drawdown"
        last_sent = self._sent_alerts.get(alert_key)
        if last_sent and (now - last_sent).total_seconds() < DRAWDOWN_ALERT_COOLDOWN_SEC:
            return  # Already alerted recently

        self._sent_alerts[alert_key] = now
        msg = (
            f"Portfolio drawdown: ${total_pnl:.2f} | "
            f"{underwater} of {len(open_trades)} positions underwater"
        )
        logger.warning(f"SwarmMonitor: {msg}")

        # Telegram alert
        if _telegram_token() and _telegram_chat_id():
            self._send_telegram(f"Portfolio drawdown: ${total_pnl:.2f} | {underwater}/{len(open_trades)} positions underwater")

        # DB backlog item
        if self.db:
            try:
                existing = self.db.client.table("system_backlog") \
                    .select("id").eq("title", "Portfolio Drawdown Alert").eq("status", "PENDING").execute()
                if not existing.data:
                    self.db.client.table("system_backlog").insert({
                        "title": "Portfolio Drawdown Alert",
                        "description": (
                            f"SwarmMonitor detected portfolio P&L at ${total_pnl:.2f} "
                            f"({underwater}/{len(open_trades)} positions underwater). "
                            f"Threshold: ${DRAWDOWN_ALERT_USD}. "
                            f"Consider running `python scripts/market_retrospective.py` for root-cause analysis."
                        ),
                        "priority": 9,
                        "status": "PENDING",
                        "category": "PERFORMANCE",
                        "created_by": "SwarmMonitor",
                        "created_at": now.isoformat(),
                    }).execute()
            except Exception as e:
                logger.debug(f"SwarmMonitor: could not push drawdown backlog item: {e}")

    # ──────────────────────────────────────────
    # Check 5: Auto-param change notifications
    # ──────────────────────────────────────────

    def _check_auto_param_changes(self):
        """
        Detect changes to config/auto_params.json written by the Auditor.
        Fires a Telegram notification for each changed parameter.
        Uses deduplication so the same change is not re-alerted.
        """
        if not os.path.exists(self.AUTO_PARAMS_FILE):
            return

        try:
            with open(self.AUTO_PARAMS_FILE, "r") as f:
                current = json.load(f)
        except Exception as e:
            logger.debug(f"SwarmMonitor: could not read auto_params.json: {e}")
            return

        # Skip meta/bounds keys; compare only tunable values
        tunable_keys = [k for k in current if not k.startswith("_")]

        if not self._prev_auto_params:
            # First read — just store snapshot, no alert
            self._prev_auto_params = {k: current[k] for k in tunable_keys}
            return

        meta = current.get("_meta", {})
        changed_by = meta.get("last_changed_by", "unknown")
        reason = meta.get("change_reason", "")

        changes = []
        for k in tunable_keys:
            old_val = self._prev_auto_params.get(k)
            new_val = current.get(k)
            if old_val is not None and old_val != new_val:
                changes.append((k, old_val, new_val))

        # Update snapshot regardless
        self._prev_auto_params = {k: current[k] for k in tunable_keys}

        if not changes:
            return

        if not _telegram_token() or not _telegram_chat_id():
            for k, old_val, new_val in changes:
                logger.info(f"[AutoTune] {k}: {old_val} -> {new_val} | {reason}")
            return

        now = datetime.now(timezone.utc)
        for k, old_val, new_val in changes:
            alert_key = f"auto_param_change:{k}:{new_val}"
            last_sent = self._sent_alerts.get(alert_key)
            if last_sent and (now - last_sent).total_seconds() < ALERT_COOLDOWN_SEC:
                continue
            self._sent_alerts[alert_key] = now

            msg = (
                f"[AutoTune] `{k}`: {old_val} -> {new_val}\n"
                f"By: {changed_by} | Reason: {reason}"
            )
            logger.info(f"SwarmMonitor: {msg}")
            self._send_telegram(msg)

    # ──────────────────────────────────────────
    # Check 6: AutoExecutor pending veto
    # ──────────────────────────────────────────

    def _check_auto_executor(self):
        """Process pending AUTO_PARAM veto windows — apply or discard as time expires."""
        if not self._auto_executor:
            return
        try:
            self._auto_executor.check_pending()
        except Exception as e:
            logger.debug(f"SwarmMonitor: AutoExecutor check failed: {e}")

    # ──────────────────────────────────────────
    # Check 7: Pipeline null-signal detection
    # ──────────────────────────────────────────

    DECISION_HISTORY_FILE = "decision_history.json"
    SIGNAL_HEALTH_WINDOW = 10          # number of recent decisions to inspect
    SIGNAL_HEALTH_COOLDOWN_SEC = 3600  # 1 hour between repeat alerts

    def _check_signal_health(self, now: datetime):
        """
        Detect the symptom of all-null scored decisions — the signature of a
        crashed or API-mismatched analyst (e.g. TechnicalAnalyst returning None
        due to a signature mismatch after a hot-patch).

        If every one of the last SIGNAL_HEALTH_WINDOW decisions has score=None
        (or weighted_score=None), fire an immediate Telegram alert.
        """
        if not os.path.exists(self.DECISION_HISTORY_FILE):
            return

        try:
            with open(self.DECISION_HISTORY_FILE, "r") as f:
                history = json.load(f)
        except Exception as e:
            logger.debug(f"SwarmMonitor: could not read decision_history.json: {e}")
            return

        if not isinstance(history, list) or len(history) == 0:
            return

        # Take the most recent N entries
        recent = history[-self.SIGNAL_HEALTH_WINDOW:]
        if len(recent) < self.SIGNAL_HEALTH_WINDOW:
            return  # Not enough data yet — avoid false positives at startup

        def _is_null_score(entry):
            # A score of 0.0 is a VALID neutral reading (e.g. closed-market XYZ
            # tickers), not a null. Only a genuinely absent/None score signals a
            # pipeline failure. NB: decision_history has no "weighted_score" field
            # (the real field is "score"), so `score or weighted_score` used to turn
            # every 0.0 into None — the false "TA crash" alarm.
            score = entry.get("score")
            if score is None:
                score = entry.get("weighted_score")
            return score is None

        if not all(_is_null_score(e) for e in recent):
            return  # At least one valid score — pipeline is working

        # All null — check cooldown before alerting
        alert_key = "signal_health_all_null"
        last_sent = self._sent_alerts.get(alert_key)
        if last_sent and (now - last_sent).total_seconds() < self.SIGNAL_HEALTH_COOLDOWN_SEC:
            return

        self._sent_alerts[alert_key] = now
        n = len(recent)
        msg = (
            f"[Swarm] Pipeline signal failure — last {n} decisions all null. "
            f"TA crash likely. Check logs."
        )
        logger.warning(f"SwarmMonitor: {msg}")

        if _telegram_token() and _telegram_chat_id():
            self._send_telegram(msg)

    # ──────────────────────────────────────────
    # Check 9: Threshold deadlock detection
    # ──────────────────────────────────────────

    DEADLOCK_THRESHOLD_MIN = 0.47   # Alert when score_threshold reaches this
    DEADLOCK_NO_TRADE_HOURS = 48    # And no new trades opened in this window
    DEADLOCK_ALERT_COOLDOWN_SEC = 6 * 3600  # Max once per 6 hours

    # ──────────────────────────────────────────
    # Check 18: Trade drought (threshold-independent)
    # ──────────────────────────────────────────

    DROUGHT_HOURS = 72            # Alert when no entry for this long
    DROUGHT_ALERT_COOLDOWN_SEC = 24 * 3600  # Max once per day

    def _check_trade_drought(self, now: datetime):
        """
        Alert when no trade has been OPENED for DROUGHT_HOURS, regardless of
        score_threshold. The threshold-deadlock check (below) only fires at
        threshold >= 0.47 — in June 2026 the swarm sat at threshold 0.20 and
        still traded zero for 5 days (LLM-band dead zone) without any alarm,
        while fixed costs kept running. A silent halt is the most expensive
        failure mode and must page regardless of WHY the funnel is dry.
        """
        # The monitor passes an aware `now` (UTC); trade_log timestamps are a mix
        # of naive and aware. Normalize EVERYTHING to naive UTC before arithmetic.
        if now.tzinfo is not None:
            now = now.replace(tzinfo=None)

        try:
            with open("trade_log.json", "r", encoding="utf-8") as f:
                trades = json.load(f)
        except Exception:
            return

        last_entry = None
        for t in trades:
            raw = t.get("entry_time")
            if not raw:
                continue
            try:
                ts = datetime.fromtimestamp(float(raw))
            except (TypeError, ValueError):
                try:
                    ts = datetime.fromisoformat(str(raw).replace("Z", ""))
                except (TypeError, ValueError):
                    continue
            # trade_log mixes naive and tz-aware ISO strings — normalize to
            # naive so subtraction against the monitor's naive `now` works
            ts = ts.replace(tzinfo=None)
            if last_entry is None or ts > last_entry:
                last_entry = ts

        if last_entry is None:
            return  # empty/unparseable log — covered by other checks
        drought_h = (now - last_entry).total_seconds() / 3600
        if drought_h < self.DROUGHT_HOURS:
            return

        alert_key = "trade_drought"
        last_sent = self._sent_alerts.get(alert_key)
        if last_sent and (now - last_sent).total_seconds() < self.DROUGHT_ALERT_COOLDOWN_SEC:
            return
        self._sent_alerts[alert_key] = now
        msg = (
            f"🏜️ TRADE DROUGHT: geen nieuwe trade in {drought_h:.0f}u "
            f"(laatste entry {last_entry:%Y-%m-%d %H:%M}).\n"
            f"Swarm draait maar handelt niet — check funnel (learning_report.json: "
            f"bottleneck_gate), score-verdeling en LLM-band-alignment.\n"
            f"Kosten lopen door; HL-marge staat idle."
        )
        self._send_telegram(msg)
        logger.warning(f"[SwarmMonitor] Trade drought alert verstuurd ({drought_h:.0f}h)")

    def _check_threshold_deadlock(self, now: datetime):
        """
        Alert via Telegram when score_threshold is high AND no trades have been
        opened in the last 48 hours — the signature of the Auditor deadlock.
        """
        # Read current threshold
        try:
            with open(self.AUTO_PARAMS_FILE, "r") as f:
                params = json.load(f)
            threshold = float(params.get("score_threshold", 0))
        except Exception:
            return

        if threshold < self.DEADLOCK_THRESHOLD_MIN:
            return

        # Check whether any trade was opened in the last N hours
        try:
            with open("trade_log.json", "r", encoding="utf-8") as f:
                trades = json.load(f)
            cutoff = (now - timedelta(hours=self.DEADLOCK_NO_TRADE_HOURS)).isoformat()
            recent = [t for t in trades if (t.get("entry_time") or "") >= cutoff]
        except Exception:
            return

        if recent:
            return  # Trades are flowing — no deadlock

        # Deadlock confirmed — check cooldown
        alert_key = "threshold_deadlock"
        last_sent = self._sent_alerts.get(alert_key)
        if last_sent and (now - last_sent).total_seconds() < self.DEADLOCK_ALERT_COOLDOWN_SEC:
            return

        self._sent_alerts[alert_key] = now
        msg = (
            f"⚠️ THRESHOLD DEADLOCK gedetecteerd\n"
            f"score_threshold = {threshold:.2f} (≥ {self.DEADLOCK_THRESHOLD_MIN})\n"
            f"Geen nieuwe trades in de laatste {self.DEADLOCK_NO_TRADE_HOURS}u.\n"
            f"Actie: reset score_threshold handmatig naar 0.40 via config/auto_params.json"
        )
        self._send_telegram(msg)
        logger.warning(f"[SwarmMonitor] Threshold deadlock alert verstuurd (threshold={threshold:.2f})")

    # ──────────────────────────────────────────
    # Check 8: Wallet balance
    # ──────────────────────────────────────────

    # Require N consecutive zero-readings (~15 min) before treating as real
    # empty wallet. Single HL API blips can return spot=0+perp=0 transiently;
    # logged false-positive 2026-04-25 07:33 UTC where one reading at $0 was
    # bracketed by $475 readings 5 min before/after.
    WALLET_ZERO_STREAK_REQUIRED = 3

    def _check_wallet_balance(self):
        """Alert once per hour if the HL wallet has $0 USDC for N consecutive checks."""
        if not self.exchange_client:
            return
        try:
            balance = self.exchange_client.get_balance()
            if balance > 0:
                self._wallet_zero_streak = 0
                self._wallet_empty_alert_time = 0  # Reset cooldown once funded
                return
            # Balance = 0 — increment streak; only alert after threshold reached
            self._wallet_zero_streak += 1
            if self._wallet_zero_streak < self.WALLET_ZERO_STREAK_REQUIRED:
                logger.info(
                    f"[SwarmMonitor] Wallet $0 reading {self._wallet_zero_streak}/"
                    f"{self.WALLET_ZERO_STREAK_REQUIRED} — debouncing API blip"
                )
                return
            if time.time() - self._wallet_empty_alert_time < 3600:
                return
            self._wallet_empty_alert_time = time.time()
            msg = (
                f"⚠️ WALLET LEEG: HL USDC balance = $0.00 ({self._wallet_zero_streak}× achtereen)\n"
                "Trading is gepauzeerd totdat USDC wordt gestort.\n"
                "Actie: deposit USDC op de HL wallet om trading te hervatten."
            )
            self._send_telegram(msg)
            logger.warning("[SwarmMonitor] Wallet empty — Telegram alert verstuurd")
        except Exception as e:
            logger.error(f"_check_wallet_balance: {e}")

    # ──────────────────────────────────────────
    # Check 10: HL position sync / ghost-asset detector
    # ──────────────────────────────────────────

    POSITION_SYNC_INTERVAL_SEC = 24 * 3600  # Once per 24 hours
    ACTIVE_ASSETS_FILE = "active_assets.json"
    TRADE_LOG_FILE = "trade_log.json"

    def _check_position_sync(self, now: datetime):
        """
        Every 24h, fetch live positions from Hyperliquid and reconcile:
        - active_assets.json: ghost entries (not on HL) removed; real HL positions added if missing
        - trade_log.json: OPEN trades with no corresponding HL position are marked CLOSED (ghost)
        Sends a Telegram summary of everything that was auto-corrected (or a clean-bill-of-health
        if nothing needed fixing).
        """
        if not self.exchange_client:
            return

        # 24h cooldown — reuse _sent_alerts dict with a sentinel key
        last_sync = self._sent_alerts.get("_position_sync_ts")
        if last_sync and (now - last_sync).total_seconds() < self.POSITION_SYNC_INTERVAL_SEC:
            return

        try:
            # ── Fetch live HL positions ──────────────────────────────────
            user_addr = (
                getattr(self.exchange_client, "vault_address", None)
                or getattr(self.exchange_client, "wallet_address", None)
            )
            signing = getattr(self.exchange_client, "signing_client", None)
            if not user_addr or not signing:
                return

            # Use fetch_all_positions() to include XYZ clearinghouse
            positions = self.exchange_client.fetch_all_positions()
            hl_open_bases = {
                pos.get("symbol", "").split("/")[0].upper()
                for pos in positions
                if abs(float(
                    pos.get("contracts")
                    or (pos.get("info") or {}).get("szi")
                    or 0
                )) > 1e-9
            }

            # ── Read current active_assets ───────────────────────────────
            try:
                with open(self.ACTIVE_ASSETS_FILE, "r") as f:
                    active_assets: list = json.load(f)
            except Exception:
                active_assets = []
            active_bases = {t.split("/")[0].upper() for t in active_assets}

            # ── Read OPEN trades in trade_log ────────────────────────────
            try:
                with open(self.TRADE_LOG_FILE, "r", encoding="utf-8") as f:
                    trades: list = json.load(f)
            except Exception:
                trades = []
            open_trades = [t for t in trades if t.get("status") == "OPEN"]

            # ── Safety guard: HL returned 0 positions but OPEN trades exist ────
            # This likely means the HL API is down or the account has an issue.
            # Do NOT auto-close — alert and abort to avoid false positives.
            if not hl_open_bases and open_trades:
                logger.warning(
                    f"[PositionSync] SAFETY ABORT: HL returned 0 positions but "
                    f"{len(open_trades)} OPEN trade(s) in trade_log. Skipping auto-close."
                )
                alert_key = "position_sync_hl_zero"
                last_sent = self._sent_alerts.get(alert_key)
                if not last_sent or (now - last_sent).total_seconds() > 6 * 3600:
                    self._sent_alerts[alert_key] = now
                    tickers = [t.get("ticker", "?") for t in open_trades]
                    msg = (
                        f"⚠️ *Position Sync — Handmatige review vereist*\n"
                        f"HL returned 0 posities maar {len(open_trades)} OPEN trade(s) in trade\\_log.\n"
                        f"Tickers: `{tickers}`\n"
                        f"Auto-close gepauzeerd — check HL account handmatig."
                    )
                    if _telegram_token() and _telegram_chat_id():
                        self._send_telegram(msg)
                self._sent_alerts["_position_sync_ts"] = now
                return

            corrections: list[str] = []

            # ── Fix 1: ghost entries in active_assets (not on HL) ────────
            ghost_assets = active_bases - hl_open_bases
            if ghost_assets:
                cleaned = [t for t in active_assets if t.split("/")[0].upper() not in ghost_assets]
                try:
                    with open(self.ACTIVE_ASSETS_FILE, "w") as f:
                        json.dump(cleaned, f, indent=4)
                    active_assets = cleaned
                    active_bases -= ghost_assets
                    corrections.append(f"Ghost entries verwijderd uit active\\_assets: {sorted(ghost_assets)}")
                    logger.warning(f"[PositionSync] Removed ghost active_assets: {sorted(ghost_assets)}")
                except Exception as e:
                    logger.error(f"[PositionSync] active_assets write failed: {e}")

            # ── Fix 2: real HL positions missing from active_assets ───────
            missing_assets = hl_open_bases - active_bases
            if missing_assets:
                updated = list(active_assets) + [f"{b}/USDC" for b in missing_assets]
                try:
                    with open(self.ACTIVE_ASSETS_FILE, "w") as f:
                        json.dump(updated, f, indent=4)
                    corrections.append(f"Ontbrekende HL posities toegevoegd aan active\\_assets: {sorted(missing_assets)}")
                    logger.warning(f"[PositionSync] Added missing active_assets from HL: {sorted(missing_assets)}")
                except Exception as e:
                    logger.error(f"[PositionSync] active_assets add failed: {e}")

            # ── Fix 3: phantom OPEN trades in trade_log ──────────────────
            # Skip XYZ trades if XYZ clearinghouse fetch failed
            _xyz_ok = getattr(self.exchange_client, '_xyz_fetch_ok', True)
            phantom = [
                t for t in open_trades
                if t.get("ticker", "").split("/")[0].upper() not in hl_open_bases
                and (not t.get("ticker", "").startswith("XYZ-") or _xyz_ok)
            ]
            if phantom:
                phantom_tickers = [t.get("ticker", "?") for t in phantom]
                for trade in trades:
                    base = trade.get("ticker", "").split("/")[0].upper()
                    is_xyz = trade.get("ticker", "").startswith("XYZ-")
                    if trade.get("status") == "OPEN" and base not in hl_open_bases and (not is_xyz or _xyz_ok):
                        trade["status"] = "CLOSED"
                        trade["close_reason"] = "GHOST_POSITION_SYNC"
                        trade["exit_time"] = now.isoformat()
                        trade["pnl"] = trade.get("pnl") or 0.0
                try:
                    with open(self.TRADE_LOG_FILE, "w", encoding="utf-8") as f:
                        json.dump(trades, f, indent=2, default=str)
                    corrections.append(f"{len(phantom)} phantom OPEN trade(s) gesloten: {phantom_tickers}")
                    logger.warning(f"[PositionSync] Closed phantom OPEN trades: {phantom_tickers}")
                except Exception as e:
                    logger.error(f"[PositionSync] trade_log write failed: {e}")

            # ── Mark cooldown ────────────────────────────────────────────
            self._sent_alerts["_position_sync_ts"] = now

            # ── Telegram report ──────────────────────────────────────────
            if corrections:
                msg = (
                    f"🔄 *Position Sync — correcties uitgevoerd*\n"
                    f"HL open: `{sorted(hl_open_bases) if hl_open_bases else 'geen'}`\n\n"
                    + "\n".join(f"✅ {c}" for c in corrections)
                )
                logger.warning(f"[PositionSync] Corrections applied: {corrections}")
            else:
                msg = (
                    f"✅ *Position Sync OK*\n"
                    f"HL open: `{sorted(hl_open_bases) if hl_open_bases else 'geen'}` | "
                    f"active\\_assets: `{sorted(active_bases) if active_bases else 'geen'}` | "
                    f"open trades: {len(open_trades)} — alles klopt"
                )
                logger.info(f"[PositionSync] All consistent. HL={sorted(hl_open_bases)}")

            if _telegram_token() and _telegram_chat_id():
                self._send_telegram(msg)

        except Exception as e:
            logger.error(f"_check_position_sync: {e}", exc_info=True)

    # ──────────────────────────────────────────
    # Check 11: BUILD_CASE orphan detection
    # ──────────────────────────────────────────

    BUILD_CASE_ORPHAN_WINDOW_HOURS = 24
    BUILD_CASE_ORPHAN_MIN_DECISIONS = 3
    BUILD_CASE_ORPHAN_COOLDOWN_SEC = 6 * 3600

    def _check_build_case_orphan(self, now: datetime):
        """
        Check 11: Alert when ≥3 BUILD_CASE decisions exist in the last 24h
        but 0 trades were executed in that same window.
        This is the early-warning signal for the ghost active_assets deadlock pattern —
        it would have fired within hours of the incident instead of days.
        """
        if not os.path.exists(self.DECISION_HISTORY_FILE):
            return
        try:
            with open(self.DECISION_HISTORY_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            return

        if not isinstance(history, list):
            return

        cutoff_str = (now - timedelta(hours=self.BUILD_CASE_ORPHAN_WINDOW_HOURS)).isoformat()
        cutoff_ts  = (now - timedelta(hours=self.BUILD_CASE_ORPHAN_WINDOW_HOURS)).timestamp()
        recent = [e for e in history if (e.get("timestamp") or "") >= cutoff_str]
        build_cases = [e for e in recent if e.get("decision") == "BUILD_CASE"]

        if len(build_cases) < self.BUILD_CASE_ORPHAN_MIN_DECISIONS:
            return

        # Check whether any trades were executed in the same window
        try:
            with open(self.TRADE_LOG_FILE, "r", encoding="utf-8") as f:
                trades = json.load(f)
        except Exception:
            trades = []

        # entry_time is a unix float — compare numerically, not against ISO string
        executed = [
            t for t in trades
            if float(t.get("entry_time") or 0) >= cutoff_ts
            and t.get("status") in ("OPEN", "CLOSED", "PENDING_FOUNDER_APPROVAL")
        ]
        if executed:
            return  # Trades are flowing — pipeline is healthy

        alert_key = "build_case_orphan"
        last_sent = self._sent_alerts.get(alert_key)
        if last_sent and (now - last_sent).total_seconds() < self.BUILD_CASE_ORPHAN_COOLDOWN_SEC:
            return

        self._sent_alerts[alert_key] = now

        orphan_tickers = sorted({e.get("ticker", "?") for e in build_cases})

        # Find most common veto reason from NO_GO decisions in the same window
        no_go_entries = [e for e in recent if e.get("decision") == "NO_GO"]
        reason_counts: Dict[str, int] = {}
        for e in no_go_entries:
            key = (e.get("reason") or "unknown")[:80]
            reason_counts[key] = reason_counts.get(key, 0) + 1
        top_reason = max(reason_counts, key=reason_counts.get) if reason_counts else "unknown"

        msg = (
            f"⚠️ *BUILD\\_CASE Orphan gedetecteerd*\n"
            f"Laatste {self.BUILD_CASE_ORPHAN_WINDOW_HOURS}u: "
            f"`{len(build_cases)}` BUILD\\_CASE beslissingen, 0 uitgevoerde trades.\n"
            f"Tickers: `{orphan_tickers[:8]}`\n"
            f"Meest voorkomende veto: _{top_reason[:120]}_\n"
            f"Check: active\\_assets.json ghost entries, Risk Manager marge."
        )
        logger.warning(
            f"[SwarmMonitor] Check11: {len(build_cases)} BUILD_CASE decisions, "
            f"0 executions in {self.BUILD_CASE_ORPHAN_WINDOW_HOURS}h"
        )
        if _telegram_token() and _telegram_chat_id():
            self._send_telegram(msg)

    # ──────────────────────────────────────────
    # Check 12: 3-day P&L digest (trend view)
    # ──────────────────────────────────────────

    PNL_DIGEST_INTERVAL_SEC = 3 * 24 * 3600  # 3 days

    def _check_pnl_digest(self, now: datetime):
        """
        Send a comparative P&L digest showing trend across 4 windows:
        L3d (last 3d), Prev3d (3-6d ago), L9d, L18d.
        Also splits crypto vs XYZ stocks and flags anomalies.
        """
        if not _telegram_token() or not _telegram_chat_id():
            return

        alert_key = "pnl_digest"
        last_sent = self._sent_alerts.get(alert_key)
        if last_sent and (now - last_sent).total_seconds() < self.PNL_DIGEST_INTERVAL_SEC:
            return

        try:
            if not os.path.exists("trade_log.json"):
                return
            with open("trade_log.json", "r", encoding="utf-8-sig") as f:
                trades = json.load(f)
        except Exception as e:
            logger.debug(f"SwarmMonitor: pnl_digest could not read trade_log.json: {e}")
            return

        real   = [t for t in trades if t.get("close_reason") not in ("HL_HISTORY_IMPORT", "GHOST_POSITION_SYNC")]
        closed = [t for t in real if t.get("status") == "CLOSED"]
        open_t = [t for t in real if t.get("status") == "OPEN"]

        if not closed:
            return

        from collections import Counter

        def _pnl(t):
            return float(t.get("realized_pnl") or t.get("pnl") or 0)

        def _exit_ts(t):
            et = t.get("exit_time")
            if et:
                try:
                    s = str(et).replace("Z", "+00:00")
                    return datetime.fromisoformat(s).timestamp()
                except Exception:
                    pass
            return float(t.get("entry_time") or 0)

        now_ts = now.timestamp()

        def window(days_ago_from, days_ago_to=0):
            lo = now_ts - days_ago_from * 86400
            hi = now_ts - days_ago_to   * 86400
            return [t for t in closed if lo <= _exit_ts(t) <= hi]

        def stats(subset):
            if not subset:
                return {"n": 0, "wr": 0.0, "pnl": 0.0, "pf": 0.0, "avg_w": 0.0, "avg_l": 0.0}
            pnls = [_pnl(t) for t in subset]
            wins = [p for p in pnls if p > 0]
            loss = [p for p in pnls if p < 0]
            wr   = len(wins) / len(pnls) * 100
            pf   = abs(sum(wins) / sum(loss)) if loss and sum(loss) != 0 else 0.0
            return {
                "n":     len(pnls),
                "wr":    wr,
                "pnl":   sum(pnls),
                "pf":    pf,
                "avg_w": sum(wins) / len(wins) if wins else 0.0,
                "avg_l": sum(loss) / len(loss) if loss else 0.0,
            }

        def fp(v):
            return f"+${v:.2f}" if v >= 0 else f"-${abs(v):.2f}"

        w3    = window(3)
        prev3 = window(6, 3)
        w9    = window(9)
        w18   = window(18)

        s3    = stats(w3)
        sp3   = stats(prev3)
        s9    = stats(w9)
        s18   = stats(w18)

        # ── Trend table ──────────────────────────────────────────────────────
        hdr  = f"{'':10} {'L3d':>6} {'Prev3d':>7} {'L9d':>6} {'L18d':>6}"
        r_n  = f"{'Trades':10} {s3['n']:>6} {sp3['n']:>7} {s9['n']:>6} {s18['n']:>6}"
        r_wr = f"{'WR':10} {s3['wr']:>5.0f}% {sp3['wr']:>6.0f}% {s9['wr']:>5.0f}% {s18['wr']:>5.0f}%"
        r_pnl= f"{'PnL':10} {fp(s3['pnl']):>6} {fp(sp3['pnl']):>7} {fp(s9['pnl']):>6} {fp(s18['pnl']):>6}"
        r_pf = f"{'PF':10} {s3['pf']:>6.2f} {sp3['pf']:>7.2f} {s9['pf']:>6.2f} {s18['pf']:>6.2f}"

        # ── Category split (last 3 days) ─────────────────────────────────────
        stocks3 = stats([t for t in w3 if t.get("ticker", "").startswith("XYZ-")])
        crypto3 = stats([t for t in w3 if not t.get("ticker", "").startswith("XYZ-")])
        cat_lines = [
            f"  Crypto: {crypto3['n']}x | WR {crypto3['wr']:.0f}% | {fp(crypto3['pnl'])} | PF {crypto3['pf']:.2f}",
            f"  Stocks: {stocks3['n']}x | WR {stocks3['wr']:.0f}% | {fp(stocks3['pnl'])} | PF {stocks3['pf']:.2f}",
        ]

        # ── Close reasons (last 3 days) ──────────────────────────────────────
        reasons3 = Counter(t.get("close_reason", "?") for t in w3)
        reason_lines = []
        for reason, n in reasons3.most_common(7):
            ps  = [_pnl(t) for t in w3 if t.get("close_reason") == reason]
            avg = sum(ps) / len(ps) if ps else 0
            reason_lines.append(f"  {reason}: {n}x (avg {fp(avg)})")

        # ── Direction (last 3 days) ──────────────────────────────────────────
        dir_lines = []
        for act in ("BUY", "SELL"):
            g = stats([t for t in w3 if t.get("action") == act])
            if g["n"]:
                dir_lines.append(f"  {act}: {g['n']}x | WR {g['wr']:.0f}% | {fp(g['pnl'])}")

        # ── Anomaly detection ────────────────────────────────────────────────
        anomalies = []

        # WR trend vs prev period
        if sp3["n"] >= 3 and s3["n"] >= 3:
            delta = s3["wr"] - sp3["wr"]
            if delta >= 10:
                anomalies.append(f"WR verbeterd {sp3['wr']:.0f}% → {s3['wr']:.0f}% (L3d vs prev3d)")
            elif delta <= -10:
                anomalies.append(f"WR verslechterd {sp3['wr']:.0f}% → {s3['wr']:.0f}% (L3d vs prev3d)")

        # PnL swing
        if sp3["n"] >= 3 and s3["n"] >= 3:
            pnl_delta = s3["pnl"] - sp3["pnl"]
            if abs(pnl_delta) >= 10:
                sign = "+" if pnl_delta >= 0 else ""
                anomalies.append(f"PnL swing {sign}${pnl_delta:.2f} vs vorige periode")

        # High SL rate
        sl_n = reasons3.get("STOP_LOSS", 0)
        if s3["n"] > 0 and sl_n / s3["n"] > 0.70:
            anomalies.append(f"Hoge SL-rate {sl_n}/{s3['n']} ({sl_n/s3['n']*100:.0f}%) — entries te vroeg?")

        # Stage=0 SL exits
        stage0_sl = sum(1 for t in w3 if t.get("close_reason") == "STOP_LOSS" and t.get("sl_stage", 0) == 0)
        if sl_n > 0 and stage0_sl / sl_n > 0.80:
            anomalies.append(f"{stage0_sl}/{sl_n} SL-exits op stage=0 — trades bereiken geen BE")

        # Near-zero PnL trades (possible min-notional / fee issue)
        zero_n = sum(1 for t in w3 if abs(_pnl(t)) < 0.05)
        if zero_n >= 3:
            anomalies.append(f"{zero_n} trades met ~$0 PnL — min notional of fee probleem?")

        # Stock vs crypto divergence
        if stocks3["n"] >= 2 and crypto3["n"] >= 2:
            diff = stocks3["wr"] - crypto3["wr"]
            if diff >= 20:
                anomalies.append(f"Stocks ({stocks3['wr']:.0f}% WR) >> Crypto ({crypto3['wr']:.0f}%) — overweeg universe aanpassing")
            elif diff <= -20:
                anomalies.append(f"Crypto ({crypto3['wr']:.0f}% WR) >> Stocks ({stocks3['wr']:.0f}%) — stocks underperformen")

        # Sell outperformance
        sell_s = stats([t for t in w3 if t.get("action") == "SELL"])
        buy_s  = stats([t for t in w3 if t.get("action") == "BUY"])
        if sell_s["n"] >= 3 and buy_s["n"] >= 3 and sell_s["wr"] > buy_s["wr"] + 20:
            anomalies.append(f"SELL ({sell_s['wr']:.0f}% WR) >> BUY ({buy_s['wr']:.0f}%) — bearish regime?")

        # ── Open positions ───────────────────────────────────────────────────
        open_unrealized = sum(_pnl(t) for t in open_t)
        open_flags = []
        for t in open_t:
            held_h = (now_ts - float(t.get("entry_time") or now_ts)) / 3600
            sl_pct = float(t.get("sl_pct") or 0)
            stage  = t.get("sl_stage", 0)
            ticker = t.get("ticker", "?")
            action = t.get("action", "?")
            pv     = _pnl(t)
            flag   = None
            if sl_pct > 5:
                flag = f"wide SL {sl_pct:.1f}%"
            elif stage == 0 and held_h > 48:
                flag = f"stage=0 {held_h:.0f}h"
            if flag:
                open_flags.append(f"  ⚠ {ticker} {action} — {flag} ({fp(pv)})")

        # ── Assemble message ─────────────────────────────────────────────────
        date_str = now.strftime("%d %b %H:%M UTC")
        lines = [
            f"*Agent Trader — P&L Digest [{date_str}]*",
            "",
            "*TREND (gesloten trades)*",
            f"`{hdr}`",
            f"`{r_n}`",
            f"`{r_wr}`",
            f"`{r_pnl}`",
            f"`{r_pf}`",
            "",
            "*CATEGORIE (L3d)*",
        ] + cat_lines + [
            "",
            "*CLOSE REASONS (L3d)*",
        ] + reason_lines + [
            "",
            "*RICHTING (L3d)*",
        ] + dir_lines

        if anomalies:
            lines += ["", "*OPVALLEND*"] + [f"  • {a}" for a in anomalies]

        open_header = f"*OPEN ({len(open_t)}x | unrealized: {fp(open_unrealized)})*"
        lines += ["", open_header]
        lines += open_flags if open_flags else ["  — geen risico-vlaggen"]

        self._sent_alerts[alert_key] = now
        self._send_telegram("\n".join(lines))
        logger.info("SwarmMonitor: P&L digest (trend view) sent via Telegram")

    # ──────────────────────────────────────────
    # Check 13: Health heartbeat (every 4h)
    # ──────────────────────────────────────────

    HEARTBEAT_INTERVAL_SEC = 4 * 3600

    def _build_heartbeat_lines(self, now: datetime) -> list[str]:
        """Build heartbeat message lines. Returns list of strings."""
        lines = [f"🏥 *Swarm Health — {now.strftime('%d %b %H:%M UTC')}*", ""]
        blockers = []

        # Balance & free margin
        try:
            if self.exchange_client:
                bal  = self.exchange_client.get_balance()
                free = self.exchange_client.get_free_margin()
                free_pct = free / bal * 100 if bal > 0 else 0
                lines.append(f"💰 Balance: ${bal:.2f} | Free: ${free:.2f} ({free_pct:.0f}%)")
        except Exception:
            lines.append("💰 Balance: unavailable")

        # Drawdown
        try:
            with open("portfolio_peak.json") as f:
                peak_data = json.load(f)
            peak_eq = float(peak_data.get("peak_equity", 0))
            if peak_eq > 0 and self.exchange_client:
                bal = self.exchange_client.get_balance()
                # Include capital in yield protocols (Aave, Morpho, etc.) so treasury
                # redeployments don't show as false drawdowns — mirrors risk_manager logic.
                try:
                    from utils.treasury_executor import get_total_yield_balance, _TREASURY_WALLET
                    bal += get_total_yield_balance(_TREASURY_WALLET)
                except Exception:
                    pass
                dd  = (peak_eq - bal) / peak_eq * 100
                dd_icon = "✅" if dd < 10 else ("⚠️" if dd < 15 else "🔴")
                lines.append(f"{dd_icon} Drawdown: {dd:.1f}% (peak ${peak_eq:.0f}, limit 15%)")
                if dd >= 15:
                    blockers.append(f"Drawdown {dd:.1f}% ≥ 15% — TRADES GEBLOKKEERD")
        except Exception:
            pass

        # Circuit breaker
        try:
            with open("cb_state.json") as f:
                cb = json.load(f)
            if cb.get("paused"):
                lines.append(f"🔴 CircuitBreaker: GEPAUZEERD ({cb.get('reason', '?')})")
                blockers.append(f"CircuitBreaker gepauzeerd: {cb.get('reason', '?')}")
            else:
                lines.append("✅ CircuitBreaker: open")
        except Exception:
            lines.append("✅ CircuitBreaker: open")

        # Open trades & recent WR
        try:
            with open("trade_log.json") as f:
                raw = json.load(f)
            trades = list(raw.values()) if isinstance(raw, dict) else raw
            open_t   = [t for t in trades if t.get("status") == "OPEN" and not t.get("harvest")]
            closed   = [
                t for t in trades
                if t.get("status") == "CLOSED"
                and t.get("pnl") is not None
                and not str(t.get("id", "")).startswith("RECOVERED_")
                and not t.get("harvest")
            ]
            cutoff   = now.timestamp() - 30 * 86400
            closed30 = [t for t in closed if float(t.get("entry_time") or 0) >= cutoff]
            wr = (
                sum(1 for t in closed30 if (t.get("pnl") or 0) > 0) / len(closed30) * 100
                if closed30 else 0
            )
            lines.append(f"📊 Open trades: {len(open_t)} | WR (30d): {wr:.0f}% ({len(closed30)} trades)")
        except Exception:
            lines.append("📊 Trades: unavailable")

        # Auto-params
        try:
            with open("config/auto_params.json") as f:
                params = json.load(f)
            score_t   = float(params.get("score_threshold", 0))
            prefilter = float(params.get("tech_prefilter_min", 0))
            lines.append(f"⚙️ Auto-params: score={score_t:.2f} | prefilter={prefilter:.2f}")
            if score_t >= 0.47:
                blockers.append(f"score_threshold={score_t:.2f} ≥ 0.47 — dreigt deadlock")
        except Exception:
            pass

        # Treasury yield + wallet
        try:
            with open("treasury_state.json") as f:
                ts = json.load(f)
            total_yield   = float(ts.get("total_yield", 0))
            treasury_usdc = float(ts.get("treasury_wallet_usdc", 0))
            ts_age_h = (now.timestamp() - datetime.fromisoformat(ts["timestamp"].replace("Z", "+00:00")).timestamp()) / 3600
            stale = " ⚠️ STALE" if ts_age_h > 3 else ""
            lines.append(f"🏦 Yield: ${total_yield:.0f} | Treasury wallet: ${treasury_usdc:.0f}{stale}")
        except Exception:
            lines.append("🏦 Treasury: unavailable")

        # Pending/in-flight proposals
        try:
            with open("treasury_proposals.json") as f:
                proposals = json.load(f)
            pending  = [p for p in proposals if p.get("status") == "PENDING"]
            inflight = [p for p in proposals if p.get("status") in {
                "APPROVED", "SWITCHING", "WITHDRAWING", "BRIDGED", "REBALANCING"
            }]
            parts = []
            if pending:
                parts.append(f"{len(pending)} PENDING")
            if inflight:
                parts.append(f"{len(inflight)} in-flight")
            if parts:
                lines.append(f"📋 Proposals: {', '.join(parts)}")
                if pending:
                    pids = ", ".join(p.get("id", "?") for p in pending[:3])
                    lines.append(f"   `/approve {pending[0].get('id','?')}` om te activeren")
        except Exception:
            pass

        # Blockers summary
        lines.append("")
        if blockers:
            lines.append("⛔ *BLOCKERS:*")
            for b in blockers:
                lines.append(f"  • {b}")
        else:
            lines.append("✅ Geen actieve blockers")

        return lines

    def _check_heartbeat(self, now: datetime):
        """Send health heartbeat every 4 hours."""
        if not _telegram_token() or not _telegram_chat_id():
            return
        alert_key = "health_heartbeat"
        last_sent = self._sent_alerts.get(alert_key)
        if last_sent and (now - last_sent).total_seconds() < self.HEARTBEAT_INTERVAL_SEC:
            return
        self._sent_alerts[alert_key] = now
        self._send_telegram("\n".join(self._build_heartbeat_lines(now)))
        logger.info("SwarmMonitor: health heartbeat sent")

    # ──────────────────────────────────────────
    # Check 14: Stuck treasury proposals
    # ──────────────────────────────────────────

    STUCK_PENDING_H  = 24
    STUCK_APPROVED_H = 6
    STUCK_COOLDOWN_SEC = 6 * 3600

    def _check_stuck_proposals(self, now: datetime):
        """Alert on proposals stuck in PENDING >24h or in-flight >6h without advancing."""
        try:
            with open("treasury_proposals.json") as f:
                proposals = json.load(f)
        except Exception:
            return

        stuck = []
        for p in proposals:
            status = p.get("status", "")
            created = p.get("created_at", "")
            if not created:
                continue
            try:
                age_h = (
                    now.timestamp()
                    - datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
                ) / 3600
            except Exception:
                continue

            if status == "PENDING" and age_h > self.STUCK_PENDING_H:
                stuck.append((p.get("id", "?"), status, age_h, p.get("title", "")))
            elif status in {"APPROVED", "SWITCHING", "WITHDRAWING", "BRIDGED", "REBALANCING"} and age_h > self.STUCK_APPROVED_H:
                stuck.append((p.get("id", "?"), status, age_h, p.get("title", "")))

        if not stuck:
            return

        alert_key = "stuck_proposals"
        last_sent = self._sent_alerts.get(alert_key)
        if last_sent and (now - last_sent).total_seconds() < self.STUCK_COOLDOWN_SEC:
            return

        self._sent_alerts[alert_key] = now
        lines = ["⏰ *Treasury: Vastgelopen voorstellen*", ""]
        for pid, status, age_h, title in stuck:
            lines.append(f"• `{pid}` [{status}] {age_h:.0f}h — {title[:60]}")
            if status == "PENDING":
                lines.append(f"  → `/approve {pid}` om te activeren")
        if _telegram_token() and _telegram_chat_id():
            self._send_telegram("\n".join(lines))
        logger.warning(f"SwarmMonitor: {len(stuck)} stuck proposal(s)")

    # ──────────────────────────────────────────
    # Check 15: MONITOR deadlock per ticker
    # ──────────────────────────────────────────

    MONITOR_DEADLOCK_THRESHOLD = 50   # consecutive MONITOR cycles before alerting
    MONITOR_DEADLOCK_COOLDOWN_SEC = 6 * 3600

    def _check_monitor_deadlock(self, now: datetime):
        """Alert when a ticker has been stuck in MONITOR for too many consecutive cycles."""
        try:
            with open("ticker_state.json") as f:
                states = json.load(f)
        except Exception:
            return

        deadlocked = []
        for setup_id, state in states.items():
            if setup_id == "__ticker_cooldowns__" or not isinstance(state, dict):
                continue
            count = state.get("consecutive_monitor_count", 0)
            if count >= self.MONITOR_DEADLOCK_THRESHOLD:
                deadlocked.append((setup_id, count, state.get("last_score", 0.0)))

        if not deadlocked:
            return

        alert_key = "monitor_deadlock"
        last_sent = self._sent_alerts.get(alert_key)
        if last_sent and (now - last_sent).total_seconds() < self.MONITOR_DEADLOCK_COOLDOWN_SEC:
            return

        self._sent_alerts[alert_key] = now
        lines = ["⏸ *MONITOR Deadlock gedetecteerd*", ""]
        for sid, cnt, score in deadlocked[:5]:
            lines.append(f"• `{sid}` — {cnt} cycles, score={score:.2f}")
        if len(deadlocked) > 5:
            lines.append(f"  … en {len(deadlocked) - 5} meer")
        lines.append("\nAuto-promote wordt na 50 cycles getriggerd in main.py.")
        if _telegram_token() and _telegram_chat_id():
            self._send_telegram("\n".join(lines))
        logger.warning(f"SwarmMonitor: {len(deadlocked)} ticker(s) in MONITOR deadlock")

    # ──────────────────────────────────────────
    # Check 16: XYZ zero-execute detection
    # ──────────────────────────────────────────

    XYZ_ZERO_EXECUTE_WINDOW = 200  # decisions to look back
    XYZ_ZERO_EXECUTE_COOLDOWN_SEC = 12 * 3600  # max once per 12h

    def _check_xyz_zero_execute(self, now: datetime):
        """Alert when XYZ stocks have had 0 executes in the last N decisions.
        Only checks decisions from within US market hours (14:30–21:00 UTC Mon–Fri)
        to avoid false positives when the market is closed."""
        # Skip check when currently outside US market hours
        is_market_hours = (now.weekday() < 5 and 14 <= now.hour <= 20)
        if not is_market_hours:
            return

        try:
            with open("decision_history.json") as f:
                history = json.load(f)
        except Exception:
            return

        if not isinstance(history, list):
            return

        recent = history[-self.XYZ_ZERO_EXECUTE_WINDOW:]
        # Only include XYZ decisions with non-zero scores (market-hours analysis produces
        # scores > 0; closed-market NO_GO decisions have score=0.0)
        xyz_decisions = [
            d for d in recent
            if d.get("ticker", "").startswith("XYZ-") and abs(d.get("score", 0.0)) > 0.01
        ]

        if len(xyz_decisions) < 20:
            return  # Not enough market-hours data

        executes = sum(1 for d in xyz_decisions if d.get("next_step") == "BUILD_CASE")
        if executes > 0:
            return

        alert_key = "xyz_zero_execute"
        last_sent = self._sent_alerts.get(alert_key)
        if last_sent and (now - last_sent).total_seconds() < self.XYZ_ZERO_EXECUTE_COOLDOWN_SEC:
            return

        self._sent_alerts[alert_key] = now
        msg = (
            f"📉 *XYZ Stocks: 0 executes in last {len(xyz_decisions)} decisions*\n"
            f"Bekijk de SA-gate, market-hours skip en MONITOR deadlock in ticker_state.json."
        )
        if _telegram_token() and _telegram_chat_id():
            self._send_telegram(msg)
        logger.warning(f"SwarmMonitor: XYZ stocks — 0 executes in last {len(xyz_decisions)} decisions")

    # ──────────────────────────────────────────
    # Check 17: Treasury state staleness
    # ──────────────────────────────────────────

    TREASURY_STALE_HOURS = 3.0
    TREASURY_STALE_COOLDOWN_SEC = 4 * 3600

    def _check_treasury_staleness(self, now: datetime):
        """Alert when treasury_state.json hasn't been refreshed in TREASURY_STALE_HOURS."""
        try:
            with open("treasury_state.json") as f:
                state = json.load(f)
            ts_str = state.get("timestamp")
            if not ts_str:
                return
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_h = (now - ts).total_seconds() / 3600
        except Exception:
            return

        if age_h < self.TREASURY_STALE_HOURS:
            return

        alert_key = "treasury_stale"
        last_sent = self._sent_alerts.get(alert_key)
        if last_sent and (now - last_sent).total_seconds() < self.TREASURY_STALE_COOLDOWN_SEC:
            return

        self._sent_alerts[alert_key] = now
        msg = (
            f"⚠️ *Treasury state {age_h:.1f}h oud*\n"
            f"TreasuryAgent.run() vuurt bij cycle_count % 60 == 0. "
            f"Frequent deploys kunnen dit blokkeren."
        )
        if _telegram_token() and _telegram_chat_id():
            self._send_telegram(msg)
        logger.warning(f"SwarmMonitor: treasury_state.json is {age_h:.1f}h stale")

    # ──────────────────────────────────────────
    # Telegram command polling
    # ──────────────────────────────────────────

    _TELEGRAM_OFFSET_FILE = "monitor_telegram_offset.json"

    def _start_telegram_poll_thread(self):
        """Start background thread to receive Telegram commands via getUpdates."""
        if not _telegram_token() or not _telegram_chat_id():
            logger.info("SwarmMonitor: Telegram not configured — command polling disabled")
            return
        t = threading.Thread(target=self._telegram_poll_loop, daemon=True, name="TelegramPoll")
        t.start()
        logger.info("SwarmMonitor: Telegram command polling started")

    def _telegram_poll_loop(self):
        """Poll getUpdates every 30s for incoming commands."""
        offset = 0
        try:
            with open(self._TELEGRAM_OFFSET_FILE) as f:
                offset = json.load(f).get("offset", 0)
        except Exception:
            pass

        while self._running:
            try:
                updates = self._get_telegram_updates(offset)
                for upd in updates:
                    offset = upd["update_id"] + 1
                    self._dispatch_telegram_command(upd)
                try:
                    with open(self._TELEGRAM_OFFSET_FILE, "w") as f:
                        json.dump({"offset": offset}, f)
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"TelegramPoll: {e}")
            time.sleep(30)

    def _get_telegram_updates(self, offset: int) -> list:
        import urllib.request as _req, urllib.parse as _parse
        params = _parse.urlencode({
            "offset": offset, "timeout": 5,
            "allowed_updates": '["message"]',
        })
        url = f"https://api.telegram.org/bot{_telegram_token()}/getUpdates?{params}"
        with _req.urlopen(_req.Request(url), timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get("result", []) if data.get("ok") else []

    def _dispatch_telegram_command(self, update: dict):
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        # Security: only from the configured chat
        if str(msg.get("chat", {}).get("id", "")) != str(_telegram_chat_id()):
            return
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return
        parts = text.split()
        cmd   = parts[0].lower().split("@")[0]
        args  = parts[1:]
        logger.info(f"TelegramPoll: command {cmd} args={args}")
        if cmd == "/approve" and args:
            self._cmd_approve(args[0])
        elif cmd == "/reject" and args:
            self._cmd_reject(args[0])
        elif cmd == "/proposals":
            self._cmd_proposals()
        elif cmd == "/status":
            self._cmd_status()
        elif cmd == "/help":
            self._cmd_help()
        else:
            self._send_telegram(f"Onbekend commando: `{cmd}`\nGebruik /help voor een overzicht.")

    def _cmd_approve(self, proposal_id: str):
        try:
            with open("treasury_proposals.json") as f:
                proposals = json.load(f)
        except Exception as e:
            self._send_telegram(f"❌ Kan proposals niet laden: {e}")
            return
        for p in proposals:
            if p.get("id", "").upper() == proposal_id.upper():
                if p.get("status") != "PENDING":
                    self._send_telegram(
                        f"⚠️ `{proposal_id}` heeft status `{p.get('status')}` — "
                        f"alleen PENDING kan worden goedgekeurd."
                    )
                    return
                p["status"] = "APPROVED"
                p["approved_at"] = datetime.utcnow().isoformat()
                p["approved_via"] = "telegram"
                try:
                    with open("treasury_proposals.json", "w") as f:
                        json.dump(proposals, f, indent=2)
                    self._send_telegram(
                        f"✅ *`{proposal_id}` goedgekeurd*\n"
                        f"{p.get('title', '')}\n"
                        f"De executor pikt dit op binnen 5 min."
                    )
                    logger.info(f"TelegramPoll: {proposal_id} approved via Telegram")
                except Exception as e:
                    self._send_telegram(f"❌ Opslaan mislukt: {e}")
                return
        self._send_telegram(f"❌ Voorstel `{proposal_id}` niet gevonden.")

    def _cmd_reject(self, proposal_id: str):
        try:
            with open("treasury_proposals.json") as f:
                proposals = json.load(f)
        except Exception as e:
            self._send_telegram(f"❌ Kan proposals niet laden: {e}")
            return
        for p in proposals:
            if p.get("id", "").upper() == proposal_id.upper():
                if p.get("status") not in {"PENDING", "APPROVED"}:
                    self._send_telegram(
                        f"⚠️ `{proposal_id}` heeft status `{p.get('status')}` — kan niet worden afgewezen."
                    )
                    return
                p["status"] = "REJECTED"
                p["rejected_at"] = datetime.utcnow().isoformat()
                p["rejected_via"] = "telegram"
                try:
                    with open("treasury_proposals.json", "w") as f:
                        json.dump(proposals, f, indent=2)
                    self._send_telegram(f"🚫 `{proposal_id}` afgewezen.")
                    logger.info(f"TelegramPoll: {proposal_id} rejected via Telegram")
                except Exception as e:
                    self._send_telegram(f"❌ Opslaan mislukt: {e}")
                return
        self._send_telegram(f"❌ Voorstel `{proposal_id}` niet gevonden.")

    def _cmd_proposals(self):
        try:
            with open("treasury_proposals.json") as f:
                proposals = json.load(f)
        except Exception as e:
            self._send_telegram(f"❌ Kan proposals niet laden: {e}")
            return
        terminal = {"DEPLOYED", "COMPLETED", "REJECTED", "FAILED"}
        active = [p for p in proposals if p.get("status") not in terminal]
        if not active:
            self._send_telegram("📋 Geen actieve treasury voorstellen.")
            return
        lines = ["📋 *Actieve treasury voorstellen*", ""]
        for p in active[-10:]:
            status = p.get("status", "?")
            pid    = p.get("id", "?")
            title  = (p.get("title") or "")[:60]
            icon   = "⏳" if status == "PENDING" else "▶️"
            lines.append(f"{icon} `{pid}` [{status}]")
            lines.append(f"   {title}")
            if status == "PENDING":
                lines.append(f"   → `/approve {pid}` of `/reject {pid}`")
            lines.append("")
        self._send_telegram("\n".join(lines))

    def _cmd_status(self):
        now = datetime.now(timezone.utc)
        self._send_telegram("\n".join(self._build_heartbeat_lines(now)))

    def _cmd_help(self):
        self._send_telegram(
            "*Swarm Commands*\n\n"
            "/proposals — toon actieve treasury voorstellen\n"
            "/approve `<ID>` — keur een PENDING voorstel goed\n"
            "/reject `<ID>` — wijs een PENDING/APPROVED voorstel af\n"
            "/status — stuur een health snapshot\n"
            "/help — dit menu"
        )

    # ──────────────────────────────────────────
    # Alert state persistence (survive restarts)
    # ──────────────────────────────────────────

    def _load_alert_state(self):
        """Load persisted _sent_alerts from disk so cooldowns survive container restarts."""
        try:
            if not os.path.exists(self.ALERT_STATE_FILE):
                return
            with open(self.ALERT_STATE_FILE, "r") as f:
                raw = json.load(f)
            loaded = 0
            for k, v in raw.items():
                try:
                    dt = datetime.fromisoformat(v)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    self._sent_alerts[k] = dt
                    loaded += 1
                except Exception:
                    pass
            logger.info(f"SwarmMonitor: loaded {loaded} alert states from disk")
        except Exception as e:
            logger.warning(f"SwarmMonitor: could not load alert state: {e}")

    def _save_alert_state(self):
        """Persist _sent_alerts to disk so cooldowns survive container restarts."""
        try:
            serializable = {
                k: v.isoformat() if isinstance(v, datetime) else str(v)
                for k, v in self._sent_alerts.items()
            }
            with open(self.ALERT_STATE_FILE, "w") as f:
                json.dump(serializable, f, indent=2)
        except Exception as e:
            logger.warning(f"SwarmMonitor: could not save alert state: {e}")

    # ──────────────────────────────────────────
    # Supabase persistence
    # ──────────────────────────────────────────

    def _report_to_supabase(self, status: str, meta: Dict, error_summary: Optional[str]):
        """Write SwarmMonitor's own health record to Supabase."""
        if not self.db:
            return
        try:
            self.db.update_swarm_health(
                agent_name="SwarmMonitor",
                status=status,
                task=meta.get("current_task", "Monitoring"),
                reasoning=meta.get("last_activity", ""),
                meta=meta,
                cycle_count=self._check_count,
                last_error=error_summary,
            )
        except Exception as e:
            logger.warning(f"SwarmMonitor: failed to persist to Supabase: {e}")

    # ──────────────────────────────────────────
    # Telegram alerts (with deduplication)
    # ──────────────────────────────────────────

    def _maybe_send_telegram_alert(self, findings: List[Dict]):
        """Send a Telegram alert for new/recurring issues, respecting cooldown."""
        if not _telegram_token() or not _telegram_chat_id():
            return

        now = datetime.now(timezone.utc)

        # Build one message per unique alert_key
        new_findings = []
        for f in findings:
            key = f"{f['type']}:{f.get('agent', '')}"
            last_sent = self._sent_alerts.get(key)
            if last_sent is None or (now - last_sent).total_seconds() > ALERT_COOLDOWN_SEC:
                new_findings.append(f)
                self._sent_alerts[key] = now

        if not new_findings:
            return  # All already alerted recently

        # Build message
        lines = ["🚨 *Swarm Monitor Alert*", f"_Detected at {now.strftime('%H:%M UTC')}_", ""]
        for f in new_findings:
            sev_emoji = "🔴" if f["severity"] == "HIGH" else "🟡"
            lines.append(f"{sev_emoji} *{f['type']}* — `{f.get('agent', '?')}`")
            lines.append(f"   {f['message'][:200]}")
            if "detail" in f:
                lines.append(f"```\n{f['detail'][:1500]}\n```")
            lines.append("")

        message = "\n".join(lines)
        self._send_telegram(message)

    def _send_telegram(self, text: str):
        """Send message via Telegram Bot API."""
        try:
            import urllib.request
            import urllib.parse
            url = f"https://api.telegram.org/bot{_telegram_token()}/sendMessage"
            params = urllib.parse.urlencode({
                "chat_id": _telegram_chat_id(),
                "text": text,
                "parse_mode": "Markdown",
            }).encode()
            req = urllib.request.Request(url, data=params, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.info(f"✅ Telegram alert sent (status {resp.status})")
        except Exception as e:
            logger.warning(f"Failed to send Telegram alert: {e}")


# ──────────────────────────────────────────────
# Standalone test runner
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv(".env.adk")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    from utils.db_client import DatabaseClient

    db = DatabaseClient()
    monitor = SwarmMonitor(db_client=db)

    if "--test" in sys.argv:
        print("\n=== SwarmMonitor Test Run ===\n")

        # Test Telegram
        if _telegram_token() and _telegram_chat_id():
            print("Sending Telegram test message...")
            monitor._send_telegram("🔧 SwarmMonitor test message — ignore this")
            print("✅ Telegram message sent (check your chat)")
        else:
            print("⚠️ Telegram not configured (set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)")

        # Test check
        print("\nRunning health check...")
        results = monitor.run_once()
        print(f"\nResult: {'✅ All OK' if results['ok'] else '⚠️ Issues detected'}")
        for iss in results.get("issues", []):
            sev = iss.get("severity", "?")
            icon = "🔴" if sev == "HIGH" else "🟡"
            print(f"  {icon} [{iss['type']}] {iss.get('agent','')} — {iss['message']}")

        if not results.get("issues"):
            print("  No issues found.")
    else:
        # Run continuously
        print("Starting SwarmMonitor (Ctrl+C to stop)...")
        monitor.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            monitor.stop()
