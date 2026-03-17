import logging
import datetime
import re
from utils.web_intelligence import WebIntelligence
from utils.llm_client import LLMClient

class SentimentAnalyst:
    """
    Sentiment Analyst Agent.
    Responsibility: Monitor social media (X, Reddit) and News for sentiment.
    """
    def __init__(self, db_client=None):
        self.logger = logging.getLogger("SentimentAnalyst")
        self.web_intel = WebIntelligence()
        self.llm = LLMClient(model_name="gemini-3-flash-preview")
        self.db_client = db_client
        self.last_analysis_time = {} # Store timestamp per ticker
        
    async def analyze_async(self, ticker: str) -> dict:
        import asyncio
        return await asyncio.to_thread(self.analyze, ticker)

    def analyze(self, ticker: str) -> dict:
        """
        Analyzes the ticker based on market sentiment.
        Returns a signal between -1.0 (Bearish) and +1.0 (Bullish).
        """
        self.logger.info(f"Analyzing sentiment for {ticker}...")
        
        current_time = datetime.datetime.now()
        
        # 1. Check Supabase Cache (TTL: 4 hours)
        cache_key = f"SENTIMENT_{ticker}"
        if self.db_client:
            cached_result = self.db_client.get_agent_cache(cache_key, ttl_hours=8.0)
            if cached_result:
                self.logger.info(f"✅ Using 8-hour cached sentiment data for {ticker}")
                return cached_result
        
        # Check freshness local
        last_time = self.last_analysis_time.get(ticker)
        is_stale = False
        if last_time:
            delta = current_time - last_time
            if delta.total_seconds() > 900: # 15 minutes
                self.logger.warning(f"Sentiment data for {ticker} might be stale (last run: {last_time}). refreshing...")
                is_stale = True

        # 2. Gather Data
        search_term = ticker.split('/')[0] if '/' in ticker else ticker
        
        social_data = self.web_intel.scan_social_media(search_term)
        news_data = self.web_intel.scan_news(search_term)
        all_data = social_data + news_data
        
        self.logger.info(f"Raw data items found: {len(all_data)}")

        # 3. Filter Noise
        filtered_data = self._filter_noise(all_data)
        self.logger.info(f"Items after noise filtering: {len(filtered_data)}")

        if not filtered_data:
            self.logger.warning(f"No valid data found for {ticker}. Returning neutral.")
            return {
                "agent": "SentimentAnalyst",
                "signal": 0.0,
                "ticker": ticker,
                "status": "NO_DATA",
                "timestamp": current_time.isoformat()
            }

        # 4. LLM Analysis
        sentiment_score, rationale = self._analyze_with_llm(ticker, filtered_data)
        
        # Update timestamp
        self.last_analysis_time[ticker] = current_time

        result = {
            "agent": "SentimentAnalyst",
            "signal": sentiment_score,
            "ticker": ticker,
            "metrics": {
                "source_count": len(filtered_data),
                "is_stale_warning": is_stale,
                "rationale": rationale
            },
            "timestamp": current_time.isoformat(),
            "summary": f"Sent: {sentiment_score:+.2f} — {rationale}"
        }
        
        # Save to DB cache
        if self.db_client:
            self.db_client.set_agent_cache(cache_key, result)
            
        return result

    def _filter_noise(self, data: list[dict]) -> list[dict]:
        """
        Basic filter logic to remove bots/spam.
        Criteria:
        - Deduplicate by text content.
        - Ignore very short text (< 15 chars).
        - Ignore text with excessive hashtags (> 5) - sign of spam/promo.
        """
        unique_texts = set()
        clean_data = []

        for item in data:
            text = item.get('text', '').strip()
            
            # 1. Length check
            if len(text) < 15:
                continue
            
            # 2. Deduplication using hash of first 50 chars (fuzzy) or exact
            if text in unique_texts:
                continue
            unique_texts.add(text)

            # 3. Hashtag spam check
            hashtag_count = text.count('#')
            if hashtag_count > 5:
                continue

            # 4. keyword check for obvious spam phrases (optional, extendable)
            spam_keywords = ["giveaway", "airdrop", "join my telegram", "guaranteed profit"]
            if any(keyword in text.lower() for keyword in spam_keywords):
                continue

            clean_data.append(item)
            
        return clean_data

    def _analyze_with_llm(self, ticker: str, data: list[dict]) -> tuple[float, str]:
        """
        Constructs a prompt for the LLM to score the sentiment.
        """
        combined_text = "\n".join([f"- [{d['source']}] {d['text']}" for d in data])
        
        prompt = f"""
        You are a quantitative sentiment analyst for a hedge fund.
        Analyze the following social media and news snippets for the asset '{ticker}'.
        
        Data:
        {combined_text}
        
        Task:
        1. Determine the overall sentiment score between -1.0 (Extreme Fear/Bearish) and +1.0 (Extreme Greed/Bullish).
        2. Provide a brief rationale (max 1 sentence).
        3. Ignore any remaining noise or irrelevant posts.
        
        Output format:
        SCORE: <float>
        RATIONALE: <text>
        """
        
        response_text = self.llm.analyze_text(prompt, agent_name="SentimentAnalyst")

        # Parse response
        score = 0.0
        rationale = "Analysis failed or mock response."
        
        try:
            # Simple parsing logic
            match_score = re.search(r"SCORE:\s*([-+]?\d*\.?\d+)", response_text)
            if match_score:
                score = float(match_score.group(1))
                # Clamp score
                score = max(-1.0, min(1.0, score))
            
            match_rationale = re.search(r"RATIONALE:\s*(.*)", response_text, re.DOTALL)
            if match_rationale:
                rationale = match_rationale.group(1).strip()
            elif "MOCK_RESPONSE" in response_text:
                score = 0.8 # Mock value
                rationale = "Simulated bullish sentiment from mock LLM."
                
        except Exception as e:
            self.logger.error(f"Error parsing LLM response: {e}")
            
        return score, rationale

    def get_global_vibe(self) -> dict:
        """
        Calculates a global macroeconomic vibe score (-1.0 to 1.0) based on overarching news.
        Cached for 4 hours to avoid redundant LLM calls.
        """
        cache_key = "GLOBAL_MACRO_VIBE"
        if self.db_client:
            cached_result = self.db_client.get_agent_cache(cache_key, ttl_hours=8.0)
            if cached_result:
                self.logger.info("✅ Using 8-hour cached Global Macro Vibe")
                return cached_result
                
        self.logger.info("🌍 Analyzing Global Macro Vibe...")
        
        # 1. Gather global data
        news_data = self.web_intel.scan_news("Global Crypto Market Macro SEC Economy Interest Rates")
        filtered_data = self._filter_noise(news_data)
        
        if not filtered_data:
            self.logger.warning("No global macro data found. Returning neutral vibe.")
            return {"signal": 0.0, "rationale": "No macro data found."}
            
        # 2. LLM Analysis
        combined_text = "\n".join([f"- [{d['source']}] {d['text']}" for d in filtered_data[:15]])
        prompt = f"""
        You are a global macroeconomic analyst assessing the overall risk environment for crypto.
        Analyze the following broad news headlines:
        
        Data:
        {combined_text}
        
        Task:
        1. Determine the overall macro vibe score between -1.0 (Extreme Systemic Risk/Bearish) and +1.0 (Extreme Risk-On/Bullish).
        2. Provide a brief 1-sentence rationale.
        
        Output format:
        SCORE: <float>
        RATIONALE: <text>
        """
        
        response_text = self.llm.analyze_text(prompt, agent_name="SentimentAnalyst")

        score = 0.0
        rationale = "Macro analysis failed."
        match_score = re.search(r"SCORE:\s*([-+]?\d*\.?\d+)", response_text)
        if match_score:
            score = max(-1.0, min(1.0, float(match_score.group(1))))
        
        match_rationale = re.search(r"RATIONALE:\s*(.*)", response_text, re.DOTALL)
        if match_rationale:
            rationale = match_rationale.group(1).strip()
            
        result = {
            "signal": score,
            "rationale": rationale,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        if self.db_client:
            self.db_client.set_agent_cache(cache_key, result)
            
        return result
