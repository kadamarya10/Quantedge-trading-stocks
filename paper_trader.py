"""
Paper Trading & Execution Manager  -- v2

Fixes vs v1
-----------
* Uses signal_info["buyer_profile"] (ATR-aware SL / target / breakeven / time-stop) at entry.
* Trailing stages are driven by the PEAK price and checked highest-first (v1 missed spikes
  between ticks and ratcheted one stage per tick).
* max_daily_trades counts only TODAY's trades (v1 counted the whole history, so a long-running
  server stopped trading forever after 8 trades).
* Daily loss limit (max_daily_loss_pct of initial capital).
* Realistic costs: exit slippage + brokerage + a % of sell turnover for statutory charges.
  These are APPROXIMATIONS: set them from your broker's contract note.
* lot_size default 65 (current NIFTY lot). Optional `lots` multiplier.
* Optional JSON state file so capital / trades / open position survive restarts
  (note: Render's free disk is ephemeral; use MongoDB there).
* Every public name used by main.py / server.py is unchanged. New constructor args are optional.
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, Any, Optional, List


class PaperTrader:
    def __init__(
        self,
        initial_capital: float = 100000.0,
        lot_size: int = 65,
        sl_percent: float = 0.16,
        target_percent: float = 0.40,
        min_hold_seconds: int = 90,
        cooldown_seconds: int = 120,
        min_confluence_to_enter: int = 75,
        confirm_ticks_required: int = 2,
        max_daily_trades: int = 8,
        lots: int = 1,
        max_daily_loss_pct: float = 3.0,
        exit_slippage_pct: float = 0.3,
        brokerage_per_order: float = 20.0,
        statutory_pct_of_sell: float = 0.15,
        state_file: Optional[str] = None,
    ):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.lot_size = lot_size
        self.lots = lots
        self.sl_percent = sl_percent
        self.target_percent = target_percent
        self.min_hold_seconds = min_hold_seconds
        self.cooldown_seconds = cooldown_seconds
        self.min_confluence_to_enter = min_confluence_to_enter
        self.confirm_ticks_required = confirm_ticks_required
        self.max_daily_trades = max_daily_trades
        self.max_daily_loss_pct = max_daily_loss_pct
        self.exit_slippage_pct = exit_slippage_pct
        self.brokerage_per_order = brokerage_per_order
        self.statutory_pct_of_sell = statutory_pct_of_sell
        self.state_file = state_file

        self.current_position: Optional[Dict[str, Any]] = None
        self.trade_history: List[Dict[str, Any]] = []

        self.last_exit_time: float = 0.0
        self._pending_signal: Optional[str] = None
        self._pending_signal_count: int = 0
        self._opposite_signal_count: int = 0

        self._load_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _save_state(self):
        if not self.state_file:
            return
        try:
            tmp = self.state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "capital": self.capital,
                    "trade_history": self.trade_history,
                    "current_position": self.current_position,
                    "last_exit_time": self.last_exit_time,
                }, f)
            os.replace(tmp, self.state_file)
        except Exception:
            pass

    def _load_state(self):
        if not self.state_file or not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                s = json.load(f)
            self.capital = s.get("capital", self.capital)
            self.trade_history = s.get("trade_history", [])
            self.current_position = s.get("current_position")
            self.last_exit_time = s.get("last_exit_time", 0.0)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _today_trades(self) -> List[Dict[str, Any]]:
        today = datetime.now().strftime("%Y-%m-%d")
        return [t for t in self.trade_history if str(t.get("exit_time", t.get("entry_time", ""))).startswith(today)]

    def _today_pnl(self) -> float:
        return sum(t.get("realized_pnl", 0.0) for t in self._today_trades())

    def get_position_status(self, current_ltp: float) -> Optional[Dict[str, Any]]:
        if not self.current_position:
            return None
        pos = self.current_position
        entry_price, qty, pos_type = pos["entry_price"], pos["qty"], pos["type"]
        if pos_type == "SHORT":
            pnl = (entry_price - current_ltp) * qty
            pct = (entry_price - current_ltp) / entry_price * 100 if entry_price > 0 else 0.0
        else:
            pnl = (current_ltp - entry_price) * qty
            pct = (current_ltp - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
        held = int(time.time() - pos.get("entry_ts", time.time()))
        ts_limit = pos.get("time_stop_sec", 600)
        return {
            **pos,
            "current_ltp": current_ltp,
            "unrealized_pnl": round(pnl, 2),
            "pnl_percentage": round(pct, 2),
            "held_seconds": held,
            "min_hold_remaining": max(0, self.min_hold_seconds - held),
            "time_stop_remaining_sec": max(0, ts_limit - held),
            "is_breakeven_locked": pos.get("is_breakeven_locked", False),
            "trailing_stage": pos.get("trailing_stage", 0),
        }

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def process_signal(self, signal_info: Dict[str, Any], current_ltp: float) -> Optional[str]:
        action_msg = None
        now = time.time()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ---------------- 1. manage open position ----------------
        if self.current_position:
            pos = self.current_position
            pos_type = pos["type"]
            entry_price = pos["entry_price"]
            held_seconds = now - pos.get("entry_ts", now)
            gain_pct = (current_ltp - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
            changed = False

            if pos_type != "SHORT":
                if current_ltp > pos.get("peak_price", entry_price):
                    pos["peak_price"] = current_ltp
                    changed = True
                peak_gain = (pos["peak_price"] - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
                be = pos.get("be_trigger_pct", 18.0)
                stage = pos.get("trailing_stage", 0)

                # highest stage first; stages scale with the breakeven trigger (18 -> 18/30/45)
                if peak_gain >= 2.5 * be and stage < 3:
                    pos["stop_loss"] = round(entry_price * (1 + (5 / 3) * be / 100), 2)
                    pos["target"] = round(entry_price * (1 + (10 / 3) * be / 100), 2)
                    pos["trailing_stage"] = 3
                    pos["is_breakeven_locked"] = True
                    changed = True
                elif peak_gain >= (5 / 3) * be and stage < 2:
                    pos["stop_loss"] = round(entry_price * (1 + be / 100), 2)
                    pos["trailing_stage"] = 2
                    pos["is_breakeven_locked"] = True
                    changed = True
                elif peak_gain >= be and stage < 1:
                    pos["stop_loss"] = entry_price
                    pos["trailing_stage"] = 1
                    pos["is_breakeven_locked"] = True
                    changed = True
            if changed:
                self._save_state()

            sl_price, tgt_price = pos["stop_loss"], pos["target"]

            # Theta time-stop
            time_stop = pos.get("time_stop_sec", 600)
            if held_seconds >= time_stop and gain_pct < 8.0:
                return self.close_position(current_ltp, reason=f"⏱️ {int(time_stop / 60)}m Time-Stop Hit (Theta Decay Protection)")

            # Hard SL / target
            if pos_type == "SHORT":
                if current_ltp >= sl_price:
                    return self.close_position(current_ltp, reason="Stop-Loss Hit")
                if current_ltp <= tgt_price:
                    return self.close_position(current_ltp, reason="Target Hit")
            else:
                if current_ltp <= sl_price:
                    reason = "🛡️ Trailing SL Hit" if pos.get("trailing_stage", 0) > 0 else "Stop-Loss Hit"
                    return self.close_position(current_ltp, reason=reason)
                if current_ltp >= tgt_price:
                    return self.close_position(current_ltp, reason="🎯 Target Hit (Full Profit Secured)")

            # Opposite-signal reversal (protected by min-hold and persistence)
            sig = signal_info.get("signal", "")
            is_opposite = (
                (pos_type in ("CE", "LONG") and sig in ("BUY_PE", "FAST_BUY_PE", "SHORT_FUT"))
                or (pos_type in ("PE", "SHORT") and sig in ("BUY_CE", "FAST_BUY_CE", "LONG_FUT"))
            )
            if is_opposite:
                if held_seconds < self.min_hold_seconds:
                    self._opposite_signal_count = 0
                    return None
                if signal_info.get("confluence_pct", 0) >= 80:
                    self._opposite_signal_count += 1
                    if self._opposite_signal_count >= 3:
                        self._opposite_signal_count = 0
                        return self.close_position(current_ltp, reason="Confirmed Trend Reversal (3-Tick Sustained)")
                else:
                    self._opposite_signal_count = 0
            else:
                self._opposite_signal_count = 0
            return None

        # ---------------- 2. entry prerequisites ----------------
        if len(self._today_trades()) >= self.max_daily_trades:
            self._reset_pending()
            return "[RMS] Maximum daily trade limit reached. Capital preserved."

        if self._today_pnl() <= -(self.max_daily_loss_pct / 100.0) * self.initial_capital:
            self._reset_pending()
            return f"[RMS] Daily loss limit ({self.max_daily_loss_pct}%) reached. No new trades today."

        elapsed = now - self.last_exit_time
        if elapsed < self.cooldown_seconds:
            self._reset_pending()
            return f"[COOLDOWN] Waiting {int(self.cooldown_seconds - elapsed)}s cooldown before next trade."

        confluence = signal_info.get("confluence_pct", 0)
        if confluence < self.min_confluence_to_enter:
            self._reset_pending()
            return None

        # ---------------- 3. persistence + entry ----------------
        signal = signal_info.get("signal")
        valid = ("BUY_CE", "BUY_PE", "FAST_BUY_CE", "FAST_BUY_PE", "LONG_FUT", "SHORT_FUT")
        if signal in valid and current_ltp > 0.0 and signal_info.get("instrument"):
            if signal == self._pending_signal:
                self._pending_signal_count += 1
            else:
                self._pending_signal, self._pending_signal_count = signal, 1

            if self._pending_signal_count < self.confirm_ticks_required:
                return (f"⏳ [CONFIRMING] Signal {signal} ({self._pending_signal_count}/"
                        f"{self.confirm_ticks_required} ticks) with {confluence}% confluence...")
            self._reset_pending()

            qty = self.lot_size * self.lots
            cost = current_ltp * qty if "FUT" not in signal else current_ltp * qty * 0.20
            if cost > self.capital:
                return f"[RMS] Insufficient capital (Required: ₹{cost:.2f}, Available: ₹{self.capital:.2f})"

            bp = signal_info.get("buyer_profile", {}) or {}
            sl_pct = bp.get("initial_sl_pct", self.sl_percent * 100) / 100.0
            tgt_pct = bp.get("initial_tgt_pct", self.target_percent * 100) / 100.0
            be_trigger = bp.get("breakeven_trigger_pct", 18.0)
            time_stop = bp.get("time_stop_limit_sec", 600)

            if signal == "SHORT_FUT":
                pos_type = "SHORT"
                stop_loss = round(current_ltp * (1 + sl_pct), 2)
                target = round(current_ltp * (1 - tgt_pct), 2)
            else:
                pos_type = "LONG" if "LONG" in signal else ("CE" if "CE" in signal else "PE")
                stop_loss = round(current_ltp * (1 - sl_pct), 2)
                target = round(current_ltp * (1 + tgt_pct), 2)

            self.current_position = {
                "type": pos_type,
                "instrument": signal_info["instrument"],
                "entry_time": now_str,
                "entry_ts": now,
                "entry_price": current_ltp,
                "peak_price": current_ltp,
                "qty": qty,
                "stop_loss": stop_loss,
                "target": target,
                "sl_pct": round(sl_pct * 100, 2),
                "be_trigger_pct": be_trigger,
                "time_stop_sec": time_stop,
                "is_breakeven_locked": False,
                "trailing_stage": 0,
                "confluence_at_entry": confluence,
                "entry_reason": signal_info.get("reason", ""),
            }
            self._save_state()
            prefix = "⚡ [INSTITUTIONAL FAST SNIPER]" if "FAST" in signal else "🎯 [INSTITUTIONAL SNIPER ORDER]"
            action_msg = (f"{prefix} {signal} | {signal_info['instrument']} | Qty: {qty} @ ₹{current_ltp:.2f} | "
                          f"SL: ₹{stop_loss:.2f} ({sl_pct * 100:.0f}%) | Target: ₹{target:.2f} | Confluence: {confluence}%")
        else:
            self._reset_pending()
        return action_msg

    def _reset_pending(self):
        self._pending_signal = None
        self._pending_signal_count = 0

    # ------------------------------------------------------------------
    def close_position(self, exit_price: float, reason: str = "Manual Exit") -> str:
        if not self.current_position:
            return "No open position to close."

        pos = self.current_position
        entry_price, qty, pos_type = pos["entry_price"], pos["qty"], pos["type"]

        # exit slippage (selling a long option at the bid, buying back a short at the ask)
        slip = self.exit_slippage_pct / 100.0
        fill = exit_price * (1 + slip) if pos_type == "SHORT" else exit_price * (1 - slip)
        fill = round(fill, 2)

        gross = (entry_price - fill) * qty if pos_type == "SHORT" else (fill - entry_price) * qty
        sell_value = (entry_price if pos_type == "SHORT" else fill) * qty
        charges = round(2 * self.brokerage_per_order + sell_value * self.statutory_pct_of_sell / 100.0, 2)
        pnl = round(gross - charges, 2)
        pnl_pct = (pnl / (entry_price * qty) * 100) if entry_price > 0 else 0.0

        self.capital += pnl
        now = time.time()
        self.last_exit_time = now
        self._reset_pending()
        self._opposite_signal_count = 0
        held = int(now - pos.get("entry_ts", now))

        self.trade_history.append({
            **pos,
            "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exit_price": fill,
            "gross_pnl": round(gross, 2),
            "charges": charges,
            "realized_pnl": pnl,
            "pnl_percent": round(pnl_pct, 2),
            "exit_reason": reason,
            "holding_seconds": held,
        })
        name = pos["instrument"]
        self.current_position = None
        self._save_state()

        emoji = "🟢 PROFIT" if pnl >= 0 else "🔴 LOSS"
        return (f"⏹️ [TRADE CLOSED - {reason}] {name} | Exit: ₹{fill:.2f} | Net P&L: ₹{pnl:+.2f} "
                f"({pnl_pct:+.2f}%, charges ₹{charges:.2f}) | {emoji} | Held: {held}s | Balance: ₹{self.capital:,.2f}")
