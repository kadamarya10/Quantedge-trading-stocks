"""
Stock Target & Stoploss Tracker and Recommendation Audit History Engine
Tracks AI stock suggestions from issuance through live monitoring to Target Hit or Stoploss Hit.
All past calls removed; starts fresh from TODAY.
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

TRACKER_DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_tracker_data.json")

# Starts fresh from today — zero past calls
SEED_TRACK_RECORD: List[Dict[str, Any]] = []


class StockTracker:
    def __init__(self, data_file: str = TRACKER_DATA_FILE):
        self.data_file = data_file
        self.calls: List[Dict[str, Any]] = []
        self.recent_alerts: List[Dict[str, Any]] = []
        self.load_data()

    def _sanitize_call(self, c: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates and repairs equity growth call targets:
        Ensures Target > Entry price (upside target) and Stoploss < Entry price (protective floor).
        Resets prematurely closed calls caused by inverted levels.
        """
        entry = float(c.get("entry_price") or 0.0)
        if entry <= 0.0:
            return c
        tgt = float(c.get("target_price") or 0.0)
        sl = float(c.get("stop_loss") or 0.0)

        # Fix inverted or invalid target (must be > entry)
        if tgt <= entry:
            tgt = round(entry * 1.065, 2)
            c["target_price"] = tgt
            c["target_pct"] = 6.5

        # Fix inverted or invalid stoploss (must be 0 < sl < entry)
        if sl <= 0.0 or sl >= entry:
            sl = round(entry * 0.972, 2)
            c["stop_loss"] = sl
            c["sl_pct"] = -2.8

        # Recalculate percentages
        c["target_pct"] = round(((tgt - entry) / entry) * 100, 2)
        c["sl_pct"] = round(((sl - entry) / entry) * 100, 2)

        # If it was erroneously closed due to inverted levels with near ~0% PnL, reset to ACTIVE
        if c.get("status") in ("TARGET_HIT", "STOPLOSS_HIT"):
            exit_p = float(c.get("exit_price") or entry)
            # A true target hit must reach or exceed target
            # A true stoploss hit must touch or drop below stop loss
            if c["status"] == "TARGET_HIT" and exit_p < tgt:
                c["status"] = "ACTIVE"
                c["exit_price"] = None
                c["exit_date"] = None
                c["time_held"] = "Active Today"
            elif c["status"] == "STOPLOSS_HIT" and exit_p > sl:
                c["status"] = "ACTIVE"
                c["exit_price"] = None
                c["exit_date"] = None
                c["time_held"] = "Active Today"

        return c

    def load_data(self):
        """Loads tracker data, strictly keeping only calls started TODAY and sanitizing target/stoploss levels."""
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as f:
                    raw_calls = json.load(f)
                    # Strictly filter: keep ONLY calls whose entry_date is TODAY and sanitize levels
                    self.calls = [
                        self._sanitize_call(c) for c in raw_calls 
                        if str(c.get("entry_date", "")).startswith(today_prefix)
                    ]
                    self.save_data()
                    return
            except Exception as e:
                print(f"[StockTracker] Error reading {self.data_file}: {e}")

        self.calls = []
        self.save_data()

    def save_data(self):
        """Saves current state to JSON file."""
        try:
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self.calls, f, indent=2)
        except Exception as e:
            print(f"[StockTracker] Error saving to {self.data_file}: {e}")

    def sync_suggestions(self, suggested_stocks: List[Dict[str, Any]]):
        """
        Registers any newly discovered suggested catalyst stocks into the tracker as ACTIVE calls for TODAY.
        If a call for that symbol already exists as ACTIVE, updates its live levels.
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        updated = False

        for s in suggested_stocks:
            sym = s.get("symbol")
            if not sym:
                continue

            ltp = float(s.get("ltp") or 0.0)
            if ltp <= 0.0:
                continue

            thesis = s.get("ai_growth_thesis") or {}
            pred = s.get("prediction") or {}
            mt = pred.get("mid_term") or {}

            # Calculated targets and stoploss levels for growth calls
            raw_target = float(thesis.get("target_price") or mt.get("target") or (ltp * 1.065))
            raw_sl = float(thesis.get("stop_loss") or mt.get("stop_loss") or (ltp * 0.975))

            # Ensure proper direction: Target > LTP and SL < LTP for long growth calls
            target = round(raw_target if raw_target > ltp else (ltp * 1.065), 2)
            sl = round(raw_sl if 0.0 < raw_sl < ltp else (ltp * 0.975), 2)

            rr = str(thesis.get("risk_reward") or mt.get("rr_ratio") or "1 : 2.4")
            catalyst = str(thesis.get("growth_catalyst") or (s.get("news", {}).get("catalyst")) or "Technical & Volume Breakout")
            why_rising = str(thesis.get("why_rising") or f"{sym} exhibiting institutional delivery accumulation with breakout momentum.")
            triggers = thesis.get("active_triggers") or ["📈 Breakout"]

            # Check if active call already exists
            existing_active = next((c for c in self.calls if c.get("symbol") == sym and c.get("status") == "ACTIVE"), None)

            if existing_active:
                # Update current ltp and watermarks
                existing_active["current_ltp"] = ltp
                existing_active["high_price"] = max(existing_active.get("high_price", ltp), ltp)
                existing_active["low_price"] = min(existing_active.get("low_price", ltp), ltp)
                pnl = round(((ltp - existing_active["entry_price"]) / existing_active["entry_price"]) * 100, 2)
                existing_active["pnl_percent"] = pnl
                updated = True
            else:
                # Check if there is already a closed call for this symbol today
                has_closed_today = any(
                    c.get("symbol") == sym and c.get("status") in ("TARGET_HIT", "STOPLOSS_HIT") and
                    str(c.get("exit_date", "")).startswith(today_prefix)
                    for c in self.calls
                )

                if not has_closed_today:
                    new_call = {
                        "id": f"TRK-{sym}-{int(time.time())}",
                        "symbol": sym,
                        "company_name": s.get("company_name") or sym,
                        "sector": s.get("sector_tag") or s.get("industry") or "NSE",
                        "entry_price": ltp,
                        "entry_date": now_str,
                        "target_price": target,
                        "stop_loss": sl,
                        "target_pct": round(((target - ltp) / ltp) * 100, 2),
                        "sl_pct": round(((sl - ltp) / ltp) * 100, 2),
                        "risk_reward": rr,
                        "catalyst": catalyst,
                        "why_rising": why_rising,
                        "triggers": triggers,
                        "status": "ACTIVE",
                        "exit_price": None,
                        "exit_date": None,
                        "pnl_percent": 0.0,
                        "time_held": "Active Today",
                        "current_ltp": ltp,
                        "high_price": ltp,
                        "low_price": ltp
                    }
                    # Insert active calls at the top
                    self.calls.insert(0, new_call)
                    updated = True

        if updated:
            self.save_data()

    def update_ticks(self, ticks: Dict[str, Dict[str, Any]]):
        """
        Called on every real-time micro-tick.
        Checks if active calls have hit their target price or stoploss price today.
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updated = False

        for c in self.calls:
            if c.get("status") != "ACTIVE":
                continue

            sym = c.get("symbol")
            if sym not in ticks:
                continue

            tick = ticks[sym]
            new_ltp = float(tick.get("ltp") or 0.0)
            if new_ltp <= 0.0:
                continue

            c["current_ltp"] = new_ltp
            c["high_price"] = max(c.get("high_price", new_ltp), new_ltp)
            c["low_price"] = min(c.get("low_price", new_ltp), new_ltp)

            entry_price = float(c.get("entry_price") or new_ltp)
            tgt_price = float(c.get("target_price") or 0.0)
            sl_price = float(c.get("stop_loss") or 0.0)

            # Check TARGET HIT (requires target to be above entry and price to have reached target)
            if tgt_price > entry_price and new_ltp >= tgt_price:
                c["status"] = "TARGET_HIT"
                c["exit_price"] = new_ltp
                c["exit_date"] = now_str
                c["pnl_percent"] = round(((new_ltp - entry_price) / entry_price) * 100, 2)
                c["time_held"] = self._compute_duration(c.get("entry_date", now_str), now_str)
                updated = True

                self.recent_alerts.append({
                    "id": c.get("id"),
                    "type": "TARGET_HIT",
                    "symbol": sym,
                    "company_name": c.get("company_name", sym),
                    "entry_price": entry_price,
                    "exit_price": new_ltp,
                    "target_price": tgt_price,
                    "pnl_percent": c["pnl_percent"],
                    "timestamp": now_str,
                    "message": f"🎯 TARGET HIT: {sym} reached ₹{new_ltp:.2f} (+{c['pnl_percent']:.2f}%)!"
                })

            # Check STOPLOSS HIT (requires stoploss to be below entry and price to have touched stoploss)
            elif 0.0 < sl_price < entry_price and new_ltp <= sl_price:
                c["status"] = "STOPLOSS_HIT"
                c["exit_price"] = new_ltp
                c["exit_date"] = now_str
                c["pnl_percent"] = round(((new_ltp - entry_price) / entry_price) * 100, 2)
                c["time_held"] = self._compute_duration(c.get("entry_date", now_str), now_str)
                updated = True

                self.recent_alerts.append({
                    "id": c.get("id"),
                    "type": "STOPLOSS_HIT",
                    "symbol": sym,
                    "company_name": c.get("company_name", sym),
                    "entry_price": entry_price,
                    "exit_price": new_ltp,
                    "stop_loss": sl_price,
                    "pnl_percent": c["pnl_percent"],
                    "timestamp": now_str,
                    "message": f"🛑 STOPLOSS HIT: {sym} touched ₹{new_ltp:.2f} ({c['pnl_percent']:.2f}%). Capital protected."
                })
            else:
                # Active PnL fluctuation
                c["pnl_percent"] = round(((new_ltp - entry_price) / entry_price) * 100, 2)
                updated = True

        if updated:
            self.save_data()

    def get_summary(self) -> Dict[str, Any]:
        """Calculates track record performance statistics starting from today."""
        closed_calls = [c for c in self.calls if c.get("status") in ("TARGET_HIT", "STOPLOSS_HIT")]
        active_calls = [c for c in self.calls if c.get("status") == "ACTIVE"]

        target_hits = [c for c in closed_calls if c.get("status") == "TARGET_HIT"]
        sl_hits = [c for c in closed_calls if c.get("status") == "STOPLOSS_HIT"]

        total_closed = len(closed_calls)
        hit_rate = round((len(target_hits) / total_closed) * 100, 1) if total_closed > 0 else 0.0
        sl_rate = round((len(sl_hits) / total_closed) * 100, 1) if total_closed > 0 else 0.0

        total_return_pct = round(sum(c.get("pnl_percent", 0.0) for c in closed_calls), 2)
        avg_win_pct = round(sum(c.get("pnl_percent", 0.0) for c in target_hits) / (len(target_hits) or 1), 2) if target_hits else 0.0
        avg_loss_pct = round(sum(c.get("pnl_percent", 0.0) for c in sl_hits) / (len(sl_hits) or 1), 2) if sl_hits else 0.0

        total_gains = sum(c.get("pnl_percent", 0.0) for c in target_hits)
        total_losses = abs(sum(c.get("pnl_percent", 0.0) for c in sl_hits))
        profit_factor = round(total_gains / (total_losses or 0.01), 2) if total_losses > 0 else (99.0 if total_gains > 0 else 0.0)
        payoff_ratio = round(abs(avg_win_pct / (avg_loss_pct or -1.0)), 2) if avg_loss_pct != 0 else 0.0

        return {
            "total_calls": len(self.calls),
            "closed_calls": total_closed,
            "target_hits_count": len(target_hits),
            "stoploss_hits_count": len(sl_hits),
            "active_calls_count": len(active_calls),
            "win_rate_percent": hit_rate,
            "stoploss_rate_percent": sl_rate,
            "net_cumulative_return_pct": total_return_pct,
            "avg_win_pct": avg_win_pct,
            "avg_loss_pct": avg_loss_pct,
            "profit_factor": profit_factor,
            "payoff_ratio": payoff_ratio,
            "tracking_started_date": datetime.now().strftime("%Y-%m-%d")
        }

    def get_calls(self, filter_status: str = "all") -> List[Dict[str, Any]]:
        """Returns list of calls filtered by status ('all', 'target', 'stoploss', 'active')."""
        if filter_status == "target":
            return [c for c in self.calls if c.get("status") == "TARGET_HIT"]
        elif filter_status == "stoploss":
            return [c for c in self.calls if c.get("status") == "STOPLOSS_HIT"]
        elif filter_status == "active":
            return [c for c in self.calls if c.get("status") == "ACTIVE"]
        return list(self.calls)

    def pop_recent_alerts(self) -> List[Dict[str, Any]]:
        """Returns and empties pending real-time hit alerts."""
        alerts = list(self.recent_alerts)
        self.recent_alerts.clear()
        return alerts

    def reset_tracker(self):
        """Resets tracker to start clean from today."""
        self.calls = []
        self.recent_alerts.clear()
        self.save_data()

    def _compute_duration(self, start_str: str, end_str: str) -> str:
        """Computes human readable duration string between two dates."""
        try:
            fmt = "%Y-%m-%d %H:%M:%S"
            t1 = datetime.strptime(start_str, fmt)
            t2 = datetime.strptime(end_str, fmt)
            diff = t2 - t1
            days = diff.days
            hours = diff.seconds // 3600
            mins = (diff.seconds % 3600) // 60
            if days > 0:
                return f"{days}d {hours}h"
            elif hours > 0:
                return f"{hours}h {mins}m"
            else:
                return f"{max(1, mins)}m"
        except Exception:
            return "Today"


# Global singleton instance
tracker_engine = StockTracker()
