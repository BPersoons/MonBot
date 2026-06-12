import logging
import urllib.request
import urllib.parse


def _send_telegram(text: str):
    """Send a Telegram notification from ProjectLead. Reads secrets lazily."""
    try:
        import os, json as _j
        from utils.gcp_secrets import get_secret
        token   = os.getenv("TELEGRAM_BOT_TOKEN") or get_secret("TELEGRAM_BOT_TOKEN") or ""
        chat_id = os.getenv("TELEGRAM_CHAT_ID")   or get_secret("TELEGRAM_CHAT_ID")   or ""
        if not token or not chat_id:
            return
        body = _j.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}).encode('utf-8')
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body, method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as _e:
        logging.getLogger("ProjectLead").warning(f"Telegram send failed: {_e}")


from agents.technical_analyst import TechnicalAnalyst
try:
    from agents.xyz_technical_analyst import StockTechnicalAnalyst
except ImportError:
    StockTechnicalAnalyst = None
from agents.fundamental_analyst import FundamentalAnalyst
from agents.sentiment_analyst import SentimentAnalyst
from agents.risk_manager import RiskManager
from agents.execution_agent import ExecutionAgent
from agents.research_agent import ResearchAgent
try:
    from agents.polymarket_analyst import PolymarketAnalyst
except ImportError:
    PolymarketAnalyst = None
from utils.reporting import report_status
from utils.pipeline_events import log_event as log_pipeline_event
import json
import os
from datetime import datetime, timezone


from utils.dashboard_query_layer import DashboardDataProvider

class ProjectLead:
    def __init__(self, db_client=None):
        self.logger = logging.getLogger("ProjectLead")
        self.technical_analyst = TechnicalAnalyst()
        self.stock_technical_analyst = StockTechnicalAnalyst() if StockTechnicalAnalyst else self.technical_analyst
        self.fundamental_analyst = FundamentalAnalyst(db_client=db_client)
        self.sentiment_analyst = SentimentAnalyst(db_client=db_client)
        self.execution_agent = ExecutionAgent()
        # Inject the live exchange client from ExecutionAgent into RiskManager
        self.risk_manager = RiskManager(exchange_client=self.execution_agent.exchange)
        self.research_agent = ResearchAgent(db_client=db_client)
        # Polymarket shadow analyst (Phase 1: log only, no scoring impact)
        try:
            self.polymarket_analyst = PolymarketAnalyst(db_client=db_client) if PolymarketAnalyst else None
        except Exception:
            self.polymarket_analyst = None
        self.dashboard_provider = DashboardDataProvider(db_client=db_client)
        self.active_assets_file = "active_assets.json"
        self.weights_file = "core/agent_weights.json"
        self.reasoning_history = []
        self._risk_veto_alert_times: dict = {}  # ticker → last_sent datetime (1h cooldown)
        self.load_weights()
        try:
            from utils.auto_params import AutoParams
            self._auto_params = AutoParams()
        except Exception:
            self._auto_params = None
        try:
            from utils.llm_client import LLMClient
            self.llm = LLMClient(model_name="gemini-3.1-pro-preview")
        except:
             self.llm = None

    def _get_score_threshold(self) -> float:
        # During shadow mode, use the candidate value so the test validates the proposed change
        if self._auto_params:
            try:
                return float(self._auto_params.get_candidate_value("score_threshold"))
            except Exception:
                pass
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

    def _determine_strategic_weights(self, details: dict, direction: str = "LONG") -> tuple[dict, str]:
        """
        Dynamically adjusts weights based on market context (Timeframe Alignment).
        For SHORT candidates, TA weight is boosted to dominate over direction-agnostic FA/SA.
        Returns: (weights_dict, strategy_name)
        """
        try:
            tech_data = details.get('technical', {}).get('timeframes', {})

            # Signals: >0.2 (Bull), <-0.2 (Bear)
            s15m = tech_data.get('15m', {}).get('score', 0)
            s4h = tech_data.get('4h', {}).get('score', 0)

            # SHORT_MOMENTUM: FA and SA are direction-agnostic and score bullish even in
            # downtrends. For SHORT candidates, boost TA weight so bearish price action
            # dominates; FA/SA bullishness reduces conviction (correctly) but doesn't veto.
            if direction == "SHORT":
                return {"technical": 0.60, "fundamental": 0.20, "sentiment": 0.20}, "SHORT_MOMENTUM"

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

    # Regime-specific threshold multipliers applied on top of the base score_threshold.
    # RANGING keeps the same threshold — quality is enforced by the SA gate below, not by
    # lowering the bar (which would let in more noise, not better signals).
    # VOLATILE raises it so only the cleanest setups enter during high-volatility.
    _REGIME_THRESHOLD_MULT = {
        "TRENDING_BULL": 1.00,
        "TRENDING_BEAR": 0.85,
        "RANGING":       1.00,  # gate enforced by SA quality check, not threshold reduction
        "VOLATILE":      1.10,
    }

    # In RANGING, the tech prefilter is relaxed so SA/FA can still run on moderate-TA setups.
    # Without this, news-catalyst tickers (low TA but high SA) would never reach the SA gate.
    # NEWS_SENTIMENT catalysts bypass the prefilter entirely — SA is the primary signal.
    _RANGING_TECH_PREFILTER = 0.06

    # RANGING quality gates: SA must signal a real catalyst; FA must not be a structural red flag.
    _RANGING_SA_MIN   = 0.30   # below this → no clear catalyst in a ranging market
    _RANGING_FA_FLOOR = -0.20  # below this → fundamental red flag, not worth the risk

    async def synthesize_signals_async(self, ticker: str, market_context: dict = None) -> dict:
        """
        Gather signals from analysts concurrently and synthesize using LLM Council Debate.
        """
        import asyncio
        catalyst = "TA_BACKTEST"
        timeframe = "1h Macro"
        strategy = "Unknown"
        direction = "LONG"
        regime_info = {}

        if market_context and ticker in market_context:
            catalyst    = market_context[ticker].get('catalyst_reason', 'TA_BACKTEST')
            timeframe   = market_context[ticker].get('timeframe', '1h Macro')
            strategy    = market_context[ticker].get('strategy', 'Unknown')
            direction   = market_context[ticker].get('direction', 'LONG')
            regime_info = market_context[ticker].get('market_regime', {})

        regime = regime_info.get("regime", "NEUTRAL")

        # 1. Gather Raw Signals — Technical first (pure math, no LLM cost)
        self.logger.info(f"[{ticker}] Launching Technical analysis (pre-filter)...")

        tech_view = {"signal": 0.0, "status": "ERROR", "timeframes": {}, "summary": "TA Failed"}
        fund_view = {"signal": 0.0, "status": "SKIPPED", "summary": "Skipped (tech pre-filter)"}
        sent_view = {"signal": 0.0, "status": "SKIPPED", "summary": "Skipped (tech pre-filter)"}

        # XYZ — skip analysis when the underlying market is closed (asset-class aware):
        # equities trade Mon-Fri 14:30-21:00 UTC; commodities ~24/5 (Sun 23:00–Fri 22:00,
        # with a daily 22:00-23:00 break). Outside hours the 1h filter returns ~0 usable rows
        # and the TA falls back to noisy data, so deferring saves LLM cost and false signals.
        if ticker.startswith('XYZ-'):
            from core.strategy_logic import detect_asset_class as _detect_ac
            from agents.xyz_technical_analyst import _market_is_open as _xyz_open
            _xyz_ac = _detect_ac(ticker)
            if not _xyz_open(_xyz_ac, datetime.now(timezone.utc)):
                self.logger.debug(f"[{ticker}] {_xyz_ac} market closed — deferring analysis")
                return {
                    "combined_score": 0.0,
                    "details": {
                        "technical": tech_view, "fundamental": fund_view,
                        "sentiment": sent_view, "polymarket_shadow": {"signal": 0.0, "status": "SHADOW"},
                    },
                    "bull_case": "Skipped",
                    "bear_case": "Skipped",
                    "next_step": "NO_GO",
                    "synthesis_report": f"{_xyz_ac} market closed. Analysis deferred.",
                    "has_conflict": False,
                    "rrr": "1:1.5",
                    "stop_loss_pct": 5.0,
                    "target_entry_price": 0.0,
                }

        try:
            _ta = self.stock_technical_analyst if ticker.startswith('XYZ-') else self.technical_analyst
            from core.strategy_logic import detect_asset_class as _detect_asset_class
            _asset_class = _detect_asset_class(ticker)
            tech_view = await _ta.analyze_async(ticker, catalyst=catalyst, direction=direction, regime=regime, asset_class=_asset_class)
        except Exception as e:
            self.logger.error(f"Technical Analyst failed for {ticker}: {e}")
            tech_view = {"signal": 0.0, "status": "ERROR", "timeframes": {}, "summary": f"TA Failed: {e}"}

        tech_signal = tech_view.get("signal", 0.0) if isinstance(tech_view, dict) else 0.0

        # Technical pre-filter: use candidate value during shadow mode, but cap at
        # a hard ceiling so FA/SA can never be silenced by Auditor over-tightening.
        # In RANGING regime the ceiling is relaxed so SA/FA can run on moderate-TA setups.
        _TECH_PREFILTER_CEILING = 0.12
        tech_prefilter_min = min(
            self._auto_params.get_candidate_value("tech_prefilter_min") if self._auto_params else 0.15,
            _TECH_PREFILTER_CEILING,
        )
        if regime == "RANGING":
            if catalyst == "NEWS_SENTIMENT":
                # News catalyst: SA is the primary signal — bypass tech prefilter entirely.
                tech_prefilter_min = 0.0
                self.logger.debug(f"[{ticker}] RANGING+NEWS_SENTIMENT: tech prefilter bypassed, SA will gate")
            elif catalyst == "MEAN_REVERSION":
                # Mean reversion: RSI/BB extremes are the signal — prefilter must be very low
                # because momentum-mode TA scores are near zero on oversold/overbought setups.
                tech_prefilter_min = 0.04
                self.logger.debug(f"[{ticker}] RANGING+MEAN_REVERSION: tech prefilter set to 0.04")
            else:
                tech_prefilter_min = min(tech_prefilter_min, self._RANGING_TECH_PREFILTER)
                self.logger.debug(f"[{ticker}] RANGING regime: tech_prefilter relaxed to {tech_prefilter_min}")
        if abs(tech_signal) >= tech_prefilter_min:
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
            self.logger.info(f"[FUNNEL] {ticker}: TECH_PREFILTER_FAILED tech={tech_signal:.2f} < {tech_prefilter_min} → skipping LLM analysts")

        # --- POLYMARKET SHADOW SIGNAL (Phase 1: log only, no scoring impact) ---
        poly_shadow = {"signal": 0.0, "status": "SHADOW", "markets_matched": 0}
        try:
            if self.polymarket_analyst:
                poly_shadow = await self.polymarket_analyst.analyze_async(ticker)
        except Exception as e:
            self.logger.debug(f"Polymarket shadow failed for {ticker}: {e}")

        # --- FAST-FAIL CIRCUIT BREAKER ---

        details = {
            "technical": tech_view,
            "fundamental": fund_view,
            "sentiment": sent_view,
            "polymarket_shadow": poly_shadow,
        }
        
        # DEBUG: Log types to find the string indices error
        self.logger.info(f"DEBUG_TYPES [{ticker}]: Tech={type(tech_view)}, Fund={type(fund_view)}, Sent={type(sent_view)}")
        if not isinstance(tech_view, dict): self.logger.error(f"CRITICAL: Tech view is not dict: {tech_view}")
        if not isinstance(fund_view, dict): self.logger.error(f"CRITICAL: Fund view is not dict: {fund_view}")
        if not isinstance(sent_view, dict): self.logger.error(f"CRITICAL: Sent view is not dict: {sent_view}")

        # 2. Dynamic Weighting — pass direction so SHORT gets TA-dominant weights
        active_weights, strategy_mode = self._determine_strategic_weights(details, direction=direction)

        # 3. Calculate Weighted Score and apply Global Macro Vibe
        global_vibe = self.sentiment_analyst.get_global_vibe()
        global_vibe_score = global_vibe.get("signal", 0.0)

        # Reload learned agent weights from disk so auditor updates take effect each cycle.
        # These are signal multipliers (floor 0.5, ceil 1.5): a penalised agent's signals
        # count for less; a rewarded agent's signals count for more.
        self.load_weights()
        aw = self.weights  # shorthand: {"technical": 1.0, "fundamental": 0.5, "sentiment": 0.5}

        # Regime-adaptive signal multipliers applied on top of learned agent weights.
        # In RANGING markets sentiment is the primary driver (news/catalysts move sideways markets).
        # FA is down-weighted in ranging because on-chain metrics are noisy with no trend to anchor to.
        _regime_boost = {
            "TRENDING_BULL": {"technical": 1.0,  "fundamental": 1.0,  "sentiment": 1.0},
            "TRENDING_BEAR": {"technical": 1.0,  "fundamental": 0.8,  "sentiment": 1.0},
            "RANGING":       {"technical": 0.85, "fundamental": 0.70, "sentiment": 1.40},
            "VOLATILE":      {"technical": 1.10, "fundamental": 0.90, "sentiment": 0.90},
        }.get(regime, {"technical": 1.0, "fundamental": 1.0, "sentiment": 1.0})

        tech_signal  = tech_view.get('signal', 0.0)  * aw.get('technical',  1.0) * _regime_boost['technical']
        fund_signal  = fund_view.get('signal', 0.0)  * aw.get('fundamental', 1.0) * _regime_boost['fundamental']
        sent_signal  = sent_view.get('signal', 0.0)  * aw.get('sentiment',   1.0) * _regime_boost['sentiment']

        if regime != "NEUTRAL":
            self.logger.debug(
                f"[{ticker}] Regime {regime}: tech×{_regime_boost['technical']} "
                f"fund×{_regime_boost['fundamental']} sent×{_regime_boost['sentiment']}"
            )

        if direction == "SHORT":
            # FA and SA measure asset quality/popularity, not directional conviction.
            # A good SHORT candidate often still has strong fundamentals (it was recently
            # bullish). Inverting FA/SA creates a structural penalty that blocks valid SHORTs.
            # Only TA drives SHORT conviction; FA/SA are excluded from SHORT scoring.
            ta_only_score = tech_signal * active_weights['technical']
            # Global macro vibe: bullish market = reversal risk for SHORT, so invert.
            vibe_contribution = -global_vibe_score
            ta_only_score += (vibe_contribution * 0.15)
            base_score = max(-1.0, min(1.0, -ta_only_score))
            raw_base_score = ta_only_score  # keep for logging consistency
        else:
            raw_base_score = (
                (tech_signal * active_weights['technical']) +
                (fund_signal * active_weights['fundamental']) +
                (sent_signal * active_weights['sentiment'])
            )
            # Apply 15% global macro overlay sway.
            vibe_contribution = global_vibe_score
            raw_base_score += (vibe_contribution * 0.15)
            # Clamp to -1.0 to 1.0
            raw_base_score = max(-1.0, min(1.0, raw_base_score))
            base_score = raw_base_score

        # Inject strategy into details for reasoning extraction later
        details['strategy_mode'] = strategy_mode
        details['active_weights'] = active_weights
        details['global_vibe'] = global_vibe_score
        details['agent_weight_multipliers'] = {k: round(aw.get(k, 1.0), 3) for k in ('technical', 'fundamental', 'sentiment')}
        details['market_regime'] = regime_info

        # RANGING quality gate — applied before composite score check.
        # In a ranging market, momentum signals are near-zero noise. Only enter when:
        #   1. SA ≥ 0.30: a real news/catalyst is driving the move (not random sentiment drift)
        #   2. FA ≥ -0.20: no structural fundamental red flag
        # MEAN_REVERSION setups are exempt: they are TA-driven (RSI/BB extremes), not catalyst-driven.
        if regime == "RANGING" and direction != "SHORT" and catalyst != "MEAN_REVERSION":
            sa_raw = sent_view.get('signal', 0.0)
            fa_raw = fund_view.get('signal', 0.0)
            # Fix 1: XYZ stocks have inherently lower SA volatility than crypto — a news signal
            # of 0.10–0.20 (mild positive news, analyst upgrade) is meaningful for stocks but
            # looks like noise under the crypto threshold of 0.30. Relax for XYZ assets.
            _ranging_sa_min = 0.12 if ticker.startswith('XYZ-') else self._RANGING_SA_MIN
            if sa_raw < _ranging_sa_min:
                self.logger.info(
                    f"[FUNNEL] {ticker}: RANGING_SA_GATE SA={sa_raw:.2f} < {_ranging_sa_min} "
                    f"— no catalyst in choppy market, skipping"
                )
                return {
                    "combined_score": base_score,
                    "details": details,
                    "bull_case": "Skipped",
                    "bear_case": "Skipped",
                    "next_step": "NO_GO",
                    "synthesis_report": f"RANGING regime: SA {sa_raw:.2f} below catalyst threshold {_ranging_sa_min}. No clear news driver.",
                    "has_conflict": False,
                    "rrr": "1:1.5",
                    "stop_loss_pct": 5.0,
                }
            if fa_raw < self._RANGING_FA_FLOOR:
                self.logger.info(
                    f"[FUNNEL] {ticker}: RANGING_FA_GATE FA={fa_raw:.2f} < {self._RANGING_FA_FLOOR} "
                    f"— fundamental red flag in choppy market, skipping"
                )
                return {
                    "combined_score": base_score,
                    "details": details,
                    "bull_case": "Skipped",
                    "bear_case": "Skipped",
                    "next_step": "NO_GO",
                    "synthesis_report": f"RANGING regime: FA {fa_raw:.2f} below floor {self._RANGING_FA_FLOOR}. Structural red flag.",
                    "has_conflict": False,
                    "rrr": "1:1.5",
                    "stop_loss_pct": 5.0,
                }
            self.logger.info(
                f"[{ticker}] RANGING quality gate PASSED: SA={sa_raw:.2f} FA={fa_raw:.2f} → proceeding to composite"
            )

        # 4. Filter Noise - Skip LLM if algorithmic score is weak.
        # SHORT signals are structurally weaker: the TA composite mixes positive (MACD/EMA/ADX)
        # and negative (RSI/BB) indicator contributions. Apply a 60% effective threshold for SHORT
        # so valid bear setups aren't systematically gated out.
        # Regime-adaptive threshold: RANGING lowers the bar (SA-driven setups can pass),
        # VOLATILE raises it (only high-conviction in choppy conditions).
        _threshold = self._get_score_threshold()
        _threshold *= self._REGIME_THRESHOLD_MULT.get(regime, 1.0)
        _effective_threshold = _threshold * 0.60 if direction == "SHORT" else _threshold
        if regime not in ("NEUTRAL", "RANGING", "TRENDING_BULL"):
            self.logger.info(
                f"[{ticker}] Regime={regime} → threshold={_threshold:.3f} "
                f"(mult={self._REGIME_THRESHOLD_MULT.get(regime, 1.0)})"
            )
        if abs(base_score) < _effective_threshold:
            self.logger.info(f"[FUNNEL] {ticker}: GATE_1_FAILED score={base_score:.2f} < {_effective_threshold:.3f} threshold (dir={direction})")
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
            _regime_adx  = regime_info.get('adx', '?')
            _regime_dir  = regime_info.get('direction', '?')
            # B1 fix (2026-06-12): decision bands derive from the LIVE score threshold
            # instead of hardcoded values (crypto was 0.38/0.28 while auto_params
            # score_threshold=0.20). That mismatch created a dead zone: candidates in
            # [threshold, 0.28) passed the algorithmic gate, cost an LLM call, and were
            # then rejected by instruction — funnel showed 100% drop at llm_build_case.
            # Bands: BUILD_CASE >= thr+0.05 · MONITOR [thr, thr+0.05) · NO_GO < thr.
            # _effective_threshold already includes the regime multiplier and the 0.60
            # SHORT discount, so the bands move with both. The setup-aware conviction
            # gate (SETUP_MIN_CONVICTION) downstream still applies to BUILD_CASE.
            _mon_floor = round(_effective_threshold, 2)
            _bc_floor = round(_effective_threshold + 0.05, 2)
            _decision_rules = (
                f"- BUILD_CASE: Score >= {_bc_floor:.2f} AND no critical bear case. "
                f"This means execute {direction}. Use this when the setup is actionable NOW.\n"
                f"            - MONITOR: Score {_mon_floor:.2f}–{_bc_floor:.2f} AND there is a SPECIFIC, CONCRETE timing reason to wait "
                f"(e.g. 'RSI overbought, wait for pullback to 0.382 fib'). Name the exact condition and price level.\n"
                f"            - NO_GO: Score < {_mon_floor:.2f} OR clear structural reason to reject "
                f"(e.g. negative macro divergence, regulatory risk)."
            )
            _bc_threshold = f"{_bc_floor:.2f}"
            prompt = f"""
            You are the Project Lead of an elite crypto trading swarm.
            Conduct a debate based on these analyst inputs for {ticker}:

            CONTEXT: The Scout proposed this opportunity based on:
            - Catalyst: {catalyst}
            - Strategy: {strategy}
            - Timeframe: {timeframe}
            - Direction: {direction}
            - Current Market Price: ${current_price:.6f}
            - Market Regime: {regime} (ADX={_regime_adx}, BTC dir={_regime_dir})

            Technical Analyst ({tech_view['signal']:.2f}): {tech_view.get('summary', 'No summary')}
            Fundamental Analyst ({fund_view['signal']:.2f}): {fund_view.get('summary', 'No summary')}
            Sentiment Analyst ({sent_view['signal']:.2f}): {sent_view.get('summary', 'No summary')}

            Algorithmic Conviction Score: {base_score:.2f} (passed the {_threshold:.2f} noise filter — this is a real signal)
            Strategy Mode: {strategy_mode} | Weights: {active_weights}

            DECISION RULES — follow strictly:
            {_decision_rules}

            IMPORTANT: The algorithmic score is {base_score:.2f}. If score >= {_bc_threshold}, BUILD_CASE is the expected outcome.
            MONITOR is only valid when you can name a SPECIFIC price level or indicator condition to watch — not as a general expression of doubt.
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
                response = self.llm.analyze_text(prompt, agent_name="ProjectLead", thinking=False)
                import json, re, ast
                # Robust JSON extraction: find the first { ... } block
                clean_json = response.replace('```json', '').replace('```', '').strip()
                brace_match = re.search(r'\{[\s\S]*\}', clean_json)
                if brace_match:
                    clean_json = brace_match.group(0)
                try:
                    llm_data = json.loads(clean_json)
                except json.JSONDecodeError:
                    # Try JSON repair: Python booleans, trailing commas, literal newlines in strings
                    self.logger.debug(f"json.loads failed, trying JSON repair. Raw: {clean_json[:200]}")
                    try:
                        repaired = re.sub(r'\bTrue\b', 'true', clean_json)
                        repaired = re.sub(r'\bFalse\b', 'false', repaired)
                        repaired = re.sub(r'\bNone\b', 'null', repaired)
                        repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
                        # Escape bare newlines inside string values
                        repaired = re.sub(r'(?<=[\w"\'.,!?])\n(?=[\w"\'.,!?])', r'\\n', repaired)
                        llm_data = json.loads(repaired)
                    except Exception:
                        # Last resort: extract each field with regex (handles single-quoted values)
                        self.logger.debug(f"JSON repair failed, using regex extraction. Raw: {clean_json[:300]}")
                        llm_data = {}
                        for _f, _num in [('bull_case', False), ('bear_case', False), ('synthesis', False),
                                         ('final_score', True), ('rrr', False), ('stop_loss_pct', True),
                                         ('next_step', False), ('target_entry_price', True),
                                         ('monitoring_rationale', False), ('trend_timeframe', False)]:
                            if _num:
                                _m = re.search(rf'["\']?{_f}["\']?\s*:\s*([0-9.]+)', clean_json)
                                if _m:
                                    try: llm_data[_f] = float(_m.group(1))
                                    except ValueError: pass
                            else:
                                _m = re.search(rf'["\']?{_f}["\']?\s*:\s*"([^"]*)"', clean_json)
                                if not _m:
                                    _m = re.search(rf"[\"']?{_f}[\"']?\\s*:\\s*'([^']*)'", clean_json)
                                if _m:
                                    llm_data[_f] = _m.group(1)
                
                final_score = llm_data.get('final_score', base_score)
                synthesis_report = llm_data.get('synthesis', "Debate concluded.")
                bull_case = llm_data.get('bull_case', "N/A")
                bear_case = llm_data.get('bear_case', "N/A")
                rrr = llm_data.get('rrr', "1:1.5")
                sl_pct = llm_data.get('stop_loss_pct', 5.0)
                next_step = llm_data.get('next_step', "NO_GO").upper()
                raw_target = llm_data.get('target_entry_price')
                try:
                    target_entry_price = float(raw_target) if raw_target is not None else current_price
                except (TypeError, ValueError):
                    target_entry_price = current_price
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

        # Polymarket shadow log — record signal for offline validation
        try:
            if self.polymarket_analyst and details.get('polymarket_shadow'):
                self.polymarket_analyst.log_shadow(
                    ticker=ticker,
                    result=details['polymarket_shadow'],
                    existing_signals={
                        "technical": details.get('technical', {}).get('signal', 0),
                        "fundamental": details.get('fundamental', {}).get('signal', 0),
                        "sentiment": details.get('sentiment', {}).get('signal', 0),
                    },
                    combined_score=combined_score,
                    pipeline_outcome=analysis.get('next_step', 'UNKNOWN'),
                )
        except Exception:
            pass
        
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

        risk_decision = {}

        # Gate: minimum conviction to execute — setup-aware.
        # 4h Swing is stricter (binds margin longer → demand more overtuiging).
        # Phase 3: LLM_BUILD_CASE_STRICT env flag controls funnel tightness.
        # loose mode drops each threshold ~one quantile to re-open the funnel
        # once Phase-1 exit geometry has proven itself.
        import os as _os_pl
        # Phase 3 48h window: default is loose (false). Set LLM_BUILD_CASE_STRICT=true to restore pre-Phase-3 behavior.
        _strict = _os_pl.getenv("LLM_BUILD_CASE_STRICT", "false").lower() == "true"
        if _strict:
            SETUP_MIN_CONVICTION = {
                "1h Macro":   0.35,
                "Macro News": 0.30,
                "4h Swing":   0.40,
            }
        else:
            SETUP_MIN_CONVICTION = {
                "1h Macro":   0.25,
                "Macro News": 0.20,
                "4h Swing":   0.30,
            }
        _setup_tf = (market_context or {}).get(ticker, {}).get('timeframe', '1h Macro')
        MIN_CONVICTION = SETUP_MIN_CONVICTION.get(_setup_tf, SETUP_MIN_CONVICTION["1h Macro"])
        # SHORT discount (2026-06-12): gate 1 applies a 0.60 effective threshold for
        # SHORT (composites are structurally weaker — mixed sign conventions), and the
        # LLM bands follow that. This gate ignored the discount, so a SHORT could pass
        # gate 1 + get BUILD_CASE and still be bounced here below the auto-promote
        # floor — a permanent MONITOR loop for our best-performing direction
        # (live: SHORT PF 1.89 vs LONG 0.94 over 248 trades).
        if direction_label == "SHORT":
            MIN_CONVICTION = round(MIN_CONVICTION * 0.60, 3)
        if next_step == "BUILD_CASE" and abs(combined_score) < MIN_CONVICTION:
            self.logger.info(
                f"[FUNNEL] {ticker}: CONVICTION_GATE score={combined_score:.2f} < {MIN_CONVICTION} "
                f"(setup={_setup_tf}) → downgraded BUILD_CASE to MONITOR"
            )
            next_step = "MONITOR"

        # Structure-based RRR gate — skip trades where market structure doesn't
        # offer >=1.5 reward per unit risk. Measured on swing-low/high + Fib 1.618.
        MIN_STRUCTURE_RRR = 1.5
        _swing = details.get('technical', {}).get('swing_levels', {}) or {}
        if next_step == "BUILD_CASE" and _swing.get('valid'):
            _irrr = float(_swing.get('implied_rrr', 0.0) or 0.0)
            if _irrr < MIN_STRUCTURE_RRR:
                self.logger.info(
                    f"[FUNNEL] {ticker}: RRR_GATE implied_rrr={_irrr:.2f} < {MIN_STRUCTURE_RRR} "
                    f"(sl={_swing.get('sl_suggest')}, tp={_swing.get('tp_suggest')}) → MONITOR"
                )
                next_step = "MONITOR"

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
                 
                 # Parse LLM's risk-reward ratio (e.g. "1:2" -> 2.0, "1:1.5" -> 1.5)
                 _rrr_str = analysis.get("rrr", "1:1.5")
                 try:
                     _rrr_parts = str(_rrr_str).split(":")
                     _net_odds = float(_rrr_parts[1]) / float(_rrr_parts[0]) if len(_rrr_parts) == 2 else 1.5
                 except (ValueError, IndexError, ZeroDivisionError):
                     _net_odds = 1.5

                 # Conviction-scaled win probability:
                 # Score range ~0.08-2.15. Map to win_prob 0.51-0.65 range.
                 # Higher conviction = higher win probability = larger Kelly size.
                 _conviction = abs(combined_score)
                 _win_prob = min(0.50 + (_conviction * 0.10), 0.65)  # cap at 65%

                 trade_proposal = {
                    "ticker": ticker,
                    "action": action,
                    "timeframe": (market_context or {}).get(ticker, {}).get('timeframe', '1h Macro'),
                    "conviction": _conviction,
                    "price": current_price,
                    "win_probability": _win_prob,
                    "net_odds": _net_odds,
                    "stop_loss_pct": analysis.get("stop_loss_pct", 5.0),
                    "rrr": _rrr_str,
                    "metrics": details.get('technical', {}).get('metrics', {}),
                    "swing_levels": details.get('technical', {}).get('swing_levels', {}),
                    "analyst_signals": {
                        "technical": details['technical']['signal'],
                        "fundamental": details['fundamental']['signal'],
                        "sentiment": details['sentiment']['signal']
                    },
                    "polymarket_shadow_signal": details.get('polymarket_shadow', {}).get('signal', 0.0),
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
                      # ── Telegram alert for Risk Veto (max 1 per ticker per hour) ──
                      try:
                          from datetime import datetime as _dt, timezone as _tz
                          _now = _dt.now(_tz.utc)
                          _last = self._risk_veto_alert_times.get(ticker)
                          if not _last or (_now - _last).total_seconds() > 3600:
                              self._risk_veto_alert_times[ticker] = _now
                              _veto_reason = risk_decision.get("reason", "High Risk")
                              _free_margin = "unknown"
                              try:
                                  _fm = (risk_decision.get("metrics") or {}).get("free_margin_pct")
                                  if _fm is not None:
                                      _free_margin = f"{_fm:.1f}%"
                              except Exception:
                                  pass
                              _send_telegram(
                                  f"🚫 *Risk Manager Veto*\n"
                                  f"Ticker: `{ticker}` | Score: `{combined_score:.2f}`\n"
                                  f"Reden: {_veto_reason[:200]}\n"
                                  f"Vrije marge: {_free_margin}"
                              )
                      except Exception as _tg_e:
                          self.logger.warning(f"Risk veto Telegram failed: {_tg_e}")
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
            "risk_metrics": risk_decision if risk_status == "RISK_VETO" else {},
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
