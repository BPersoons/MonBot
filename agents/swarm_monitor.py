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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
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

    def __init__(self, db_client=None):
        self.db = db_client
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # Alert deduplication: maps alert_key -> last_sent_timestamp
        self._sent_alerts: Dict[str, datetime] = {}
        # Snapshot of previous cycle counts for freeze detection
        self._prev_cycle_counts: Dict[str, int] = {}
        self._prev_check_time: Optional[datetime] = None
        self._check_count = 0
        # Pipeline output snapshots for stale detection
        self._prev_output_snapshots: Dict[str, str] = {}

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

    def _run_checks(self) -> Dict:
        """Run all checks and return consolidated findings."""
        self._check_count += 1
        now = datetime.now(timezone.utc)
        findings = []  # list of issue dicts
        all_ok = True

        logger.info(f"🔍 SwarmMonitor: running check #{self._check_count}")

        # ── Check 1: Supabase swarm_health ──────────
        db_issues = self._check_supabase_health(now)
        findings.extend(db_issues)
        if db_issues:
            all_ok = False

        # ── Check 2: Docker log errors ───────────────
        log_issues = self._check_docker_logs()
        findings.extend(log_issues)
        if log_issues:
            all_ok = False

        # ── Check 3: Pipeline output analysis ────────
        pipeline_issues = self._check_pipeline_output(now)
        findings.extend(pipeline_issues)
        if pipeline_issues:
            all_ok = False
            
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
                error_msg = agent.get("last_error", "No details")
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

            # Frozen cycle count (only detectable on 2nd+ check)
            if self._prev_check_time and agent_name in self._prev_cycle_counts:
                prev_count = self._prev_cycle_counts[agent_name]
                curr_count = agent.get("cycle_count", 0)
                elapsed_min = (now - self._prev_check_time).total_seconds() / 60
                # Only flag if agent is supposed to cycle and hasn't for > 2 intervals
                if curr_count == prev_count and elapsed_min > (CHECK_INTERVAL_SEC / 60 * 2):
                    issues.append({
                        "type": "CYCLE_FROZEN",
                        "severity": "MEDIUM",
                        "agent": agent_name,
                        "message": f"Cycle count frozen at {curr_count} for {elapsed_min:.0f} min",
                        "last_pulse": pulse_raw,
                    })

            # Update snapshot
            self._prev_cycle_counts[agent_name] = agent.get("cycle_count", 0)

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
            cycle = agent.get("cycle_count", 0)

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
            
            scout_cycle = scout_agent.get("cycle_count", 0) if isinstance(scout_agent, dict) else 0
            pl_cycle = pl_agent.get("cycle_count", 0) if isinstance(pl_agent, dict) else 0
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
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
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
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            params = urllib.parse.urlencode({
                "chat_id": TELEGRAM_CHAT_ID,
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
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
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
