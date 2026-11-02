"""
Open Interest (OI) Analytics Engine  -- v2

What changed vs v1
------------------
* Duplicate feed snapshots are ignored (NSE data updates far slower than your refresh loop).
* All "velocity" numbers are WINDOWED (default 5 min) deltas, not day-cumulative values.
* Per-strike buildup is classified using premium (LTP) change, adjusted for the spot move:
      OI up   + premium down -> writing      OI up   + premium up -> buying
      OI down + premium up   -> covering     OI down + premium down -> long unwinding
* Negative-OI comparisons fixed: uses a normalized imbalance in [-1, +1].
* Thresholds are percentages of total OI instead of fixed contract counts.
* Per-strike tracking: "ATM unwinding" now follows the SAME strike over the window,
  so it is not fooled by the ATM strike shifting with spot.
* Both-sides unwinding (expiry / rollover / end of day) is flagged as BROAD_UNWINDING (neutral).
* Adds days_to_expiry, snapshot_seq, day_imbalance, flow_imbalance for the strategy and logger.

All tunables are class attributes (see below). Tune them from your logged data.
"""

import time
from collections import deque
from datetime import datetime
from typing import Dict, Any, List, Optional


def oi_imbalance(pe_val: float, ce_val: float) -> float:
    """Normalized imbalance in [-1, +1]. +1 = all PE build, -1 = all CE build.
    Safe for negative values (unlike ratio comparisons)."""
    d = abs(pe_val) + abs(ce_val)
    return (pe_val - ce_val) / d if d else 0.0


def _parse_expiry(s: Any):
    if not s:
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d/%m/%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _approx_call_delta(strike: float, spot: float) -> float:
    """Very rough call delta from moneyness (~0.5 ATM, ~0.25 at 200 pts OTM)."""
    return max(0.05, min(0.95, 0.5 - (strike - spot) / 800.0))


class OIAnalyzer:
    # ---- tunables -------------------------------------------------------
    WINDOW_SEC = 300            # short window for flow / velocity
    LONG_WINDOW_SEC = 900       # context window (PCR trend)
    MIN_WARMUP_SEC = 45         # use oldest snapshot as reference once it is this old
    FLOW_MIN_PCT = 0.10         # gross near-ATM flow must be >= this % of total OI
    FLOW_FAST_PCT = 0.25        # ...and >= this % to count as a FAST trigger
    FLOW_DOMINANCE = 0.35       # |flow imbalance| needed to call a direction
    BROAD_UNWIND_PCT = 0.30     # both sides down by this % => broad unwinding
    ATM_UNWIND_PCT = 4.0        # ATM strike OI drop (%) over window => ATM covering
    LTP_EPS_ABS = 0.5           # ignore residual premium moves smaller than this (Rs)
    LTP_EPS_REL = 0.005         # ...or smaller than this fraction of premium
    SPOT_CONFIRM_PTS = 5.0      # spot must not move against the flow by more than this
    WEIGHTS = {"writing": 1.0, "covering": 1.0, "buying": 0.6, "long_unwind": 0.6}
    BULL_KEYS = ("ce_covering", "pe_writing", "ce_buying", "pe_long_unwind")
    BEAR_KEYS = ("pe_covering", "ce_writing", "pe_buying", "ce_long_unwind")

    def __init__(self):
        self.history: deque = deque()
        self._seq = 0
        self._last_key = None
        self._cached: Optional[Dict[str, Any]] = None
        self.prev_snapshot: Optional[Dict[str, Any]] = None  # backward compat

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------
    @staticmethod
    def calculate_max_pain(strikes: List[Dict[str, Any]]) -> float:
        """Strike where total option-buyer payout at expiry is minimal."""
        if not strikes:
            return 0.0
        min_pain = float("inf")
        max_pain_strike = strikes[0]["strike"]
        for target in strikes:
            t = target["strike"]
            total = 0.0
            for s in strikes:
                k = s["strike"]
                if t > k:
                    total += (t - k) * s.get("ce_oi", 0)
                if t < k:
                    total += (k - t) * s.get("pe_oi", 0)
            if total < min_pain:
                min_pain = total
                max_pain_strike = t
        return max_pain_strike

    @staticmethod
    def analyze_buildup(price_chg: float, oi_chg: float) -> str:
        if oi_chg > 0:
            return "Long Buildup (Bullish)" if price_chg >= 0 else "Short Buildup (Bearish)"
        if oi_chg < 0:
            return "Short Covering (Bullish Reversal)" if price_chg >= 0 else "Long Unwinding (Bearish Reversal)"
        return "Neutral"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _reference(self, now: float, window: int) -> Optional[Dict[str, Any]]:
        """Newest snapshot that is at least `window` seconds old.
        During warm-up falls back to the oldest snapshot once it is MIN_WARMUP_SEC old."""
        if not self.history:
            return None
        for s in reversed(self.history):
            if now - s["ts"] >= window:
                return s
        oldest = self.history[0]
        if now - oldest["ts"] >= self.MIN_WARMUP_SEC:
            return oldest
        return None

    def _residual(self, strike: float, spot: float, spot_d: float, side: str, ltp_d: float) -> float:
        """Premium change after removing the part explained by the spot move."""
        d_ce = _approx_call_delta(strike, spot)
        delta = d_ce if side == "ce" else d_ce - 1.0
        return ltp_d - delta * spot_d

    def _classify(self, side: str, oi_d: float, resid: float, prev_ltp: float, comps: Dict[str, float]):
        eps = max(self.LTP_EPS_ABS, self.LTP_EPS_REL * prev_ltp)
        if oi_d == 0 or abs(resid) < eps:
            return  # ambiguous -> ignore
        if oi_d > 0:
            kind = "writing" if resid < 0 else "buying"
        else:
            kind = "covering" if resid > 0 else "long_unwind"
        comps[f"{side}_{kind}"] += abs(oi_d)

    def _flow_components(self, ref: Dict[str, Any], focus: List[Dict[str, Any]], spot: float) -> Dict[str, float]:
        comps = {f"{side}_{k}": 0.0 for side in ("ce", "pe") for k in self.WEIGHTS}
        spot_d = spot - ref["spot"]
        for s in focus:
            k = s["strike"]
            prev = ref["strikes"].get(k)
            if not prev:
                continue
            for side in ("ce", "pe"):
                cur_ltp = s.get(f"{side}_ltp", 0.0) or 0.0
                prev_ltp = prev[f"{side}_ltp"]
                if cur_ltp <= 0 or prev_ltp <= 0:
                    continue
                oi_d = s.get(f"{side}_oi", 0) - prev[f"{side}_oi"]
                resid = self._residual(k, spot, spot_d, side, cur_ltp - prev_ltp)
                self._classify(side, oi_d, resid, prev_ltp, comps)
        return comps

    def _velocity(self, ref, comps, d_ce_pct, d_pe_pct, delta_spot, total_oi) -> Dict[str, Any]:
        out = {
            "status": "STABLE", "direction": "NEUTRAL", "fast_oi_trigger": False,
            "badge": "⚪ STABLE", "description": "Open Interest flow is quiet.",
            "flow_imbalance": 0.0, "flow_pct": 0.0, "bull_flow": 0.0, "bear_flow": 0.0,
            "warming_up": ref is None,
        }
        if ref is None:
            out["description"] = "Warming up: collecting OI history for windowed flow."
            return out

        w = self.WEIGHTS
        bull = sum(comps[k] * w[k.split("_", 1)[1]] for k in self.BULL_KEYS)
        bear = sum(comps[k] * w[k.split("_", 1)[1]] for k in self.BEAR_KEYS)
        gross_pct = (bull + bear) / total_oi * 100 if total_oi else 0.0
        imb = (bull - bear) / (bull + bear) if (bull + bear) else 0.0
        out.update(flow_imbalance=round(imb, 3), flow_pct=round(gross_pct, 3),
                   bull_flow=round(bull), bear_flow=round(bear))

        # Both sides shedding OI together = expiry / rollover / session-end noise
        if d_ce_pct <= -self.BROAD_UNWIND_PCT and d_pe_pct <= -self.BROAD_UNWIND_PCT:
            out.update(status="BROAD_UNWINDING", badge="🟠 BROAD UNWINDING",
                       description=f"Both CE ({d_ce_pct:.2f}%) and PE ({d_pe_pct:.2f}%) OI falling: no directional read.")
            return out

        if gross_pct < self.FLOW_MIN_PCT or abs(imb) < self.FLOW_DOMINANCE:
            return out

        bullish = imb > 0
        # spot must not be moving against the flow
        if (bullish and delta_spot < -self.SPOT_CONFIRM_PTS) or (not bullish and delta_spot > self.SPOT_CONFIRM_PTS):
            out.update(status="OI_PRICE_DIVERGENCE", badge="🟡 OI/PRICE DIVERGENCE",
                       description=f"OI flow leans {'bullish' if bullish else 'bearish'} but spot moved {delta_spot:+.1f} pts against it.")
            return out

        keys = self.BULL_KEYS if bullish else self.BEAR_KEYS
        dom = max(keys, key=lambda k: comps[k] * w[k.split("_", 1)[1]])
        if bullish:
            if dom == "ce_covering":
                st, badge = "RAPID_SHORT_COVERING", "⚡ RAPID SHORT COVERING"
                desc = "Call writers covering (CE OI falling while premium holds up)."
            elif dom == "pe_writing":
                st, badge = "AGGRESSIVE_PUT_WRITING", "⚡ AGGRESSIVE PUT WRITING"
                desc = "Fresh put writing near ATM (PE OI up, premium down): floor forming."
            else:
                st, badge = "BULLISH_OI_ACCUMULATION", "🟢 BULLISH OI FLOW"
                desc = "Near-ATM OI flow favors bulls."
            direction = "BULLISH"
        else:
            if dom in ("pe_covering", "ce_long_unwind"):
                st, badge = "RAPID_LONG_UNWINDING", "⚡ RAPID LONG UNWINDING"
                desc = "Put writers covering / call longs exiting: downside pressure."
            elif dom == "ce_writing":
                st, badge = "AGGRESSIVE_CALL_WRITING", "⚡ AGGRESSIVE CALL WRITING"
                desc = "Fresh call writing near ATM (CE OI up, premium down): ceiling forming."
            else:
                st, badge = "BEARISH_OI_ACCUMULATION", "🔴 BEARISH OI FLOW"
                desc = "Near-ATM OI flow favors bears."
            direction = "BEARISH"

        rapid = st in ("RAPID_SHORT_COVERING", "RAPID_LONG_UNWINDING",
                       "AGGRESSIVE_PUT_WRITING", "AGGRESSIVE_CALL_WRITING")
        out.update(status=st, direction=direction, badge=badge,
                   description=f"{desc} (flow {gross_pct:.2f}% of OI, imbalance {imb:+.2f})",
                   fast_oi_trigger=bool(rapid and gross_pct >= self.FLOW_FAST_PCT))
        return out

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------
    def analyze(self, data: Dict[str, Any], range_strikes: int = 10) -> Optional[Dict[str, Any]]:
        if not data or not data.get("strikes"):
            return None

        now = time.time()
        spot = data["spot_price"]
        strikes = sorted(data["strikes"], key=lambda x: x["strike"])

        total_ce_oi = sum(s["ce_oi"] for s in strikes)
        total_pe_oi = sum(s["pe_oi"] for s in strikes)

        # ---- ignore duplicate snapshots (same data re-served by the feed) ----
        key = (data.get("timestamp"), total_ce_oi, total_pe_oi, round(spot, 2))
        if key == self._last_key and self._cached is not None:
            return dict(self._cached)

        # a long gap (new session / restart) invalidates history
        if self.history and now - self.history[-1]["ts"] > 3600:
            self.history.clear()

        total_ce_chg = sum(s["ce_chg_oi"] for s in strikes)
        total_pe_chg = sum(s["pe_chg_oi"] for s in strikes)
        pcr = round(total_pe_oi / total_ce_oi, 3) if total_ce_oi > 0 else 1.0
        pcr_chg = round(total_pe_chg / total_ce_chg, 3) if total_ce_chg > 0 else 1.0
        max_pain = self.calculate_max_pain(strikes)

        closest = min(strikes, key=lambda x: abs(x["strike"] - spot))
        atm_strike = closest["strike"]
        atm_idx = strikes.index(closest)
        focus = strikes[max(0, atm_idx - range_strikes): min(len(strikes), atm_idx + range_strikes + 1)]

        max_call_oi_strike = max(focus, key=lambda x: x["ce_oi"])["strike"]
        max_put_oi_strike = max(focus, key=lambda x: x["pe_oi"])["strike"]
        max_call_writing_strike = max(focus, key=lambda x: x["ce_chg_oi"])["strike"]
        max_put_writing_strike = max(focus, key=lambda x: x["pe_chg_oi"])["strike"]

        # ---- windowed deltas ----------------------------------------------
        ref = self._reference(now, self.WINDOW_SEC)
        ref_long = self._reference(now, self.LONG_WINDOW_SEC)

        delta_ce_oi = delta_pe_oi = 0
        delta_spot = delta_pcr = delta_pcr_long = 0.0
        d_ce_pct = d_pe_pct = 0.0
        atm_ce_unwinding = atm_pe_unwinding = False
        comps = {f"{s}_{k}": 0.0 for s in ("ce", "pe") for k in self.WEIGHTS}

        if ref is not None:
            delta_ce_oi = total_ce_oi - ref["total_ce_oi"]
            delta_pe_oi = total_pe_oi - ref["total_pe_oi"]
            delta_spot = round(spot - ref["spot"], 2)
            delta_pcr = round(pcr - ref["pcr"], 3)
            d_ce_pct = delta_ce_oi / ref["total_ce_oi"] * 100 if ref["total_ce_oi"] else 0.0
            d_pe_pct = delta_pe_oi / ref["total_pe_oi"] * 100 if ref["total_pe_oi"] else 0.0
            comps = self._flow_components(ref, focus, spot)

            # ATM strike tracked by strike value (not by "whatever is ATM now")
            p = ref["strikes"].get(atm_strike)
            if p:
                spot_d = spot - ref["spot"]
                ce_ltp, pe_ltp = closest.get("ce_ltp", 0.0) or 0.0, closest.get("pe_ltp", 0.0) or 0.0
                if p["ce_oi"] > 0 and p["ce_ltp"] > 0 and ce_ltp > 0:
                    pct = (closest["ce_oi"] - p["ce_oi"]) / p["ce_oi"] * 100
                    res = self._residual(atm_strike, spot, spot_d, "ce", ce_ltp - p["ce_ltp"])
                    atm_ce_unwinding = pct <= -self.ATM_UNWIND_PCT and res > self.LTP_EPS_ABS
                if p["pe_oi"] > 0 and p["pe_ltp"] > 0 and pe_ltp > 0:
                    pct = (closest["pe_oi"] - p["pe_oi"]) / p["pe_oi"] * 100
                    res = self._residual(atm_strike, spot, spot_d, "pe", pe_ltp - p["pe_ltp"])
                    atm_pe_unwinding = pct <= -self.ATM_UNWIND_PCT and res > self.LTP_EPS_ABS
                if atm_ce_unwinding and atm_pe_unwinding:   # straddle covering = vol event, no direction
                    atm_ce_unwinding = atm_pe_unwinding = False

        if ref_long is not None:
            delta_pcr_long = round(pcr - ref_long["pcr"], 3)

        velocity = self._velocity(ref, comps, d_ce_pct, d_pe_pct, delta_spot, total_ce_oi + total_pe_oi)
        velocity.update({
            "window_sec": self.WINDOW_SEC,
            "delta_ce_oi": delta_ce_oi, "delta_pe_oi": delta_pe_oi,
            "delta_ce_pct": round(d_ce_pct, 3), "delta_pe_pct": round(d_pe_pct, 3),
            "delta_spot": delta_spot, "delta_pcr": delta_pcr, "delta_pcr_long": delta_pcr_long,
            "atm_ce_chg": closest.get("ce_chg_oi", 0), "atm_pe_chg": closest.get("pe_chg_oi", 0),
            "atm_ce_unwinding": atm_ce_unwinding, "atm_pe_unwinding": atm_pe_unwinding,
            "components": {k: round(v) for k, v in comps.items()},
        })

        # ---- day-level read -------------------------------------------------
        day_imb = round(oi_imbalance(total_pe_chg, total_ce_chg), 3)
        sentiment = "NEUTRAL"
        if pcr > 1.25 and day_imb > 0.10:
            sentiment = "BULLISH (Put Writing Dominates)"
        elif pcr < 0.80 and day_imb < -0.10:
            sentiment = "BEARISH (Call Writing Dominates)"
        elif day_imb >= 0.40:
            sentiment = "BULLISH INTRADAY (Strong Put Additions)"
        elif day_imb <= -0.40:
            sentiment = "BEARISH INTRADAY (Strong Call Additions)"

        exp_str = data.get("current_expiry") or data.get("expiry")
        exp_date = _parse_expiry(exp_str)
        dte = (exp_date - datetime.now().date()).days if exp_date else None

        # ---- store snapshot (after computing deltas so ref excludes self) ----
        self._seq += 1
        snap = {
            "ts": now, "seq": self._seq, "spot": spot, "pcr": pcr,
            "total_ce_oi": total_ce_oi, "total_pe_oi": total_pe_oi,
            "strikes": {
                s["strike"]: {
                    "ce_oi": s["ce_oi"], "pe_oi": s["pe_oi"],
                    "ce_ltp": s.get("ce_ltp", 0.0) or 0.0, "pe_ltp": s.get("pe_ltp", 0.0) or 0.0,
                } for s in strikes
            },
        }
        self.history.append(snap)
        while self.history and now - self.history[0]["ts"] > self.LONG_WINDOW_SEC + 300:
            self.history.popleft()
        self.prev_snapshot = {k: snap[k] for k in ("total_ce_oi", "total_pe_oi", "spot", "pcr")}
        self.prev_snapshot["timestamp"] = data.get("timestamp")

        result = {
            "symbol": data.get("symbol", "NIFTY"),
            "spot_price": spot,
            "timestamp": data.get("timestamp"),
            "expiry": exp_str,
            "expiry_dates": data.get("expiry_dates", []),
            "days_to_expiry": dte,
            "is_expiry_day": (dte == 0) if dte is not None else False,
            "snapshot_seq": self._seq,
            "atm_strike": atm_strike,
            "pcr": pcr,
            "pcr_chg": pcr_chg,
            "max_pain": max_pain,
            "max_pain_gap": round(spot - max_pain, 1) if max_pain else 0.0,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "total_ce_chg_oi": total_ce_chg,
            "total_pe_chg_oi": total_pe_chg,
            "day_imbalance": day_imb,
            "resistance_strike": max_call_oi_strike,
            "support_strike": max_put_oi_strike,
            "active_call_writing": max_call_writing_strike,
            "active_put_writing": max_put_writing_strike,
            "sentiment": sentiment,
            "oi_velocity": velocity,
            "table_data": focus,
        }
        self._last_key = key
        self._cached = result
        return dict(result)