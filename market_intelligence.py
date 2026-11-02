"""
Market Intelligence & Accuracy Enhancement Engine for NIFTY 50
Integrates:
1. India VIX (Volatility Index) Live Tracking & Option Greek Regime
2. NIFTY Heavyweights Driver Check (HDFC Bank, Reliance, ICICI Bank - 31% index weight)
3. Time-of-Day Trading Session Regimes (Opening Momentum, Midday Chop Zone, European Squeeze)
"""

import time
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List


class MarketIntelligence:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "Accept": "application/json"
        })
        self._vix_cache: Optional[Dict[str, Any]] = None
        self._vix_fetch_time = 0.0

        self._heavyweights_cache: Optional[Dict[str, Any]] = None
        self._heavyweights_fetch_time = 0.0

    def fetch_india_vix(self) -> Dict[str, Any]:
        """
        Fetches live India VIX (^INDIAVIX) from Yahoo Finance.
        Classifies volatility regime and option buying suitability.
        Caches for 30s.
        """
        now = time.time()
        if self._vix_cache and (now - self._vix_fetch_time) < 30:
            return self._vix_cache

        default_result = {
            "vix": 14.5,
            "change_pct": 0.0,
            "change_pts": 0.0,
            "regime": "OPTIMAL_VOLATILITY",
            "badge": "🟢 OPTIMAL (VIX ~14.5)",
            "bias": "NEUTRAL",
            "description": "Healthy baseline volatility for directional options buying."
        }

        try:
            url = "https://query1.finance.yahoo.com/v8/finance/chart/^INDIAVIX?interval=5m&range=1d"
            res = self.session.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                price = meta.get("regularMarketPrice")
                prev_close = meta.get("chartPreviousClose") or price

                if price:
                    chg_pts = round(price - prev_close, 2)
                    chg_pct = round((chg_pts / prev_close) * 100, 2) if prev_close else 0.0

                    # Volatility Regime Classification
                    if price < 12.5:
                        regime = "LOW_VOLATILITY"
                        badge = f"🔵 LOW VOL ({price:.2f})"
                        desc = "Low option premiums. Clean, steady trending moves without wild whipsaws."
                        bias = "FAVORS_BULLS" if chg_pct <= 0 else "NEUTRAL"
                    elif price <= 17.0:
                        regime = "OPTIMAL_VOLATILITY"
                        badge = f"🟢 OPTIMAL ({price:.2f})"
                        desc = "Prime options buying liquidity and healthy intraday directional swings."
                        bias = "BULLISH_BIAS" if chg_pct < 0 else ("BEARISH_HEDGING" if chg_pct > 3.0 else "BALANCED")
                    elif price <= 22.0:
                        regime = "ELEVATED_VOLATILITY"
                        badge = f"🟠 ELEVATED ({price:.2f})"
                        desc = "Fast wide swings. Options expensive. Widen trailing stops & take quicker targets."
                        bias = "FEAR_ELEVATED"
                    else:
                        regime = "EXTREME_PANIC"
                        badge = f"🔴 PANIC VIX ({price:.2f})"
                        desc = "Severe market fear. Huge IV crush risk on reversals. Scalp only."
                        bias = "EXTREME_PANIC"

                    self._vix_cache = {
                        "vix": round(price, 2),
                        "prev_close": round(prev_close, 2),
                        "change_pct": chg_pct,
                        "change_pts": chg_pts,
                        "regime": regime,
                        "badge": badge,
                        "bias": bias,
                        "description": desc
                    }
                    self._vix_fetch_time = now
                    return self._vix_cache
        except Exception:
            pass

        return default_result if not self._vix_cache else self._vix_cache

    def fetch_heavyweights(self) -> Dict[str, Any]:
        """
        Fetches live performance for NIFTY's top 3 heavyweights:
        - HDFCBANK (~13.5% weight)
        - RELIANCE (~9.5% weight)
        - ICICIBANK (~8.2% weight)
        Total index influence: >31%
        """
        now = time.time()
        if self._heavyweights_cache and (now - self._heavyweights_fetch_time) < 30:
            return self._heavyweights_cache

        symbols = {
            "HDFCBANK.NS": {"name": "HDFCBANK", "weight": 13.5},
            "RELIANCE.NS": {"name": "RELIANCE", "weight": 9.5},
            "ICICIBANK.NS": {"name": "ICICIBANK", "weight": 8.2}
        }

        results = {}
        green_count = 0
        red_count = 0
        total_weighted_chg = 0.0

        for ticker, info in symbols.items():
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=5m&range=1d"
                res = self.session.get(url, timeout=4)
                if res.status_code == 200:
                    data = res.json()
                    meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                    price = meta.get("regularMarketPrice", 0.0)
                    prev = meta.get("chartPreviousClose", price) or price
                    pct = round(((price - prev) / prev) * 100, 2) if prev > 0 else 0.0

                    if pct > 0.10:
                        green_count += 1
                    elif pct < -0.10:
                        red_count += 1

                    total_weighted_chg += pct * (info["weight"] / 31.2)
                    results[info["name"]] = {"price": price, "pct": pct}
            except Exception:
                pass

        # If network error, provide graceful fallback
        if not results:
            results = {
                "HDFCBANK": {"price": 712.0, "pct": 0.0},
                "RELIANCE": {"price": 1225.0, "pct": 0.0},
                "ICICIBANK": {"price": 1405.0, "pct": 0.0}
            }

        # Determine Driver Bias
        if green_count >= 2:
            bias = "BULLISH_SUPPORT"
            badge = f"🟢 HEAVYWEIGHTS BULLISH ({green_count}/3 Green)"
            desc = f"NIFTY heavyweights driving upside (Reliance, HDFC, ICICI avg: {total_weighted_chg:+.2f}%)."
        elif red_count >= 2:
            bias = "BEARISH_DRAG"
            badge = f"🔴 HEAVYWEIGHTS BEARISH ({red_count}/3 Red)"
            desc = f"NIFTY heavyweights dragging downward (avg: {total_weighted_chg:+.2f}%)."
        else:
            bias = "MIXED_DIVERGENT"
            badge = "⚪ HEAVYWEIGHTS MIXED"
            desc = "Heavyweights pulling in opposite directions; index likely rangebound."

        self._heavyweights_cache = {
            "stocks": results,
            "green_count": green_count,
            "red_count": red_count,
            "bias": bias,
            "badge": badge,
            "avg_weighted_pct": round(total_weighted_chg, 2),
            "description": desc
        }
        self._heavyweights_fetch_time = now
        return self._heavyweights_cache

    @staticmethod
    def get_time_of_day_regime() -> Dict[str, Any]:
        """
        Determines current Indian Standard Time (IST = UTC+5:30) trading session regime.
        Filters out high-failure midday theta chop zone (11:30 AM - 1:15 PM).
        """
        utc_now = datetime.now(timezone.utc)
        ist_now = utc_now + timedelta(hours=5, minutes=30)
        curr_time = ist_now.time()
        hour = curr_time.hour
        minute = curr_time.minute
        time_minutes = hour * 60 + minute

        mkt_open = 9 * 60 + 15      # 09:15
        orb_end = 10 * 60 + 45     # 10:45
        chop_start = 11 * 60 + 30  # 11:30
        chop_end = 13 * 60 + 15    # 13:15
        expiry_end = 15 * 60 + 15  # 15:15
        mkt_close = 15 * 60 + 30   # 15:30

        if time_minutes < mkt_open:
            return {
                "regime": "PRE_MARKET",
                "badge": "⏳ PRE-MARKET",
                "is_chop_zone": False,
                "allow_fresh_trades": False,
                "min_confluence": 60,
                "note": "Market opens at 09:15 AM IST."
            }
        elif mkt_open <= time_minutes < orb_end:
            return {
                "regime": "OPENING_MOMENTUM",
                "badge": "⚡ OPENING MOMENTUM (09:15 - 10:45)",
                "is_chop_zone": False,
                "allow_fresh_trades": True,
                "min_confluence": 60,
                "note": "High intraday volume & genuine opening breakout follow-through."
            }
        elif orb_end <= time_minutes < chop_start:
            return {
                "regime": "EARLY_MIDDAY",
                "badge": "⚖️ EARLY MIDDAY (10:45 - 11:30)",
                "is_chop_zone": False,
                "allow_fresh_trades": True,
                "min_confluence": 65,
                "note": "Trend continuation or consolidation before lunch zone."
            }
        elif chop_start <= time_minutes < chop_end:
            return {
                "regime": "MIDDAY_THETA_CHOP",
                "badge": "⚠️ MIDDAY CHOP ZONE (11:30 - 13:15)",
                "is_chop_zone": True,
                "allow_fresh_trades": False,  # Discourages fresh trades unless fast catalyst
                "min_confluence": 80,
                "note": "Option sellers dominate; false breakout rate is 70%. Requiring 80%+ confluence."
            }
        elif chop_end <= time_minutes < expiry_end:
            return {
                "regime": "EUROPEAN_OPEN_&_EXPIRY_SQUEEZE",
                "badge": "🚀 EUROPEAN SQUEEZE (13:15 - 15:15)",
                "is_chop_zone": False,
                "allow_fresh_trades": True,
                "min_confluence": 65,
                "note": "European market open & gamma short-covering squeezes."
            }
        elif expiry_end <= time_minutes <= mkt_close:
            return {
                "regime": "INTRADAY_SQUAREOFF",
                "badge": "⏹️ SQUARE-OFF PHASE (15:15 - 15:30)",
                "is_chop_zone": False,
                "allow_fresh_trades": False,
                "min_confluence": 90,
                "note": "Intraday broker auto-square-off zone. Close open positions."
            }
        else:
            return {
                "regime": "MARKET_CLOSED",
                "badge": "🌙 MARKET CLOSED",
                "is_chop_zone": False,
                "allow_fresh_trades": True,  # Allow simulation/demo testing
                "min_confluence": 60,
                "note": "Market is closed. Running live simulation / evaluation mode."
            }

    def get_market_intelligence_context(self) -> Dict[str, Any]:
        """Consolidates VIX, Heavyweights, and Session Regime into a single intelligence payload."""
        vix = self.fetch_india_vix()
        hw = self.fetch_heavyweights()
        session = self.get_time_of_day_regime()

        return {
            "vix": vix,
            "heavyweights": hw,
            "session": session,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
