"""
Signal / feature logger.

Appends one row per NEW data snapshot (or whenever the signal changes) to a CSV.
That CSV is the dataset for evaluate_signals.py and for training a model later.

Usage in main.py (after strategy.evaluate_signal):
    from signal_logger import SignalLogger
    sig_logger = SignalLogger("signal_log.csv")      # create once, before the loop
    ...
    sig_logger.log(signal_info)
"""

import csv
import os
import threading
from typing import Dict, Any, Optional


class SignalLogger:
    def __init__(self, path: str = "signal_log.csv"):
        self.path = path
        self._lock = threading.Lock()
        self._fields: Optional[list] = None
        self._last_key = None
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, "r", newline="", encoding="utf-8") as f:
                self._fields = next(csv.reader(f), None)

    def log(self, signal_info: Dict[str, Any]) -> bool:
        """Returns True if a row was written."""
        feats = signal_info.get("features")
        if not feats:
            return False
        key = (feats.get("snapshot_seq"), feats.get("signal"))
        if key == self._last_key:
            return False
        self._last_key = key
        row = dict(feats)
        row["reason"] = (signal_info.get("reason") or "")[:200]
        row["blockers"] = "; ".join(signal_info.get("blockers", []))[:200]
        with self._lock:
            new_file = self._fields is None
            if new_file:
                self._fields = list(row.keys())
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=self._fields, extrasaction="ignore")
                if new_file:
                    w.writeheader()
                w.writerow(row)
        return True
