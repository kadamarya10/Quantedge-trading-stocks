"""
NIFTY Algorithmic Trading Strategy Engine -- v2

Works with oi_analyzer.py v2 (windowed OI flow) and your existing main.py / paper_trader.py.
Return dict keeps every key the old version returned, plus a few extras.

What changed vs v1
------------------
* Negative-OI bug fixed: uses normalized imbalance, not ratio comparisons.
* No more free "bearish +1" when EMA/VWAP data is missing or neutral. Trades need chart data.
* Scoring is order-independent: contributions are collected, penalties applied once at the end.
* Derivatives pillar is MANDATORY: OI flow must confirm (price-only setups are skipped).
* confluence_pct is now real: it gates entries (it used to be a cosmetic floor).
* Fast triggers no longer bypass the chop-zone filter; they only get a slightly lower bar.
* Signal must persist across N distinct data snapshots (not N loop ticks) + flip cooldown.
* Chart patterns/news are down-weighted and capped (weak evidence at this horizon).
* Entry price uses ask (if the feed provides it) + slippage.
* Expiry-day / broad-unwinding / warm-up make the bar higher.
* Returns a flat `features` dict so you can log every decision and train on it later.
"""

import time
from typing import Dict, Any, Optional, List


def _imb(pe_val: float, ce_val: float) -> float:
    d = abs(pe_val) + abs(ce_val)
    return (pe_val - ce_val) / d if d else 0.0


class OIStrategy:
    # ---- weights / caps (tune from your logs) -----------------------------
    W_CANDLE = 1
    W_FORMATION = 2
    CAP_CANDLE = 3
    CAP_FORMATION = 4
    BASE_MIN_SCORE = 7
    FAST_MIN_SCORE = 6
    CHOP_MIN_SCORE = 8
    CHOP_FAST_MIN_SCORE = 7
    BASE_MIN_CONF = 75
    CHOP_MIN_CONF = 85
    DOMINANCE = 3

    def __init__(
        self,
        pcr_bullish_threshold: float = 1.15,
        pcr_bearish_threshold: float = 0.85,
        confirm_snapshots: int = 2,
        flip_cooldown_sec: int = 300,
        entry_slippage_pct: float = 0.3,
    ):
        self.pcr_bullish_threshold = pcr_bullish_threshold
        self.pcr_bearish_threshold = pcr_bearish_threshold
        self.confirm_snapshots = confirm_snapshots
        self.flip_cooldown_sec = flip_cooldown_sec
        self.entry_slippage_pct = entry_slippage_pct
        # persistence state
        self._cand_dir: Optional[str] = None
        self._cand_count = 0
        self._cand_seq: Any = None
        self._last_dir: Optional[str] = None
        self._last_ts = 0.0

    # ------------------------------------------------------------------
    @staticmethod
    def _ask(row: Dict[str, Any], side: str) -> float:
        for k in (f"{side}_ask", f"{side}_ask_price", f"{side}_askPrice"):
            v = row.get(k)
            if v and v > 0:
                return float(v)
        return 0.0

    # ------------------------------------------------------------------
    def evaluate_signal(
        self,
        current: Dict[str, Any],
        chart_analysis: Optional[Dict[str, Any]] = None,
        news_analysis: Optional[Dict[str, Any]] = None,
        market_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        spot = current["spot_price"]
        pcr = current["pcr"]
        support = current.get("support_strike")
        resistance = current.get("resistance_strike")
        atm_strike = current["atm_strike"]
        table = current.get("table_data", []) or []
        vel = current.get("oi_velocity", {}) or {}
        max_pain = current.get("max_pain", 0) or 0
        dte = current.get("days_to_expiry")
        is_expiry_day = bool(current.get("is_expiry_day", False))
        day_imb = current.get("day_imbalance")
        if day_imb is None:
            day_imb = _imb(current.get("total_pe_chg_oi", 0), current.get("total_ce_chg_oi", 0))

        bull: List[tuple] = []   # (points, reason)
        bear: List[tuple] = []
        bull_pen = 0
        bear_pen = 0
        fast_bull: List[str] = []
        fast_bear: List[str] = []

        def add(side: str, pts: int, text: str):
            (bull if side == "B" else bear).append((pts, text))

        # ---- chart inputs -------------------------------------------------
        ca = chart_analysis or {}
        ind = ca.get("indicators", {}) or {}
        mtf = ca.get("mtf") or {}
        vwap_bias = ind.get("vwap_bias", "") or ""
        ema_trend = ind.get("ema_trend", "") or ""
        rsi = ind.get("rsi", 50.0)
        atr = ind.get("atr")
        mtf_status = mtf.get("status", "") or ""
        chart_ok = bool(ind) and bool(vwap_bias)

        # ---- 1. Baseline OI -----------------------------------------------
        if day_imb >= 0.50:
            add("B", 2, f"Day OI build strongly favors puts (imbalance {day_imb:+.2f})")
        elif day_imb >= 0.25:
            add("B", 1, f"Day OI build favors puts (imbalance {day_imb:+.2f})")
        if day_imb <= -0.50:
            add("A", 2, f"Day OI build strongly favors calls (imbalance {day_imb:+.2f})")
        elif day_imb <= -0.25:
            add("A", 1, f"Day OI build favors calls (imbalance {day_imb:+.2f})")

        if self.pcr_bullish_threshold <= pcr <= 1.7:
            add("B", 1, f"Bullish PCR ({pcr:.2f})")
        elif pcr <= self.pcr_bearish_threshold:
            add("A", 1, f"Bearish PCR ({pcr:.2f})")

        prox = 60.0
        if atr:
            prox = max(40.0, min(90.0, 2.0 * float(atr)))
        near_support = support and 0 <= spot - support < prox
        near_resist = resistance and 0 <= resistance - spot < prox
        if near_support and not near_resist:
            add("B", 1, f"Near OI support ({support})")
        elif near_resist and not near_support:
            add("A", 1, f"Near OI resistance ({resistance})")

        if is_expiry_day and max_pain and abs(spot - max_pain) > 40:
            if spot > max_pain:
                add("A", 1, f"Expiry-day pull toward max pain ({max_pain})")
            else:
                add("B", 1, f"Expiry-day pull toward max pain ({max_pain})")

        # ---- 2. Windowed OI flow (from oi_analyzer v2) --------------------
        v_status = vel.get("status", "")
        v_dir = vel.get("direction", "NEUTRAL")
        v_fast = bool(vel.get("fast_oi_trigger", False))
        warming = bool(vel.get("warming_up", False))
        broad_unwind = v_status == "BROAD_UNWINDING"

        if v_status == "RAPID_SHORT_COVERING":
            add("B", 4, "Rapid short covering (call writers exiting)")
            if v_fast:
                fast_bull.append("OI shock: rapid short covering")
        elif v_status == "RAPID_LONG_UNWINDING":
            add("A", 4, "Rapid long unwinding / put covering")
            if v_fast:
                fast_bear.append("OI shock: rapid long unwinding")
        elif v_status == "AGGRESSIVE_PUT_WRITING":
            add("B", 3, "Aggressive put writing near ATM")
            if v_fast:
                fast_bull.append("OI shock: aggressive put writing")
        elif v_status == "AGGRESSIVE_CALL_WRITING":
            add("A", 3, "Aggressive call writing near ATM")
            if v_fast:
                fast_bear.append("OI shock: aggressive call writing")
        elif v_dir == "BULLISH":
            add("B", 1, "OI flow favors bulls")
        elif v_dir == "BEARISH":
            add("A", 1, "OI flow favors bears")

        if vel.get("atm_ce_unwinding") and v_dir != "BEARISH":
            add("B", 2, "ATM call writers covering")
            fast_bull.append("ATM call-writer capitulation")
        if vel.get("atm_pe_unwinding") and v_dir != "BULLISH":
            add("A", 2, "ATM put writers covering")
            fast_bear.append("ATM put-writer capitulation")

        # ---- 3. News (low weight; fast only if OI agrees) -----------------
        if news_analysis:
            n_score = news_analysis.get("score", 0.0)
            if n_score >= 30:
                add("B", 1, f"Bullish news sentiment ({n_score:+.0f})")
            elif n_score <= -30:
                add("A", 1, f"Bearish news sentiment ({n_score:+.0f})")
            if news_analysis.get("fast_catalyst"):
                cat = news_analysis.get("catalyst_direction", "NONE")
                alerts = news_analysis.get("critical_alerts", []) or []
                label = alerts[0] if alerts else "Breaking news catalyst"
                if cat == "BULLISH":
                    add("B", 2, "Breaking bullish news")
                    if v_dir == "BULLISH":
                        fast_bull.append(f"News + OI agree: {label}")
                elif cat == "BEARISH":
                    add("A", 2, "Breaking bearish news")
                    if v_dir == "BEARISH":
                        fast_bear.append(f"News + OI agree: {label}")

        # ---- 4. Multi-timeframe -------------------------------------------
        if mtf_status == "ALIGNED_BULLISH":
            add("B", 3, "MTF aligned bullish (15m + 5m)")
        elif mtf_status == "ALIGNED_BEARISH":
            add("A", 3, "MTF aligned bearish (15m + 5m)")
        elif mtf_status == "BEARISH_BOUNCE":
            bull_pen += 2
        elif mtf_status == "BULLISH_PULLBACK":
            bear_pen += 2

        # ---- 5. VIX -------------------------------------------------------
        vix_d = (market_context or {}).get("vix") or {}
        if vix_d:
            chg = vix_d.get("change_pct", 0.0)
            if chg <= -2.5:
                bull_pen += 1
                bear_pen += 1   # IV crush hurts option buyers on both sides
            elif chg <= -1.0:
                add("B", 1, f"VIX cooling ({chg:+.1f}%)")
            elif chg >= 2.5:
                add("A", 2, f"VIX spiking ({chg:+.1f}%)")

        # ---- 6. Heavyweights ----------------------------------------------
        hw = (market_context or {}).get("heavyweights") or {}
        hw_bias = hw.get("bias", "") or ""
        if hw_bias == "BULLISH_SUPPORT":
            add("B", 2, "Heavyweights supportive")
            bear_pen += 2
        elif hw_bias == "BEARISH_DRAG":
            add("A", 2, "Heavyweights dragging")
            bull_pen += 2

        # ---- 7. Price action (explicit conditions only) -------------------
        cb = [p.get("name", "?") for p in ca.get("candlestick_patterns", []) if p.get("type") == "BULLISH"]
        ca_b = [p.get("name", "?") for p in ca.get("candlestick_patterns", []) if p.get("type") == "BEARISH"]
        fb = [f.get("name", "?") for f in ca.get("chart_formations", []) if f.get("type") == "BULLISH"]
        fa = [f.get("name", "?") for f in ca.get("chart_formations", []) if f.get("type") == "BEARISH"]
        if cb:
            add("B", min(self.CAP_CANDLE, self.W_CANDLE * len(cb)), "Chart: " + ", ".join(cb[:2]))
        if ca_b:
            add("A", min(self.CAP_CANDLE, self.W_CANDLE * len(ca_b)), "Chart: " + ", ".join(ca_b[:2]))
        if fb:
            add("B", min(self.CAP_FORMATION, self.W_FORMATION * len(fb)), "Formation: " + ", ".join(fb[:2]))
        if fa:
            add("A", min(self.CAP_FORMATION, self.W_FORMATION * len(fa)), "Formation: " + ", ".join(fa[:2]))

        if ema_trend == "BULLISH":
            add("B", 1, "EMA(9) > EMA(21)")
        elif ema_trend == "BEARISH":
            add("A", 1, "EMA(9) < EMA(21)")
        if "ABOVE_VWAP" in vwap_bias:
            add("B", 1, "Above VWAP")
        elif "BELOW_VWAP" in vwap_bias:
            add("A", 1, "Below VWAP")
        if rsi > 55:
            add("B", 1, f"RSI momentum ({rsi:.1f})")
        elif rsi < 45:
            add("A", 1, f"RSI momentum ({rsi:.1f})")
        if rsi >= 78:
            bull_pen += 1   # exhaustion
        elif rsi <= 22:
            bear_pen += 1

        bull_score = max(0, sum(p for p, _ in bull) - bull_pen)
        bear_score = max(0, sum(p for p, _ in bear) - bear_pen)
        bull.sort(key=lambda x: -x[0])
        bear.sort(key=lambda x: -x[0])
        reasons_bull = [t for _, t in bull]
        reasons_bear = [t for _, t in bear]

        # ---- 8. Session / thresholds --------------------------------------
        sess = (market_context or {}).get("session") or {}
        is_chop_zone = bool(sess.get("is_chop_zone", False))
        sess_min = sess.get("min_confluence")

        # ---- 9. Pillars (derivatives pillar is mandatory) -----------------
        if v_dir == "BULLISH":
            bull_p1, bear_p1 = True, False
        elif v_dir == "BEARISH":
            bull_p1, bear_p1 = False, True
        else:  # neutral flow or warming up -> fall back to day-level imbalance
            bull_p1, bear_p1 = day_imb >= 0.35, day_imb <= -0.35
        bull_p2 = mtf_status == "ALIGNED_BULLISH" or (
            ema_trend == "BULLISH" and mtf_status not in ("ALIGNED_BEARISH", "BEARISH_BOUNCE"))
        bear_p2 = mtf_status == "ALIGNED_BEARISH" or (
            ema_trend == "BEARISH" and mtf_status not in ("ALIGNED_BULLISH", "BULLISH_PULLBACK"))
        bull_p3 = "ABOVE_VWAP" in vwap_bias and hw_bias != "BEARISH_DRAG"
        bear_p3 = "BELOW_VWAP" in vwap_bias and hw_bias != "BULLISH_SUPPORT"
        bull_p4 = bool(cb or fb) or (rsi > 55 and ema_trend == "BULLISH")
        bear_p4 = bool(ca_b or fa) or (rsi < 45 and ema_trend == "BEARISH")
        bull_pillars = sum([bull_p1, bull_p2, bull_p3, bull_p4])
        bear_pillars = sum([bear_p1, bear_p2, bear_p3, bear_p4])

        # ---- 10. Evaluate each side ---------------------------------------
        sides: Dict[str, Dict[str, Any]] = {}
        for side in ("CE", "PE"):
            is_bull = side == "CE"
            score = bull_score if is_bull else bear_score
            opp = bear_score if is_bull else bull_score
            pillars = bull_pillars if is_bull else bear_pillars
            p1 = bull_p1 if is_bull else bear_p1
            fast_list = fast_bull if is_bull else fast_bear

            vetoes: List[str] = []
            if not chart_ok:
                vetoes.append("chart data unavailable")
            if is_bull:
                if chart_ok and "ABOVE_VWAP" not in vwap_bias:
                    vetoes.append("below VWAP")
                if hw_bias == "BEARISH_DRAG":
                    vetoes.append("heavyweights dragging")
                if mtf_status == "ALIGNED_BEARISH":
                    vetoes.append("15m trend bearish")
            else:
                if chart_ok and "BELOW_VWAP" not in vwap_bias:
                    vetoes.append("above VWAP")
                if hw_bias == "BULLISH_SUPPORT":
                    vetoes.append("heavyweights supportive")
                if mtf_status == "ALIGNED_BULLISH":
                    vetoes.append("15m trend bullish")

            fast = bool(fast_list)
            if is_chop_zone:
                min_score = self.CHOP_FAST_MIN_SCORE if fast else self.CHOP_MIN_SCORE
                min_conf = self.CHOP_MIN_CONF
            else:
                min_score = self.FAST_MIN_SCORE if fast else self.BASE_MIN_SCORE
                min_conf = self.BASE_MIN_CONF
            if sess_min:
                min_conf = max(min_conf, min(int(sess_min), 90))
            if is_expiry_day:
                min_score += 1
            if broad_unwind or warming:
                min_score += 1

            share = score / max(1, score + opp)
            conf = int(min(99, round(0.5 * (pillars / 4 * 100) + 0.5 * (share * 100))))

            blockers = list(vetoes)
            if score < min_score:
                blockers.append(f"score {score}<{min_score}")
            if score < opp + self.DOMINANCE:
                blockers.append("no clear score dominance")
            if not p1:
                blockers.append("OI flow not confirming")
            if pillars < 3:
                blockers.append(f"pillars {pillars}/4")
            if conf < min_conf:
                blockers.append(f"confluence {conf}%<{min_conf}%")
            if is_chop_zone and not fast and blockers:
                blockers.append("midday chop zone: stricter filter")

            sides[side] = {
                "ok": not blockers, "score": score, "pillars": pillars, "conf": conf,
                "fast": fast, "fast_reasons": fast_list, "blockers": blockers,
                "min_score": min_score, "min_conf": min_conf,
            }

        chosen: Optional[str] = None
        ok_sides = [s for s in ("CE", "PE") if sides[s]["ok"]]
        if ok_sides:
            chosen = max(ok_sides, key=lambda s: sides[s]["score"])

        lean = "CE" if bull_score >= bear_score else "PE"
        info = sides[chosen] if chosen else sides[lean]

        # ---- 11. Persistence, flip cooldown -------------------------------
        now = time.time()
        hold_note = ""
        if chosen:
            seq = current.get("snapshot_seq")
            if chosen == self._cand_dir:
                if seq is None or seq != self._cand_seq:
                    self._cand_count += 1
                    self._cand_seq = seq
            else:
                self._cand_dir, self._cand_count, self._cand_seq = chosen, 1, seq
            needed = 1 if info["fast"] else self.confirm_snapshots
            if self._last_dir and chosen != self._last_dir and now - self._last_ts < self.flip_cooldown_sec:
                hold_note = f"flip cooldown ({int(self.flip_cooldown_sec - (now - self._last_ts))}s left)"
                chosen = None
            elif self._cand_count < needed:
                hold_note = f"awaiting confirmation ({self._cand_count}/{needed} data snapshots)"
                chosen = None
        else:
            self._cand_dir, self._cand_count, self._cand_seq = None, 0, None

        # ---- 12. Build output ---------------------------------------------
        atm_row = next((s for s in table if s["strike"] == atm_strike), None)
        signal, instrument, entry_px, urgency = "HOLD", None, 0.0, "PATIENT_OBSERVING"
        confluence_pct = 50
        reason = ""
        is_fast_out = bool(info["fast"])

        if chosen:
            is_ce = chosen == "CE"
            signal = ("FAST_BUY_CE" if is_ce else "FAST_BUY_PE") if info["fast"] else ("BUY_CE" if is_ce else "BUY_PE")
            urgency = "⚡ HIGH_CONFLUENCE_FAST" if info["fast"] else "🎯 HIGH_CONFLUENCE_SNIPER"
            instrument = f"NIFTY {atm_strike} {chosen}"
            if atm_row:
                side_key = "ce" if is_ce else "pe"
                base = self._ask(atm_row, side_key) or atm_row.get(f"{side_key}_ltp", 0.0)
                entry_px = round(base * (1 + self.entry_slippage_pct / 100.0), 2) if base else 0.0
            reasons = reasons_bull if is_ce else reasons_bear
            lead = info["fast_reasons"] if info["fast"] else reasons[:3]
            reason = " | ".join(lead + [r for r in reasons if r not in lead][:2])
            confluence_pct = info["conf"]
            self._last_dir, self._last_ts = chosen, now
        else:
            if hold_note:
                reason = f"Holding: {hold_note}"
            elif max(bull_score, bear_score) == 0:
                reason = "Holding: no directional edge."
            else:
                lean_txt = "bullish" if lean == "CE" else "bearish"
                reason = f"Holding ({lean_txt} lean {max(bull_score, bear_score)}): " + "; ".join(info["blockers"][:3])
            if "midday chop" in reason:
                reason = "Midday theta chop zone: " + reason

        # buyer profile: ATR-aware stop, wider on expiry day
        sl_pct, tgt_mult = 16.0, 2.5
        if atr and entry_px > 0:
            sl_pct = max(12.0, min(30.0, (1.2 * float(atr) * 0.5) / entry_px * 100.0))
        if is_expiry_day:
            sl_pct = max(sl_pct, 20.0)
        buyer_profile = {
            "sweet_spot_delta": "0.50 (Peak Gamma ATM)",
            "time_stop_limit_sec": 600,
            "breakeven_trigger_pct": round(1.1 * sl_pct, 1),
            "initial_sl_pct": round(sl_pct, 1),
            "initial_tgt_pct": round(tgt_mult * sl_pct, 1),
            "theta_defense_active": bool(is_chop_zone or is_expiry_day),
        }

        features = {
            "ts": round(now, 2), "snapshot_seq": current.get("snapshot_seq"),
            "spot": spot, "atm_strike": atm_strike, "pcr": pcr, "dte": dte,
            "day_imbalance": round(day_imb, 3),
            "flow_imbalance": vel.get("flow_imbalance"), "flow_pct": vel.get("flow_pct"),
            "v_status": v_status, "delta_ce_pct": vel.get("delta_ce_pct"), "delta_pe_pct": vel.get("delta_pe_pct"),
            "delta_spot": vel.get("delta_spot"), "delta_pcr": vel.get("delta_pcr"),
            "vix_chg": vix_d.get("change_pct") if vix_d else None,
            "hw_bias": hw_bias, "mtf": mtf_status, "ema_trend": ema_trend, "vwap_bias": vwap_bias,
            "rsi": rsi, "atr": atr, "news_score": (news_analysis or {}).get("score"),
            "bull_score": bull_score, "bear_score": bear_score,
            "bull_pillars": bull_pillars, "bear_pillars": bear_pillars,
            "chop": int(is_chop_zone), "expiry_day": int(is_expiry_day),
            "atm_ce_ltp": (atm_row or {}).get("ce_ltp"), "atm_pe_ltp": (atm_row or {}).get("pe_ltp"),
            "signal": signal, "confluence_pct": confluence_pct,
        }

        return {
            "signal": signal,
            "instrument": instrument,
            "strike": atm_strike,
            "estimated_entry_price": entry_px,
            "reason": reason,
            "bullish_score": bull_score,
            "bearish_score": bear_score,
            "confluence_pct": confluence_pct,
            "spot_price": spot,
            "support": support,
            "resistance": resistance,
            "pcr": pcr,
            "is_fast_trigger": is_fast_out,
            "is_chop_zone": is_chop_zone,
            "urgency": urgency,
            "buyer_profile": buyer_profile,
            "pillars_bull": bull_pillars,
            "pillars_bear": bear_pillars,
            "min_score_required": info["min_score"],
            "min_confluence_required": info["min_conf"],
            "blockers": info["blockers"],
            "features": features,
        }
