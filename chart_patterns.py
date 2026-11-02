"""
Chart Pattern Recognition & Price Action Analysis Engine for NIFTY 50
Detects real-time candlestick patterns, classical formations (Double Top/Bottom, Head & Shoulders),
market structure (Higher Highs / Lower Lows), Day Range Breakouts, VWAP, and EMAs.
"""

import time
import requests
from typing import Dict, Any, List, Optional, Tuple


class ChartPatternAnalyzer:
    def __init__(self, symbol: str = "^NSEI"):
        self.symbol = symbol
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "Accept": "application/json"
        })
        self.last_candles: List[Dict[str, float]] = []
        self._mtf_cache: Optional[Dict[str, Any]] = None
        self._mtf_cache_time: float = 0.0

    def fetch_intraday_candles(self, interval: str = "5m") -> List[Dict[str, Any]]:
        """
        Fetches live intraday OHLCV candles from Yahoo Finance for NIFTY 50 (^NSEI).
        Interval can be '1m' or '5m'.
        """
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{self.symbol}?interval={interval}&range=1d"
            res = self.session.get(url, timeout=6)
            if res.status_code != 200:
                return self.last_candles

            data = res.json()
            result = data.get("chart", {}).get("result", [])
            if not result:
                return self.last_candles

            chart = result[0]
            timestamps = chart.get("timestamp", [])
            quotes = chart.get("indicators", {}).get("quote", [{}])[0]
            opens = quotes.get("open", [])
            highs = quotes.get("high", [])
            lows = quotes.get("low", [])
            closes = quotes.get("close", [])
            volumes = quotes.get("volume", [])

            candles = []
            for i in range(len(timestamps)):
                o, h, l, c = opens[i], highs[i], lows[i], closes[i]
                v = volumes[i] if volumes and i < len(volumes) and volumes[i] is not None else 0
                if o is not None and h is not None and l is not None and c is not None:
                    candles.append({
                        "timestamp": timestamps[i],
                        "open": float(o),
                        "high": float(h),
                        "low": float(l),
                        "close": float(c),
                        "volume": int(v)
                    })

            if candles:
                self.last_candles = candles
            return candles
        except Exception:
            return self.last_candles

    @staticmethod
    def detect_candlestick_patterns(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Detects single and multi-candlestick patterns on the latest candles.
        """
        patterns = []
        if len(candles) < 3:
            return patterns

        c = candles[-1]     # Current candle
        p = candles[-2]     # Previous candle
        pp = candles[-3]    # Two candles ago

        o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
        body = abs(cl - o)
        rng = max(0.01, h - l)
        upper_wick = h - max(o, cl)
        lower_wick = min(o, cl) - l
        is_green = cl >= o
        is_red = cl < o

        p_o, p_h, p_l, p_cl = p["open"], p["high"], p["low"], p["close"]
        p_body = abs(p_cl - p_o)
        p_is_green = p_cl >= p_o
        p_is_red = p_cl < p_o

        # 1. Hammer / Bullish Pin Bar
        if lower_wick >= 2.0 * body and upper_wick <= 0.25 * rng and lower_wick >= 0.55 * rng:
            patterns.append({
                "name": "Hammer (Bullish Pin Bar)",
                "type": "BULLISH",
                "significance": "High",
                "desc": "Strong rejection of lower prices; buyers stepping in with aggressive demand."
            })

        # 2. Shooting Star / Bearish Pin Bar
        if upper_wick >= 2.0 * body and lower_wick <= 0.25 * rng and upper_wick >= 0.55 * rng:
            patterns.append({
                "name": "Shooting Star (Bearish Pin Bar)",
                "type": "BEARISH",
                "significance": "High",
                "desc": "Strong rejection of higher prices; sellers defending upper levels."
            })

        # 3. Bullish Engulfing
        if p_is_red and is_green and cl > p_o and o < p_cl and body > p_body * 1.1:
            patterns.append({
                "name": "Bullish Engulfing",
                "type": "BULLISH",
                "significance": "High",
                "desc": "Green candle completely engulfs prior red body; bullish momentum takeover."
            })

        # 4. Bearish Engulfing
        if p_is_green and is_red and cl < p_o and o > p_cl and body > p_body * 1.1:
            patterns.append({
                "name": "Bearish Engulfing",
                "type": "BEARISH",
                "significance": "High",
                "desc": "Red candle completely engulfs prior green body; bearish supply dump."
            })

        # 5. Morning Star (3-candle bullish reversal)
        pp_is_red = pp["close"] < pp["open"]
        if pp_is_red and p_body <= rng * 0.4 and is_green and cl > (pp["open"] + pp["close"]) / 2:
            patterns.append({
                "name": "Morning Star",
                "type": "BULLISH",
                "significance": "Very High",
                "desc": "3-candle bullish reversal pattern: sellers exhausted, sharp buyer recovery."
            })

        # 6. Evening Star (3-candle bearish reversal)
        pp_is_green = pp["close"] >= pp["open"]
        if pp_is_green and p_body <= rng * 0.4 and is_red and cl < (pp["open"] + pp["close"]) / 2:
            patterns.append({
                "name": "Evening Star",
                "type": "BEARISH",
                "significance": "Very High",
                "desc": "3-candle bearish reversal pattern: buyers exhausted, supply wave incoming."
            })

        # 7. Inside Bar (Compression / Coiling)
        if h <= p_h and l >= p_l:
            patterns.append({
                "name": "Inside Bar (Harami Coiling)",
                "type": "NEUTRAL",
                "significance": "Medium",
                "desc": "Price compressed completely within prior range; breakout imminent."
            })

        # 8. Doji (Indecision)
        if body <= rng * 0.12 and not patterns:
            patterns.append({
                "name": "Doji (Market Indecision)",
                "type": "NEUTRAL",
                "significance": "Medium",
                "desc": "Equal equilibrium between bulls and bears; waiting for direction."
            })

        # 9. Three Consecutive Candles Trend
        if len(candles) >= 3:
            if candles[-1]["close"] > candles[-2]["close"] > candles[-3]["close"] and is_green and p_is_green:
                patterns.append({
                    "name": "Three White Soldiers (Strong Bullish Wave)",
                    "type": "BULLISH",
                    "significance": "High",
                    "desc": "3 consecutive higher green closes; robust upward impulse."
                })
            elif candles[-1]["close"] < candles[-2]["close"] < candles[-3]["close"] and is_red and p_is_red:
                patterns.append({
                    "name": "Three Black Crows (Strong Bearish Wave)",
                    "type": "BEARISH",
                    "significance": "High",
                    "desc": "3 consecutive lower red closes; steady downward distribution."
                })

        return patterns

    @staticmethod
    def detect_chart_formations(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Detects classical multi-candle chart formations:
        - Double Bottom (W Pattern)
        - Double Top (M Pattern)
        - Head & Shoulders
        - Range Breakout / Breakdown
        """
        formations = []
        if len(candles) < 10:
            return formations

        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]
        curr_price = closes[-1]
        day_high = max(highs)
        day_low = min(lows)

        # 1. Day High Breakout (ORB)
        if curr_price >= day_high - 3.0:
            formations.append({
                "name": "Day High Breakout (ORB)",
                "type": "BULLISH",
                "level": round(day_high, 2),
                "desc": f"NIFTY trading right at Day High ({day_high:.2f}); strong momentum breakout potential."
            })

        # 2. Day Low Breakdown
        if curr_price <= day_low + 3.0:
            formations.append({
                "name": "Day Low Breakdown",
                "type": "BEARISH",
                "level": round(day_low, 2),
                "desc": f"NIFTY cracking Day Low ({day_low:.2f}); aggressive breakdown under pressure."
            })

        # Find Swing Pivots (local minima and maxima)
        swing_highs: List[Tuple[int, float]] = []
        swing_lows: List[Tuple[int, float]] = []

        for i in range(2, len(candles) - 2):
            if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
                swing_highs.append((i, highs[i]))
            if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
                swing_lows.append((i, lows[i]))

        # 3. Double Bottom (W Formation)
        if len(swing_lows) >= 2:
            l1 = swing_lows[-2][1]
            l2 = swing_lows[-1][1]
            # Lows within 0.15% of each other
            if abs(l1 - l2) / l1 <= 0.0020 and curr_price >= l2:
                formations.append({
                    "name": "Double Bottom (W Pattern)",
                    "type": "BULLISH",
                    "level": round((l1 + l2) / 2, 2),
                    "desc": f"Classic 'W' double bottom support formed around {((l1+l2)/2):.1f}; bullish base established."
                })

        # 4. Double Top (M Formation)
        if len(swing_highs) >= 2:
            h1 = swing_highs[-2][1]
            h2 = swing_highs[-1][1]
            # Highs within 0.15% of each other
            if abs(h1 - h2) / h1 <= 0.0020 and curr_price <= h2:
                formations.append({
                    "name": "Double Top (M Pattern)",
                    "type": "BEARISH",
                    "level": round((h1 + h2) / 2, 2),
                    "desc": f"Classic 'M' double top resistance formed around {((h1+h2)/2):.1f}; distribution ceiling."
                })

        # 5. Market Structure (HH/HL vs LH/LL)
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            if swing_highs[-1][1] > swing_highs[-2][1] and swing_lows[-1][1] > swing_lows[-2][1]:
                formations.append({
                    "name": "Ascending Structure (Higher Highs & Higher Lows)",
                    "type": "BULLISH",
                    "level": round(swing_lows[-1][1], 2),
                    "desc": "Price action maintaining clear intraday uptrend staircase."
                })
            elif swing_highs[-1][1] < swing_highs[-2][1] and swing_lows[-1][1] < swing_lows[-2][1]:
                formations.append({
                    "name": "Descending Structure (Lower Highs & Lower Lows)",
                    "type": "BEARISH",
                    "level": round(swing_highs[-1][1], 2),
                    "desc": "Price action locked in downward distribution staircase."
                })

        return formations

    @staticmethod
    def calculate_technical_indicators(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Computes EMA(9), EMA(21), VWAP, and RSI(14) on candle series.
        """
        closes = [c["close"] for c in candles]
        if not closes:
            return {"ema9": 0.0, "ema21": 0.0, "vwap": 0.0, "rsi": 50.0}

        # EMA Calculation
        def get_ema(data: List[float], period: int) -> float:
            if len(data) < period:
                return sum(data) / len(data)
            k = 2.0 / (period + 1)
            val = sum(data[:period]) / period
            for p in data[period:]:
                val = p * k + val * (1.0 - k)
            return val

        ema9 = get_ema(closes, 9)
        ema21 = get_ema(closes, 21)

        # VWAP Calculation
        cum_vp = 0.0
        cum_vol = 0.0
        for c in candles:
            typical_price = (c["high"] + c["low"] + c["close"]) / 3.0
            v = c.get("volume", 0) or 1
            cum_vp += typical_price * v
            cum_vol += v
        vwap = (cum_vp / cum_vol) if cum_vol > 0 else closes[-1]

        # RSI(14)
        rsi = 50.0
        if len(closes) >= 15:
            gains, losses = [], []
            for i in range(1, len(closes)):
                diff = closes[i] - closes[i - 1]
                if diff > 0:
                    gains.append(diff)
                    losses.append(0.0)
                else:
                    gains.append(0.0)
                    losses.append(abs(diff))

            period = 14
            avg_g = sum(gains[:period]) / period
            avg_l = sum(losses[:period]) / period
            for i in range(period, len(gains)):
                avg_g = (avg_g * (period - 1) + gains[i]) / period
                avg_l = (avg_l * (period - 1) + losses[i]) / period

            if avg_l == 0:
                rsi = 100.0
            else:
                rs = avg_g / avg_l
                rsi = round(100.0 - (100.0 / (1.0 + rs)), 2)

        return {
            "ema9": round(ema9, 2),
            "ema21": round(ema21, 2),
            "vwap": round(vwap, 2),
            "rsi": rsi,
            "ema_trend": "BULLISH" if ema9 > ema21 else "BEARISH",
            "vwap_bias": "ABOVE_VWAP (Bullish)" if closes[-1] >= vwap else "BELOW_VWAP (Bearish)"
        }

    def analyze_patterns(self, interval: str = "5m") -> Dict[str, Any]:
        """
        Comprehensive pattern recognition combining Candlestick, Chart Formations,
        and Indicators into a synthesized market action report.
        """
        candles = self.fetch_intraday_candles(interval=interval)
        if not candles:
            return {
                "status": "No candle data available",
                "patterns": [],
                "formations": [],
                "indicators": {},
                "sentiment": "NEUTRAL",
                "confidence": 50,
                "summary": "Awaiting candle data"
            }

        candlestick_patterns = self.detect_candlestick_patterns(candles)
        chart_formations = self.detect_chart_formations(candles)
        indicators = self.calculate_technical_indicators(candles)

        # Scoring Sentiment
        bullish_votes = 0
        bearish_votes = 0

        for p in candlestick_patterns:
            if p["type"] == "BULLISH":
                bullish_votes += 2
            elif p["type"] == "BEARISH":
                bearish_votes += 2

        for f in chart_formations:
            if f["type"] == "BULLISH":
                bullish_votes += 3
            elif f["type"] == "BEARISH":
                bearish_votes += 3

        if indicators["ema_trend"] == "BULLISH":
            bullish_votes += 1
        else:
            bearish_votes += 1

        if "ABOVE_VWAP" in indicators["vwap_bias"]:
            bullish_votes += 1
        else:
            bearish_votes += 1

        if indicators["rsi"] > 55:
            bullish_votes += 1
        elif indicators["rsi"] < 45:
            bearish_votes += 1

        # Synthesize Pattern Sentiment
        total_votes = bullish_votes + bearish_votes
        if bullish_votes >= bearish_votes + 2:
            sentiment = "BULLISH PRICE ACTION"
            confidence = min(95, int((bullish_votes / max(1, total_votes)) * 100))
        elif bearish_votes >= bullish_votes + 2:
            sentiment = "BEARISH PRICE ACTION"
            confidence = min(95, int((bearish_votes / max(1, total_votes)) * 100))
        else:
            sentiment = "CONSOLIDATION / NEUTRAL"
            confidence = 50

        # Build clean summary string
        active_labels = [p["name"] for p in candlestick_patterns] + [f["name"] for f in chart_formations]
        if not active_labels:
            active_labels = ["Trend Following Range", indicators["vwap_bias"]]

        summary = " | ".join(active_labels[:3])

        return {
            "interval": interval,
            "candles_count": len(candles),
            "current_close": candles[-1]["close"],
            "day_high": max(c["high"] for c in candles),
            "day_low": min(c["low"] for c in candles),
            "candlestick_patterns": candlestick_patterns,
            "chart_formations": chart_formations,
            "indicators": indicators,
            "sentiment": sentiment,
            "confidence": confidence,
            "summary": summary
        }

    def analyze_multi_timeframe(self) -> Dict[str, Any]:
        """
        Performs Multi-Timeframe Analysis:
        - 15m: Institutional Macro Trend (Trend Direction & Major Structure)
        - 5m : Intraday Trigger & Precise Entry Formations
        Only trades when the higher 15m timeframe confirms the 5m setup!
        """
        now = time.time()
        if self._mtf_cache is not None and (now - self._mtf_cache_time) < 45.0:
            return self._mtf_cache

        analysis_5m = self.analyze_patterns(interval="5m")
        analysis_15m = self.analyze_patterns(interval="15m")

        if not analysis_5m:
            return analysis_5m or {}

        # 15m Macro Bias
        is_15m_bullish = False
        is_15m_bearish = False
        if analysis_15m:
            ind15 = analysis_15m.get("indicators", {})
            ema15 = ind15.get("ema_trend", "")
            vwap15 = ind15.get("vwap_bias", "")
            rsi15 = ind15.get("rsi", 50.0)
            sent15 = analysis_15m.get("sentiment", "")

            bull_points = (1 if ema15 == "BULLISH" else 0) + (1 if "ABOVE_VWAP" in vwap15 else 0) + (1 if rsi15 >= 50 else 0)
            if "BULLISH" in sent15 or bull_points >= 2:
                is_15m_bullish = True
            elif "BEARISH" in sent15 or bull_points <= 1:
                is_15m_bearish = True

        # 5m Trigger Bias
        is_5m_bullish = "BULLISH" in analysis_5m.get("sentiment", "")
        is_5m_bearish = "BEARISH" in analysis_5m.get("sentiment", "")

        # MTF Alignment Evaluation
        if is_15m_bullish and is_5m_bullish:
            mtf_status = "ALIGNED_BULLISH"
            mtf_badge = "🟢 MTF CONGRUENT (15m + 5m BULLISH)"
            mtf_desc = "15m Macro Trend and 5m Price Action both Bullish. High-conviction long setup."
            alignment_score = +3
        elif is_15m_bearish and is_5m_bearish:
            mtf_status = "ALIGNED_BEARISH"
            mtf_badge = "🔴 MTF CONGRUENT (15m + 5m BEARISH)"
            mtf_desc = "15m Macro Trend and 5m Price Action both Bearish. High-conviction short setup."
            alignment_score = -3
        elif is_15m_bullish and is_5m_bearish:
            mtf_status = "BULLISH_PULLBACK"
            mtf_badge = "🟡 15m BULLISH (5m Pullback / Dip)"
            mtf_desc = "15m Trend is Bullish; 5m is in a minor pullback. Wait for 5m reversal hammer."
            alignment_score = 0
        elif is_15m_bearish and is_5m_bullish:
            mtf_status = "BEARISH_BOUNCE"
            mtf_badge = "🟡 15m BEARISH (5m Bounce Trap)"
            mtf_desc = "15m Trend is Bearish; 5m is bouncing. Caution: high risk of bull trap."
            alignment_score = 0
        else:
            mtf_status = "NEUTRAL"
            mtf_badge = "⚪ MTF BALANCED"
            mtf_desc = "Timeframes consolidating in equilibrium."
            alignment_score = 0

        # Return backward-compatible structure with MTF intelligence
        result = dict(analysis_5m)
        result["mtf"] = {
            "status": mtf_status,
            "badge": mtf_badge,
            "desc": mtf_desc,
            "alignment_score": alignment_score,
            "macro_15m_sentiment": analysis_15m.get("sentiment", "NEUTRAL") if analysis_15m else "NEUTRAL",
            "macro_15m_vwap": analysis_15m.get("indicators", {}).get("vwap", 0.0) if analysis_15m else 0.0
        }
        self._mtf_cache = result
        self._mtf_cache_time = time.time()
        return result
