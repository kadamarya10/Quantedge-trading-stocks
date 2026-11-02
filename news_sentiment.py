"""
Live Financial News & Sentiment Analysis Engine for Indian Markets (NIFTY 50)
Pulls real-time breaking market headlines from verified financial sources
(Economic Times, Livemint, Moneycontrol, CNBC-TV18, Zee Business via Google News RSS)
and computes live sentiment, breaking news catalysts, and fast-trade triggers.
"""

import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Any, List, Optional


BULLISH_KEYWORDS = {
    "rally": 2.0, "surge": 2.5, "surges": 2.5, "jump": 2.0, "jumps": 2.0,
    "soar": 2.5, "soars": 2.5, "rise": 1.5, "rises": 1.5, "gain": 1.5, "gains": 1.5,
    "bull": 2.0, "bulls": 2.0, "bullish": 2.0, "high": 1.0, "record high": 3.0,
    "rate cut": 3.0, "stimulus": 3.0, "fii buying": 2.5, "breakout": 2.0,
    "strong earnings": 2.5, "beats estimates": 2.5, "outperform": 2.0, "upbeat": 1.5,
    "positive": 1.5, "green": 1.0, "recovery": 2.0, "growth": 1.5
}

BEARISH_KEYWORDS = {
    "crash": 3.0, "crashes": 3.0, "plunge": 3.0, "plunges": 3.0, "slump": 2.5,
    "fall": 1.5, "falls": 1.5, "drop": 1.5, "drops": 1.5, "sink": 2.0, "sinks": 2.0,
    "bear": 2.0, "bears": 2.0, "bearish": 2.0, "selloff": 2.5, "bloodbath": 3.0,
    "tumble": 2.5, "tumbles": 2.5, "war": 3.5, "conflict": 3.0, "attack": 3.0,
    "rate hike": 3.0, "inflation": 2.0, "crude spike": 2.5, "fii selling": 2.5,
    "misses estimates": 2.5, "downbeat": 1.5, "negative": 1.5, "red": 1.0,
    "losses": 2.0, "recession": 3.0, "probe": 2.0, "fraud": 3.0, "sanctions": 2.5
}


class NewsSentimentAnalyzer:
    def __init__(self, query: str = "Nifty stock market India"):
        self.query = query
        self.rss_url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}+when:1d&hl=en-IN&gl=IN&ceid=IN:en"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "Accept": "application/rss+xml, application/xml, text/xml"
        })
        self.last_headlines: List[Dict[str, Any]] = []
        self.last_fetch_time = 0
        self.cached_analysis: Optional[Dict[str, Any]] = None

    def fetch_live_headlines(self, max_items: int = 15) -> List[Dict[str, Any]]:
        """
        Fetches live breaking news headlines. Caches for 45s to avoid rate limiting.
        """
        now = time.time()
        if self.last_headlines and (now - self.last_fetch_time) < 45:
            return self.last_headlines

        try:
            res = self.session.get(self.rss_url, timeout=6)
            if res.status_code != 200:
                return self.last_headlines

            root = ET.fromstring(res.content)
            items = root.findall(".//item")
            headlines = []

            for item in items[:max_items]:
                title = item.find("title").text if item.find("title") is not None else ""
                pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                link = item.find("link").text if item.find("link") is not None else ""
                source_elem = item.find("source")
                source = source_elem.text if source_elem is not None else "Financial News"

                if title:
                    headlines.append({
                        "title": title,
                        "pub_date": pub_date,
                        "source": source,
                        "link": link
                    })

            if headlines:
                self.last_headlines = headlines
                self.last_fetch_time = now

            return self.last_headlines
        except Exception:
            return self.last_headlines

    def analyze_news_sentiment(self) -> Dict[str, Any]:
        """
        Scores live headlines to extract market sentiment, catalyst flags, and fast-action trigger.
        """
        headlines = self.fetch_live_headlines()
        if not headlines:
            return {
                "sentiment": "NEUTRAL",
                "score": 0.0,
                "fast_catalyst": False,
                "catalyst_direction": "NONE",
                "headline_count": 0,
                "latest_headline": "No recent breaking news detected.",
                "sentiment_badge": "⚪ NEUTRAL"
            }

        total_bullish = 0.0
        total_bearish = 0.0
        critical_alerts = []

        seen_alert_titles = set()
        for h in headlines:
            title_text = h["title"]
            text = title_text.lower()
            
            # Check Bullish keywords
            for kw, weight in BULLISH_KEYWORDS.items():
                if kw in text:
                    total_bullish += weight
                    if weight >= 2.5 and title_text not in seen_alert_titles:
                        critical_alerts.append((f"🟢 Catalyst: '{title_text}'", "BULLISH"))
                        seen_alert_titles.add(title_text)

            # Check Bearish keywords
            for kw, weight in BEARISH_KEYWORDS.items():
                if kw in text:
                    total_bearish += weight
                    if weight >= 2.5 and title_text not in seen_alert_titles:
                        critical_alerts.append((f"🔴 Catalyst: '{title_text}'", "BEARISH"))
                        seen_alert_titles.add(title_text)

        net_score = total_bullish - total_bearish
        total_signals = total_bullish + total_bearish

        # Normalize score between -100 and +100
        normalized_score = 0.0
        if total_signals > 0:
            normalized_score = round((net_score / total_signals) * 100, 1)

        fast_catalyst = False
        catalyst_direction = "NONE"

        if normalized_score >= 35 or (total_bullish >= 6.0 and total_bullish > total_bearish * 1.8):
            sentiment = "BULLISH NEWS FLOW"
            sentiment_badge = "🟢 BULLISH CATALYST"
            if total_bullish >= 8.0:
                fast_catalyst = True
                catalyst_direction = "BULLISH"
        elif normalized_score <= -35 or (total_bearish >= 6.0 and total_bearish > total_bullish * 1.8):
            sentiment = "BEARISH NEWS FLOW"
            sentiment_badge = "🔴 BEARISH CATALYST"
            if total_bearish >= 8.0:
                fast_catalyst = True
                catalyst_direction = "BEARISH"
        else:
            sentiment = "BALANCED / NEUTRAL NEWS"
            sentiment_badge = "⚪ BALANCED"

        latest_title = headlines[0]["title"] if headlines else ""

        self.cached_analysis = {
            "sentiment": sentiment,
            "sentiment_badge": sentiment_badge,
            "score": normalized_score,
            "bullish_points": round(total_bullish, 1),
            "bearish_points": round(total_bearish, 1),
            "fast_catalyst": fast_catalyst,
            "catalyst_direction": catalyst_direction,
            "critical_alerts": [a[0] for a in critical_alerts[:2]],
            "latest_headline": latest_title,
            "headline_count": len(headlines)
        }
        return self.cached_analysis
