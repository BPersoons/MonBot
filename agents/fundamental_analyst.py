import logging
import datetime
import time
import re
from utils.web_intelligence import WebIntelligence
from utils.llm_client import LLMClient
from core.xyz_tokens import XYZ_EQUITY_MAP

# Module-level yfinance cache (4h TTL) — avoids repeat calls within a session
_yf_cache: dict = {}


class FundamentalAnalyst:
    """
    Fundamental Analyst Agent (Macro-Expert).
    
    Analyzes real-time fundamental data using web intelligence + LLM scoring:
    - ETF inflows/outflows
    - Whale movements and on-chain metrics
    - Regulatory news (SEC, legislation)
    - Network health (TVL, active addresses, protocol updates)
    
    Same architecture as SentimentAnalyst: WebIntelligence gathers data,
    LLMClient scores it. No simulated/random data.
    """

    def __init__(self, db_client=None):
        self.logger = logging.getLogger("FundamentalAnalyst")
        self.web_intel = WebIntelligence()
        self.llm = LLMClient(model_name="gemini-3-flash-preview")
        self.db_client = db_client
        self.last_analysis_time = {}  # Cache timestamp per ticker

    def _detect_asset_class(self, base_ticker: str) -> str:
        """Detects asset class from base ticker. Returns 'commodity', 'equity', 'index', or 'crypto'."""
        from core.strategy_logic import COMMODITY_TICKERS
        # FA-specific extras: XYZ-WTIOIL (alt crude ticker) and PAXG (gold-backed token)
        fa_commodities = COMMODITY_TICKERS | {'XYZ-WTIOIL', 'PAXG'}
        indices = {'XYZ-SP500', 'XYZ-XYZ100'}
        if base_ticker in fa_commodities:
            return 'commodity'
        if base_ticker in XYZ_EQUITY_MAP:
            return 'equity'
        if base_ticker in indices:
            return 'index'
        return 'crypto'

    def _get_equity_financials(self, base_symbol: str) -> str:
        """Fetch real financial metrics from yfinance for an equity symbol (e.g. 'NVDA').
        Returns a formatted block to prepend to the LLM prompt, or '' on failure."""
        now = time.time()
        cached = _yf_cache.get(base_symbol)
        if cached:
            text, ts = cached
            if now - ts < 4 * 3600:
                return text

        try:
            import yfinance as yf
            info = yf.Ticker(base_symbol).info

            parts = []
            pe = info.get("trailingPE")
            fpe = info.get("forwardPE")
            eps = info.get("trailingEps")
            earn_growth = info.get("earningsGrowth")
            rev_growth = info.get("revenueGrowth")
            profit_margin = info.get("profitMargins")
            rec_mean = info.get("recommendationMean")
            target = info.get("targetMeanPrice")
            price = info.get("currentPrice") or info.get("regularMarketPrice")
            week52_change = info.get("52WeekChange")

            if pe is not None:          parts.append(f"Trailing P/E: {pe:.1f}x")
            if fpe is not None:         parts.append(f"Forward P/E: {fpe:.1f}x")
            if eps is not None:         parts.append(f"EPS (TTM): ${eps:.2f}")
            if earn_growth is not None: parts.append(f"EPS Growth YoY: {earn_growth*100:+.1f}%")
            if rev_growth is not None:  parts.append(f"Revenue Growth YoY: {rev_growth*100:+.1f}%")
            if profit_margin is not None: parts.append(f"Profit Margin: {profit_margin*100:.1f}%")
            if rec_mean is not None:
                label = {1: "Strong Buy", 2: "Buy", 3: "Hold", 4: "Sell", 5: "Strong Sell"}.get(round(rec_mean), "")
                parts.append(f"Analyst Consensus: {rec_mean:.1f}/5 ({label})")
            if target is not None and price:
                upside = (target - price) / price * 100
                parts.append(f"Mean Target: ${target:.2f} ({upside:+.1f}% upside)")
            if week52_change is not None: parts.append(f"52-Week Change: {week52_change*100:+.1f}%")

            if not parts:
                _yf_cache[base_symbol] = ("", now)
                return ""

            lines = ["=== REAL FINANCIAL DATA (yfinance) ==="]
            lines.append("  |  ".join(parts[:5]))
            if len(parts) > 5:
                lines.append("  |  ".join(parts[5:]))
            lines.append("======================================")
            text = "\n".join(lines)

            _yf_cache[base_symbol] = (text, now)
            self.logger.info(f"[FA] yfinance enrichment: {base_symbol} — {', '.join(parts[:3])}")
            return text

        except Exception as e:
            self.logger.warning(f"[FA] yfinance fetch failed for {base_symbol}: {e}")
            _yf_cache[base_symbol] = ("", now)
            return ""

    def _gather_fundamental_data(self, ticker: str) -> list[dict]:
        """
        Gathers real fundamental data via web search.
        Runs multiple targeted queries for different fundamental aspects.
        """
        base_ticker = ticker.split('/')[0] if '/' in ticker else ticker
        asset_class = self._detect_asset_class(base_ticker)

        if asset_class == 'commodity':
            readable = base_ticker.replace('XYZ-', '').lower()
            if readable == 'brentoil':
                readable = 'crude oil brent'
            elif readable == 'paxg':
                readable = 'gold'
            queries = [
                f"{readable} ETF flows institutional demand latest",
                f"{readable} futures open interest COT report positioning",
                f"DXY dollar index Fed policy inflation {readable} outlook",
                f"OPEC supply output {readable}" if 'oil' in readable else f"{readable} central bank reserves demand",
                f"{readable} spot price technical macro catalyst",
            ]
        elif asset_class == 'equity':
            readable = base_ticker.replace('XYZ-', '').upper()
            queries = [
                f"{readable} earnings revenue guidance analyst latest",
                f"{readable} institutional holdings SEC 13F fund flows",
                f"{readable} analyst upgrade downgrade price target",
                f"{readable} macro interest rate policy sector impact",
                f"{readable} stock news catalyst product launch",
            ]
        elif asset_class == 'index':
            queries = [
                "S&P 500 Fed policy rate decision interest rates outlook",
                "S&P 500 earnings season breadth revenue growth",
                "VIX volatility index fear greed market risk-off",
                "S&P 500 sector rotation institutional flows latest",
                "CPI inflation jobs report macro economic data S&P 500",
            ]
        else:  # crypto
            # Strip exchange prefixes (XYZ-, k, etc.) for readable search terms
            readable = base_ticker.replace('XYZ-', '').replace('k', '').upper()
            queries = [
                f"{readable} crypto ETF inflow outflow latest",
                f"{readable} whale alert large transaction exchange",
                f"{readable} on-chain metrics TVL active addresses",
                f"{readable} crypto regulation news SEC",
                f"{readable} protocol upgrade news development",
            ]
        
        all_data = []
        for q in queries:
            try:
                news_results = self.web_intel.scan_news(q)
                all_data.extend(news_results)
            except Exception as e:
                self.logger.warning(f"Fundamental data fetch failed for query '{q}': {e}")
        
        self.logger.info(f"Gathered {len(all_data)} fundamental data points for {ticker}")
        return all_data

    def _filter_data(self, data: list[dict]) -> list[dict]:
        """Remove duplicates and low-quality items."""
        seen_texts = set()
        filtered = []
        
        for item in data:
            text = item.get('text', '').strip()
            if len(text) < 15:
                continue
            # Simple dedup on first 80 chars
            key = text[:80].lower()
            if key in seen_texts:
                continue
            seen_texts.add(key)
            filtered.append(item)
        
        return filtered

    def _analyze_with_llm(self, ticker: str, data: list[dict]) -> tuple[float, str, list[str]]:
        """
        Uses LLM to score the fundamental data.
        Returns: (score, rationale, reasoning_list)
        """
        combined_text = "\n".join([f"- [{d.get('source', 'news')}] {d['text']}" for d in data[:15]])  # Limit to 15 items

        base_ticker = ticker.split('/')[0] if '/' in ticker else ticker
        asset_class = self._detect_asset_class(base_ticker)

        # For XYZ equity tokens, prepend real financial metrics so the LLM has actual numbers
        if asset_class == 'equity':
            base_symbol = XYZ_EQUITY_MAP.get(base_ticker)
            if base_symbol:
                financials = self._get_equity_financials(base_symbol)
                if financials:
                    combined_text = financials + "\n\n" + combined_text

        if asset_class == 'commodity':
            analyst_role = "commodity macro analyst"
            categories = (
                "1. INSTITUTIONAL DEMAND: ETF flows, central bank buying/selling, futures positioning (COT report)\n"
                "2. MACRO / USD: Dollar strength (DXY), Fed rate policy, inflation expectations\n"
                "3. SUPPLY FACTORS: OPEC output (for oil), mine/production disruptions (for gold/silver)\n"
                "4. OPEN INTEREST: Futures market positioning — are speculators net long or short?\n"
                "5. GEOPOLITICAL / RISK-OFF: Safe-haven demand or risk-on rotation away from commodities?"
            )
        elif asset_class == 'equity':
            analyst_role = "equity fundamental analyst"
            categories = (
                "1. EARNINGS / REVENUE: Recent results, guidance, analyst estimates vs actuals\n"
                "2. INSTITUTIONAL FLOWS: 13F filings, fund accumulation or distribution\n"
                "3. ANALYST SENTIMENT: Upgrades, downgrades, price target changes\n"
                "4. MACRO / RATES: Interest rate environment impact on sector valuation\n"
                "5. COMPANY CATALYST: Product launches, regulatory approvals, major contracts"
            )
        elif asset_class == 'index':
            analyst_role = "macro equity index analyst"
            categories = (
                "1. FED POLICY: Rate decisions, dot plot, forward guidance — bullish or bearish for equities?\n"
                "2. EARNINGS SEASON: Breadth of beats/misses, revenue growth, forward guidance\n"
                "3. VOLATILITY / SENTIMENT: VIX level, fear/greed index, put/call ratio\n"
                "4. SECTOR ROTATION: Institutional flows into or out of risk assets\n"
                "5. MACRO DATA: CPI, jobs report, GDP — supportive or headwind for index?"
            )
        else:  # crypto
            analyst_role = "fundamental crypto analyst"
            categories = (
                "1. ETF FLOWS: Are institutional investors buying or selling? (High impact)\n"
                "2. WHALE ACTIVITY: Are whales accumulating (moving to wallets) or distributing (moving to exchanges)?\n"
                "3. ON-CHAIN HEALTH: TVL trends, active addresses, network usage\n"
                "4. REGULATORY: Favorable or unfavorable regulatory developments?\n"
                "5. PROTOCOL/DEVELOPMENT: Upgrades, partnerships, ecosystem growth?"
            )

        prompt = f"""You are a {analyst_role} for an institutional trading desk.
        Analyze the following real-time data for {ticker}:

        Data:
        {combined_text}

        Evaluate based on these fundamental categories:
        {categories}

        Task:
        1. Score between -1.0 (Strong Bearish fundamentals) and +1.0 (Strong Bullish fundamentals)
        2. Provide a brief rationale (max 1 sentence)
        3. List the top 2-3 key factors driving your score

        If data is mixed or unclear, lean toward 0.0 (neutral).
        If no relevant fundamental data exists, score exactly 0.0.

        Output format:
        SCORE: <float>
        RATIONALE: <text>
        FACTORS: <comma-separated list>
        """
        
        response_text = self.llm.analyze_text(prompt, agent_name="FundamentalAnalyst", thinking=False)
        
        score = 0.0
        rationale = "Analysis completed."
        factors = []
        
        try:
            # Parse score
            match_score = re.search(r"SCORE:\s*([-+]?\d*\.?\d+)", response_text)
            if match_score:
                score = float(match_score.group(1))
                score = max(-1.0, min(1.0, score))
            
            # Parse rationale
            match_rationale = re.search(r"RATIONALE:\s*(.*?)(?:\n|FACTORS:|$)", response_text, re.DOTALL)
            if match_rationale:
                rationale = match_rationale.group(1).strip()
            
            # Parse factors
            match_factors = re.search(r"FACTORS:\s*(.*)", response_text, re.DOTALL)
            if match_factors:
                factors = [f.strip() for f in match_factors.group(1).split(',') if f.strip()]
            
            # Handle mock LLM responses
            if "MOCK_RESPONSE" in response_text:
                score = 0.0  # Neutral for mock — don't bias with fake data
                rationale = "LLM in mock mode — fundamentals neutral."
                factors = ["mock_mode"]
                
        except Exception as e:
            self.logger.error(f"Error parsing LLM fundamental response: {e}")
            
        return score, rationale, factors

    async def analyze_async(self, ticker: str) -> dict:
        import asyncio
        return await asyncio.to_thread(self.analyze, ticker)

    def analyze(self, ticker: str) -> dict:
        """
        Analyzes the ticker based on real fundamental data.
        Result: Score between -1.0 (Bearish) and +1.0 (Bullish).
        """
        self.logger.info(f"Analyzing fundamentals for {ticker}...")
        
        current_time = datetime.datetime.now()
        
        # 1. Check Supabase Cache (TTL: 5 hours)
        cache_key = f"FUNDAMENTAL_{ticker}"
        if self.db_client:
            cached_result = self.db_client.get_agent_cache(cache_key, ttl_hours=5.0)
            if cached_result:
                self.logger.info(f"✅ Using 5-hour cached fundamental data for {ticker}")
                return cached_result
        
        # Check freshness local
        last_time = self.last_analysis_time.get(ticker)
        is_stale = False
        if last_time:
            delta = current_time - last_time
            if delta.total_seconds() > 1800:  # 30 minutes
                is_stale = True

        # 2. Gather real fundamental data
        raw_data = self._gather_fundamental_data(ticker)
        
        # 3. Filter noise
        filtered_data = self._filter_data(raw_data)
        self.logger.info(f"Fundamental data after filtering: {len(filtered_data)} items for {ticker}")
        
        if not filtered_data:
            self.logger.warning(f"No fundamental data found for {ticker}. Returning neutral.")
            return {
                "agent": "FundamentalAnalyst",
                "signal": 0.0,
                "ticker": ticker,
                "status": "NO_DATA",
                "reason": "No fundamental data available.",
                "reasoning": [],
                "summary": "Fund: 0.00 (no data)",
                "timestamp": current_time.isoformat()
            }
        
        # 3. LLM Analysis
        score, rationale, factors = self._analyze_with_llm(ticker, filtered_data)
        
        # Update timestamp
        self.last_analysis_time[ticker] = current_time
        
        # Determine status
        status = "NEUTRAL"
        if score > 0.3:
            status = "BULLISH"
        elif score < -0.3:
            status = "BEARISH"
        
        result = {
            "agent": "FundamentalAnalyst",
            "signal": round(score, 2),
            "ticker": ticker,
            "status": status,
            "reason": rationale,
            "reasoning": factors,
            "summary": f"Fund: {score:+.2f} — {rationale}",
            "data_points": {
                "source_count": len(filtered_data),
                "is_stale_warning": is_stale,
            },
            "timestamp": current_time.isoformat()
        }
        
        # Save to DB cache
        if self.db_client:
            self.db_client.set_agent_cache(cache_key, result)
        
        return result
