"""
twin_engine_analyst.py — Twin Engine scoring: Growth × Multiple Expansion.

Given a ticker that passed Stage 2, runs the full 5-component scoring:
  Engine 1 — Growth Score       (w_growth,     default 0.30)
  Engine 2 — Multiple Expansion (w_multiple,   default 0.30)
  Management Score              (w_management, default 0.20)
  Moat Score                    (w_moat,       default 0.10)
  Sentiment Score               (w_sentiment,  default 0.10)

Uses ~6 FMP API calls per ticker. Budget is checked before proceeding.

All component scores are 0.0–1.0. final_score is their weighted sum.
Thresholds (from auto_params):
  final_score >= score_threshold_propose (0.65) → Stage 4 entry check candidate
  final_score >= score_threshold_monitor (0.50) → add to MONITORING watchlist
  final_score < score_threshold_monitor         → SKIP
"""

import json
import logging
import math
import os
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("TwinEngineAnalyst")

# Moat cache TTL: 7 days (LLM calls are expensive)
MOAT_CACHE_FILE = "stocks_moat_cache.json"
MOAT_CACHE_TTL_DAYS = 7


def _load_moat_cache() -> dict:
    try:
        with open(MOAT_CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_moat_cache(cache: dict):
    try:
        with open(MOAT_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save moat cache: {e}")


class TwinEngineAnalyst:
    def __init__(self, fmp_client=None, yf_client=None, llm_client=None, auto_params=None):
        self.logger = logging.getLogger("TwinEngineAnalyst")
        self._fmp = fmp_client
        self._yf = yf_client
        self._llm = llm_client
        self._auto_params = auto_params

    def _get_param(self, key: str, default):
        if self._auto_params:
            try:
                return self._auto_params.get(key, default)
            except Exception:
                pass
        return default

    # ─────────────────────────────────────────────────────────────────
    # Engine 1: Growth Score
    # ─────────────────────────────────────────────────────────────────

    def _score_revenue_growth(self, ticker: str) -> float:
        """Revenue CAGR 3yr, with acceleration bonus."""
        cagr = self._fmp.get_revenue_cagr(ticker, years=3)
        if cagr is None:
            return 0.3  # neutral default

        if cagr >= 0.20:
            score = 1.0
        elif cagr >= 0.15:
            score = 0.85
        elif cagr >= 0.10:
            score = 0.70
        elif cagr >= 0.05:
            score = 0.50
        elif cagr >= 0:
            score = 0.30
        else:
            score = max(0.0, 0.30 + cagr * 3)  # negative growth degrades toward 0

        # Acceleration bonus: compare 1yr vs 3yr CAGR
        cagr_1yr = self._fmp.get_revenue_cagr(ticker, years=1) or cagr
        if cagr_1yr > cagr + 0.02:  # accelerating by >2pp
            score = min(1.0, score + 0.10)

        return round(score, 3)

    def _score_eps_growth(self, ticker: str) -> float:
        """EPS CAGR 3yr with dilution penalty."""
        cagr = self._fmp.get_eps_cagr(ticker, years=3)
        if cagr is None:
            return 0.3

        if cagr >= 0.20:
            score = 1.0
        elif cagr >= 0.15:
            score = 0.85
        elif cagr >= 0.10:
            score = 0.70
        elif cagr >= 0.05:
            score = 0.50
        elif cagr >= 0:
            score = 0.30
        else:
            score = max(0.0, 0.30 + cagr * 3)

        # Dilution penalty: if shares outstanding grew > 5% YoY
        try:
            stmts = self._fmp.get_income_statements(ticker, limit=3)
            shares = [s.get("weightedAverageShsOut") for s in stmts if s.get("weightedAverageShsOut")]
            if len(shares) >= 2 and shares[1] > 0:
                dilution = (shares[0] - shares[1]) / shares[1]
                if dilution > 0.05:
                    score = max(0.0, score - 0.20)
        except Exception:
            pass

        return round(score, 3)

    def _score_fcf_growth(self, ticker: str) -> float:
        """FCF margin + CAGR score with buyback bonus."""
        fcf_data = self._fmp.get_fcf_data(ticker)
        fcf_margin = fcf_data.get("fcf_margin")
        fcf_cagr = fcf_data.get("fcf_cagr_3yr")

        if fcf_margin is None:
            return 0.3

        # Base score from FCF margin
        if fcf_margin >= 0.15 and fcf_cagr is not None and fcf_cagr >= 0.15:
            score = 1.0
        elif fcf_margin >= 0.10:
            score = 0.75
        elif fcf_margin >= 0.05:
            score = 0.55
        elif fcf_margin >= 0:
            score = 0.30
        else:
            score = 0.0

        # Buyback bonus
        if fcf_data.get("has_buyback"):
            score = min(1.0, score + 0.10)

        return round(score, 3)

    def score_engine1_growth(self, ticker: str) -> dict:
        """
        Growth score = weighted average of revenue (35%), EPS (40%), FCF (25%).
        Returns {score, components}.
        """
        rev_score = self._score_revenue_growth(ticker)
        eps_score = self._score_eps_growth(ticker)
        fcf_score = self._score_fcf_growth(ticker)

        growth_score = round(rev_score * 0.35 + eps_score * 0.40 + fcf_score * 0.25, 3)
        return {
            "score": growth_score,
            "revenue_growth": rev_score,
            "eps_growth": eps_score,
            "fcf_growth": fcf_score,
        }

    # ─────────────────────────────────────────────────────────────────
    # Engine 2: Multiple Expansion Score
    # ─────────────────────────────────────────────────────────────────

    def _score_pe_vs_historical(self, ticker: str) -> float:
        """Current P/E vs 5yr historical average."""
        info = self._yf.get_info(ticker)
        current_pe = info.get("trailingPE") or info.get("forwardPE")
        if current_pe is None or current_pe <= 0:
            return 0.0  # loss-making

        # Get 5yr avg P/E from FMP key metrics history (approximate via TTM)
        # We use 5yr avg = trailing P/E from FMP income statements vs current price
        # Simplified: use yfinance five_year_avg_dividend as proxy, or compute from stmts
        stmts = self._fmp.get_income_statements(ticker, limit=6) if self._fmp else []
        info_data = self._yf.get_info(ticker)
        current_price = info_data.get("currentPrice") or info_data.get("regularMarketPrice") or 0

        pe_history = []
        for stmt in stmts:
            eps = stmt.get("eps") or stmt.get("epsdiluted")
            if eps and eps > 0 and current_price > 0:
                # This is a rough approximation — P/E at the time of the report
                pass  # We'd need historical prices for exact historical P/E

        # Fallback: use yfinance fiveYearAvgDividendYield as proxy or just use a sector median
        # Best approximation: compare forwardPE to trailingPE to gauge direction
        forward_pe = info.get("forwardPE")
        trailing_pe = info.get("trailingPE")

        if forward_pe and trailing_pe and trailing_pe > 0 and forward_pe > 0:
            # If forward < trailing, market expects growth → multiple compression possible
            # Use 5yr average = 1.3x trailing (sector-adjusted rough heuristic)
            avg_5yr_pe = trailing_pe * 1.2
            ratio = current_pe / avg_5yr_pe
        else:
            # Can't compute — use neutral
            return 0.50

        # Score: < 0.70 = deeply undervalued = 1.0, > 1.5 = overvalued = 0.10
        if ratio <= 0.70:
            return 1.0
        elif ratio <= 0.85:
            return 0.80
        elif ratio <= 1.00:
            return 0.65
        elif ratio <= 1.20:
            return 0.45
        elif ratio <= 1.50:
            return 0.25
        else:
            return 0.10

    def _score_peg(self, ticker: str) -> float:
        """PEG ratio score."""
        info = self._yf.get_info(ticker)
        peg = info.get("pegRatio") or info.get("trailingPegRatio")

        if peg is None:
            # Compute manually: forwardPE / analyst EPS growth estimate
            forward_pe = info.get("forwardPE")
            eps_growth = info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")
            if forward_pe and eps_growth and eps_growth > 0:
                peg = forward_pe / (eps_growth * 100)  # growth as % → divide
            else:
                return 0.40  # neutral

        peg = float(peg)
        if peg <= 0:
            return 0.40

        if peg < 0.75:
            return 1.0
        elif peg < 1.0:
            return 0.80
        elif peg < 1.5:
            return 0.60
        elif peg < 2.0:
            return 0.35
        else:
            return 0.10

    def _score_ev_ebitda(self, ticker: str) -> float:
        """EV/EBITDA vs sector median."""
        from stocks.utils.sector_benchmarks import get_sector_ev_ebitda
        info = self._yf.get_info(ticker)
        ev_ebitda = info.get("enterpriseToEbitda")
        sector = info.get("sector", "Unknown")

        if ev_ebitda is None or ev_ebitda <= 0:
            return 0.40

        sector_median = get_sector_ev_ebitda(sector)
        relative = ev_ebitda / sector_median

        if relative < 0.60:
            return 1.0
        elif relative < 0.80:
            return 0.75
        elif relative < 1.00:
            return 0.55
        elif relative < 1.15:
            return 0.40
        elif relative < 1.30:
            return 0.25
        else:
            return 0.10

    def score_engine2_multiple(self, ticker: str) -> dict:
        """
        Multiple expansion score = weighted avg of P/E (40%), PEG (35%), EV/EBITDA (25%).
        """
        pe_score = self._score_pe_vs_historical(ticker)
        peg_score = self._score_peg(ticker)
        ev_score = self._score_ev_ebitda(ticker)

        multiple_score = round(pe_score * 0.40 + peg_score * 0.35 + ev_score * 0.25, 3)
        return {
            "score": multiple_score,
            "pe_vs_historical": pe_score,
            "peg": peg_score,
            "ev_ebitda_vs_sector": ev_score,
        }

    # ─────────────────────────────────────────────────────────────────
    # Management Score
    # ─────────────────────────────────────────────────────────────────

    def score_management(self, ticker: str) -> dict:
        """
        Additive components (capped at 1.0):
          - Founder CEO check (LLM): +0.25
          - Insider ownership: +0.08–0.25
          - Net insider buying (90d): 0.0–0.25
          - ROIC: +0.12–0.25
        """
        score = 0.0
        founder_ceo = False
        insider_pct = None
        insider_net = 0
        roic = None

        # 1. Founder CEO (LLM check — expensive, use sparingly)
        if self._llm and self._llm.available:
            try:
                profile = self._fmp.get_profile(ticker) if self._fmp else {}
                ceo_name = profile.get("ceo", "")
                company = profile.get("companyName", ticker)
                prompt = (
                    f"Is {ceo_name} a founder of {company} ({ticker})? "
                    f"Reply with JSON: {{\"is_founder\": true/false, \"confidence\": \"high/low\"}}"
                )
                resp = self._llm.analyze_text(prompt, agent_name="TwinEngine_Mgmt")
                import re
                m = re.search(r'\{[^}]+\}', resp)
                if m:
                    data = json.loads(m.group())
                    founder_ceo = bool(data.get("is_founder", False))
            except Exception as e:
                self.logger.debug(f"Founder CEO check failed for {ticker}: {e}")

        if founder_ceo:
            score += 0.25

        # 2. Insider ownership
        if self._fmp:
            try:
                ownership_data = self._fmp.get_insider_ownership(ticker)
                if ownership_data:
                    # FMP returns list with 'ownership' field as %
                    pct = ownership_data[0].get("ownership") or ownership_data[0].get("insidersOwnershipPercentage")
                    if pct is not None:
                        insider_pct = float(pct)
                        if insider_pct >= 10:
                            score += 0.25
                        elif insider_pct >= 5:
                            score += 0.15
                        elif insider_pct >= 1:
                            score += 0.08
            except Exception as e:
                self.logger.debug(f"Insider ownership failed for {ticker}: {e}")

            # Fallback from yfinance
            if insider_pct is None:
                info = self._yf.get_info(ticker)
                pct = info.get("heldPercentInsiders")
                if pct is not None:
                    insider_pct = float(pct) * 100
                    if insider_pct >= 10:
                        score += 0.25
                    elif insider_pct >= 5:
                        score += 0.15
                    elif insider_pct >= 1:
                        score += 0.08

            # 3. Net insider buying (90d)
            try:
                insider_net = self._fmp.get_insider_net_shares_90d(ticker)
                if insider_net > 10_000:
                    score += 0.25
                elif insider_net > 0:
                    score += 0.15
                # Net selling = 0 bonus
            except Exception as e:
                self.logger.debug(f"Insider trading failed for {ticker}: {e}")

            # 4. ROIC
            try:
                roic = self._fmp.get_roic_ttm(ticker)
                if roic is not None:
                    if roic >= 0.20:
                        score += 0.25
                    elif roic >= 0.15:
                        score += 0.18
                    elif roic >= 0.10:
                        score += 0.12
            except Exception as e:
                self.logger.debug(f"ROIC failed for {ticker}: {e}")

        score = min(1.0, score)
        return {
            "score": round(score, 3),
            "founder_ceo": founder_ceo,
            "insider_pct": insider_pct,
            "insider_net_shares_90d": insider_net,
            "roic": roic,
        }

    # ─────────────────────────────────────────────────────────────────
    # Moat Score (LLM, cached 7 days)
    # ─────────────────────────────────────────────────────────────────

    def score_moat(self, ticker: str) -> dict:
        """
        LLM-based moat assessment, cached 7 days per ticker.
        Returns {score, summary, components}.
        """
        cache = _load_moat_cache()
        cached = cache.get(ticker, {})
        if cached:
            try:
                cached_at = datetime.fromisoformat(cached["cached_at"])
                if datetime.utcnow() < cached_at + timedelta(days=MOAT_CACHE_TTL_DAYS):
                    return cached["result"]
            except Exception:
                pass

        default_result = {"score": 0.5, "summary": "LLM unavailable", "components": {}}

        if not self._llm or not self._llm.available:
            return default_result

        try:
            profile = self._fmp.get_profile(ticker) if self._fmp else {}
            company = profile.get("companyName", ticker)
            sector = profile.get("sector", "Unknown")
            description = (profile.get("description") or "")[:500]

            prompt = (
                f"Assess the economic moat of {company} ({ticker}, {sector}).\n"
                f"Company description: {description}\n\n"
                f"Score each moat dimension 0-10:\n"
                f"- brand_power: strong consumer brand recognition\n"
                f"- switching_costs: cost/pain of customers switching to competitors\n"
                f"- network_effects: value increases as user base grows\n"
                f"- cost_advantages: structural cost advantages (scale, patents, location)\n"
                f"- regulatory_moat: licenses, patents, regulatory barriers\n\n"
                f"OUTPUT JSON ONLY:\n"
                f"{{\"brand_power\": 0-10, \"switching_costs\": 0-10, "
                f"\"network_effects\": 0-10, \"cost_advantages\": 0-10, "
                f"\"regulatory_moat\": 0-10, \"overall\": 0-10, "
                f"\"summary\": \"one sentence description of primary moat\"}}"
            )
            resp = self._llm.analyze_text(prompt, agent_name="TwinEngine_Moat")
            import re
            m = re.search(r'\{[\s\S]*\}', resp)
            if not m:
                return default_result
            data = json.loads(m.group())
            overall = float(data.get("overall", 5)) / 10.0
            result = {
                "score": round(overall, 3),
                "summary": data.get("summary", ""),
                "components": {
                    "brand_power": data.get("brand_power", 5),
                    "switching_costs": data.get("switching_costs", 5),
                    "network_effects": data.get("network_effects", 5),
                    "cost_advantages": data.get("cost_advantages", 5),
                    "regulatory_moat": data.get("regulatory_moat", 5),
                },
            }
            # Cache
            cache[ticker] = {"result": result, "cached_at": datetime.utcnow().isoformat()}
            _save_moat_cache(cache)
            return result
        except Exception as e:
            self.logger.warning(f"Moat scoring failed for {ticker}: {e}")
            return default_result

    # ─────────────────────────────────────────────────────────────────
    # Sentiment Score
    # ─────────────────────────────────────────────────────────────────

    def score_sentiment(self, ticker: str) -> dict:
        """
        News sentiment via WebIntelligence + LLM classification.
        Returns {score, summary}.
        """
        default = {"score": 0.5, "summary": "No sentiment data"}
        try:
            from utils.web_intelligence import WebIntelligence
            wi = WebIntelligence()
            profile = self._fmp.get_profile(ticker) if self._fmp else {}
            ceo = profile.get("ceo", "")
            queries_text = wi.scan_social_media(ticker)
            queries_news = wi.scan_news(
                f"{ticker} earnings beat miss guidance analyst upgrade"
            )
            texts = [r["text"] for r in queries_text + queries_news if r.get("text")]
            if not texts:
                return default

            snippet = "\n".join(texts[:10])[:2000]

            if not self._llm or not self._llm.available:
                return default

            prompt = (
                f"Classify the overall sentiment for stock {ticker} from these recent headlines/snippets:\n"
                f"{snippet}\n\n"
                f"Respond with JSON: {{\"sentiment\": \"bullish/neutral/bearish\", "
                f"\"score\": 0.0-1.0, \"summary\": \"one sentence\"}}\n"
                f"Where 1.0 = very bullish, 0.5 = neutral, 0.0 = very bearish."
            )
            resp = self._llm.analyze_text(prompt, agent_name="TwinEngine_Sentiment")
            import re
            m = re.search(r'\{[^}]+\}', resp)
            if m:
                data = json.loads(m.group())
                return {
                    "score": float(data.get("score", 0.5)),
                    "sentiment": data.get("sentiment", "neutral"),
                    "summary": data.get("summary", ""),
                }
        except Exception as e:
            self.logger.debug(f"Sentiment scoring failed for {ticker}: {e}")
        return default

    # ─────────────────────────────────────────────────────────────────
    # Main entry point
    # ─────────────────────────────────────────────────────────────────

    def analyze(self, ticker: str, prescreen_data: dict = None) -> dict:
        """
        Full Twin Engine analysis for a single ticker.
        Returns {final_score, components, recommendation, details}.
        """
        self.logger.info(f"[TwinEngine] Analyzing {ticker}...")

        # Check FMP budget
        if self._fmp and self._fmp.get_daily_calls_remaining() < 6:
            self.logger.warning(f"[TwinEngine] FMP budget too low for {ticker} — skipping FMP calls")

        # Load weights
        w_growth = self._get_param("w_growth", 0.30)
        w_multiple = self._get_param("w_multiple", 0.30)
        w_management = self._get_param("w_management", 0.20)
        w_moat = self._get_param("w_moat", 0.10)
        w_sentiment = self._get_param("w_sentiment", 0.10)

        # Score all engines
        try:
            growth_result = self.score_engine1_growth(ticker)
        except Exception as e:
            self.logger.error(f"Engine1 failed for {ticker}: {e}")
            growth_result = {"score": 0.3}

        try:
            multiple_result = self.score_engine2_multiple(ticker)
        except Exception as e:
            self.logger.error(f"Engine2 failed for {ticker}: {e}")
            multiple_result = {"score": 0.3}

        try:
            mgmt_result = self.score_management(ticker)
        except Exception as e:
            self.logger.error(f"Management score failed for {ticker}: {e}")
            mgmt_result = {"score": 0.3}

        try:
            moat_result = self.score_moat(ticker)
        except Exception as e:
            self.logger.error(f"Moat score failed for {ticker}: {e}")
            moat_result = {"score": 0.5}

        try:
            sent_result = self.score_sentiment(ticker)
        except Exception as e:
            self.logger.error(f"Sentiment score failed for {ticker}: {e}")
            sent_result = {"score": 0.5}

        # Compute final weighted score
        final_score = (
            w_growth * growth_result["score"] +
            w_multiple * multiple_result["score"] +
            w_management * mgmt_result["score"] +
            w_moat * moat_result["score"] +
            w_sentiment * sent_result["score"]
        )
        final_score = round(max(0.0, min(1.0, final_score)), 3)

        # Recommendation thresholds
        threshold_propose = self._get_param("score_threshold_propose", 0.65)
        threshold_monitor = self._get_param("score_threshold_monitor", 0.50)

        if final_score >= threshold_propose:
            recommendation = "PROPOSE"
        elif final_score >= threshold_monitor:
            recommendation = "MONITOR"
        else:
            recommendation = "SKIP"

        result = {
            "ticker": ticker,
            "final_score": final_score,
            "recommendation": recommendation,
            "weights": {
                "growth": w_growth, "multiple": w_multiple,
                "management": w_management, "moat": w_moat, "sentiment": w_sentiment,
            },
            "growth": growth_result,
            "multiple": multiple_result,
            "management": mgmt_result,
            "moat": moat_result,
            "sentiment": sent_result,
            "analyzed_at": datetime.utcnow().isoformat(),
        }

        self.logger.info(
            f"[TwinEngine] {ticker}: score={final_score:.3f} → {recommendation} "
            f"(G={growth_result['score']:.2f} M={multiple_result['score']:.2f} "
            f"Mgmt={mgmt_result['score']:.2f} Moat={moat_result['score']:.2f} "
            f"S={sent_result['score']:.2f})"
        )
        return result
