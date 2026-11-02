"""
Main Orchestrator & Live Console Dashboard
Runs live NIFTY Open Interest tracking, Strategy Signals, and Paper Trading.
Supports DhanHQ Official Live Feed, NSE Web Feed, and Simulation Mode.
"""

import os
import sys
import time
import argparse
from datetime import datetime
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load .env file
dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path)

from nse_fetcher import NSEFetcher
from dhan_fetcher import DhanFetcher
from oi_analyzer import OIAnalyzer
from strategy import OIStrategy
from paper_trader import PaperTrader
from chart_patterns import ChartPatternAnalyzer
from news_sentiment import NewsSentimentAnalyzer
from market_intelligence import MarketIntelligence


def format_num(val: float) -> str:
    """Format large numbers with sign and comma."""
    if abs(val) >= 100000:
        return f"{val / 100000:+.2f}L"
    elif abs(val) >= 1000:
        return f"{val / 1000:+.1f}K"
    return f"{val:+.0f}"


def get_position_current_ltp(pos: dict, table_data: list) -> float:
    """Finds the current real-time market price of the held position's strike."""
    try:
        strike_num = int(pos["instrument"].split()[1])
        match = next((s for s in table_data if int(s["strike"]) == strike_num), None)
        if match:
            return match["ce_ltp"] if pos["type"] == "CE" else match["pe_ltp"]
    except Exception:
        pass
    return pos["entry_price"]


def display_dashboard(
    analysis: dict, 
    signal_info: dict, 
    trader: PaperTrader, 
    chart_info: Optional[dict] = None, 
    news_info: Optional[dict] = None,
    market_context: Optional[dict] = None,
    source_label: str = "LIVE"
):
    """Renders a comprehensive live terminal dashboard with OI, MTF Chart Patterns, VIX, Heavyweights & News."""
    print("\n" + "=" * 80)
    print(f" 📈 NIFTY LIVE ALGO TRADING & OPEN INTEREST  [{source_label}]")
    print("=" * 80)
    
    spot = analysis["spot_price"]
    pcr = analysis["pcr"]
    max_pain = analysis["max_pain"]
    sentiment = analysis["sentiment"]
    timestamp = analysis["timestamp"]
    expiry = analysis.get("expiry") or analysis.get("current_expiry", "")
    
    lat_ms = analysis.get("latency_ms", 0)
    lat_str = f"  |  ⚡ Latency: {lat_ms}ms" if lat_ms > 0 else ""
    print(f" Timestamp  : {timestamp}  |  Expiry: {expiry}{lat_str}")
    print(f" NIFTY Spot : {spot:,.2f}  |  ATM Strike: {analysis['atm_strike']}")
    print(f" PCR        : {pcr:.3f}   |  Max Pain  : {max_pain}")
    print(f" Resistance : {analysis['resistance_strike']} (Max CE OI) | Support: {analysis['support_strike']} (Max PE OI)")
    print(f" OI Sentiment : {sentiment}")
    print("-" * 80)

    # 1. Market Intelligence: India VIX, Heavyweights, and Session Filter
    if market_context:
        vix = market_context.get("vix", {})
        hw = market_context.get("heavyweights", {})
        sess = market_context.get("session", {})

        vix_str = f"{vix.get('badge', '')} | Δ: {vix.get('change_pct', 0.0):+.2f}% | Bias: {vix.get('bias', '')}"
        print(f" 📊 INDIA VIX      : {vix_str}")
        
        st = hw.get("stocks", {})
        rel_str = f"RELIANCE: {st.get('RELIANCE', {}).get('pct', 0.0):+.2f}%"
        icici_str = f"ICICI: {st.get('ICICIBANK', {}).get('pct', 0.0):+.2f}%"
        hdfc_str = f"HDFC: {st.get('HDFCBANK', {}).get('pct', 0.0):+.2f}%"
        print(f" 🏛️  HEAVYWEIGHTS  : {hw.get('badge', '')} | {rel_str} | {icici_str} | {hdfc_str}")

        print(f" ⏰ SESSION REGIME : {sess.get('badge', '')} | {sess.get('note', '')}")
        print("-" * 80)

    # 2. OI Velocity & Rapid Shift Tracking
    oi_vel = analysis.get("oi_velocity")
    if oi_vel:
        badge = oi_vel.get("badge", "⚪ STABLE")
        d_ce = format_num(oi_vel.get("delta_ce_oi", 0))
        d_pe = format_num(oi_vel.get("delta_pe_oi", 0))
        d_spot = oi_vel.get("delta_spot", 0.0)
        fast_flag = "⚡ [FAST MOVE TRIGGERED]" if oi_vel.get("fast_oi_trigger") else ""
        print(f" ⚡ OI VELOCITY    : {badge} {fast_flag}")
        print(f"    Shift Metrics  : Δ Spot: {d_spot:+.1f} pts | Δ CE OI: {d_ce} | Δ PE OI: {d_pe}")
        print(f"    Shift Detail   : {oi_vel.get('description', '')}")
        print("-" * 80)

    # 3. Multi-Timeframe Chart Patterns & Technicals
    if chart_info:
        ind = chart_info.get("indicators", {})
        mtf = chart_info.get("mtf", {})
        mtf_badge = mtf.get("badge", "") if mtf else ""
        print(f" 🕯️  CHART PATTERNS: {chart_info['sentiment']} ({chart_info['confidence']}%) | {mtf_badge}")
        if mtf and mtf.get("desc"):
            print(f"    MTF Context    : {mtf.get('desc', '')}")
        print(f"    5m Formations  : {chart_info['summary']}")
        if ind:
            print(f"    5m Technicals  : EMA(9): ₹{ind.get('ema9', 0):,.1f} | EMA(21): ₹{ind.get('ema21', 0):,.1f} | VWAP: ₹{ind.get('vwap', 0):,.1f} | RSI: {ind.get('rsi', 0):.1f}")
        print("-" * 80)

    # 4. Breaking News Flow & Sentiment Catalyst
    if news_info:
        n_badge = news_info.get("sentiment_badge", "⚪ NEUTRAL")
        n_score = news_info.get("score", 0.0)
        top_h = news_info.get("latest_headline", "")
        alerts = news_info.get("critical_alerts", [])
        print(f" 📰 BREAKING NEWS  : {n_badge} (Score: {n_score:+.1f}/100) | Live Financial Feeds")
        if top_h:
            print(f"    Top Headline   : {top_h[:72] + '...' if len(top_h) > 72 else top_h}")
        if alerts:
            print(f"    Fast Catalyst  : {alerts[0][:72] + '...' if len(alerts[0]) > 72 else alerts[0]}")
        print("-" * 80)
    
    # 5. Algo Strategy Signal with Confluence & Accuracy Filters
    sig = signal_info["signal"]
    sig_icon = "🟢" if "CE" in sig else ("🔴" if "PE" in sig else "⚪")
    conf = signal_info.get("confluence_pct", 50)
    is_fast = signal_info.get("is_fast_trigger", False)
    is_chop = signal_info.get("is_chop_zone", False)
    if is_fast:
        mode_tag = "⚡ FAST TRIGGER [PRIORITY MOVE]"
    elif is_chop:
        mode_tag = "⚠️ CHOP ZONE [STRICT FILTER]"
    else:
        mode_tag = "STANDARD CONFLUENCE"

    print(f" 🎯 ALGO SIGNAL   : {sig_icon} [{sig}] | {mode_tag} | Confluence: {conf}%")
    print(f"    Execution Target: {signal_info.get('instrument', 'None')} @ ₹{signal_info.get('estimated_entry_price', 0.0):.2f}")
    print(f"    Reasoning      : {signal_info['reason']}")
    print("-" * 80)

    # 6. Option Chain Focus Table around ATM
    print(f"{'CE OI':>10} | {'CE Chg OI':>11} | {'CE LTP':>8} | {'STRIKE':^8} | {'PE LTP':>8} | {'PE Chg OI':>11} | {'PE OI':>10}")
    print("-" * 80)
    
    table_rows = analysis.get("table_data", [])
    atm = analysis["atm_strike"]
    
    for row in table_rows:
        strike = int(row["strike"])
        is_atm = "🎯" if strike == atm else "  "
        ce_oi_str = format_num(row["ce_oi"])
        ce_chg_str = format_num(row["ce_chg_oi"])
        pe_chg_str = format_num(row["pe_chg_oi"])
        pe_oi_str = format_num(row["pe_oi"])

        print(
            f"{ce_oi_str:>10} | {ce_chg_str:>11} | {row['ce_ltp']:>8.2f} | "
            f"{is_atm}{strike:^6} | {row['pe_ltp']:>8.2f} | {pe_chg_str:>11} | {pe_oi_str:>10}"
        )

    print("-" * 80)
    # 7. Active Position Management with Breakeven & Trailing SL
    if trader.current_position:
        pos = trader.current_position
        curr_ltp = get_position_current_ltp(pos, table_rows)
        pos_status = trader.get_position_status(curr_ltp)
        be_status = "🔒 BREAKEVEN LOCKED" if pos.get("is_breakeven_locked") else f"SL: ₹{pos['stop_loss']:.2f}"
        trail_stage = f" (Stage {pos.get('trailing_stage', 0)})" if pos.get("trailing_stage", 0) > 0 else ""
        print(f" 💼 ACTIVE POSITION: {pos['instrument']} x {pos['qty']} [{be_status}{trail_stage}]")
        print(f"    Entry: ₹{pos['entry_price']:.2f} | Peak: ₹{pos.get('peak_price', curr_ltp):.2f} | Current: ₹{curr_ltp:.2f} | "
              f"P&L: ₹{pos_status['unrealized_pnl']:+,.2f} ({pos_status['pnl_percentage']:+,.2f}%)")
        print(f"    Current Stop-Loss: ₹{pos['stop_loss']:.2f} | Target: ₹{pos['target']:.2f}")
    else:
        print(" 💼 ACTIVE POSITION: None (Awaiting high-probability confluence confirmation)")

    print(f" 💰 Virtual Capital: ₹{trader.capital:,.2f} | Closed Trades: {len(trader.trade_history)}")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Live NIFTY Algo Trading & OI System")
    parser.add_argument("--interval", type=int, default=5, help="Refresh interval in seconds (default: 5)")
    parser.add_argument("--fast", action="store_true", help="High-speed mode: refreshes option chain every 3 seconds")
    parser.add_argument("--once", action="store_true", help="Run a single snapshot and exit")
    parser.add_argument("--demo", action="store_true", help="Force demo/simulation mode")
    parser.add_argument("--spot", type=float, default=22880.0, help="Initial NIFTY spot price for demo (default: 22880.0)")
    parser.add_argument("--source", choices=["auto", "dhan", "nse"], default="nse", help="Data source provider (default: nse)")
    args = parser.parse_args()

    if args.fast:
        args.interval = 3

    analyzer = OIAnalyzer()
    strategy = OIStrategy()
    trader = PaperTrader(initial_capital=100000.0, lot_size=50)
    chart_analyzer = ChartPatternAnalyzer()
    news_analyzer = NewsSentimentAnalyzer()
    market_intel = MarketIntelligence()

    # Initialize Dhan and NSE fetchers
    dhan = DhanFetcher()
    nse = NSEFetcher(symbol="NIFTY", use_mock_on_failure=args.demo)
    if args.spot:
        nse._mock_spot = args.spot

    # Determine data source
    use_dhan = False
    if args.source == "dhan":
        use_dhan = True
    elif args.source == "auto" and not args.demo and dhan.is_configured():
        use_dhan = True

    print("\nStarting NIFTY Live Algo Trading & OI System...")
    if args.demo:
        source_label = "🟡 SIMULATION / DEMO MODE"
        print(f"Running mode: {source_label} (Spot initialized to {args.spot})")
    elif use_dhan:
        source_label = f"🟢 DHANHQ OFFICIAL LIVE API (Client: {dhan.client_id})"
        print(f"Running mode: {source_label}")
    else:
        source_label = "🌐 NSE LIVE WEB FEED"
        print(f"Running mode: {source_label}")
        print("⚡ Pre-warming live NSE session cookies for instant option chain loading...")
        nse.prewarm()
        print("✅ Session pre-warmed! Option chain ready for fast streaming.")

    print(f"⏱️  Refresh Speed: Every {args.interval}s (Run with --fast for 3s refresh)\n")
    fail_count = 0
    fallback_to_demo = False
    while True:
        try:
            t_fetch_start = time.time()
            raw_data = None
            if args.demo or fallback_to_demo:
                raw_data = nse.get_mock_data()
            elif use_dhan:
                raw_data = dhan.get_parsed_data()
                if not raw_data:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Dhan API: {dhan.last_error}")
                    if args.source == "auto":
                        print("ℹ️ Switching to NSE Live Web Feed...")
                        use_dhan = False
                        source_label = "🌐 NSE LIVE WEB FEED"
                        raw_data = nse.get_parsed_data()
                        if not raw_data:
                            print(f"[{datetime.now().strftime('%H:%M:%S')}] NSE Feed: {nse.last_error or 'Unavailable'}")
            else:
                raw_data = nse.get_parsed_data()
                if not raw_data:
                    fail_count += 1
                    err = nse.last_error or "Timeout / Unreachable"
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] NSE Error: {err}")

            if not raw_data:
                fail_count += 1
                if fail_count >= 2 and not fallback_to_demo and args.source == "auto":
                    print("\n⚠️  Live feeds unavailable (Market closed / Dhan Data API not subscribed).")
                    print("🔄 Switching to realistic SIMULATION / DEMO MODE to demonstrate algo trading & OI...\n")
                    fallback_to_demo = True
                    raw_data = nse.get_mock_data()
                else:
                    print(f"Retrying in {args.interval}s...")
                    time.sleep(args.interval)
                    continue

            fail_count = 0
            is_sim = raw_data.get("is_simulation", args.demo or fallback_to_demo)
            active_label = "🟡 SIMULATION / DEMO MODE" if is_sim else source_label

            analysis = analyzer.analyze(raw_data, range_strikes=6)
            if not analysis:
                print("Failed to compute analysis. Retrying...")
                time.sleep(args.interval)
                continue

            analysis["latency_ms"] = int((time.time() - t_fetch_start) * 1000)

            # Analyze Multi-Timeframe (15m Macro Trend + 5m Action)
            chart_info = chart_analyzer.analyze_multi_timeframe()

            # Analyze real-time Indian Financial Market News & Breaking Catalysts
            news_info = news_analyzer.analyze_news_sentiment()

            # Analyze India VIX Volatility Regime, Top Heavyweights & Session Regime
            market_context = market_intel.get_market_intelligence_context()

            # Evaluate strategy with multi-factor confluence and fast-trigger capability
            signal_info = strategy.evaluate_signal(
                analysis, 
                chart_analysis=chart_info, 
                news_analysis=news_info, 
                market_context=market_context
            )
            
            # Determine correct market price for position management
            if trader.current_position:
                curr_eval_price = get_position_current_ltp(trader.current_position, analysis["table_data"])
            else:
                curr_eval_price = signal_info.get("estimated_entry_price", 0.0)

            trade_action = trader.process_signal(signal_info, curr_eval_price)

            display_dashboard(
                analysis, 
                signal_info, 
                trader, 
                chart_info=chart_info, 
                news_info=news_info, 
                market_context=market_context, 
                source_label=active_label
            )

            if trade_action:
                print(f"\n🔔 ACTION: {trade_action}\n")

            if args.once:
                break

            time.sleep(args.interval)

        except KeyboardInterrupt:
            print("\nExiting live trading loop. Happy trading!")
            sys.exit(0)
        except Exception as e:
            print(f"Unexpected error: {e}")
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
