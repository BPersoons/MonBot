from duckduckgo_search import DDGS
import requests
from bs4 import BeautifulSoup
import logging
import datetime

class WebIntelligence:
    def __init__(self):
        self.logger = logging.getLogger("WebIntelligence")
        self.ddgs = DDGS()

    def scan_social_media(self, ticker: str) -> list[dict]:
        """
        Scans 'social' sources (simulated via search) for X and Reddit discussions.
        Returns a list of finding dicts: {source, text, timestamp, url}
        """
        self.logger.info(f"Scanning social media for {ticker}...")
        results = []
        
        # Search queries for "recent discussions"
        queries = [
            f"{ticker} crypto sentiment site:twitter.com",
            f"{ticker} stock sentiment site:reddit.com",
            f"${ticker} analysis site:twitter.com"
        ]

        for q in queries:
            try:
                # limited to 5 results per query for speed/demo
                search_results = self.ddgs.text(q, max_results=5)
                if search_results:
                    for res in search_results:
                        results.append({
                            "source": "social_search",
                            "text": res.get('body', '') or res.get('title', ''),
                            "url": res.get('href', ''),
                            "timestamp": datetime.datetime.now().isoformat()
                        })
            except Exception as e:
                self.logger.warning(f"Search failed for query '{q}': {e}")
        
        return results

    def scan_news(self, ticker: str) -> list[dict]:
        """
        Scans for news headlines.
        """
        self.logger.info(f"Scanning news for {ticker}...")
        results = []
        try:
             news_results = self.ddgs.news(keywords=ticker, max_results=5)
             if news_results:
                 for res in news_results:
                     results.append({
                         "source": "news",
                         "text": res.get('title', ''),
                         "url": res.get('url', ''),
                         "timestamp": res.get('date', datetime.datetime.now().isoformat())
                     })
        except Exception as e:
            self.logger.warning(f"News search failed: {e}")

        return results
