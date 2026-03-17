import logging
import datetime
import re
from utils.web_intelligence import WebIntelligence
from utils.llm_client import LLMClient


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

    def _gather_fundamental_data(self, ticker: str) -> list[dict]:
        """
        Gathers real fundamental data via web search.
        Runs multiple targeted queries for different fundamental aspects.
        """
        base_ticker = ticker.split('/')[0] if '/' in ticker else ticker
        
        queries = [
            f"{base_ticker} crypto ETF inflow outflow latest",
            f"{base_ticker} whale alert large transaction exchange",
            f"{base_ticker} on-chain metrics TVL active addresses",
            f"{base_ticker} crypto regulation news SEC",
            f"{base_ticker} protocol upgrade news development",
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
        
        prompt = f"""You are a fundamental crypto analyst for an institutional trading desk.
        Analyze the following real-time data for {ticker}:
        
        Data:
        {combined_text}
        
        Evaluate based on these fundamental categories:
        1. ETF FLOWS: Are institutional investors buying or selling? (High impact)
        2. WHALE ACTIVITY: Are whales accumulating (moving to wallets) or distributing (moving to exchanges)?
        3. ON-CHAIN HEALTH: TVL trends, active addresses, network usage
        4. REGULATORY: Favorable or unfavorable regulatory developments?
        5. PROTOCOL/DEVELOPMENT: Upgrades, partnerships, ecosystem growth?
        
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
        
        response_text = self.llm.analyze_text(prompt, agent_name="FundamentalAnalyst")
        
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
        
        # 1. Check Supabase Cache (TTL: 24 hours)
        cache_key = f"FUNDAMENTAL_{ticker}"
        if self.db_client:
            cached_result = self.db_client.get_agent_cache(cache_key, ttl_hours=24.0)
            if cached_result:
                self.logger.info(f"✅ Using 24-hour cached fundamental data for {ticker}")
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
