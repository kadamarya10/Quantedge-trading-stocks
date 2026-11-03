"""
Chart Pattern Recognition & Price Action Analysis Engine for NIFTY 50  -- v2

Fixes vs v1
-----------
* Patterns / formations are detected on CLOSED candles only (no repainting on the forming candle).
* Candle cache is kept PER INTERVAL (v1 could return 15m candles as 5m after a failed fetch).
* Stale data is detected (last candle too old) and reported instead of silently used.
* Fetches 5 days so EMA/RSI/ATR are meaningful early in the day; VWAP, day high/low and
  patterns use TODAY's session only.
* VWAP is volume-weighted only when the feed has volume. Yahoo's ^NSEI index has none, so it
  falls back to an equal-weighted anchor and says so ("vwap_is_volume_weighted": False).
* Adds ATR(14). EMA / VWAP get a neutral band (no more forced bullish/bearish vote).
* Morning/Evening Star range bug fixed; Hammer/Shooting Star need a preceding move;
  Three Soldiers/Crows need real bodies and proper opens.
* Double Top/Bottom use an ATR-based tolerance, need depth + separation + recency.
* Head & Shoulders (and inverse) are now actually implemented, with a neckline break.
* Day-high breakout means a CLOSE above all prior session highs (not "near the high").
* 15m macro trend can be NEUTRAL.

Pass allow_stale=True (e.g. for --demo / market closed) to analyze old data anyway.
"""

import time
import requests
from typing import Dict, Any, List, Optional, Tuple

INTERVAL_SEC = {"1m": 60, "5m": 300, "15m": 900}
IST_OFFSET = 19800  # seconds


def _day(ts: float) -> int:
    """IST calendar day number for an epoch timestamp."""
    return int((ts + IST_OFFSET) // 86400)


def _atr(candles: List[Dict[str, Any]], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    trs = []
    for p, c in zip(candles[:-1], candles[1:]):
        trs.append(max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"])))
    tail = trs[-period:]
    return sum(tail) / len(tail) if tail else 0.0


class ChartPatternAnalyzer:
    MAX_CACHE_AGE_SEC = 600

    def __init__(self, symbol: str = "^NSEI", allow_stale: bool = False):
        self.symbol = symbol
        self.allow_stale = allow_stale
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        self._candle_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self._mtf_cache: Optional[Dict[str, Any]] = None
        self._mtf_cache_time: float = 0.0

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def fetch_intraday_candles(self, interval: str = "5m") -> List[Dict[str, Any]]:
        """Fetches 5 days of OHLCV candles from Yahoo (includes the still-forming candle).
        Falls back to a per-interval cache for up to MAX_CACHE_AGE_SEC."""
        try:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{self.symbol}"
                   f"?interval={interval}&range=5d")
            res = self.session.get(url, timeout=6)
            if res.status_code == 200:
                result = res.json().get("chart", {}).get("result", [])
                if result:
                    chart = result[0]
                    timestamps = chart.get("timestamp", []) or []
                    q = chart.get("indicators", {}).get("quote", [{}])[0]
                    opens, highs, lows = q.get("open", []), q.get("high", []), q.get("low", [])
                    closes, volumes = q.get("close", []), q.get("volume", [])
                    candles = []
                    for i in range(len(timestamps)):
                        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
                        v = volumes[i] if volumes and i < len(volumes) and volumes[i] is not None else 0
                        if None not in (o, h, l, c):
                            candles.append({"timestamp": timestamps[i], "open": float(o), "high": float(h),
                                            "low": float(l), "close": float(c), "volume": int(v)})
                    if candles:
                        self._candle_cache[interval] = (time.time(), candles)
                        return candles
        except Exception:
            pass
        cached = self._candle_cache.get(interval)
        if cached and time.time() - cached[0] <= self.MAX_CACHE_AGE_SEC:
            return cached[1]
        return []

    # ------------------------------------------------------------------
    # Candlestick patterns (pass CLOSED candles only)
    # ------------------------------------------------------------------
    @staticmethod
    def detect_candlestick_patterns(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        patterns: List[Dict[str, Any]] = []
        if len(candles) < 3:
            return patterns

        c, p, pp = candles[-1], candles[-2], candles[-3]
        o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
        body = abs(cl - o)
        rng = max(0.01, h - l)
        upper_wick = h - max(o, cl)
        lower_wick = min(o, cl) - l
        is_green, is_red = cl >= o, cl < o

        p_o, p_h, p_l, p_cl = p["open"], p["high"], p["low"], p["close"]
        p_body = abs(p_cl - p_o)
        p_rng = max(0.01, p_h - p_l)
        p_is_green, p_is_red = p_cl >= p_o, p_cl < p_o
        pp_body = abs(pp["close"] - pp["open"])

        downtrend = len(candles) >= 4 and candles[-4]["close"] > p_cl
        uptrend = len(candles) >= 4 and candles[-4]["close"] < p_cl

        if downtrend and lower_wick >= 2.0 * body and upper_wick <= 0.25 * rng and lower_wick >= 0.55 * rng:
            patterns.append({"name": "Hammer (Bullish Pin Bar)", "type": "BULLISH", "significance": "High",
                             "desc": "Rejection of lower prices after a decline; buyers stepping in."})
        if uptrend and upper_wick >= 2.0 * body and lower_wick <= 0.25 * rng and upper_wick >= 0.55 * rng:
            patterns.append({"name": "Shooting Star (Bearish Pin Bar)", "type": "BEARISH", "significance": "High",
                             "desc": "Rejection of higher prices after a rise; sellers defending the top."})
        if p_is_red and is_green and cl > p_o and o < p_cl and body > p_body * 1.1:
            patterns.append({"name": "Bullish Engulfing", "type": "BULLISH", "significance": "High",
                             "desc": "Green candle engulfs prior red body."})
        if p_is_green and is_red and cl < p_o and o > p_cl and body > p_body * 1.1:
            patterns.append({"name": "Bearish Engulfing", "type": "BEARISH", "significance": "High",
                             "desc": "Red candle engulfs prior green body."})
        # Morning / Evening Star: compare the MIDDLE candle to ITS OWN range and the first body
        if (pp["close"] < pp["open"] and pp_body > 0 and p_body <= p_rng * 0.4 and p_body < pp_body * 0.6
                and is_green and cl > (pp["open"] + pp["close"]) / 2):
            patterns.append({"name": "Morning Star", "type": "BULLISH", "significance": "Very High",
                             "desc": "3-candle bullish reversal: sellers exhausted, buyers recover."})
        if (pp["close"] >= pp["open"] and pp_body > 0 and p_body <= p_rng * 0.4 and p_body < pp_body * 0.6
                and is_red and cl < (pp["open"] + pp["close"]) / 2):
            patterns.append({"name": "Evening Star", "type": "BEARISH", "significance": "Very High",
                             "desc": "3-candle bearish reversal: buyers exhausted, supply arrives."})
        if h <= p_h and l >= p_l:
            patterns.append({"name": "Inside Bar (Harami Coiling)", "type": "NEUTRAL", "significance": "Medium",
                             "desc": "Price compressed inside prior range; breakout pending."})
        if body <= rng * 0.12 and not patterns:
            patterns.append({"name": "Doji (Market Indecision)", "type": "NEUTRAL", "significance": "Medium",
                             "desc": "Bulls and bears balanced."})

        def strong_green(x):
            return x["close"] > x["open"] and (x["close"] - x["open"]) >= 0.5 * max(0.01, x["high"] - x["low"])

        def strong_red(x):
            return x["close"] < x["open"] and (x["open"] - x["close"]) >= 0.5 * max(0.01, x["high"] - x["low"])

        if (strong_green(c) and strong_green(p) and strong_green(pp) and cl > p_cl > pp["close"]
                and pp["open"] <= p_o <= pp["close"] and p_o <= o <= p_cl):
            patterns.append({"name": "Three White Soldiers (Strong Bullish Wave)", "type": "BULLISH",
                             "significance": "High", "desc": "3 strong green candles, each opening inside the last body."})
        elif (strong_red(c) and strong_red(p) and strong_red(pp) and cl < p_cl < pp["close"]
              and pp["close"] <= p_o <= pp["open"] and p_cl <= o <= p_o):
            patterns.append({"name": "Three Black Crows (Strong Bearish Wave)", "type": "BEARISH",
                             "significance": "High", "desc": "3 strong red candles, each opening inside the last body."})
        return patterns

    # ------------------------------------------------------------------
    # Formations (pass TODAY's CLOSED candles)
    # ------------------------------------------------------------------
    @staticmethod
    def _swings(highs: List[float], lows: List[float]):
        sh, sl = [], []
        for i in range(2, len(highs) - 2):
            if highs[i] > max(highs[i - 2:i]) and highs[i] > max(highs[i + 1:i + 3]):
                sh.append((i, highs[i]))
            if lows[i] < min(lows[i - 2:i]) and lows[i] < min(lows[i + 1:i + 3]):
                sl.append((i, lows[i]))
        return sh, sl

    @staticmethod
    def detect_chart_formations(candles: List[Dict[str, Any]], atr: Optional[float] = None) -> List[Dict[str, Any]]:
        formations: List[Dict[str, Any]] = []
        if len(candles) < 10:
            return formations

        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]
        n = len(candles)
        price = closes[-1]
        if atr is None or atr <= 0:
            atr = _atr(candles) or price * 0.001
        tol = max(0.35 * atr, 0.0005 * price)
        RECENT = 15  # last pivot must be within this many candles

        # 1. Breakout / breakdown: a CLOSE beyond every prior session high/low
        prior_high, prior_low = max(highs[:-1]), min(lows[:-1])
        if price > prior_high:
            formations.append({"name": "Day High Breakout", "type": "BULLISH", "level": round(prior_high, 2),
                               "desc": f"Closed above all prior session highs ({prior_high:.2f})."})
        elif price < prior_low:
            formations.append({"name": "Day Low Breakdown", "type": "BEARISH", "level": round(prior_low, 2),
                               "desc": f"Closed below all prior session lows ({prior_low:.2f})."})

        sh, sl = ChartPatternAnalyzer._swings(highs, lows)

        # 2. Double Bottom
        if len(sl) >= 2:
            (i1, l1), (i2, l2) = sl[-2], sl[-1]
            peak = max(highs[i1:i2 + 1])
            if (n - 1 - i2 <= RECENT and i2 - i1 >= 4 and abs(l1 - l2) <= tol
                    and (peak - max(l1, l2)) >= 1.0 * atr and price >= l2):
                formations.append({"name": "Double Bottom (W Pattern)", "type": "BULLISH",
                                   "level": round((l1 + l2) / 2, 2),
                                   "desc": f"W base around {(l1 + l2) / 2:.1f} with a rally between the lows."})
        # 3. Double Top
        if len(sh) >= 2:
            (i1, h1), (i2, h2) = sh[-2], sh[-1]
            trough = min(lows[i1:i2 + 1])
            if (n - 1 - i2 <= RECENT and i2 - i1 >= 4 and abs(h1 - h2) <= tol
                    and (min(h1, h2) - trough) >= 1.0 * atr and price <= h2):
                formations.append({"name": "Double Top (M Pattern)", "type": "BEARISH",
                                   "level": round((h1 + h2) / 2, 2),
                                   "desc": f"M ceiling around {(h1 + h2) / 2:.1f} with a dip between the highs."})
        # 4. Head & Shoulders (needs neckline break)
        if len(sh) >= 3:
            (i1, h1), (i2, h2), (i3, h3) = sh[-3:]
            neck = min(min(lows[i1:i2 + 1]), min(lows[i2:i3 + 1]))
            if (n - 1 - i3 <= RECENT and h2 > max(h1, h3) + 0.5 * atr and abs(h1 - h3) <= 1.0 * atr
                    and price < neck):
                formations.append({"name": "Head & Shoulders", "type": "BEARISH", "level": round(neck, 2),
                                   "desc": f"Neckline {neck:.1f} broken after a head-and-shoulders top."})
        if len(sl) >= 3:
            (i1, l1), (i2, l2), (i3, l3) = sl[-3:]
            neck = max(max(highs[i1:i2 + 1]), max(highs[i2:i3 + 1]))
            if (n - 1 - i3 <= RECENT and l2 < min(l1, l3) - 0.5 * atr and abs(l1 - l3) <= 1.0 * atr
                    and price > neck):
                formations.append({"name": "Inverse Head & Shoulders", "type": "BULLISH", "level": round(neck, 2),
                                   "desc": f"Neckline {neck:.1f} broken after an inverse head-and-shoulders."})
        # 5. Market structure
        if len(sh) >= 2 and len(sl) >= 2:
            if sh[-1][1] > sh[-2][1] and sl[-1][1] > sl[-2][1]:
                formations.append({"name": "Ascending Structure (Higher Highs & Higher Lows)", "type": "BULLISH",
                                   "level": round(sl[-1][1], 2), "desc": "Intraday uptrend staircase."})
            elif sh[-1][1] < sh[-2][1] and sl[-1][1] < sl[-2][1]:
                formations.append({"name": "Descending Structure (Lower Highs & Lower Lows)", "type": "BEARISH",
                                   "level": round(sh[-1][1], 2), "desc": "Intraday downtrend staircase."})
        return formations

    # ------------------------------------------------------------------
    # Indicators
    # ------------------------------------------------------------------
    @staticmethod
    def calculate_technical_indicators(
        candles: List[Dict[str, Any]],
        session_candles: Optional[List[Dict[str, Any]]] = None,
        live_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """EMA/RSI/ATR use `candles` (multi-day, closed). VWAP uses `session_candles` (today).
        vwap_bias compares `live_price` (or last close) with VWAP."""
        closes = [c["close"] for c in candles]
        if not closes:
            return {}
        session = session_candles if session_candles else candles

        def get_ema(data: List[float], period: int) -> float:
            if len(data) < period:
                return sum(data) / len(data)
            k = 2.0 / (period + 1)
            val = sum(data[:period]) / period
            for x in data[period:]:
                val = x * k + val * (1.0 - k)
            return val

        ema9, ema21 = get_ema(closes, 9), get_ema(closes, 21)
        atr = _atr(candles)

        total_vol = sum(c.get("volume", 0) or 0 for c in session)
        vol_weighted = total_vol > 0
        cum_vp = cum_v = 0.0
        for c in session:
            tp = (c["high"] + c["low"] + c["close"]) / 3.0
            v = (c.get("volume", 0) or 0) if vol_weighted else 1
            cum_vp += tp * v
            cum_v += v
        price = live_price if live_price else closes[-1]
        vwap = cum_vp / cum_v if cum_v > 0 else price

        rsi = 50.0
        if len(closes) >= 15:
            gains, losses = [], []
            for i in range(1, len(closes)):
                d = closes[i] - closes[i - 1]
                gains.append(max(d, 0.0))
                losses.append(max(-d, 0.0))
            period = 14
            avg_g = sum(gains[:period]) / period
            avg_l = sum(losses[:period]) / period
            for i in range(period, len(gains)):
                avg_g = (avg_g * (period - 1) + gains[i]) / period
                avg_l = (avg_l * (period - 1) + losses[i]) / period
            rsi = 100.0 if avg_l == 0 else round(100.0 - 100.0 / (1.0 + avg_g / avg_l), 2)

        band = 0.05 * atr
        if ema9 - ema21 > band:
            ema_trend = "BULLISH"
        elif ema21 - ema9 > band:
            ema_trend = "BEARISH"
        else:
            ema_trend = "NEUTRAL"

        vband = 0.10 * atr
        if price - vwap > vband:
            vwap_bias = "ABOVE_VWAP (Bullish)"
        elif vwap - price > vband:
            vwap_bias = "BELOW_VWAP (Bearish)"
        else:
            vwap_bias = "NEAR_VWAP (Neutral)"

        return {
            "ema9": round(ema9, 2), "ema21": round(ema21, 2), "vwap": round(vwap, 2),
            "vwap_is_volume_weighted": vol_weighted, "rsi": rsi, "atr": round(atr, 2),
            "ema_trend": ema_trend, "vwap_bias": vwap_bias,
        }

    # ------------------------------------------------------------------
    def _empty(self, interval: str, status: str) -> Dict[str, Any]:
        return {
            "interval": interval, "status": status, "is_stale": True,
            "candlestick_patterns": [], "chart_formations": [], "indicators": {},
            "sentiment": "NEUTRAL", "confidence": 50, "summary": status,
        }

    def analyze_patterns(self, interval: str = "5m") -> Dict[str, Any]:
        all_c = self.fetch_intraday_candles(interval=interval)
        if not all_c:
            return self._empty(interval, "No candle data available")

        step = INTERVAL_SEC.get(interval, 300)
        now = time.time()
        age = now - all_c[-1]["timestamp"]
        stale = age > step * 3 + 60
        if stale and not self.allow_stale:
            return self._empty(interval, f"Stale candles ({int(age)}s old): market closed or feed delayed")

        # closed = fully formed candles. If data is stale/old, everything is closed.
        closed_all = [c for c in all_c if c["timestamp"] + step <= now] or all_c[:-1] or all_c
        today = _day(all_c[-1]["timestamp"])
        session_all = [c for c in all_c if _day(c["timestamp"]) == today]
        session_closed = [c for c in closed_all if _day(c["timestamp"]) == today]
        live_price = all_c[-1]["close"]

        indicators = self.calculate_technical_indicators(closed_all, session_all, live_price)
        atr = indicators.get("atr", 0.0)
        candlestick_patterns = self.detect_candlestick_patterns(session_closed)
        chart_formations = self.detect_chart_formations(session_closed, atr)

        bull = bear = 0
        for p in candlestick_patterns:
            bull += 2 if p["type"] == "BULLISH" else 0
            bear += 2 if p["type"] == "BEARISH" else 0
        for f in chart_formations:
            bull += 3 if f["type"] == "BULLISH" else 0
            bear += 3 if f["type"] == "BEARISH" else 0
        if indicators.get("ema_trend") == "BULLISH":
            bull += 1
        elif indicators.get("ema_trend") == "BEARISH":
            bear += 1
        if "ABOVE_VWAP" in indicators.get("vwap_bias", ""):
            bull += 1
        elif "BELOW_VWAP" in indicators.get("vwap_bias", ""):
            bear += 1
        rsi = indicators.get("rsi", 50.0)
        if rsi > 55:
            bull += 1
        elif rsi < 45:
            bear += 1

        total = bull + bear
        if bull >= bear + 2:
            sentiment, confidence = "BULLISH PRICE ACTION", min(95, int(bull / max(1, total) * 100))
        elif bear >= bull + 2:
            sentiment, confidence = "BEARISH PRICE ACTION", min(95, int(bear / max(1, total) * 100))
        else:
            sentiment, confidence = "CONSOLIDATION / NEUTRAL", 50

        labels = [p["name"] for p in candlestick_patterns] + [f["name"] for f in chart_formations]
        if not labels:
            labels = ["Trend Following Range", indicators.get("vwap_bias", "")]

        return {
            "interval": interval,
            "candles_count": len(session_closed),
            "current_close": live_price,
            "day_high": max(c["high"] for c in session_all),
            "day_low": min(c["low"] for c in session_all),
            "candlestick_patterns": candlestick_patterns,
            "chart_formations": chart_formations,
            "indicators": indicators,
            "sentiment": sentiment,
            "confidence": confidence,
            "summary": " | ".join(labels[:3]),
            "is_stale": stale,
            "last_candle_age_sec": int(age),
        }

    # ------------------------------------------------------------------
    def analyze_multi_timeframe(self) -> Dict[str, Any]:
        """15m macro trend + 5m trigger. Cached for 45 s."""
        now = time.time()
        if self._mtf_cache is not None and (now - self._mtf_cache_time) < 45.0:
            return self._mtf_cache

        a5 = self.analyze_patterns(interval="5m")
        a15 = self.analyze_patterns(interval="15m")
        if not a5 or not a5.get("indicators"):
            return a5 or {}

        bull15 = bear15 = False
        if a15 and a15.get("indicators"):
            ind = a15["indicators"]
            bp = (ind.get("ema_trend") == "BULLISH") + ("ABOVE_VWAP" in ind.get("vwap_bias", "")) + (ind.get("rsi", 50) >= 55)
            sp = (ind.get("ema_trend") == "BEARISH") + ("BELOW_VWAP" in ind.get("vwap_bias", "")) + (ind.get("rsi", 50) <= 45)
            sent = a15.get("sentiment", "")
            bull15 = "BULLISH" in sent or (bp >= 2 and bp > sp)
            bear15 = "BEARISH" in sent or (sp >= 2 and sp > bp)
            if bull15 and bear15:
                bull15 = bear15 = False

        bull5 = "BULLISH" in a5.get("sentiment", "")
        bear5 = "BEARISH" in a5.get("sentiment", "")

        if bull15 and bull5:
            st, badge, desc, score = ("ALIGNED_BULLISH", "🟢 MTF CONGRUENT (15m + 5m BULLISH)",
                                      "15m trend and 5m price action both bullish.", 3)
        elif bear15 and bear5:
            st, badge, desc, score = ("ALIGNED_BEARISH", "🔴 MTF CONGRUENT (15m + 5m BEARISH)",
                                      "15m trend and 5m price action both bearish.", -3)
        elif bull15 and bear5:
            st, badge, desc, score = ("BULLISH_PULLBACK", "🟡 15m BULLISH (5m Pullback / Dip)",
                                      "15m bullish; 5m in a pullback. Wait for a 5m reversal.", 0)
        elif bear15 and bull5:
            st, badge, desc, score = ("BEARISH_BOUNCE", "🟡 15m BEARISH (5m Bounce Trap)",
                                      "15m bearish; 5m bouncing. Bull-trap risk.", 0)
        else:
            st, badge, desc, score = ("NEUTRAL", "⚪ MTF BALANCED", "Timeframes in equilibrium.", 0)

        result = dict(a5)
        result["mtf"] = {
            "status": st, "badge": badge, "desc": desc, "alignment_score": score,
            "macro_15m_sentiment": a15.get("sentiment", "NEUTRAL") if a15 else "NEUTRAL",
            "macro_15m_vwap": (a15.get("indicators", {}) or {}).get("vwap", 0.0) if a15 else 0.0,
        }
        self._mtf_cache = result
        self._mtf_cache_time = time.time()
        return result
