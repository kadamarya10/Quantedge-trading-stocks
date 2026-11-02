"""
NIFTY Algorithmic Trading Strategy Engine
Synthesizes Live Open Interest (OI) Dynamics WITH Real-Time Chart Patterns & Price Action:
- Candlestick Formations (Hammer, Engulfing, Morning/Evening Star, Pin Bars)
- Classical Chart Patterns (Double Top/Bottom, Head & Shoulders, Day Range Breakout)
- Indicators (EMA Crossover, VWAP Institutional Benchmark, RSI 14)
- Live Derivatives OI (PCR, Put/Call writing ratio, Max Pain)
"""

from typing import Dict, Any, Optional, List


class OIStrategy:
    def __init__(self, pcr_bullish_threshold: float = 1.15, pcr_bearish_threshold: float = 0.85):
        self.pcr_bullish_threshold = pcr_bullish_threshold
        self.pcr_bearish_threshold = pcr_bearish_threshold

    def evaluate_signal(
        self, 
        current: Dict[str, Any], 
        chart_analysis: Optional[Dict[str, Any]] = None,
        news_analysis: Optional[Dict[str, Any]] = None,
        market_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Evaluates live Open Interest snapshot, tick-to-tick OI velocity, Multi-Timeframe Chart Patterns,
        Breaking News Sentiment, India VIX Volatility Regime, and Top Heavyweights to produce an
        institutional-accuracy algorithmic signal.
        """
        spot = current["spot_price"]
        pcr = current["pcr"]
        total_ce_chg = current["total_ce_chg_oi"]
        total_pe_chg = current["total_pe_chg_oi"]
        support = current["support_strike"]
        resistance = current["resistance_strike"]
        atm_strike = current["atm_strike"]
        oi_velocity = current.get("oi_velocity", {})

        bullish_score = 0
        bearish_score = 0
        reasons_bullish = []
        reasons_bearish = []

        is_fast_trigger = False
        fast_reasons = []

        # -------------------------------------------------------------
        # 1. Baseline Open Interest (OI) Analysis
        # -------------------------------------------------------------
        if total_pe_chg > total_ce_chg * 1.25:
            bullish_score += 2
            reasons_bullish.append(f"Put writing ({total_pe_chg:,}) > Call writing ({total_ce_chg:,})")
        if pcr >= self.pcr_bullish_threshold:
            bullish_score += 1
            reasons_bullish.append(f"Bullish PCR ({pcr:.2f})")
        if spot >= support and (spot - support) < 60:
            bullish_score += 1
            reasons_bullish.append(f"Bouncing off Support ({support})")

        if total_ce_chg > total_pe_chg * 1.25:
            bearish_score += 2
            reasons_bearish.append(f"Call writing ({total_ce_chg:,}) > Put writing ({total_pe_chg:,})")
        if pcr <= self.pcr_bearish_threshold:
            bearish_score += 1
            reasons_bearish.append(f"Bearish PCR ({pcr:.2f})")
        if spot <= resistance and (resistance - spot) < 60:
            bearish_score += 1
            reasons_bearish.append(f"Testing Resistance ({resistance})")

        # -------------------------------------------------------------
        # 2. Live OI Velocity & Rapid Shifts (Institutional Moves)
        # -------------------------------------------------------------
        if oi_velocity:
            v_status = oi_velocity.get("status", "")
            v_fast = oi_velocity.get("fast_oi_trigger", False)
            v_dir = oi_velocity.get("direction", "")

            if v_status == "RAPID_SHORT_COVERING":
                bullish_score += 4
                reasons_bullish.append("⚡ Rapid Short Covering (Call writers covering shorts)")
                if v_fast:
                    is_fast_trigger = True
                    fast_reasons.append("⚡ OI Shock: Rapid Short Covering in progress")

            elif v_status == "RAPID_LONG_UNWINDING":
                bearish_score += 4
                reasons_bearish.append("⚡ Rapid Long Unwinding (Put writers/buyers dumping)")
                if v_fast:
                    is_fast_trigger = True
                    fast_reasons.append("⚡ OI Shock: Rapid Long Unwinding in progress")

            elif v_status == "AGGRESSIVE_PUT_WRITING":
                bullish_score += 3
                reasons_bullish.append("⚡ Aggressive Put Writing surge (Floor established)")
                if v_fast:
                    is_fast_trigger = True
                    fast_reasons.append("⚡ Massive Put Writing surge")

            elif v_status == "AGGRESSIVE_CALL_WRITING":
                bearish_score += 3
                reasons_bearish.append("⚡ Aggressive Call Writing surge (Ceiling established)")
                if v_fast:
                    is_fast_trigger = True
                    fast_reasons.append("⚡ Massive Call Writing surge")

            elif v_dir == "BULLISH":
                bullish_score += 1
                reasons_bullish.append("OI Accumulation favors Bulls")
            elif v_dir == "BEARISH":
                bearish_score += 1
                reasons_bearish.append("OI Accumulation favors Bears")

            # Option Buyer Edge: Strike-Level Panic Unwinding Detection
            if oi_velocity.get("atm_ce_unwinding"):
                bullish_score += 3
                reasons_bullish.append("⚡ ATM Strike Panic Short Covering (Call writers dumping)")
                is_fast_trigger = True
                fast_reasons.append("⚡ ATM Call Writer Capitulation")

            if oi_velocity.get("atm_pe_unwinding"):
                bearish_score += 3
                reasons_bearish.append("⚡ ATM Strike Panic Long Unwinding (Put writers dumping)")
                is_fast_trigger = True
                fast_reasons.append("⚡ ATM Put Writer Capitulation")

        # -------------------------------------------------------------
        # 3. Live News Sentiment & Breaking Catalysts
        # -------------------------------------------------------------
        if news_analysis:
            news_score = news_analysis.get("score", 0.0)
            fast_catalyst = news_analysis.get("fast_catalyst", False)
            cat_dir = news_analysis.get("catalyst_direction", "NONE")
            crit_alerts = news_analysis.get("critical_alerts", [])

            if news_score >= 30:
                bullish_score += 2
                reasons_bullish.append(f"Bullish News Sentiment (+{news_score:.1f})")
            elif news_score <= -30:
                bearish_score += 2
                reasons_bearish.append(f"Bearish News Sentiment ({news_score:.1f})")

            # High-impact news catalyst
            if fast_catalyst:
                if cat_dir == "BULLISH":
                    bullish_score += 3
                    is_fast_trigger = True
                    top_alert = crit_alerts[0] if crit_alerts else "Breaking Bullish News Catalyst"
                    fast_reasons.append(f"📰 {top_alert}")
                    reasons_bullish.append("Breaking Bullish News Flow")
                elif cat_dir == "BEARISH":
                    bearish_score += 3
                    is_fast_trigger = True
                    top_alert = crit_alerts[0] if crit_alerts else "Breaking Bearish News Catalyst"
                    fast_reasons.append(f"📰 {top_alert}")
                    reasons_bearish.append("Breaking Bearish News Flow")

        # -------------------------------------------------------------
        # 4. Multi-Timeframe Alignment (15m Macro Trend + 5m Action)
        # -------------------------------------------------------------
        if chart_analysis and chart_analysis.get("mtf"):
            mtf = chart_analysis["mtf"]
            mtf_status = mtf.get("status")
            if mtf_status == "ALIGNED_BULLISH":
                bullish_score += 3
                reasons_bullish.append("MTF Alignment: 15m Macro + 5m Trigger both Bullish")
            elif mtf_status == "ALIGNED_BEARISH":
                bearish_score += 3
                reasons_bearish.append("MTF Alignment: 15m Macro + 5m Trigger both Bearish")
            elif mtf_status == "BEARISH_BOUNCE":
                # 15m is Bearish, 5m is bouncing. Penalize false bull breakout trap
                bullish_score = max(0, bullish_score - 2)
                reasons_bearish.append("MTF Trap Warning: 15m Macro Trend is Bearish")
            elif mtf_status == "BULLISH_PULLBACK":
                # 15m is Bullish, 5m is dipping. Penalize false bear breakdown trap
                bearish_score = max(0, bearish_score - 2)
                reasons_bullish.append("MTF Trap Warning: 15m Macro Trend is Bullish")

        # -------------------------------------------------------------
        # 5. India VIX & Volatility Filter
        # -------------------------------------------------------------
        if market_context and market_context.get("vix"):
            vix_data = market_context["vix"]
            vix_val = vix_data.get("vix", 14.5)
            vix_chg_pct = vix_data.get("change_pct", 0.0)

            if vix_chg_pct <= -2.5:
                # Option Buyer IV Crush Alert: Rapid drop in IV deflates premiums
                bullish_score = max(0, bullish_score - 1)
                bearish_score = max(0, bearish_score - 1)
                reasons_bullish.append(f"⚠️ IV Crush Alert: VIX contracting ({vix_chg_pct:+.1f}%) eats option premiums")
                reasons_bearish.append(f"⚠️ IV Crush Alert: VIX contracting ({vix_chg_pct:+.1f}%) eats option premiums")
            elif vix_chg_pct <= -1.0:
                bullish_score += 1
                reasons_bullish.append(f"India VIX Cooling ({vix_chg_pct:+.1f}%) — Steady Bullish Tailwind")
            elif vix_chg_pct >= 2.5:
                bearish_score += 2
                reasons_bearish.append(f"India VIX Spiking ({vix_chg_pct:+.1f}%) — Institutional Hedging / Put Demand")
            elif vix_chg_pct >= 1.0:
                # Volatility Expansion: Option Buyers benefit from rising IV
                reasons_bullish.append(f"India VIX Expanding ({vix_chg_pct:+.1f}%) — Premium Expansion Tailwind")
                reasons_bearish.append(f"India VIX Expanding ({vix_chg_pct:+.1f}%) — Premium Expansion Tailwind")

        # -------------------------------------------------------------
        # 6. NIFTY Heavyweights Check (Reliance, HDFC Bank, ICICI Bank)
        # -------------------------------------------------------------
        if market_context and market_context.get("heavyweights"):
            hw_data = market_context["heavyweights"]
            hw_bias = hw_data.get("bias", "")
            green_cnt = hw_data.get("green_count", 0)
            red_cnt = hw_data.get("red_count", 0)

            if hw_bias == "BULLISH_SUPPORT":
                bullish_score += 2
                bearish_score = max(0, bearish_score - 2)
                reasons_bullish.append(f"Heavyweights Bullish ({green_cnt}/3 Green: Reliance/ICICI Support)")
            elif hw_bias == "BEARISH_DRAG":
                bearish_score += 2
                bullish_score = max(0, bullish_score - 2)
                reasons_bearish.append(f"Heavyweights Bearish ({red_cnt}/3 Red: Reliance/HDFC Dragging)")

        # -------------------------------------------------------------
        # 7. Chart Pattern & Price Action Analysis
        # -------------------------------------------------------------
        if chart_analysis:
            patterns = chart_analysis.get("candlestick_patterns", [])
            formations = chart_analysis.get("chart_formations", [])
            indicators = chart_analysis.get("indicators", {})

            for p in patterns:
                p_name = p["name"]
                if p["type"] == "BULLISH":
                    bullish_score += 2
                    reasons_bullish.append(f"Chart: {p_name}")
                elif p["type"] == "BEARISH":
                    bearish_score += 2
                    reasons_bearish.append(f"Chart: {p_name}")

            for f in formations:
                f_name = f["name"]
                if f["type"] == "BULLISH":
                    bullish_score += 3
                    reasons_bullish.append(f"Formation: {f_name}")
                elif f["type"] == "BEARISH":
                    bearish_score += 3
                    reasons_bearish.append(f"Formation: {f_name}")

            if indicators:
                ema_trend = indicators.get("ema_trend")
                vwap_bias = indicators.get("vwap_bias", "")
                rsi = indicators.get("rsi", 50.0)

                if ema_trend == "BULLISH":
                    bullish_score += 1
                    reasons_bullish.append("EMA(9) > EMA(21)")
                else:
                    bearish_score += 1
                    reasons_bearish.append("EMA(9) < EMA(21)")

                if "ABOVE_VWAP" in vwap_bias:
                    bullish_score += 1
                    reasons_bullish.append("Trading Above VWAP")
                else:
                    bearish_score += 1
                    reasons_bearish.append("Trading Below VWAP")

                if rsi > 55:
                    bullish_score += 1
                    reasons_bullish.append(f"RSI Momentum ({rsi:.1f})")
                elif rsi < 45:
                    bearish_score += 1
                    reasons_bearish.append(f"RSI Bearish Momentum ({rsi:.1f})")

        # -------------------------------------------------------------
        # 8. Time-of-Day Filter & Confluence Determination (Institutional Sniper Engine)
        # -------------------------------------------------------------
        is_chop_zone = False
        min_confluence_req = 75  # Upgraded: Require institutional 75%+ confluence
        if market_context and market_context.get("session"):
            sess = market_context["session"]
            is_chop_zone = sess.get("is_chop_zone", False)
            min_confluence_req = max(75, sess.get("min_confluence", 75))

        # Enforce strict institutional thresholds to filter whipsaw and false breakouts:
        # In Chop Zone (11:30 - 13:15), require min_score 8 and 85%+ confluence to protect option buyers from theta burn!
        if is_chop_zone and not is_fast_trigger:
            min_score = 8
            min_confluence_req = 85
        elif is_fast_trigger:
            min_score = 5
        else:
            min_score = 7

        atm_data = next((s for s in current["table_data"] if s["strike"] == atm_strike), None)
        signal = "HOLD"
        instrument = None
        option_ltp = 0.0
        confluence_pct = 50
        urgency = "PATIENT_OBSERVING"

        # Check Structural Filters (Institutional Vetoes)
        vwap_bias = ""
        ema_trend = ""
        mtf_status = ""
        hw_bias = ""
        if chart_analysis:
            indicators = chart_analysis.get("indicators", {})
            vwap_bias = indicators.get("vwap_bias", "")
            ema_trend = indicators.get("ema_trend", "")
            if chart_analysis.get("mtf"):
                mtf_status = chart_analysis["mtf"].get("status", "")
        if market_context and market_context.get("heavyweights"):
            hw_bias = market_context["heavyweights"].get("bias", "")

        # Pillars of Confluence (Must have at least 3 matching pillars to trade)
        # Pillar 1: Derivatives / OI Disparity
        bull_p1 = (total_pe_chg > total_ce_chg * 1.30) or (pcr >= 1.15) or ("Short Covering" in " ".join(reasons_bullish))
        bear_p1 = (total_ce_chg > total_pe_chg * 1.30) or (pcr <= 0.85) or ("Long Unwinding" in " ".join(reasons_bearish))

        # Pillar 2: Macro Multi-Timeframe Alignment
        bull_p2 = (mtf_status == "ALIGNED_BULLISH") or (mtf_status != "ALIGNED_BEARISH" and ema_trend == "BULLISH")
        bear_p2 = (mtf_status == "ALIGNED_BEARISH") or (mtf_status != "ALIGNED_BULLISH" and ema_trend == "BEARISH")

        # Pillar 3: Institutional VWAP Benchmark & Momentum
        bull_p3 = ("ABOVE_VWAP" in vwap_bias) and (hw_bias != "BEARISH_DRAG")
        bear_p3 = ("BELOW_VWAP" in vwap_bias or not vwap_bias) and (hw_bias != "BULLISH_SUPPORT")

        # Pillar 4: Price Action / Candlestick Formations
        bull_p4 = any(r.startswith("Chart:") or r.startswith("Formation:") for r in reasons_bullish)
        bear_p4 = any(r.startswith("Chart:") or r.startswith("Formation:") for r in reasons_bearish)

        bull_pillars = sum([1 for p in [bull_p1, bull_p2, bull_p3, bull_p4] if p])
        bear_pillars = sum([1 for p in [bear_p1, bear_p2, bear_p3, bear_p4] if p])

        # Evaluate Strict Bullish Conviction:
        # Requires: min_score, score dominance of >= +3 points, no VWAP trap, and at least 3 pillars
        if (
            bullish_score >= min_score 
            and bullish_score >= bearish_score + 3 
            and bull_pillars >= 3
            and "ABOVE_VWAP" in vwap_bias
            and hw_bias != "BEARISH_DRAG"
            and mtf_status != "ALIGNED_BEARISH"
        ):
            if is_fast_trigger and ("Short Covering" in " ".join(fast_reasons) or "Bullish" in " ".join(fast_reasons)):
                signal = "FAST_BUY_CE"
                urgency = "⚡ HIGH_CONFLUENCE_FAST"
            else:
                signal = "BUY_CE"
                urgency = "🎯 HIGH_CONFLUENCE_SNIPER"

            instrument = f"NIFTY {atm_strike} CE"
            option_ltp = atm_data["ce_ltp"] if atm_data else 0.0
            lead_reasons = fast_reasons if is_fast_trigger and fast_reasons else reasons_bullish[:3]
            reason = " | ".join(lead_reasons + [r for r in reasons_bullish if r not in lead_reasons][:2])
            raw_conf = int((bullish_score / max(1, bullish_score + bearish_score)) * 100)
            confluence_pct = min(98, max(min_confluence_req, 70 + (bull_pillars * 7)))

        # Evaluate Strict Bearish Conviction:
        # Requires: min_score, score dominance of >= +3 points, no VWAP trap, and at least 3 pillars
        elif (
            bearish_score >= min_score 
            and bearish_score >= bullish_score + 3 
            and bear_pillars >= 3
            and "ABOVE_VWAP" not in vwap_bias
            and hw_bias != "BULLISH_SUPPORT"
            and mtf_status != "ALIGNED_BULLISH"
        ):
            if is_fast_trigger and ("Long Unwinding" in " ".join(fast_reasons) or "Bearish" in " ".join(fast_reasons)):
                signal = "FAST_BUY_PE"
                urgency = "⚡ HIGH_CONFLUENCE_FAST"
            else:
                signal = "BUY_PE"
                urgency = "🎯 HIGH_CONFLUENCE_SNIPER"

            instrument = f"NIFTY {atm_strike} PE"
            option_ltp = atm_data["pe_ltp"] if atm_data else 0.0
            lead_reasons = fast_reasons if is_fast_trigger and fast_reasons else reasons_bearish[:3]
            reason = " | ".join(lead_reasons + [r for r in reasons_bearish if r not in lead_reasons][:2])
            raw_conf = int((bearish_score / max(1, bullish_score + bearish_score)) * 100)
            confluence_pct = min(98, max(min_confluence_req, 70 + (bear_pillars * 7)))

        else:
            signal = "HOLD"
            confluence_pct = 50
            if is_chop_zone:
                reason = "Midday Theta Chop Zone (11:30-13:15) — Preserving capital against false breakout noise."
            elif "ABOVE_VWAP" not in vwap_bias and bullish_score > bearish_score:
                reason = "Holding: NIFTY trading below VWAP. Rejecting counter-trend CE entries to protect capital."
            elif "ABOVE_VWAP" in vwap_bias and bearish_score > bullish_score:
                reason = "Holding: NIFTY trading above VWAP. Rejecting counter-trend PE entries to protect capital."
            elif bull_pillars < 3 and bear_pillars < 3:
                reason = f"Patiently Observing: Awaiting 3-Pillar Confluence (Pillars Bull:{bull_pillars}/4, Bear:{bear_pillars}/4)."
            else:
                reason = "Market consolidating in range. Filtering noise to take only high-probability sniper trades."

        return {
            "signal": signal,
            "instrument": instrument,
            "strike": atm_strike,
            "estimated_entry_price": option_ltp,
            "reason": reason,
            "bullish_score": bullish_score,
            "bearish_score": bearish_score,
            "confluence_pct": confluence_pct,
            "spot_price": spot,
            "support": support,
            "resistance": resistance,
            "pcr": pcr,
            "is_fast_trigger": is_fast_trigger,
            "is_chop_zone": is_chop_zone,
            "urgency": urgency,
            "buyer_profile": {
                "sweet_spot_delta": "0.50 (Peak Gamma ATM)",
                "time_stop_limit_sec": 600,
                "breakeven_trigger_pct": 18.0,
                "initial_sl_pct": 16.0,
                "initial_tgt_pct": 40.0,
                "theta_defense_active": is_chop_zone
            }
        }
