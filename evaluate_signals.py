"""
Measure how good your signals really are, from signal_log.csv.

    python evaluate_signals.py signal_log.csv

For every signal EPISODE (first row where the signal changes) it looks at the NIFTY spot
H minutes later and reports:
  * hit rate  (CE: spot higher, PE: spot lower)
  * average signed move in index points (positive = signal was right)
Also prints calibration by confluence bucket, and the HOLD baseline (how often spot rose).
This is spot-direction accuracy, a first filter. Option P&L also depends on theta, IV and costs.
"""

import sys
import numpy as np
import pandas as pd

HORIZONS_MIN = [5, 15, 30]
TOLERANCE_SEC = 180


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.dropna(subset=["ts", "spot"]).sort_values("ts").reset_index(drop=True)
    return df


def add_forward_moves(df: pd.DataFrame) -> pd.DataFrame:
    base = df[["ts", "spot"]].rename(columns={"ts": "ts_f", "spot": "spot_f"})
    for h in HORIZONS_MIN:
        left = df[["ts"]].copy()
        left["target"] = df["ts"] + h * 60
        merged = pd.merge_asof(left.sort_values("target"), base, left_on="target", right_on="ts_f",
                               direction="backward", tolerance=TOLERANCE_SEC)
        merged = merged.sort_index()
        # require the matched future row to really be ~h minutes ahead
        ok = (merged["ts_f"] - df["ts"]) >= (h * 60 - TOLERANCE_SEC)
        df[f"move_{h}m"] = np.where(ok, merged["spot_f"] - df["spot"], np.nan)
    return df


def summarize(ep: pd.DataFrame, label: str):
    print(f"\n=== {label} ({len(ep)} episodes) ===")
    for h in HORIZONS_MIN:
        col = f"move_{h}m"
        sub = ep.dropna(subset=[col])
        if sub.empty:
            print(f"  {h:>2}m: no data yet")
            continue
        sign = np.where(sub["signal"].str.contains("CE"), 1.0, -1.0)
        signed = sub[col].values * sign
        print(f"  {h:>2}m: n={len(sub):>3} | hit rate {np.mean(signed > 0)*100:5.1f}% | "
              f"avg signed move {signed.mean():+6.1f} pts | median {np.median(signed):+6.1f} pts")


def main(path: str):
    df = add_forward_moves(load(path))
    df["episode"] = df["signal"] != df["signal"].shift()
    eps = df[df["episode"]]

    trades = eps[eps["signal"] != "HOLD"]
    if trades.empty:
        print("No BUY signals logged yet. Keep collecting data.")
    else:
        for sig in sorted(trades["signal"].unique()):
            summarize(trades[trades["signal"] == sig], sig)
        summarize(trades, "ALL SIGNALS")

        if "confluence_pct" in trades.columns:
            print("\n=== Calibration: does higher confluence actually win more? (15m) ===")
            t = trades.dropna(subset=["move_15m"]).copy()
            if not t.empty:
                t["signed"] = t["move_15m"] * np.where(t["signal"].str.contains("CE"), 1.0, -1.0)
                t["bucket"] = pd.cut(t["confluence_pct"], [0, 79, 89, 100], labels=["<80", "80-89", "90+"])
                print(t.groupby("bucket", observed=True)["signed"].agg(
                    n="count", hit_rate=lambda s: (s > 0).mean() * 100, avg_pts="mean").round(1))

    hold = df[df["signal"] == "HOLD"].dropna(subset=["move_15m"])
    if not hold.empty:
        print(f"\nBaseline (HOLD rows): spot rose after 15m in {(hold['move_15m'] > 0).mean()*100:.1f}% of rows")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "signal_log.csv")
