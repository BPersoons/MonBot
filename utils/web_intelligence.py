import requests
import xml.etree.ElementTree as ET
import logging
import datetime
from concurrent.futures import ThreadPoolExecutor

try:
    from duckduckgo_search import DDGS
    _DDGS_AVAILABLE = True
except ImportError:
    _DDGS_AVAILABLE = False


class WebIntelligence:
    def __init__(self):
        self.logger = logging.getLogger("WebIntelligence")
        self.ddgs = DDGS() if _DDGS_AVAILABLE else None

    def _google_news_rss(self, query: str, max_results: int = 10) -> list[dict]:
        """Fetch news from Google News RSS (free, no API key, works from cloud IPs)."""
        try:
            url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en&gl=US&ceid=US:en"
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            items = root.findall(".//item")
            results = []
            for item in items[:max_results]:
                title = item.find("title")
                link = item.find("link")
                pub_date = item.find("pubDate")
                results.append({
                    "source": "news",
                    "text": title.text if title is not None else "",
                    "url": link.text if link is not None else "",
                    "timestamp": pub_date.text if pub_date is not None else datetime.datetime.now().isoformat(),
                })
            return results
        except Exception as e:
            self.logger.warning(f"Google News RSS failed for '{query}': {e}")
            return []

    def _social_query(self, q: str) -> list[dict]:
        """Run one social search query. Uses its OWN DDGS instance so it is safe to
        call concurrently — a shared DDGS/primp session is not thread-safe."""
        results = []
        ddgs = DDGS() if _DDGS_AVAILABLE else None
        # Try DuckDuckGo first (better for social/site-specific)
        if ddgs:
            try:
                search_results = ddgs.text(q, max_results=5)
                if search_results:
                    for res in search_results:
                        results.append({
                            "source": "social_search",
                            "text": res.get('body', '') or res.get('title', ''),
                            "url": res.get('href', ''),
                            "timestamp": datetime.datetime.now().isoformat()
                        })
                    return results  # DDG worked, skip fallback
            except Exception as e:
                self.logger.debug(f"DDG social search failed for '{q}': {e}")

        # Fallback: Google News RSS (strips site: filters)
        clean_q = q.replace("site:twitter.com", "").replace("site:reddit.com", "").replace("$", "").strip()
        gn_results = self._google_news_rss(clean_q, max_results=5)
        for r in gn_results:
            r["source"] = "social_search"
        results.extend(gn_results)
        return results

    def scan_social_media(self, ticker: str) -> list[dict]:
        """
        Scans 'social' sources (simulated via search) for X and Reddit discussions.
        Returns a list of finding dicts: {source, text, timestamp, url}
        The 3 queries run concurrently (each with its own DDGS instance).
        """
        self.logger.info(f"Scanning social media for {ticker}...")

        queries = [
            f"{ticker} crypto sentiment site:twitter.com",
            f"{ticker} stock sentiment site:reddit.com",
            f"${ticker} analysis site:twitter.com"
        ]

        results = []
        with ThreadPoolExecutor(max_workers=len(queries)) as ex:
            for chunk in ex.map(self._social_query, queries):
                results.extend(chunk)

        return results

    def scan_news(self, ticker: str) -> list[dict]:
        """
        Scans for news headlines. Uses Google News RSS (primary) with DDG fallback.
        """
        self.logger.info(f"Scanning news for {ticker}...")

        # Primary: Google News RSS (reliable from cloud IPs)
        results = self._google_news_rss(ticker, max_results=10)
        if results:
            return results

        # Fallback: DuckDuckGo
        if self.ddgs:
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
                self.logger.warning(f"DDG news fallback also failed: {e}")

        return results
