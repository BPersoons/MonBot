import json
import os
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("SwarmLearner")

SCORE_THRESHOLD = 0.4  # Must match project_lead.py noise filter

class SwarmLearner:
    """
    Learning & Diagnostics Agent.

    Analyses the decision pipeline to find bottlenecks, simulate missed
    trades and measure the effect of different score thresholds.
    Reports findings to system_backlog (Supabase) and learning_report.json.
    Does NOT change any parameters autonomously.
    """

    DECISION_HISTORY_FILE = "decision_history.json"
    PIPELINE_EVENTS_FILE  = "pipeline_events.json"
    TICKER_STATE_FILE     = "ticker_state.json"
    TRADE_LOG_FILE        = "trade_log.json"
    LEARNING_REPORT_FILE  = "learning_report.json"
    DASHBOARD_FILE        = "dashboard.json"

    # Thresholds to compare in impact analysis
    THRESHOLD_CANDIDATES  = [0.30, 0.35, 0.40, 0.45, 0.50]

    def __init__(self, exchange_client=None, db_client=None):
        self.exchange = exchange_client
        self.db = db_client

        try:
            from utils.llm_client import LLMClient
            self.llm = LLMClient(model_name="gemini-3.1-flash-lite-preview")
        except Exception as e:
            logger.warning(f"LLM not available for SwarmLearner: {e}")
            self.llm = None

    # ──────────────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────────────

    def run_learning_cycle(self) -> dict:
        """Run all analyses, save report, push insights to backlog."""
        logger.info("SwarmLearner: Starting learning cycle...")

        history = self._load_json(self.DECISION_HISTORY_FILE, [])
        trades  = self._load_json(self.TRADE_LOG_FILE, [])

        if not history:
            logger.warning("SwarmLearner: No decision history found. Skipping.")
            return {}

        report = {
            "timestamp": datetime.now().isoformat(),
            "period_analyzed": f"last_{len(history)}_decisions",
            "funnel":               self._analyze_funnel(history, trades),
            "indicator_bottleneck": self._analyze_indicator_bottleneck(history),
            "missed_trades":        self._simulate_missed_trades(history),
            "threshold_impact":     self._analyze_threshold_impact(history),
            "llm_summary":          "",
        }

        report["llm_summary"] = self._generate_llm_summary(report)

        self._save_json(self.LEARNING_REPORT_FILE, report)
        self._update_dashboard(report)
        self._push_insights_to_backlog(report)

        logger.info(
            f"SwarmLearner: Learning cycle complete. "
            f"Bottleneck={report['funnel'].get('bottleneck_gate', '?')} | "
            f"Missed trades={len(report['missed_trades'])} | "
            f"Lowest contributor={report['indicator_bottleneck'].get('lowest_contributor', '?')}"
        )
        return report

    # ──────────────────────────────────────────────────────────────
    # 1. Funnel analysis
    # ──────────────────────────────────────────────────────────────

    def _analyze_funnel(self, history: list, trades: list) -> dict:
        """
        Count how many decisions pass each gate:
          total → passed_score_threshold → llm_build_case → executed
        """
        total           = len(history)
        passed_score    = sum(1 for e in history if abs(e.get("score", 0)) >= SCORE_THRESHOLD)
        build_case      = sum(1 for e in history if e.get("decision") == "BUILD_CASE")
        monitor_count   = sum(1 for e in history if e.get("decision") == "MONITOR")
        no_go_count     = sum(1 for e in history if e.get("decision") == "NO_GO")
        executed        = len([t for t in trades if t.get("status") in ("OPEN", "CLOSED", "PENDING_FOUNDER_APPROVAL")])

        # Find narrowest gate (biggest relative drop)
        gates = [
            ("score_threshold",  total,        passed_score),
            ("llm_build_case",   passed_score, build_case),
            ("execution",        build_case,   executed),
        ]
        bottleneck_gate = "unknown"
        bottleneck_pct  = 0.0
        for name, before, after in gates:
            if before > 0:
                drop = (before - after) / before * 100
                if drop > bottleneck_pct:
                    bottleneck_pct  = drop
                    bottleneck_gate = name

        return {
            "total_analyzed":       total,
            "passed_score_threshold": passed_score,
            "llm_build_case":       build_case,
            "monitor_count":        monitor_count,
            "no_go_count":          no_go_count,
            "executed":             executed,
            "bottleneck_gate":      bottleneck_gate,
            "bottleneck_pct":       f"{bottleneck_pct:.1f}% drops here",
            "score_pass_rate":      f"{passed_score/total*100:.1f}%" if total else "0%",
            "build_case_rate":      f"{build_case/passed_score*100:.1f}%" if passed_score else "0%",
        }

    # ──────────────────────────────────────────────────────────────
    # 2. Per-indicator bottleneck
    # ──────────────────────────────────────────────────────────────

    def _analyze_indicator_bottleneck(self, history: list) -> dict:
        """
        Parse reason field ('Tech:+0.38, Fund:+0.20, Sent:+0.15') and
        correlate each sub-score with the final decision outcome.
        """
        tech_scores  = []
        fund_scores  = []
        sent_scores  = []

        no_go_tech   = []
        no_go_fund   = []
        no_go_sent   = []

        for entry in history:
            reason = entry.get("reason", "")
            t = self._parse_subscore(reason, "Tech")
            f = self._parse_subscore(reason, "Fund")
            s = self._parse_subscore(reason, "Sent")

            if t is not None: tech_scores.append(t)
            if f is not None: fund_scores.append(f)
            if s is not None: sent_scores.append(s)

            decision = entry.get("decision", "")
            if decision == "NO_GO":
                if t is not None: no_go_tech.append(t)
                if f is not None: no_go_fund.append(f)
                if s is not None: no_go_sent.append(s)

        def avg(lst): return round(sum(lst) / len(lst), 3) if lst else None

        avg_scores = {
            "tech": avg(tech_scores),
            "fund": avg(fund_scores),
            "sent": avg(sent_scores),
        }

        # Lowest average contributor
        non_null = {k: v for k, v in avg_scores.items() if v is not None}
        lowest_contributor = min(non_null, key=non_null.get) if non_null else "unknown"

        # Average sub-score on NO_GO decisions (lower = more responsible for rejections)
        avg_on_no_go = {
            "tech": avg(no_go_tech),
            "fund": avg(no_go_fund),
            "sent": avg(no_go_sent),
        }

        # Score distribution: how many cluster just below threshold (0.3-0.4)?
        near_miss = sum(
            1 for e in history
            if 0.30 <= abs(e.get("score", 0)) < SCORE_THRESHOLD
        )

        return {
            "avg_scores":          avg_scores,
            "lowest_contributor":  lowest_contributor,
            "avg_on_no_go":        avg_on_no_go,
            "near_miss_count":     near_miss,
            "near_miss_pct":       f"{near_miss/len(history)*100:.1f}%" if history else "0%",
            "sample_size":         {
                "tech": len(tech_scores),
                "fund": len(fund_scores),
                "sent": len(sent_scores),
            }
        }

    def _parse_subscore(self, reason: str, label: str) -> Optional[float]:
        """Extract numeric value from 'Tech:+0.38' style strings."""
        try:
            pattern = rf"{label}:\s*([+-]?\d+\.?\d*)"
            match   = re.search(pattern, reason, re.IGNORECASE)
            if match:
                return float(match.group(1))
        except Exception:
            pass
        return None

    # ──────────────────────────────────────────────────────────────
    # 3. Missed trade simulation
    # ──────────────────────────────────────────────────────────────

    def _simulate_missed_trades(self, history: list) -> list:
        """
        For each NO_GO / MONITOR entry with a recorded price, fetch the
        current price and estimate the hypothetical P&L.
        Only processes the 50 most-recent rejections to limit API calls.
        """
        results = []

        candidates = [
            e for e in history
            if e.get("decision") in ("NO_GO", "MONITOR")
            and e.get("current_price", 0) > 0
            and e.get("ticker")
        ]

        # Most recent 50 only
        candidates = sorted(
            candidates,
            key=lambda e: e.get("timestamp", ""),
            reverse=True
        )[:50]

        for entry in candidates:
            ticker        = entry["ticker"]
            decision_price = float(entry.get("current_price", 0))
            direction      = entry.get("direction", "LONG").upper()
            score          = entry.get("score", 0)
            decision_time  = entry.get("timestamp", "")

            current_price = self._get_current_price(ticker)
            if current_price <= 0 or decision_price <= 0:
                continue

            price_change = (current_price - decision_price) / decision_price
            hypo_pnl_pct = price_change if direction == "LONG" else -price_change

            results.append({
                "ticker":           ticker,
                "direction":        direction,
                "decision":         entry.get("decision"),
                "score":            round(score, 3),
                "decision_time":    decision_time,
                "decision_price":   decision_price,
                "current_price":    current_price,
                "hypothetical_pnl_pct": round(hypo_pnl_pct * 100, 2),
                "would_have_won":   hypo_pnl_pct > 0,
            })

        # Sort by hypothetical P&L descending (biggest missed opportunity first)
        results.sort(key=lambda x: x["hypothetical_pnl_pct"], reverse=True)
        return results

    def _get_current_price(self, ticker: str) -> float:
        """Fetch current price; returns 0.0 on failure."""
        if not self.exchange:
            return 0.0
        try:
            return self.exchange.get_market_price(ticker)
        except Exception as e:
            logger.debug(f"SwarmLearner: Could not fetch price for {ticker}: {e}")
            return 0.0

    # ──────────────────────────────────────────────────────────────
    # 4. Threshold impact analysis
    # ──────────────────────────────────────────────────────────────

    def _analyze_threshold_impact(self, history: list) -> dict:
        """
        Replay historical scores with different thresholds and show
        how many entries would have passed each.
        """
        current_count = sum(
            1 for e in history if abs(e.get("score", 0)) >= SCORE_THRESHOLD
        )

        impact = {}
        for threshold in self.THRESHOLD_CANDIDATES:
            count = sum(1 for e in history if abs(e.get("score", 0)) >= threshold)
            delta = count - current_count
            impact[str(threshold)] = {
                "would_pass": count,
                "delta":      f"{delta:+d}" if threshold != SCORE_THRESHOLD else "current",
                "pass_rate":  f"{count/len(history)*100:.1f}%" if history else "0%",
            }

        # Score histogram: buckets of 0.1
        buckets = {}
        for e in history:
            score = abs(e.get("score", 0))
            lower = round(int(score * 10) / 10, 1)
            upper = round(lower + 0.1, 1)
            key   = f"{lower:.1f}-{upper:.1f}"
            buckets[key] = buckets.get(key, 0) + 1

        return {
            "thresholds":         impact,
            "score_distribution": dict(sorted(buckets.items())),
        }

    # ──────────────────────────────────────────────────────────────
    # 5. LLM summary
    # ──────────────────────────────────────────────────────────────

    def _generate_llm_summary(self, report: dict) -> str:
        """Ask the LLM to translate raw numbers into human-readable insights."""
        if not self.llm:
            return "LLM not available."

        funnel    = report.get("funnel", {})
        indicator = report.get("indicator_bottleneck", {})
        missed    = report.get("missed_trades", [])
        threshold = report.get("threshold_impact", {})

        # Summarise top missed trade
        top_missed = ""
        if missed:
            tm = missed[0]
            top_missed = (
                f"Best missed opportunity: {tm['ticker']} {tm['direction']} "
                f"at {tm['decision_price']}, now {tm['current_price']} "
                f"({tm['hypothetical_pnl_pct']:+.1f}%)"
            )

        prompt = f"""
You are the SwarmLearner diagnostics agent for an autonomous crypto trading system.
The swarm has been running but executing ZERO trades. Analyse the data below and give
a concise 3-5 sentence diagnosis in plain English, explaining the most likely root cause
and the single most impactful recommendation to fix it.

FUNNEL DATA:
- Total decisions analysed: {funnel.get('total_analyzed', 0)}
- Passed score threshold (>={SCORE_THRESHOLD}): {funnel.get('passed_score_threshold', 0)} ({funnel.get('score_pass_rate', '?')})
- LLM said BUILD_CASE: {funnel.get('llm_build_case', 0)} ({funnel.get('build_case_rate', '?')})
- Executed trades: {funnel.get('executed', 0)}
- Primary bottleneck gate: {funnel.get('bottleneck_gate', '?')} ({funnel.get('bottleneck_pct', '?')})
- Near-miss scores (0.30-0.40): {indicator.get('near_miss_count', 0)} ({indicator.get('near_miss_pct', '?')})

INDICATOR AVERAGES:
- Tech: {indicator.get('avg_scores', {}).get('tech', '?')}
- Fund: {indicator.get('avg_scores', {}).get('fund', '?')}
- Sent: {indicator.get('avg_scores', {}).get('sent', '?')}
- Lowest contributor: {indicator.get('lowest_contributor', '?')}

THRESHOLD IMPACT (how many would pass at different thresholds):
{json.dumps(threshold.get('thresholds', {}), indent=2)}

MISSED TRADES:
{top_missed if top_missed else 'No missed trade data available (exchange prices not fetched)'}
Total missed trades simulated: {len(missed)}

Keep your answer actionable and specific. Start with the most critical finding.
"""
        try:
            return self.llm.analyze_text(prompt, agent_name="SwarmLearner").strip()
        except Exception as e:
            logger.warning(f"SwarmLearner: LLM summary failed: {e}")
            return f"LLM summary failed: {e}"

    # ──────────────────────────────────────────────────────────────
    # 6. Reporting
    # ──────────────────────────────────────────────────────────────

    def _push_insights_to_backlog(self, report: dict):
        """Write top findings as high-priority backlog items."""
        if not self.db:
            logger.warning("SwarmLearner: No DB client, skipping backlog push.")
            return

        insights = self._build_backlog_insights(report)
        for insight in insights:
            try:
                existing = self.db.client.table("system_backlog") \
                    .select("id") \
                    .eq("title", insight["title"]) \
                    .eq("status", "PENDING") \
                    .execute()
                if existing.data:
                    logger.info(f"SwarmLearner: Backlog item already exists: {insight['title']}")
                    continue

                record = {
                    "title":       insight["title"],
                    "description": insight["description"],
                    "priority":    insight["priority"],
                    "status":      "PENDING",
                    "category":    "PERFORMANCE",
                    "created_by":  "SwarmLearner",
                    "created_at":  datetime.now().isoformat(),
                }
                self.db.client.table("system_backlog").insert(record).execute()
                logger.info(f"SwarmLearner: Backlog item created: {insight['title']}")
            except Exception as e:
                logger.error(f"SwarmLearner: Failed to push backlog item: {e}")

    def _build_backlog_insights(self, report: dict) -> list:
        """Convert analysis results into structured backlog items."""
        insights = []
        funnel    = report.get("funnel", {})
        indicator = report.get("indicator_bottleneck", {})
        threshold = report.get("threshold_impact", {})
        missed    = report.get("missed_trades", [])

        # ── Insight 1: Funnel bottleneck ──────────────────────────
        bottleneck = funnel.get("bottleneck_gate", "unknown")
        pass_rate  = funnel.get("score_pass_rate", "?")
        near_miss  = indicator.get("near_miss_count", 0)

        if bottleneck == "score_threshold":
            desc = (
                f"**Score threshold is the primary bottleneck**: only {pass_rate} of decisions "
                f"pass the {SCORE_THRESHOLD} threshold. "
                f"{near_miss} decisions scored between 0.30 and {SCORE_THRESHOLD} (near-misses). "
                f"\n\nRecommendation: Consider lowering the noise-filter threshold from "
                f"{SCORE_THRESHOLD} to 0.35 and monitor whether quality degrades.\n\n"
                f"🧊 **ICE Score:** 21/30 (Impact: 8, Confidence: 8, Ease: 5)"
            )
        elif bottleneck == "llm_build_case":
            desc = (
                f"**LLM debate is the primary bottleneck**: scores pass the threshold but the LLM "
                f"rarely returns BUILD_CASE ({funnel.get('build_case_rate', '?')} of qualifying signals). "
                f"\n\nRecommendation: Review the LLM council prompt in project_lead.py — it may be "
                f"too risk-averse. Consider relaxing the BUILD_CASE criteria in the prompt.\n\n"
                f"🧊 **ICE Score:** 20/30 (Impact: 8, Confidence: 7, Ease: 5)"
            )
        else:
            desc = (
                f"Pipeline bottleneck detected at: **{bottleneck}**. "
                f"Review the relevant gate logic.\n\n"
                f"🧊 **ICE Score:** 15/30 (Impact: 7, Confidence: 5, Ease: 3)"
            )

        insights.append({
            "title":       f"[SwarmLearner] Bottleneck: {bottleneck}",
            "description": desc,
            "priority":    9,
        })

        # ── Insight 2: Weakest indicator ─────────────────────────
        lowest = indicator.get("lowest_contributor")
        avg_s  = indicator.get("avg_scores", {})
        if lowest and avg_s.get(lowest) is not None:
            insights.append({
                "title":       f"[SwarmLearner] Lowest signal contributor: {lowest}",
                "description": (
                    f"Average {lowest} score: **{avg_s[lowest]:.3f}** "
                    f"(tech={avg_s.get('tech','?')}, fund={avg_s.get('fund','?')}, "
                    f"sent={avg_s.get('sent','?')}). "
                    f"\n\nThe {lowest} analyst is systematically depressing the combined score. "
                    f"Investigate: Is the {lowest} data source returning stale or neutral signals? "
                    f"Consider temporarily reducing its weight or reviewing its prompt.\n\n"
                    f"🧊 **ICE Score:** 18/30 (Impact: 7, Confidence: 7, Ease: 4)"
                ),
                "priority": 7,
            })

        # ── Insight 3: Threshold recommendation ──────────────────
        thresholds = threshold.get("thresholds", {})
        lower_threshold = "0.35"
        if lower_threshold in thresholds:
            extra = thresholds[lower_threshold].get("delta", "?")
            insights.append({
                "title":       "[SwarmLearner] Threshold 0.35 impact",
                "description": (
                    f"Lowering the score threshold from {SCORE_THRESHOLD} to 0.35 "
                    f"would result in **{extra} additional decisions** reaching the LLM debate. "
                    f"\n\nFull distribution:\n"
                    + "\n".join(
                        f"- Threshold {k}: {v.get('would_pass',0)} pass ({v.get('pass_rate','?')}) [{v.get('delta','')}]"
                        for k, v in sorted(thresholds.items())
                    )
                    + f"\n\n🧊 **ICE Score:** 16/30 (Impact: 7, Confidence: 6, Ease: 3)"
                ),
                "priority": 6,
            })

        # ── Insight 4: Top missed trade ───────────────────────────
        if missed:
            top = missed[0]
            pct = top.get("hypothetical_pnl_pct", 0)
            if abs(pct) > 1.0:  # Only report if meaningful (> 1%)
                insights.append({
                    "title":       f"[SwarmLearner] Missed trade: {top['ticker']} {top['direction']}",
                    "description": (
                        f"Best missed opportunity: **{top['ticker']} {top['direction']}** "
                        f"was rejected at score {top['score']} ({top['decision']}) "
                        f"when price was {top['decision_price']}. "
                        f"Price is now {top['current_price']} "
                        f"(**{pct:+.1f}% hypothetical P&L**).\n\n"
                        f"Total missed trades simulated: {len(missed)} | "
                        f"Would-have-won: {sum(1 for m in missed if m['would_have_won'])} "
                        f"({sum(1 for m in missed if m['would_have_won'])/len(missed)*100:.0f}%)\n\n"
                        f"🧊 **ICE Score:** 14/30 (Impact: 6, Confidence: 5, Ease: 3)"
                    ),
                    "priority": 5,
                })

        # ── LLM summary as executive item ────────────────────────
        llm_summary = report.get("llm_summary", "")
        if llm_summary and len(llm_summary) > 20:
            insights.append({
                "title":       "[SwarmLearner] AI Diagnosis",
                "description": llm_summary,
                "priority":    8,
            })

        return insights

    def _update_dashboard(self, report: dict):
        """Add learning_summary to dashboard.json."""
        try:
            dashboard = self._load_json(self.DASHBOARD_FILE, {})
            dashboard["learning_summary"] = {
                "timestamp":           report["timestamp"],
                "bottleneck_gate":     report["funnel"].get("bottleneck_gate"),
                "score_pass_rate":     report["funnel"].get("score_pass_rate"),
                "near_miss_count":     report["indicator_bottleneck"].get("near_miss_count"),
                "lowest_contributor":  report["indicator_bottleneck"].get("lowest_contributor"),
                "missed_trades_count": len(report["missed_trades"]),
                "would_have_won_pct":  (
                    f"{sum(1 for m in report['missed_trades'] if m['would_have_won']) / len(report['missed_trades']) * 100:.0f}%"
                    if report["missed_trades"] else "n/a"
                ),
                "llm_summary":         report.get("llm_summary", "")[:300],
            }
            self._save_json(self.DASHBOARD_FILE, dashboard)
        except Exception as e:
            logger.error(f"SwarmLearner: Failed to update dashboard: {e}")

    # ──────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────

    def _load_json(self, filepath: str, default):
        if not os.path.exists(filepath):
            return default
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"SwarmLearner: Could not read {filepath}: {e}")
            return default

    def _save_json(self, filepath: str, data):
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"SwarmLearner: Could not write {filepath}: {e}")
