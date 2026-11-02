"""
Paper Trading & Execution Manager
Executes simulated orders, tracks P&L, stop-loss, profit targets, and trade logs.
Provides an easy switch to live Dhan API when you're ready.
"""

import time
from datetime import datetime
from typing import Dict, Any, Optional, List


class PaperTrader:
    def __init__(
        self, 
        initial_capital: float = 100000.0, 
        lot_size: int = 50, 
        sl_percent: float = 0.16,          # 16% risk for option buyer
        target_percent: float = 0.40,      # 40% profit target (1:2.5 Risk-to-Reward ratio)
        min_hold_seconds: int = 90,        # Minimum holding period before early opposite signal exit
        cooldown_seconds: int = 120,       # Cooldown after closing a trade before new entry
        min_confluence_to_enter: int = 75, # Minimum confluence required to trigger an entry
        confirm_ticks_required: int = 3,   # Number of consecutive ticks signal must persist
        max_daily_trades: int = 8          # Maximum executed trades allowed per session
    ):
        self.capital = initial_capital
        self.lot_size = lot_size
        self.sl_percent = sl_percent          # 16% stop-loss
        self.target_percent = target_percent  # 40% take-profit
        self.min_hold_seconds = min_hold_seconds
        self.cooldown_seconds = cooldown_seconds
        self.min_confluence_to_enter = min_confluence_to_enter
        self.confirm_ticks_required = confirm_ticks_required
        self.max_daily_trades = max_daily_trades

        self.current_position: Optional[Dict[str, Any]] = None
        self.trade_history: List[Dict[str, Any]] = []

        # Anti-Whipsaw & Churn State
        self.last_exit_time: float = 0.0
        self._pending_signal: Optional[str] = None
        self._pending_signal_count: int = 0
        self._opposite_signal_count: int = 0

    def get_position_status(self, current_ltp: float) -> Optional[Dict[str, Any]]:
        """Returns current open position with unrealized P&L."""
        if not self.current_position:
            return None

        entry_price = self.current_position["entry_price"]
        qty = self.current_position["qty"]
        pos_type = self.current_position["type"]

        if pos_type == "SHORT":
            unrealized_pnl = (entry_price - current_ltp) * qty
            pnl_pct = ((entry_price - current_ltp) / entry_price) * 100 if entry_price > 0 else 0.0
        else:
            unrealized_pnl = (current_ltp - entry_price) * qty
            pnl_pct = ((current_ltp - entry_price) / entry_price) * 100 if entry_price > 0 else 0.0

        entry_ts = self.current_position.get("entry_ts", time.time())
        held_secs = int(time.time() - entry_ts)

        return {
            **self.current_position,
            "current_ltp": current_ltp,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "pnl_percentage": round(pnl_pct, 2),
            "held_seconds": held_secs,
            "min_hold_remaining": max(0, self.min_hold_seconds - held_secs),
            "time_stop_remaining_sec": max(0, 600 - held_secs),
            "is_breakeven_locked": self.current_position.get("is_breakeven_locked", False),
            "trailing_stage": self.current_position.get("trailing_stage", 0)
        }

    def process_signal(self, signal_info: Dict[str, Any], current_ltp: float) -> Optional[str]:
        """
        Processes strategy signals and manages trade execution / risk for option buying.
        Implements 10-minute Theta time-stop, breakeven lock at +18%, and multi-stage trailing profits.
        """
        action_msg = None
        now = time.time()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # -------------------------------------------------------------
        # 1. Manage Active Position (SL, Trailing SL, Target, Reversals)
        # -------------------------------------------------------------
        if self.current_position:
            pos_type = self.current_position["type"]
            entry_price = self.current_position["entry_price"]
            sl_price = self.current_position["stop_loss"]
            tgt_price = self.current_position["target"]
            entry_ts = self.current_position.get("entry_ts", now)
            held_seconds = now - entry_ts
            gain_pct = ((current_ltp - entry_price) / entry_price) * 100 if entry_price > 0 else 0.0

            # Dynamic Breakeven & Trailing Stop-Loss for Option Buyers
            if pos_type != "SHORT":
                if current_ltp > self.current_position.get("peak_price", entry_price):
                    self.current_position["peak_price"] = current_ltp

                # Stage 1: At +18% profit, shift SL to Entry Price (Breakeven - Zero Capital Risk!)
                if gain_pct >= 18.0 and not self.current_position.get("is_breakeven_locked"):
                    self.current_position["stop_loss"] = entry_price
                    self.current_position["is_breakeven_locked"] = True
                    self.current_position["trailing_stage"] = 1
                    sl_price = entry_price

                # Stage 2: At +30% profit, lock in +18% profit guaranteed
                elif gain_pct >= 30.0 and self.current_position.get("trailing_stage", 0) < 2:
                    locked_sl = round(entry_price * 1.18, 2)
                    self.current_position["stop_loss"] = locked_sl
                    self.current_position["trailing_stage"] = 2
                    sl_price = locked_sl

                # Stage 3: At +45% profit, lock in +30% profit and extend target to +60% (Ride Gamma Runner)
                elif gain_pct >= 45.0 and self.current_position.get("trailing_stage", 0) < 3:
                    locked_sl = round(entry_price * 1.30, 2)
                    self.current_position["stop_loss"] = locked_sl
                    self.current_position["target"] = round(entry_price * 1.60, 2)
                    self.current_position["trailing_stage"] = 3
                    sl_price = locked_sl
                    tgt_price = self.current_position["target"]

            # Priority 0: Option Buyer's 10-Minute Time-Stop (Theta Kill Switch)
            # If position has been held for 10 minutes (600s) without breaking into solid profit (>= +8%),
            # exit immediately to prevent theta decay from eroding option premium in sideways chop.
            time_stop_limit_sec = 600
            if held_seconds >= time_stop_limit_sec and gain_pct < 8.0:
                return self.close_position(current_ltp, reason="⏱️ 10m Time-Stop Hit (Theta Decay Protection)")

            # Priority 1: Hard Stop-Loss Hit
            if pos_type == "SHORT":
                if current_ltp >= sl_price:
                    return self.close_position(current_ltp, reason="Stop-Loss Hit")
                if current_ltp <= tgt_price:
                    return self.close_position(current_ltp, reason="Target Hit")
            else:
                if current_ltp <= sl_price:
                    close_reason = "🛡️ Trailing SL Hit" if self.current_position.get("trailing_stage", 0) > 0 else "Stop-Loss Hit"
                    return self.close_position(current_ltp, reason=close_reason)
                if current_ltp >= tgt_price:
                    return self.close_position(current_ltp, reason="🎯 Target Hit (Full Profit Secured)")


            # Priority 2: Opposite Signal Reversal (PROTECTED BY MINIMUM HOLD & PERSISTENCE)
            sig = signal_info.get("signal", "")
            is_opposite = (
                (pos_type in ("CE", "LONG") and sig in ("BUY_PE", "FAST_BUY_PE", "SHORT_FUT")) or
                (pos_type in ("PE", "SHORT") and sig in ("BUY_CE", "FAST_BUY_CE", "LONG_FUT"))
            )

            if is_opposite:
                # Anti-Whipsaw Check A: Don't exit early if minimum hold duration hasn't elapsed
                if held_seconds < self.min_hold_seconds:
                    # Give trade breathing room to avoid shaking out on noise
                    self._opposite_signal_count = 0
                    return None

                # Anti-Whipsaw Check B: Require high confluence (>=80%) AND at least 3 consecutive ticks
                opp_conf = signal_info.get("confluence_pct", 0)
                if opp_conf >= 80:
                    self._opposite_signal_count += 1
                    if self._opposite_signal_count >= 3:
                        self._opposite_signal_count = 0
                        return self.close_position(current_ltp, reason="Confirmed Trend Reversal (3-Tick Sustained)")
                else:
                    self._opposite_signal_count = 0
            else:
                self._opposite_signal_count = 0

            return None

        # -------------------------------------------------------------
        # 2. Check Prerequisites Before Opening a New Position
        # -------------------------------------------------------------
        # RMS Filter 1: Daily Trade Limit
        if len(self.trade_history) >= self.max_daily_trades:
            self._pending_signal = None
            self._pending_signal_count = 0
            return "[RMS] Maximum daily trade limit reached. Capital preserved."

        # RMS Filter 2: Post-Exit Cooldown (Prevents rapid over-trading churn)
        elapsed_exit = now - self.last_exit_time
        if elapsed_exit < self.cooldown_seconds:
            self._pending_signal = None
            self._pending_signal_count = 0
            cooldown_left = int(self.cooldown_seconds - elapsed_exit)
            return f"[COOLDOWN] Waiting {cooldown_left}s cooldown before next high-accuracy sniper trade."

        # RMS Filter 3: Minimum Confluence Check
        confluence = signal_info.get("confluence_pct", 0)
        if confluence < self.min_confluence_to_enter:
            self._pending_signal = None
            self._pending_signal_count = 0
            return None

        # -------------------------------------------------------------
        # 3. Signal Persistence & Debounce (Must Persist for >= 3 Ticks)
        # -------------------------------------------------------------
        signal = signal_info.get("signal")
        valid_signals = ("BUY_CE", "BUY_PE", "FAST_BUY_CE", "FAST_BUY_PE", "LONG_FUT", "SHORT_FUT")
        if signal in valid_signals and current_ltp > 0.0:
            if signal == self._pending_signal:
                self._pending_signal_count += 1
            else:
                self._pending_signal = signal
                self._pending_signal_count = 1

            # Await confirmation ticks
            if self._pending_signal_count < self.confirm_ticks_required:
                return (
                    f"⏳ [CONFIRMING] Signal {signal} ({self._pending_signal_count}/{self.confirm_ticks_required} ticks) "
                    f"with {confluence}% confluence..."
                )

            # Signal Confirmed! Reset counters and execute order
            self._pending_signal = None
            self._pending_signal_count = 0

            qty = self.lot_size
            cost = current_ltp * qty if "FUT" not in signal else (current_ltp * qty * 0.20)
            if cost > self.capital:
                return f"[RMS] Insufficient capital (Required: ₹{cost:.2f}, Available: ₹{self.capital:.2f})"

            if signal == "SHORT_FUT":
                pos_type = "SHORT"
                stop_loss = round(current_ltp * (1 + self.sl_percent), 2)
                target = round(current_ltp * (1 - self.target_percent), 2)
            else:
                pos_type = "LONG" if "LONG" in signal else ("CE" if "CE" in signal else "PE")
                stop_loss = round(current_ltp * (1 - self.sl_percent), 2)
                target = round(current_ltp * (1 + self.target_percent), 2)

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
                "is_breakeven_locked": False,
                "trailing_stage": 0,
                "confluence_at_entry": confluence,
                "entry_reason": signal_info.get("reason", "")
            }

            order_prefix = "⚡ [INSTITUTIONAL FAST SNIPER]" if "FAST" in signal else "🎯 [INSTITUTIONAL SNIPER ORDER]"
            action_msg = (
                f"{order_prefix} {signal} | {signal_info['instrument']} | "
                f"Qty: {qty} @ ₹{current_ltp:.2f} | SL: ₹{stop_loss:.2f} | Target: ₹{target:.2f} | "
                f"Confluence: {confluence}%"
            )
        else:
            self._pending_signal = None
            self._pending_signal_count = 0

        return action_msg

    def close_position(self, exit_price: float, reason: str = "Manual Exit") -> str:
        """Closes active open position and records trade."""
        if not self.current_position:
            return "No open position to close."

        entry_price = self.current_position["entry_price"]
        qty = self.current_position["qty"]
        pos_type = self.current_position["type"]

        if pos_type == "SHORT":
            pnl = (entry_price - exit_price) * qty
            pnl_pct = ((entry_price - exit_price) / entry_price) * 100
        else:
            pnl = (exit_price - entry_price) * qty
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100

        self.capital += pnl
        now = time.time()
        self.last_exit_time = now
        self._pending_signal = None
        self._pending_signal_count = 0
        self._opposite_signal_count = 0

        entry_ts = self.current_position.get("entry_ts", now)
        held_duration_sec = int(now - entry_ts)

        trade_record = {
            **self.current_position,
            "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "exit_price": exit_price,
            "realized_pnl": round(pnl, 2),
            "pnl_percent": round(pnl_pct, 2),
            "exit_reason": reason,
            "holding_seconds": held_duration_sec
        }
        self.trade_history.append(trade_record)
        closed_inst = self.current_position["instrument"]
        self.current_position = None

        status_emoji = "🟢 PROFIT" if pnl >= 0 else "🔴 LOSS"
        return (
            f"⏹️ [TRADE CLOSED - {reason}] {closed_inst} | Exit: ₹{exit_price:.2f} | "
            f"P&L: ₹{pnl:+.2f} ({pnl_pct:+.2f}%) | {status_emoji} | Held: {held_duration_sec}s | Balance: ₹{self.capital:,.2f}"
        )
