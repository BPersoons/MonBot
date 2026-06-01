"""
stocks_project_lead.py — Orchestrator for the stocks department.

Responsibilities:
  1. Run daily full screening cycle (Stage 1+2 → TwinEngine analysis)
  2. Hourly: re-score watchlist candidates, check entry signals
  3. Route PROPOSE → Telegram → pending approval
  4. Process approval responses from poll_approvals()
  5. Manage stocks_watchlist via StocksOpportunityManager
  6. Read cross_signals.json to adjust score_threshold if BTC regime is BEARISH

Phase 1: No execution (IBKR skipped). Proposals are sent to Telegram for
manual tracking. Trade log records are in research-only mode.
"""

import json
import logging
import os
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger("StocksProjectLead")

CROSS_SIGNALS_FILE = "cross_signals.json"
DECISION_HISTORY_FILE = "stocks_decision_history.json"
DECISION_HISTORY_MAX = 2000


class StocksProjectLead:
    def __init__(self, fmp_client=None, yf_client=None, llm_client=None,
                 auto_params=None, db_client=None):
        self.logger = logging.getLogger("StocksProjectLead")

        self._fmp = fmp_client
        self._yf = yf_client
        self._llm = llm_client
        self._auto_params = auto_params
        self._db = db_client

        # Lazy-initialize sub-agents
        self._screener = None
        self._twin_engine = None
        self._risk_manager = None
        self._opportunity_manager = None

    def _get_param(self, key: str, default):
        if self._auto_params:
            try:
                return self._auto_params.get(key, default)
            except Exception:
                pass
        return default

    # ─────────────────────────────────────────────────────────────────
    # Lazy sub-agent accessors
    # ─────────────────────────────────────────────────────────────────

    @property
    def screener(self):
        if self._screener is None:
            from stocks.agents.stocks_screener import StocksScreener
            self._screener = StocksScreener(auto_params=self._auto_params)
        return self._screener

    @property
    def twin_engine(self):
        if self._twin_engine is None:
            from stocks.agents.twin_engine_analyst import TwinEngineAnalyst
            self._twin_engine = TwinEngineAnalyst(
                fmp_client=self._fmp,
                yf_client=self._yf,
                llm_client=self._llm,
                auto_params=self._auto_params,
            )
        return self._twin_engine

    @property
    def risk_manager(self):
        if self._risk_manager is None:
            from stocks.agents.stocks_risk_manager import StocksRiskManager
            self._risk_manager = StocksRiskManager(auto_params=self._auto_params)
        return self._risk_manager

    @property
    def opportunity_manager(self):
        if self._opportunity_manager is None:
            from stocks.utils.stocks_opportunity_manager import StocksOpportunityManager
            self._opportunity_manager = StocksOpportunityManager()
        return self._opportunity_manager

    # ─────────────────────────────────────────────────────────────────
    # Cross-signal integration (crypto → stocks)
    # ─────────────────────────────────────────────────────────────────

    def _get_btc_regime_adjustment(self) -> float:
        """
        Read cross_signals.json. If BTC is BEARISH, raise score threshold +0.05
        for tech stocks (conservative mode). Returns the adjustment delta.
        """
        try:
            if not os.path.exists(CROSS_SIGNALS_FILE):
                return 0.0
            with open(CROSS_SIGNALS_FILE) as f:
                signals = json.load(f)
            regime = signals.get("btc_regime", "NEUTRAL").upper()
            if regime == "BEARISH":
                self.logger.info("Cross-signal: BTC BEARISH → applying +0.05 score threshold adjustment")
                return 0.05
        except Exception as e:
            self.logger.debug(f"Could not read cross_signals.json: {e}")
        return 0.0

    def _get_effective_propose_threshold(self) -> float:
        base = self._get_param("score_threshold_propose", 0.65)
        adj = self._get_btc_regime_adjustment()
        return base + adj

    # ─────────────────────────────────────────────────────────────────
    # Decision history logging
    # ─────────────────────────────────────────────────────────────────

    def _log_decision(self, ticker: str, decision: str, score: float, reason: str):
        try:
            entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "ticker": ticker,
                "decision": decision,
                "score": round(score, 3),
                "reason": reason,
            }
            history = []
            if os.path.exists(DECISION_HISTORY_FILE):
                try:
                    with open(DECISION_HISTORY_FILE) as f:
                        history = json.load(f)
                except Exception:
                    history = []
            history.append(entry)
            if len(history) > DECISION_HISTORY_MAX:
                history = history[-DECISION_HISTORY_MAX:]
            with open(DECISION_HISTORY_FILE, "w") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            self.logger.debug(f"Could not log decision: {e}")

    # ─────────────────────────────────────────────────────────────────
    # Trade log helpers (Phase 1: read-only for risk checks)
    # ─────────────────────────────────────────────────────────────────

    def _load_trade_log(self) -> list:
        try:
            if os.path.exists("stocks_trade_log.json"):
                with open("stocks_trade_log.json") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _load_pending_approvals(self) -> list:
        try:
            if os.path.exists("stocks_pending_approval.json"):
                with open("stocks_pending_approval.json") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    # ─────────────────────────────────────────────────────────────────
    # Daily full screening cycle
    # ─────────────────────────────────────────────────────────────────

    def run_daily_screening(self) -> dict:
        """
        Full daily pipeline: Stage 1+2 → TwinEngine → route to watchlist or PROPOSE.
        Called once per day before market open.
        Returns summary dict.
        """
        self.logger.info("=== Starting Daily Stock Screening ===")
        start = datetime.utcnow()

        propose_threshold = self._get_effective_propose_threshold()
        monitor_threshold = self._get_param("score_threshold_monitor", 0.50)
        fmp_budget = self._fmp.get_daily_calls_remaining() if self._fmp else 0

        # How many tickers can we fully analyze given FMP budget?
        # ~6 FMP calls per ticker
        max_full_analysis = min(40, fmp_budget // 6)
        self.logger.info(
            f"FMP budget: {fmp_budget} calls remaining → max {max_full_analysis} full analyses today"
        )

        # Stage 1+2: get candidates
        candidates = self.screener.run()
        if not candidates:
            return {"status": "NO_CANDIDATES", "analyzed": 0, "proposals": 0}

        # Stage 3: TwinEngine analysis on top candidates (sorted by fast_score)
        analyzed = []
        proposals = []

        for candidate in candidates[:max_full_analysis]:
            ticker = candidate["ticker"]

            # Skip blacklisted tickers
            if self.opportunity_manager.is_blacklisted(ticker):
                self.logger.info(f"  {ticker}: BLACKLISTED (rejected within 7 days) — skip")
                continue

            # Skip if already PROPOSED and pending approval
            existing = self.opportunity_manager.get_ticker(ticker)
            if existing and existing.get("status") == "PROPOSED":
                self.logger.info(f"  {ticker}: already PROPOSED — skip re-analysis")
                continue

            try:
                result = self.twin_engine.analyze(ticker, prescreen_data=candidate)
                analyzed.append(result)

                score = result["final_score"]
                rec = result["recommendation"]

                self._log_decision(ticker, rec, score,
                                   f"Growth={result['growth']['score']:.2f} "
                                   f"Multiple={result['multiple']['score']:.2f} "
                                   f"Mgmt={result['management']['score']:.2f}")

                if rec == "PROPOSE":
                    proposals.append(result)
                    self.opportunity_manager.upsert(ticker, "MONITORING", score=score,
                                                    details=result, reason="Passed TwinEngine threshold")
                elif rec == "MONITOR":
                    self.opportunity_manager.upsert(ticker, "MONITORING", score=score,
                                                    details=result, reason="Below propose threshold")
                else:
                    # SKIP — only add to WATCHLIST if score is close (>0.40)
                    if score >= 0.40:
                        self.opportunity_manager.set_watchlist(ticker, score=score, details=result)

            except Exception as e:
                self.logger.error(f"TwinEngine failed for {ticker}: {e}", exc_info=True)

        # Stage 4: Entry signal check for PROPOSE candidates
        triggered = self._check_entry_signals(proposals)

        elapsed = (datetime.utcnow() - start).seconds
        self.logger.info(
            f"=== Daily Screening Complete: {len(analyzed)} analyzed, "
            f"{len(proposals)} proposals, {len(triggered)} sent === ({elapsed}s)"
        )
        return {
            "status": "OK",
            "analyzed": len(analyzed),
            "proposals": len(proposals),
            "triggered": len(triggered),
            "elapsed_s": elapsed,
        }

    # ─────────────────────────────────────────────────────────────────
    # Hourly watchlist re-score + entry signal check
    # ─────────────────────────────────────────────────────────────────

    def run_hourly_check(self) -> dict:
        """
        Re-score MONITORING watchlist entries and check entry signals.
        Lighter than full screening — no Stage 1+2, just TwinEngine + entry check.
        """
        self.logger.info("=== Hourly Watchlist Check ===")
        monitoring = self.opportunity_manager.get_monitoring()
        if not monitoring:
            return {"status": "NO_MONITORING", "checked": 0}

        propose_threshold = self._get_effective_propose_threshold()
        proposals = []

        for entry in monitoring:
            ticker = entry["ticker"]
            if self.opportunity_manager.is_blacklisted(ticker):
                continue
            if entry.get("status") == "PROPOSED":
                continue
            try:
                result = self.twin_engine.analyze(ticker)
                score = result["final_score"]

                if score >= propose_threshold:
                    result["recommendation"] = "PROPOSE"
                    proposals.append(result)
                    self.opportunity_manager.upsert(ticker, "MONITORING", score=score,
                                                    details=result, reason="Re-scored above propose threshold")
                else:
                    self.opportunity_manager.upsert(ticker, entry["status"], score=score,
                                                    details=result, reason="Hourly re-score")
            except Exception as e:
                self.logger.error(f"Hourly re-score failed for {ticker}: {e}")

        triggered = self._check_entry_signals(proposals)
        self.logger.info(f"Hourly check: {len(monitoring)} checked, {len(triggered)} proposals sent")
        return {"status": "OK", "checked": len(monitoring), "triggered": len(triggered)}

    # ─────────────────────────────────────────────────────────────────
    # Entry signal check (Stage 4)
    # ─────────────────────────────────────────────────────────────────

    def _check_entry_signals(self, candidates: list) -> list:
        """
        For each candidate with recommendation=PROPOSE, verify entry signal:
          - RSI not overbought (< 70)
          - Not in earnings blackout
          - Portfolio not at max positions
          - Sector not at concentration limit
        Then send Telegram proposal and mark PROPOSED.
        """
        from stocks.utils.telegram_approval import send_proposal
        trade_log = self._load_trade_log()
        portfolio_cash = self._get_param("portfolio_cash_usd", 20_000)
        blackout_days = self._get_param("earnings_blackout_days", 5)
        triggered = []

        for result in candidates:
            ticker = result["ticker"]
            try:
                info = self._yf.get_info(ticker) if self._yf else {}
                sector = info.get("sector", "Unknown")
                current_price = (info.get("currentPrice") or info.get("regularMarketPrice") or 0)
                if current_price <= 0:
                    current_price = self._yf.get_current_price(ticker) or 0

                # RSI check
                rsi = self._yf.get_rsi(ticker) if self._yf else None

                # Earnings blackout
                days_to_earn = self._yf.days_to_earnings(ticker) if self._yf else None
                if days_to_earn is not None and 0 <= days_to_earn <= blackout_days:
                    self.logger.info(f"  {ticker}: earnings in {days_to_earn}d — entry signal blocked")
                    continue

                # Risk manager validation
                risk = self.risk_manager.compute_position(
                    ticker=ticker,
                    current_price=current_price,
                    portfolio_cash=portfolio_cash,
                    trade_log=trade_log,
                    sector=sector,
                    rsi=rsi,
                )

                if not risk["approved"]:
                    self.logger.info(f"  {ticker}: risk veto — {risk['reason']}")
                    self._log_decision(ticker, "RISK_VETO", result["final_score"], risk["reason"])
                    continue

                # Build proposal payload
                mgmt = result.get("management", {})
                rev_cagr = None
                if self._fmp:
                    try:
                        cagr = self._fmp.get_revenue_cagr(ticker, years=3)
                        rev_cagr = round(cagr * 100, 1) if cagr is not None else None
                    except Exception:
                        pass

                # P/E vs 5yr avg %
                pe_info = info.get("trailingPE")
                pe_vs_avg = None
                if pe_info:
                    avg_est = pe_info * 1.2
                    pe_vs_avg = round((pe_info / avg_est - 1) * 100, 1)

                proposal_payload = {
                    "final_score": result["final_score"],
                    "growth_score": result["growth"]["score"],
                    "multiple_score": result["multiple"]["score"],
                    "management_score": result["management"]["score"],
                    "moat_score": result["moat"]["score"],
                    "sentiment_score": result["sentiment"]["score"],
                    "revenue_cagr_pct": rev_cagr,
                    "pe_vs_avg_pct": pe_vs_avg,
                    "founder_ceo": mgmt.get("founder_ceo", False),
                    "insider_pct": mgmt.get("insider_pct"),
                    "insider_net_shares_90d": mgmt.get("insider_net_shares_90d", 0),
                    "moat_summary": result["moat"].get("summary", ""),
                    "shares": risk["shares"],
                    "price": risk["limit_price"],
                    "total_cost_usd": risk["total_cost"],
                    "portfolio_pct": risk["portfolio_pct"],
                    "stop_price": risk["stop_price"],
                    "stop_pct": risk["stop_pct"],
                }

                ok = send_proposal(ticker, proposal_payload)
                if ok:
                    self.opportunity_manager.set_proposed(ticker, proposal_payload)
                    self._log_decision(ticker, "PROPOSED", result["final_score"],
                                       f"Telegram proposal sent: {risk['shares']}sh @ ${risk['limit_price']:.2f}")
                    triggered.append(ticker)
                    self.logger.info(f"  {ticker}: PROPOSED via Telegram ({risk['shares']} shares @ ${risk['limit_price']:.2f})")
                else:
                    self.logger.warning(f"  {ticker}: Telegram proposal failed — keeping in MONITORING")

            except Exception as e:
                self.logger.error(f"Entry signal check failed for {ticker}: {e}", exc_info=True)

        return triggered

    # ─────────────────────────────────────────────────────────────────
    # Approval processing
    # ─────────────────────────────────────────────────────────────────

    def process_approvals(self, approvals: list) -> dict:
        """
        Process a list of {ticker, action} dicts from Telegram poll.
        Actions: BUY, SKIP, WATCHLIST

        In Phase 1 (no IBKR): BUY → log as APPROVED, alert user.
        """
        from stocks.utils.telegram_approval import send_alert
        results = {"approved": [], "rejected": [], "watchlisted": []}

        for approval in approvals:
            ticker = approval["ticker"]
            action = approval["action"]

            entry = self.opportunity_manager.get_ticker(ticker)
            if not entry:
                self.logger.warning(f"Approval for unknown ticker {ticker} — ignoring")
                continue

            if action == "BUY":
                self.opportunity_manager.set_approved(ticker)
                self._log_decision(ticker, "APPROVED", entry.get("score", 0),
                                   "User approved via Telegram")
                send_alert(
                    f"APPROVED: {ticker} — [Phase 1] No IBKR execution yet. "
                    f"Track manually. Score: {entry.get('score', 0):.2f}"
                )
                results["approved"].append(ticker)
                self.logger.info(f"Approval: {ticker} → APPROVED (Phase 1: manual tracking)")

            elif action == "SKIP":
                self.opportunity_manager.set_rejected(ticker)
                self._log_decision(ticker, "REJECTED", entry.get("score", 0),
                                   "User rejected via Telegram (7d blackout)")
                send_alert(f"SKIPPED: {ticker} — 7-day blackout applied")
                results["rejected"].append(ticker)
                self.logger.info(f"Approval: {ticker} → REJECTED (7d blackout)")

            elif action == "WATCHLIST":
                self.opportunity_manager.set_watchlist(ticker, score=entry.get("score", 0))
                self._log_decision(ticker, "WATCHLIST", entry.get("score", 0),
                                   "User moved to WATCHLIST via Telegram")
                send_alert(f"WATCHLIST: {ticker} — added to monitoring")
                results["watchlisted"].append(ticker)
                self.logger.info(f"Approval: {ticker} → WATCHLIST")

        return results

    # ─────────────────────────────────────────────────────────────────
    # Expiry / maintenance
    # ─────────────────────────────────────────────────────────────────

    def expire_stale_proposals(self):
        """Move proposals older than 24h to WATCHLIST (no-reply policy)."""
        self.opportunity_manager.expire_old_proposals(hours=24)
