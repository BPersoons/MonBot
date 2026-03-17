import logging
import json
import os
from datetime import datetime
from typing import List, Dict
from utils.db_client import DatabaseClient

# Configure logging
logger = logging.getLogger("ProductOwner")

class ProductOwner:
    """
    The CPO (Chief Product Officer) Agent.
    Role: Proactively identifies system improvements and creates tasks in the Backlog.
    """
    
    def __init__(self):
        self.db = DatabaseClient()
        self.trade_log_path = "trade_log.json"
        self.heartbeat_log_path = "heartbeat.log"
        self.state_file = "cpo_state.json"
        
        try:
            from utils.llm_client import LLMClient
            self.llm = LLMClient(model_name="gemini-3.1-flash-lite-preview")
        except Exception as e:
            logger.critical(f"Failed to initialize LLMClient for CPO: {e}")
            self.llm = None
            
    def _load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {"last_report_time": 0}
        
    def _save_state(self, state):
        with open(self.state_file, 'w') as f:
            json.dump(state, f)

    def run_analysis_cycle(self, execution_agent=None):
        """
        Main execution method.
        1. Analyzes Logs
        2. Identifies Patterns
        3. Creates Backlog Items
        4. Sends Health Heartbeat (Every 4h)
        5. Generates Executive Summary (Every 1h)
        """
        logger.info("CPO: Starting analysis cycle...")
        
        # 1. Analyze Trade Log & Heartbeat
        issues = self._analyze_system_health()
        
        # 2. Process Issues into Tasks
        new_tasks = 0
        for issue in issues:
            if self._create_backlog_task(issue):
                new_tasks += 1
                
        logger.info(f"CPO: Analysis complete. Created {new_tasks} new backlog tasks.")
        
        # 3. Health Heartbeat (Every 4 Hours)
        self._check_send_heartbeat(execution_agent)
        
        # 4. Executive Summary (Every 1 Hour)
        self._check_executive_summary()
        
        return new_tasks

    def _check_executive_summary(self):
        """Generates a strategic summary every hour."""
        state = self._load_state()
        last_summary = state.get('last_summary_time', 0)
        current_time = datetime.now().timestamp()
        
        # Once per day = 86400 seconds
        if current_time - last_summary > 86400:
             logger.info("CPO: Generating Executive Summary...")
             if self.generate_executive_summary():
                 state['last_summary_time'] = current_time
                 self._save_state(state)

    def generate_executive_summary(self) -> bool:
        """
        Writes a high-level strategic summary to the backlog.
        """
        prompt = """
        You are the Chief Product Officer. 
        Write a 1-sentence 'State of the Market' update.
        Focus on: Volatility, Market Structure (Trending/Ranging), and Risk Appetite.
        Style: Strategic, concise, helping the Founder understand WHY we are (or aren't) trading.
        Examples:
        - "Market lateral with low volume; agents in conservative mode to preserve capital."
        - "High volatility detected in SOL ecosystem; Scout aggressively hunting breakouts."
        - "BTC dominance rising; causing altcoin bleed, reducing exposure."
        """
        
        try:
            if not self.llm: return False
            summary = self.llm.analyze_text(prompt, agent_name="ProductOwner").strip().replace('"', '')
            
            task_data = {
                "title": "Executive Summary",
                "description": summary,
                "priority": "INFO",
                "category": "EXECUTIVE_SUMMARY"
            }
            return self._create_backlog_task(task_data, allow_duplicates=True)
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return False

    def _check_send_heartbeat(self, execution_agent):
        """
        Checks if 4 hours have passed and logs status report.
        """
        state = self._load_state()
        last_report = state.get('last_report_time', 0)
        current_time = datetime.now().timestamp()
        
        # 4 Hours = 14400 seconds
        if current_time - last_report > 14400:
             logger.info("CPO: sending 4-hour System Status Report...")
             if self._send_system_status(execution_agent):
                 state['last_report_time'] = current_time
                 self._save_state(state)

    # ... (omitted _send_system_status and _analyze_system_health unchanged) ...

    def _create_backlog_task(self, task_data: Dict, allow_duplicates: bool = False) -> bool:
        """Creates a task in Supabase system_backlog."""
        if not self.db.is_available():
            logger.warning("Database unavailable. Cannot create backlog task.")
            return False
            
        try:
            # Check for duplicates (Simple check by title) if not allowed
            if not allow_duplicates:
                existing = self.db.client.table("system_backlog").select("id").eq("title", task_data['title']).eq("status", "NEW").execute()
                if existing.data and len(existing.data) > 0:
                    logger.info(f"Task '{task_data['title']}' already exists in backlog.")
                    return False
                
            # Insert new task
            record = {
                "title": task_data['title'],
                "description": task_data['description'],
                "priority": task_data['priority'],
                "status": "NEW",
                "category": task_data.get("category", "FEATURE"), # New field
                "created_at": datetime.now().isoformat()
            }
            
            self.db.client.table("system_backlog").insert(record).execute()
            logger.info(f"✅ CPO Created Task: {task_data['title']}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create backlog task: {e}")
            return False

    def _send_system_status(self, execution_agent):
        """
        Gathers stats and logs system status.
        """
        # A. Wallet Balance
        balance = 0.0
        if execution_agent:
            balance = execution_agent.get_balance()
            
        # B. Approved vs Executed
        approved_count = 0
        executed_count = 0
        
        if os.path.exists(self.trade_log_path):
            try:
                with open(self.trade_log_path, 'r') as f:
                    trades = json.load(f)
                    approved_count = len([t for t in trades if t.get('status') in ['OPEN', 'CLOSED', 'APPROVED']])
                    executed_count = len([t for t in trades if t.get('status') in ['OPEN', 'CLOSED']])
            except:
                pass

        logger.info(f"✅ CPO Status: Balance=${balance:.2f}, Approved={approved_count}, Executed={executed_count}")
        return True

    def _analyze_system_health(self) -> List[Dict]:
        """
        Uses LLM to analyze system health based on Supabase data.
        Reads from swarm_health (agent statuses) and system_backlog (previous ideas).
        """
        import re

        issues = []

        # ── 1. Gather Data from Supabase ──────────────────────
        agent_health = []
        recent_backlog = []
        try:
            agent_health = self.db.get_swarm_health() or []
            recent_backlog = self.db.get_system_backlog(limit=20) or []
        except Exception as e:
            logger.error(f"CPO: Failed to read Supabase data: {e}")
            return []

        # Hard cap: if there are already many unresolved PENDING items, skip analysis
        pending_count = sum(1 for item in recent_backlog if isinstance(item, dict) and item.get('status') == 'PENDING')
        if pending_count >= 15:
            logger.info(f"CPO: Skipping analysis — {pending_count} PENDING items already in backlog (cap=15). Resolve existing items first.")
            return []

        if not agent_health:
            logger.warning("CPO: No agent health data available, skipping analysis")
            return []

        # ── 2. Build a readable summary for the LLM ──────────
        agent_summaries = []
        for a in agent_health:
            if not isinstance(a, dict):
                continue
            name = a.get("agent_name", "?")
            status = a.get("status", "?")
            cycle = a.get("cycle_count", 0)
            error = a.get("last_error", "")
            pulse = a.get("last_pulse", "")
            meta = a.get("metadata", {})
            if not isinstance(meta, dict):
                meta = {}

            summary = f"- {name}: status={status}, cycles={cycle}, last_pulse={pulse}"
            if error:
                summary += f", last_error={error[:150]}"

            # Extract key output metrics
            if name in ("Scout", "ResearchAgent"):
                scanned = meta.get("tickers_scanned", meta.get("universe_size", 0))
                approved = meta.get("approved_count", meta.get("proposals_count", 0))
                summary += f", tickers_scanned={scanned}, approved={approved}"
            elif name == "ProjectLead":
                decisions = meta.get("latest_decisions", [])
                if isinstance(decisions, list):
                    buy_count = sum(1 for d in decisions if isinstance(d, dict) and str(d.get("decision","")).upper() in ("BUY","LONG"))
                    summary += f", decisions={len(decisions)}, buys={buy_count}"
                else:
                    summary += ", decisions=unknown_format"
            elif name == "ProductOwner":
                last_activity = meta.get("last_activity", "")
                summary += f", last_activity={last_activity}"

            agent_summaries.append(summary)

        agents_text = "\n".join(agent_summaries) if agent_summaries else "No agent data available"

        # Previous CPO ideas (to avoid duplicates)
        prev_ideas = []
        for item in recent_backlog[:5]:
            if isinstance(item, dict):
                prev_ideas.append(f"- {item.get('title', '?')} ({item.get('created_at', '?')[:10]})")
        prev_ideas_text = "\n".join(prev_ideas) if prev_ideas else "None"

        # ── 3. Build LLM Prompt ───────────────────────────────
        prompt = f"""
    You are the Chief Product Officer (CPO) of an autonomous crypto trading system.

    CURRENT SYSTEM STATUS:
    {agents_text}

    PREVIOUS CPO IDEAS (avoid duplicates):
    {prev_ideas_text}

    TASK:
    Analyze the system health and performance. Look for:
    1. Agents that are stuck, erroring, or not producing output.
    2. Pipeline bottlenecks (e.g., Scout finds opportunities but ProjectLead doesn't act).
    3. Low trading activity — if no trades in days, suggest why and what to change.
    4. Configuration improvements (scan range, thresholds, risk parameters).
    5. Strategic opportunities (new markets, better timing, improved signals).

    IMPORTANT: Do NOT repeat ideas already in the "PREVIOUS CPO IDEAS" list.

    OUTPUT:
    Generate a list of actionable 'Backlog Items' to improve the system.
    Rank the items based on their ICE score (Impact + Confidence + Ease) descending, so the most valuable ideas are first.
    Return strictly JSON format:
    [
        {{
            "title": "Short Title",
            "description": "Detailed explanation of the finding and recommended action.",
            "impact": 8,
            "confidence": 7,
            "ease": 6,
            "mission_prompt": "Determine the prompt string the user should copy/paste to hand this exact task over to their AI Agent (Antigravity).",
            "priority": "HIGH" | "MID" | "LOW"
        }}
    ]

    If the system is perfectly healthy with no improvements needed, return [].
    But if the system has been idle (no trades, low activity), ALWAYS suggest at least one improvement.
    """

        try:
            if not self.llm:
                logger.warning("CPO: LLM not available, skipping analysis")
                return []

            response = self.llm.analyze_text(prompt, agent_name="ProductOwner")

            # Clean JSON from response
            text = response.strip()
            if "```json" in text:
                match = re.search(r"```json(.*?)```", text, re.DOTALL)
                if match: text = match.group(1).strip()
            elif "```" in text:
                match = re.search(r"```(.*?)```", text, re.DOTALL)
                if match: text = match.group(1).strip()

            issues = json.loads(text)
            logger.info(f"CPO: LLM analysis returned {len(issues)} improvement ideas")

        except Exception as e:
            logger.error(f"CPO AI Analysis failed: {e}")

        return issues

    def _is_duplicate_topic(self, new_title: str) -> bool:
        """
        Checks if an existing PENDING backlog item covers the same topic via keyword overlap.
        Returns True (= skip) if >= 2 significant keywords match an existing title.
        """
        try:
            existing = self.db.client.table("system_backlog") \
                .select("title") \
                .eq("status", "PENDING") \
                .limit(30) \
                .execute()
            if not existing.data:
                return False

            # Extract significant keywords (>4 chars, skip stop words)
            stop_words = {"and", "the", "for", "with", "that", "this", "from", "into",
                          "its", "not", "are", "has", "have", "been", "when", "than",
                          "more", "also", "will", "was", "our", "your", "their"}
            new_words = {w.lower() for w in new_title.split() if len(w) > 4 and w.lower() not in stop_words}

            for item in existing.data:
                existing_title = item.get("title", "")
                existing_words = {w.lower() for w in existing_title.split() if len(w) > 4 and w.lower() not in stop_words}
                overlap = new_words & existing_words
                if len(overlap) >= 2:
                    logger.info(f"CPO: Skipping '{new_title}' — topic overlap ({overlap}) with existing: '{existing_title}'")
                    return True
        except Exception as e:
            logger.warning(f"CPO: Dedup check failed (non-critical): {e}")
        return False

    def _create_backlog_task(self, task_data: Dict, allow_duplicates: bool = False) -> bool:
        """Creates a task in Supabase system_backlog."""
        if not self.db.is_available():
            logger.warning("Database unavailable. Cannot create backlog task.")
            return False

        try:
            # Check for duplicates (exact title + keyword overlap) if not allowed
            if not allow_duplicates:
                existing = self.db.client.table("system_backlog").select("id").eq("title", task_data['title']).eq("status", "PENDING").execute()
                if existing.data and len(existing.data) > 0:
                    logger.info(f"Task '{task_data['title']}' already exists in backlog.")
                    return False
                if self._is_duplicate_topic(task_data['title']):
                    return False
            
            # Data Mapping for Strict Supabase Schema
            raw_priority = str(task_data.get('priority', 'MID')).upper()
            priority_map = {
                "URGENT": 10,
                "CRITICAL": 10,
                "HIGH": 8,
                "MID": 5,
                "MEDIUM": 5,
                "LOW": 2,
                "INFO": 1
            }
            priority_int = priority_map.get(raw_priority, 5) # Default to 5
            
            raw_category = str(task_data.get("category", "FEATURE")).upper()
            valid_categories = ['PERFORMANCE', 'RELIABILITY', 'FEATURE', 'SECURITY', 'DATA']
            if raw_category not in valid_categories:
                raw_category = 'FEATURE'
                
            # Advanced Markdown Formatting for UI
            impact = task_data.get('impact', 5)
            confidence = task_data.get('confidence', 5)
            ease = task_data.get('ease', 5)
            total_ice = impact + confidence + ease
            mission_prompt = task_data.get('mission_prompt', '')
            
            enhanced_desc = f"{task_data['description']}\n\n"
            enhanced_desc += f"🧊 **ICE Score:** {total_ice}/30 (Impact: {impact}, Confidence: {confidence}, Ease: {ease})\n\n"
            if mission_prompt:
                enhanced_desc += f"🤖 **Mission Prompt:**\n```\n{mission_prompt}\n```"
                
            # Insert new task
            record = {
                "title": task_data['title'],
                "description": enhanced_desc,
                "priority": priority_int,
                "status": "PENDING", # Must be strictly PENDING
                "category": raw_category,
                "created_at": datetime.now().isoformat()
            }
            
            self.db.client.table("system_backlog").insert(record).execute()
            logger.info(f"✅ CPO Created Task: {task_data['title']} (Priority {priority_int})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create backlog task: {e}")
            return False

if __name__ == "__main__":
    # Test Run
    logging.basicConfig(level=logging.INFO)
    cpo = ProductOwner()
    cpo.run_analysis_cycle()
