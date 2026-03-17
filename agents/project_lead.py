import logging
from agents.technical_analyst import TechnicalAnalyst
from agents.fundamental_analyst import FundamentalAnalyst
from agents.sentiment_analyst import SentimentAnalyst
from agents.risk_manager import RiskManager
from agents.execution_agent import ExecutionAgent
from agents.research_agent import ResearchAgent
from utils.reporting import report_status
from utils.pipeline_events import log_event as log_pipeline_event
import json
import os
from datetime import datetime


from utils.dashboard_query_layer import DashboardDataProvider

class ProjectLead:
    def __init__(self, db_client=None):
        self.logger = logging.getLogger("ProjectLead")
        self.technical_analyst = TechnicalAnalyst()
        self.fundamental_analyst = FundamentalAnalyst(db_client=db_client)
        self.sentiment_analyst = SentimentAnalyst(db_client=db_client)
        self.execution_agent = ExecutionAgent()
        # Inject the live exchange client from ExecutionAgent into RiskManager
        self.risk_manager = RiskManager(exchange_client=self.execution_agent.exchange)
        self.research_agent = ResearchAgent(db_client=db_client)
        self.dashboard_provider = DashboardDataProvider(db_client=db_client)
        self.active_assets_file = "active_assets.json"
        self.weights_file = "core/agent_weights.json"
        self.reasoning_history = [] # For Reasoning Stream
        self.load_weights()
        try:
            from utils.llm_client import LLMClient
            self.llm = LLMClient(model_name="gemini-3.1-pro-preview")
        except:
             self.llm = None

    def _get_score_threshold(self) -> float:
        try:
            with open("core/agent_weights.json") as f:
                return float(json.load(f).get("score_threshold", 0.40))
        except Exception:
            return 0.40

    def load_weights(self):
        self.weights = {
            "technical": 0.4,
            "fundamental": 0.3,
            "sentiment": 0.3
        }
        if os.path.exists(self.weights_file):
            try:
                with open(self.weights_file, "r") as f:
                    self.weights = json.load(f)
            except Exception as e:
                self.logger.error(f"Failed to load weights: {e}")

    def _determine_strategic_weights(self, details: dict) -> tuple[dict, str]:
        """
        Dynamically adjusts weights based on market context (Timeframe Alignment).
        Returns: (weights_dict, strategy_name)
        """
        try:
            # DEBUG: Print structure to find missing keys
            # print(f"DEBUG_STRATEGY: details keys: {list(details.keys())}")
            
            tech_data = details.get('technical', {}).get('timeframes', {})
            
            # Signals: >0.2 (Bull), <-0.2 (Bear)
            # Handle cases where data is missing (0)
            s15m = tech_data.get('15m', {}).get('score', 0)
            s4h = tech_data.get('4h', {}).get('score', 0)
            
            # Default Base Weights (Balanced)
            weights = {"technical": 0.4, "fundamental": 0.3, "sentiment": 0.3}
            strategy = "STANDARD"

            # 1. SCALP / CONTRA-TREND (High Volatility Play)
            if abs(s15m) > 0.3 and (s15m * s4h < 0): 
                strategy = "SCALP_CONTRA"
                weights = {"technical": 0.7, "fundamental": 0.1, "sentiment": 0.2}

            # 2. TREND FOLLOWING (Strong Alignment)
            elif abs(s15m) > 0.3 and abs(s4h) > 0.3 and (s15m * s4h > 0):
                strategy = "TREND_FOLLOW"
                weights = {"technical": 0.5, "fundamental": 0.2, "sentiment": 0.3}
                
            return weights, strategy
            
        except Exception as e:
            self.logger.error(f"Strategy Weight Error: {e}")
            # Fallback
            return {"technical": 0.4, "fundamental": 0.3, "sentiment": 0.3}, "ERROR_FALLBACK"

    def synthesize_signals(self, ticker: str, market_context: dict = None) -> dict:
        import asyncio
        import nest_asyncio
        nest_asyncio.apply()
        return asyncio.run(self.synthesize_signals_async(ticker, market_context))

    async def synthesize_signals_async(self, ticker: str, market_context: dict = None) -> dict:
        """
        Gather signals from analysts concurrently and synthesize using LLM Council Debate.
        """
        import asyncio
        catalyst = "TA_BACKTEST"
        timeframe = "1h Macro"
        strategy = "Unknown"
        direction = "LONG"
        
        if market_context and ticker in market_context:
            catalyst = market_context[ticker].get('catalyst_reason', 'TA_BACKTEST')
            timeframe = market_context[ticker].get('timeframe', '1h Macro')
            strategy = market_context[ticker].get('strategy', 'Unknown')
            direction = market_context[ticker].get('direction', 'LONG')

        # 1. Gather Raw Signals — Technical first (pure math, no LLM cost)
        self.logger.info(f"[{ticker}] Launching Technical analysis (pre-filter)...")

        tech_view = {"signal": 0.0, "status": "ERROR", "timeframes": {}, "summary": "TA Failed"}
        fund_view = {"signal": 0.0, "status": "SKIPPED", "summary": "Skipped (tech pre-filter)"}
        sent_view = {"signal": 0.0, "status": "SKIPPED", "summary": "Skipped (tech pre-filter)"}

        try:
            tech_view = await self.technical_analyst.analyze_async(ticker, catalyst=catalyst)
        except Exception as e:
            self.logger.error(f"Technical Analyst failed for {ticker}: {e}")
            tech_view = {"signal": 0.0, "status": "ERROR", "timeframes": {}, "summary": f"TA Failed: {e}"}

        tech_signal = tech_view.get("signal", 0.0) if isinstance(tech_view, dict) else 0.0

        # Technical pre-filter: only run LLM analysts if tech signal is meaningful
        if abs(tech_signal) >= 0.30:
            self.logger.info(f"[{ticker}] Tech pre-filter PASSED ({tech_signal:.2f}) → launching Fundamental & Sentiment...")
            try:
                fund_task = self.fundamental_analyst.analyze_async(ticker)
                sent_task = self.sentiment_analyst.analyze_async(ticker)
                results = await asyncio.gather(fund_task, sent_task, return_exceptions=True)
                fund_view = results[0] if not isinstance(results[0], Exception) else {"signal": 0.0, "status": "ERROR", "summary": f"FA Failed: {results[0]}"}
                sent_view = results[1] if not isinstance(results[1], Exception) else {"signal": 0.0, "status": "ERROR", "summary": f"SA Failed: {results[1]}"}
                if isinstance(results[0], Exception): self.logger.error(f"Fundamental Analyst failed: {results[0]}")
                if isinstance(results[1], Exception): self.logger.error(f"Sentiment Analyst failed: {results[1]}")
            except Exception as e:
                self.logger.error(f"Async gathering (fund/sent) failed for {ticker}: {e}")
                fund_view = {"signal": 0.0, "status": "ERROR", "summary": "Fundamental Analysis Failed"}
                sent_view = {"signal": 0.0, "status": "ERROR", "summary": "Sentiment Analysis Failed"}
        else:
            self.logger.info(f"[FUNNEL] {ticker}: TECH_PREFILTER_FAILED tech={tech_signal:.2f} < 0.30 → skipping LLM analysts")

        # --- FAST-FAIL CIRCUIT BREAKER ---
        
        details = {
            "technical": tech_view,
            "fundamental": fund_view,
            "sentiment": sent_view
        }
        
        # DEBUG: Log types to find the string indices error
        self.logger.info(f"DEBUG_TYPES [{ticker}]: Tech={type(tech_view)}, Fund={type(fund_view)}, Sent={type(sent_view)}")
        if not isinstance(tech_view, dict): self.logger.error(f"CRITICAL: Tech view is not dict: {tech_view}")
        if not isinstance(fund_view, dict): self.logger.error(f"CRITICAL: Fund view is not dict: {fund_view}")
        if not isinstance(sent_view, dict): self.logger.error(f"CRITICAL: Sent view is not dict: {sent_view}")

        # 2. Dynamic Weighting
        active_weights, strategy_mode = self._determine_strategic_weights(details)
        
        # 3. Calculate Weighted Score and apply Global Macro Vibe
        global_vibe = self.sentiment_analyst.get_global_vibe()
        global_vibe_score = global_vibe.get("signal", 0.0)
        
        raw_base_score = (
            (tech_view['signal'] * active_weights['technical']) +
            (fund_view['signal'] * active_weights['fundamental']) +
            (sent_view['signal'] * active_weights['sentiment'])
        )
        
        # Apply 15% global macro overlay sway
        raw_base_score += (global_vibe_score * 0.15)
        # Clamp to -1.0 to 1.0
        raw_base_score = max(-1.0, min(1.0, raw_base_score))
        
        # Invert base score context if proposing a SHORT
        # (So a highly bearish -0.8 signal becomes a +0.8 conviction for a SHORT)
        base_score = raw_base_score if direction == "LONG" else -raw_base_score
        
        # Inject strategy into details for reasoning extraction later
        details['strategy_mode'] = strategy_mode
        details['active_weights'] = active_weights
        details['global_vibe'] = global_vibe_score
        
        # 4. Filter Noise - Skip LLM if algorithmic score is weak
        _threshold = self._get_score_threshold()
        if abs(base_score) < _threshold:
            self.logger.info(f"[FUNNEL] {ticker}: GATE_1_FAILED score={base_score:.2f} < {_threshold:.3f} threshold")
            return {
                "combined_score": base_score,
                "details": details,
                "bull_case": "Skipped",
                "bear_case": "Skipped",
                "next_step": "NO_GO",
                "synthesis_report": f"LLM Debate Skipped. Algorithmic Score {base_score:.2f} too weak.",
                "has_conflict": False,
                "rrr": "1:1.5",
                "stop_loss_pct": 5.0
            }
        
        # 5. LLM Council Debate (The Soul)
        synthesis_report = "LLM Unavailable - Using Base Score"
        bull_case = "N/A"
        bear_case = "N/A"
        next_step = "NO_GO"
        final_score = base_score
        rrr = "1:1.5"
        sl_pct = 5.0
        target_entry_price = tech_view.get('price', 0.0)
        monitoring_rationale = "N/A"
        trend_timeframe = timeframe
        
        current_price = tech_view.get('price', 0.0)
        
        if self.llm and self.llm.available:
            prompt = f"""
            You are the Project Lead of an elite crypto trading swarm.
            Conduct a debate based on these analyst inputs for {ticker}:

            CONTEXT: The Scout proposed this opportunity based on:
            - Catalyst: {catalyst}
            - Strategy: {strategy}
            - Timeframe: {timeframe}
            - Direction: {direction}
            - Current Market Price: ${current_price:.6f}

            Technical Analyst ({tech_view['signal']:.2f}): {tech_view.get('summary', 'No summary')}
            Fundamental Analyst ({fund_view['signal']:.2f}): {fund_view.get('summary', 'No summary')}
            Sentiment Analyst ({sent_view['signal']:.2f}): {sent_view.get('summary', 'No summary')}

            Algorithmic Conviction Score: {base_score:.2f} (already passed the 0.4 noise filter — this is a real signal)
            Strategy Mode: {strategy_mode} | Weights: {active_weights}

            DECISION RULES — follow strictly:
            - BUILD_CASE: Score >= 0.5 AND no critical bear case. This means execute {direction}. Use this when the setup is actionable NOW.
            - MONITOR: Score 0.4-0.5 OR there is a specific timing reason to wait (e.g. "RSI overbought, wait for pullback to 0.382 fib"). Only use this if you have a CONCRETE condition to watch.
            - NO_GO: Score < 0.4 OR clear structural reason to reject (e.g. negative macro divergence, regulatory risk).

            IMPORTANT: The algorithmic score is {base_score:.2f}. At this level, BUILD_CASE is the expected outcome unless you identify a specific reason to wait or reject.
            Do NOT default to MONITOR out of caution. If the thesis is valid, commit to BUILD_CASE.

            TASK:
            1. Bull Case: arguments FOR the {direction} trade.
            2. Bear Case: arguments AGAINST (be specific, not generic).
            3. Final conviction score (-1.0 to 1.0).
            4. One-sentence synthesis.
            5. Risk-Reward Ratio and Stop Loss %.
            6. NEXT STEP: "BUILD_CASE", "MONITOR", or "NO_GO" — follow the decision rules above.
            7. If MONITOR: provide exact target_entry_price and specific monitoring_rationale.

            OUTPUT JSON ONLY:
            {{
                "bull_case": "...",
                "bear_case": "...",
                "synthesis": "...",
                "final_score": {base_score:.2f},
                "rrr": "1:2",
                "stop_loss_pct": 5.0,
                "next_step": "BUILD_CASE",
                "target_entry_price": {current_price:.6f},
                "monitoring_rationale": "",
                "trend_timeframe": "{timeframe}"
            }}
            """
            try:
                response = self.llm.analyze_text(prompt, agent_name="ProjectLead")
                import json, re
                # Robust JSON extraction: find the first { ... } block
                clean_json = response.replace('```json', '').replace('```', '').strip()
                brace_match = re.search(r'\{[\s\S]*\}', clean_json)
                if brace_match:
                    clean_json = brace_match.group(0)
                llm_data = json.loads(clean_json)
                
                final_score = llm_data.get('final_score', base_score)
                synthesis_report = llm_data.get('synthesis', "Debate concluded.")
                bull_case = llm_data.get('bull_case', "N/A")
                bear_case = llm_data.get('bear_case', "N/A")
                rrr = llm_data.get('rrr', "1:1.5")
                sl_pct = llm_data.get('stop_loss_pct', 5.0)
                next_step = llm_data.get('next_step', "NO_GO").upper()
                raw_target = llm_data.get('target_entry_price')
                target_entry_price = float(raw_target) if raw_target is not None else current_price
                monitoring_rationale = llm_data.get('monitoring_rationale', "N/A")
                trend_timeframe = llm_data.get('trend_timeframe', timeframe)
                
            except Exception as e:
                self.logger.error(f"LLM Debate Failed: {e}")
                # Fallback to base score
                final_score = base_score
                synthesis_report = f"LLM Debate Failed ({str(e)}). Using algorithmic score."
                bull_case = "N/A"
                bear_case = "N/A"
                rrr = "1:1.5"
                sl_pct = 5.0
                next_step = "BUILD_CASE" if final_score > 0.5 else ("MONITOR" if final_score > 0 else "NO_GO")
                target_entry_price = current_price
                monitoring_rationale = "Fallback monitor"
                trend_timeframe = timeframe
                
        return {
            "combined_score": final_score,
            "details": details,
            "bull_case": bull_case,
            "bear_case": bear_case,
            "next_step": next_step,
            "synthesis_report": synthesis_report,
            "has_conflict": False, # Simplified
            "rrr": rrr,
            "stop_loss_pct": sl_pct,
            "target_entry_price": target_entry_price,
            "monitoring_rationale": monitoring_rationale,
            "trend_timeframe": trend_timeframe
        }

    def detect_conflict(self, details: dict):
        analyst_keys = ['technical', 'fundamental', 'sentiment']
        signals = []
        for key in analyst_keys:
            if key in details and isinstance(details[key], dict):
                 signals.append(details[key].get('signal', 0))
        
        if not signals: return False, "No signals", []
        
        conflict = max(signals) > 0.5 and min(signals) < -0.5
        pass # simplified logic
        return False, "No conflict", []

    def generate_executive_summary(self, ticker, score, details, risk, synthesis, conflict):
        return f"Executive Summary for {ticker}\nScore: {score:.2f}\nSynthesis: {synthesis}\nRisk: {risk}"

    def _update_reasoning_stream(self, snippet: str):
        """Updates internal history and returns current list."""
        timestamp = datetime.now().strftime("%H:%M")
        entry = f"[{timestamp}] {snippet}"
        self.reasoning_history.insert(0, entry)
        if len(self.reasoning_history) > 3:
            self.reasoning_history = self.reasoning_history[:3]
        return self.reasoning_history

    def process_opportunity(self, ticker: str, market_context: dict = None, cycle_count: int = 0) -> dict:
        """
        Main execution flow.
        """
        # [STATUS 1: DEBATING]
        reasoning = "Gathering council signals..."
        self.dashboard_provider.update_agent_status(
            "ProjectLead", "ACTIVE", 
            task=f"Debating {ticker}", 
            reasoning=reasoning,
            meta={"reasoning_history": self._update_reasoning_stream(f"Started debate on {ticker}")},
            cycle_count=cycle_count
        )
        
        # Step 1: Synthesis
        try:
             analysis = self.synthesize_signals(ticker, market_context)
        except Exception as e:
             self.logger.error(f"CRITICAL: Brain Offline during synthesis for {ticker}: {e}")
             self.dashboard_provider.update_agent_status(
                "ProjectLead", "ERROR", 
                task="BRAIN_OFFLINE", 
                reasoning=f"LLM Failure: {str(e)[:50]}",
                cycle_count=cycle_count,
                last_error=str(e) # <-- Report error to Supabase
             )
             return {
                 "status": "ERROR", 
                 "decision_reason": f"Crash: {str(e)[:100]}", # Providing reason!
                 "analysis": {}, 
                 "combined_score": 0, 
                 "risk_status": "BRAIN_FAIL"
             }

        combined_score = analysis['combined_score']
        details = analysis['details']
        conflicts = analysis.get('conflicts', []) 
        _, _, conflicts_list = self.detect_conflict(details) 
        
        # Update reasoning snippet with score
        score_msg = f"Score: {combined_score:.2f} (Tech:{details['technical']['signal']:.2f}, Sent:{details['sentiment']['signal']:.2f})"
        self.dashboard_provider.update_agent_status(
            "ProjectLead", "ACTIVE", 
            task=f"Debating {ticker}", 
            reasoning=score_msg,
            meta={"reasoning_history": self._update_reasoning_stream(f"{ticker} Score: {combined_score:.2f}")},
            cycle_count=cycle_count
        )

        # Step 1.5: Cross-Market Correlation Check
        correlation_note = ""
        if market_context and "BTC/USDT" in market_context:
            btc_score = market_context["BTC/USDT"].get("combined_score", 0)
            
            if ticker != "BTC/USDT":
                if btc_score < -0.5 and combined_score > 0.5:
                    correlation_note = f"⚠️ DIVERGENCE: {ticker} is Bullish while BTC is Bearish ({btc_score:.2f}). Proceed with CAUTION."
                    combined_score -= 0.5 
                elif btc_score > 0.5 and combined_score > 0.5:
                    correlation_note = "✅ CONFIRMATION: Market Leader BTC is also Bullish."
                    combined_score += 0.2

        # Step 2: Threshold Check (> 1.5 for LONG, < -1.5 for SHORT)
        
        risk_status = "VEILIG" 
        final_decision = "HOLD"
        
        # Breakdown construction
        tech_sig = details['technical']['signal']
        fund_sig = details['fundamental']['signal']
        sent_sig = details['sentiment']['signal']
        
        # Extract timeframe context if available
        timeframes = details.get('technical', {}).get('timeframes', {})
        tf_str = []
        if timeframes:
            for tf, data in timeframes.items():
                if isinstance(data, dict) and 'signal' in data:
                     # Simplify: "4h: Bull"
                     sig = "Bull" if data['signal'] == "BULLISH" else "Bear" if data['signal'] == "BEARISH" else "Neut"
                     tf_str.append(f"{tf}: {sig}")
        
        tf_context = f" ({', '.join(tf_str)})" if tf_str else ""
        
        # Enhanced Detail: Add RSI
        rsi_val = details.get('technical', {}).get('metrics', {}).get('rsi_1h', 0)
        if rsi_val > 0:
             tf_context = f" [RSI:{rsi_val:.0f}]" + tf_context
        
        # Detailed reasoning string
        strat_mode = details.get('strategy_mode', 'STANDARD')
        reason_breakdown = f"[{strat_mode}] Tech: {tech_sig:+.2f}{tf_context} | Fund: {fund_sig:+.2f} | Sent: {sent_sig:+.2f}"
        decision_reason = f"Score {combined_score:.2f} insufficient. {reason_breakdown}"
        
        # Extract new Council Debate fields
        bull_case = analysis.get("bull_case", "N/A")
        bear_case = analysis.get("bear_case", "N/A")
        next_step = analysis.get("next_step", "NO_GO")
        
        business_case = {}
        
        direction_label = "LONG"
        if market_context and ticker in market_context:
             direction_label = market_context[ticker].get('direction', 'LONG')
             
        action = "BUY" if direction_label == "LONG" else "SELL"
        is_long = direction_label == "LONG"
        
        # Fetch current price safely for all decision branches
        current_price = details.get('technical', {}).get('price', 100.0)
        
        if abs(combined_score) >= self._get_score_threshold():
            self.logger.info(f"[FUNNEL] {ticker}: GATE_1_PASSED score={combined_score:.2f} → LLM_next_step={next_step}")
        else:
            # Score too low — LLM was skipped inside _council_debate, next_step is already NO_GO
            pass

        if next_step == "BUILD_CASE":

             report_status(f"Opportunity validated by Council for {ticker}! ({direction_label}) Score: {combined_score:.2f}. {correlation_note}", "SUCCESS")
             
             # --- NARRATOR CHECK (Phase 2) ---
             from utils.narrator import NarrativeGenerator
             narrator = NarrativeGenerator()
             
             # [STATUS: NARRATIVE]
             self.dashboard_provider.update_agent_status(
                 "Narrator", "ACTIVE", 
                 task=f"Building Case for {ticker} ({direction_label})", 
                 reasoning="Generating Thesis/Anti-Thesis"
             )
             
             business_case = narrator.generate_business_case(ticker, action, details, conflicts_list, "PENDING_RISK_CHECK")
             
             self.dashboard_provider.update_agent_status(
                 "Narrator", "IDLE", 
                 task="Waiting for next assignment", 
                 reasoning="Last case completed"
             )
             
             # --- PIPELINE EVENT: NARRATOR_CHECK ---
             try:
                 log_pipeline_event("NARRATOR_CHECK", ticker, {
                     "status": business_case.get('narrative_status', 'UNKNOWN'),
                     "thesis": str(business_case.get('thesis', ''))[:200],
                     "anti_thesis": str(business_case.get('anti_thesis', ''))[:200],
                     "direction": direction_label,
                 })
             except Exception:
                 pass

             if business_case['narrative_status'] != "VALID":
                 self.logger.info(f"[FUNNEL] {ticker}: GATE_3_FAILED narrator_veto status={business_case['narrative_status']}")
                 report_status(f"Narrator rejected proposal for {ticker}: No Bear Case identified.", "WARNING")
                 final_decision = "REJECTED_BY_NARRATOR"
                 risk_status = "NARRATIVE_FAIL"
                 decision_reason = f"Narrator Veto: No Bear Case. {reason_breakdown}"
                 self._update_reasoning_stream(f"Veto {ticker}: Narrator detected weakness")
             else:
                 self.logger.info(f"[FUNNEL] {ticker}: GATE_3_PASSED → RiskManager")
                 # [STATUS 2: AUDITING]
                 self.dashboard_provider.update_agent_status(
                     "Risk Manager", "ACTIVE", 
                     task=f"Auditing {ticker}", 
                     reasoning="Checking VaR and Allocations"
                 )
                 
                 trade_proposal = {
                    "ticker": ticker,
                    "action": action,
                    "timeframe": (market_context or {}).get(ticker, {}).get('timeframe', '1h'),
                    "conviction": abs(combined_score), # Use absolute for sizing logic?
                    "price": current_price,
                    "win_probability": 0.5 + (abs(combined_score) / 6.0),
                    "net_odds": 2.0,
                    "metrics": details.get('technical', {}).get('metrics', {}), # Approximate
                    "analyst_signals": {
                        "technical": details['technical']['signal'],
                        "fundamental": details['fundamental']['signal'],
                        "sentiment": details['sentiment']['signal']
                    },
                    "reasoning_trace": details,
                    "business_case": business_case
                }

                 _open_trades_risk, _positions_status_risk = [], {}
                 try:
                     import json as _rj, os as _ro
                     if _ro.path.exists("trade_log.json"):
                         with open("trade_log.json") as _rf:
                             _open_trades_risk = [t for t in _rj.load(_rf) if t.get('status') in ('OPEN', 'PLACED')]
                     if _ro.path.exists("positions_status.json"):
                         with open("positions_status.json") as _pf:
                             _positions_status_risk = _rj.load(_pf)
                 except Exception as _re:
                     self.logger.warning(f"Could not load portfolio state for capacity check: {_re}")

                 risk_decision = self.risk_manager.validate_trade_proposal(
                     trade_proposal,
                     open_trades=_open_trades_risk,
                     positions_status=_positions_status_risk
                 )

                 # --- PIPELINE EVENT: RISK_CHECK ---
                 try:
                     risk_metrics = risk_decision.get('metrics', {})
                     log_pipeline_event("RISK_CHECK", ticker, {
                         "approved": risk_decision.get('approved', False),
                         "reason": risk_decision.get('reason', '')[:200],
                         "kelly_fraction": risk_metrics.get('kelly_fraction', 0),
                         "expectancy": risk_metrics.get('expectancy_score', 0),
                         "allocation_usdt": risk_metrics.get('recommended_allocation_usdt', 0),
                         "anomalies": risk_decision.get('anomalies', [])[:3],
                     })
                 except Exception:
                     pass

                 self.dashboard_provider.update_agent_status("Risk Manager", "IDLE")

                 if risk_decision['approved']:
                      self.logger.info(f"[FUNNEL] {ticker}: GATE_4_PASSED risk_approved → Executing {action}")
                      report_status(f"Trade APPROVED by Risk Manager for {ticker}.", "SUCCESS", risk_decision)
                      final_decision = action 
                      decision_reason = f"Approved {action} | Score: {combined_score:.2f} | {reason_breakdown}" 
                      
                      # [STATUS 3: EXECUTING]
                      alloc = risk_decision['metrics'].get('recommended_allocation_usdt',0)
                      self.dashboard_provider.update_agent_status(
                          "Execution Agent", "ACTIVE", 
                          task=f"Executing {ticker} ({action})", 
                          reasoning=f"Allocating {alloc} USDT"
                      )
                      
                      self._update_reasoning_stream(f"Approved {action} {ticker} (${alloc})")
                      
                      trade_proposal['metrics'] = risk_decision['metrics']

                      # Guard: skip if we already have an open position for this ticker.
                      # Normalize USDT→USDC so BTC/USDT and BTC/USDC are treated as the same.
                      try:
                          import json as _json, os as _os
                          _norm = lambda s: s.replace('/USDT', '/USDC') if s else s
                          _open_tickers = set()
                          if _os.path.exists("trade_log.json"):
                              with open("trade_log.json") as _f:
                                  _open_tickers = {_norm(t['ticker']) for t in _json.load(_f) if t.get('status') in ('OPEN', 'PLACED')}
                          if _norm(ticker) in _open_tickers:
                              self.logger.info(f"[FUNNEL] {ticker}: Skipping — already have an open position. Will HOLD.")
                              final_decision = "HOLD"
                              decision_reason = f"Already in position for {ticker} — not adding to it."
                              result = None
                          else:
                              # Displacement: close weakest position first to free margin for higher-conviction trade
                              _disp = trade_proposal.pop('_displacement_candidate', None)
                              _ok_to_trade = True
                              if _disp:
                                  _disp_ticker = _disp.get('ticker', '?')
                                  self.logger.info(f"[DISPLACEMENT] Closing {_disp_ticker} to make room for {ticker}")
                                  try:
                                      _closed = self.execution_agent.close_position(
                                          _disp.get('id', ''), reason='DISPLACED_BY_HIGHER_CONVICTION'
                                      )
                                      if _closed:
                                          self.remove_active_asset(_disp_ticker)
                                          self.logger.info(f"[DISPLACEMENT] Closed {_disp_ticker} successfully")
                                      else:
                                          self.logger.warning(
                                              f"[DISPLACEMENT] close_position returned False for {_disp_ticker} — aborting new trade"
                                          )
                                          _ok_to_trade = False
                                  except Exception as _de:
                                      self.logger.warning(f"[DISPLACEMENT] Exception closing {_disp_ticker}: {_de} — aborting")
                                      _ok_to_trade = False
                              if _ok_to_trade:
                                  result = self.execution_agent.execute_order(trade_proposal)
                              else:
                                  result = None
                      except Exception as _e:
                          self.logger.warning(f"Open-position guard failed ({_e}), proceeding with order.")
                          result = self.execution_agent.execute_order(trade_proposal)
                      
                      self.dashboard_provider.update_agent_status("Execution Agent", "IDLE", cycle_count=cycle_count)
                      
                      if result is None:
                           final_decision = "SKIPPED_ALLOCATION"
                           risk_status = "MAX_ALLOCATION"
                      
                 else:
                      self.logger.info(f"[FUNNEL] {ticker}: GATE_4_FAILED risk_veto reason={risk_decision.get('reason','?')[:80]}")
                      report_status(f"Trade VETOED by Risk Manager.", "WARNING", risk_decision)
                      risk_status = "RISK_VETO"
                      final_decision = "NO_GO"
                      decision_reason = f"Risk Veto: {risk_decision.get('reason', 'High Risk')}. {reason_breakdown}"
                      self._update_reasoning_stream(f"Veto {ticker}: Risk Manager blocked")
        elif next_step == "MONITOR":
            target_entry_price = analysis.get("target_entry_price", current_price)
            # Make sure we import OpportunityManager if not injected, though it's typically handled by main.py calling add_or_update directly on its instance. 
            # In V1 architecture, `main.py` handles the OpportunityManager tracking via `discovery_data`.
            # We just need to make sure the data ships out in the return dict.
            report_status(f"Opportunity added to Monitoring Watchlist for {ticker}. Waiting for Micro Entry. Target: ${target_entry_price:.6f}", "INFO")
            final_decision = "MONITOR"
            risk_status = "WAITING"
            decision_reason = f"Macro Thesis valid, awaiting Micro timing. {reason_breakdown} (Target: ${target_entry_price:.6f})"
            self._update_reasoning_stream(f"Monitor {ticker}: Awaiting entry signal at ${target_entry_price:.6f}")
        else:
            report_status(f"Opportunity rejected by Council for {ticker}. Score {combined_score:.2f}", "INFO")
            final_decision = "NO_GO"
            self._update_reasoning_stream(f"Veto {ticker}: {next_step} / Score {combined_score:.2f}")

        # [STATUS: IDLE]
        self.dashboard_provider.update_agent_status(
            "ProjectLead", "IDLE", 
            task="Monitoring Market", 
            reasoning="Last cycle complete",
            meta={"reasoning_history": self.reasoning_history},
            cycle_count=cycle_count,
            last_error=None # <-- Clear error on success
        )

        # Step 3: Reporting & Webhook
        synthesis_report = analysis.get('synthesis_report')
        has_conflict = analysis.get('has_conflict', False)
        exec_summary = self.generate_executive_summary(
            ticker, combined_score, details, risk_status, 
            synthesis_report, has_conflict
        )
        if correlation_note:
            exec_summary += f"\n\nContext: {correlation_note}"
            
        if business_case:
            exec_summary += f"\n\nBUSINESS CASE:\nThesis: {business_case.get('thesis')}\nRisks: {business_case.get('anti_thesis')}\nDefense: {business_case.get('synthesis')}"
        
        webhook_payload = {
            "ticker": ticker,
            "consensus_score": combined_score,
            "agent_opinions": {
                "technical": details['technical']['signal'],
                "fundamental": details['fundamental']['signal'],
                "sentiment": details['sentiment']['signal']
            },
            "risk_warning": risk_status,
            "final_decision": final_decision,
            "executive_summary": exec_summary,
            "business_case": business_case 
        }
        
        return {
            "status": final_decision, 
            "decision_reason": decision_reason,
            "next_step": next_step,
            "bull_case": bull_case,
            "bear_case": bear_case,
            "score_breakdown": {
                "tech": details['technical']['signal'],
                "fund": details['fundamental']['signal'],
                "sent": details['sentiment']['signal']
            },
            "analysis": analysis, 
            "combined_score": combined_score, 
            "risk_status": risk_status,
            "payload_sent": webhook_payload,
            "target_entry_price": analysis.get("target_entry_price", current_price),
            "current_price": current_price,
            "stop_loss_pct": analysis.get("stop_loss_pct", 5.0),
            "rrr": analysis.get("rrr", "1:1.5"),
            "direction": direction_label,
            "monitoring_rationale": analysis.get("monitoring_rationale", "N/A"),
            "trend_timeframe": analysis.get("trend_timeframe", "1H")
        }

    # --- Asset Lifecycle Management ---

    def get_active_assets(self) -> list:
        if not os.path.exists(self.active_assets_file):
            return []
        try:
            with open(self.active_assets_file, "r") as f:
                assets = json.load(f)
                if not assets:
                    return []
                return assets
        except Exception as e:
            self.logger.error(f"Error loading active assets: {e}")
            return []

    def _save_active_assets(self, assets: list):
        try:
            with open(self.active_assets_file, "w") as f:
                json.dump(assets, f, indent=4)
        except Exception as e:
            self.logger.error(f"Error saving active assets: {e}")

    def add_active_asset(self, ticker: str):
        """Manually add an asset to the monitored list (e.g. after buying)."""
        assets = self.get_active_assets()
        if ticker not in assets:
            assets.append(ticker)
            self._save_active_assets(assets)
            self.logger.info(f"Added {ticker} to active assets portfolio.")

    def remove_active_asset(self, ticker: str):
        """Removes an asset from the active monitoring portfolio after closure."""
        assets = self.get_active_assets()
        if ticker in assets:
            assets.remove(ticker)
            self._save_active_assets(assets)
            self.logger.info(f"Removed {ticker} from active assets portfolio.")

    def run_research_cycle(self, cycle_count: int = 0, monitored_tickers: list = None) -> dict:
        """
        Periodically called to find new assets.
        """
        if monitored_tickers is None: monitored_tickers = []
        report_status("Project Lead initiating R&D Cycle...", "INFO")
        self.dashboard_provider.update_agent_status(
            "ProjectLead", "ACTIVE", 
            task="Scouting Markets", 
            reasoning="Running Research Cycle",
            cycle_count=cycle_count
        )
        current_assets = self.get_active_assets()
        
        # 1. Scan
        proposals = self.research_agent.scan_market(
            current_active_assets=current_assets, 
            cycle_count=cycle_count,
            monitored_tickers=monitored_tickers
        )
        
        added_assets = []
        for p in proposals:
            ticker = p['ticker']
            reason = p['reason']
            metrics = p['metrics']
            
            # 2. Validation / Promotion
            # We treat these as CANDIDATES. They are NOT added to portfolio yet.
            # Only Execution Agent or Main Loop adds them if a trade is opened.
            
            report_status(f"Project Lead identified candidate: {ticker}. {reason}", "INFO", metrics)
            # current_assets.append(ticker) <-- RE MOVED AUTO-ADD
            # added_assets.append(ticker)
        
        # if added_assets:
        #     self._save_active_assets(current_assets)
            
        return {
            "proposals": proposals,
            "added": [] # No longer adding automatically
        }

    def perform_performance_review(self):
        """
        Check for underperforming assets (De-listing).
        """
        # TODO: Implement checking trade_log.json for P&L per asset
        # For now, this is a placeholder.
        pass
