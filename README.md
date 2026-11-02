# Live NIFTY Algo Trading & Open Interest (OI) Analyzer

A live Python algorithmic trading and Open Interest (OI) system for **NIFTY 50** that works **100% free without any broker API keys or subscriptions**.

---

## 🚀 Key Features

1. **Free Real-Time NSE Data**:
   - Fetches live NIFTY Option Chain directly from NSE India.
   - Extracts CE/PE Open Interest (OI), Change in OI, Volume, LTP, and IV.
   - Zero broker credentials or subscriptions needed.

2. **Open Interest (OI) & Velocity Analytics Engine**:
   - **Put-Call Ratio (PCR)**: Live sentiment indicator.
   - **Max Pain**: The strike price where option sellers incur minimum loss.
   - **Support & Resistance**: Dynamically derived from peak Put OI and Call OI strikes.
   - **Tick-to-Tick OI Velocity**: Detects **Rapid Short Covering** (Call writers covering in panic), **Rapid Long Unwinding** (Put dumping), and aggressive writing spikes.

3. **Real-Time News Sentiment & Breaking Catalysts**:
   - Streams live headlines from verified Indian financial media (Livemint, Economic Times, Moneycontrol, CNBC-TV18 via Google News RSS).
   - Computes weighted sentiment scores (-100 to +100).
   - Flags high-impact **Breaking News Catalysts** (RBI rate decisions, budget, crude spikes, FII flows, geopolitical shocks).

4. **Multi-Timeframe Chart Patterns & Price Action**:
   - **MTF Architecture**: 15m Institutional Macro Trend + 5m Action Formations.
   - **Candlestick Formations**: Hammer, Shooting Star, Bullish/Bearish Engulfing, Morning/Evening Star, Doji, Inside Bar (Harami), Three White Soldiers / Black Crows.
   - **Classical Chart Formations**: Double Bottom (W Pattern), Double Top (M Pattern), Head & Shoulders, Day High Breakout (ORB), Day Low Breakdown.
   - **Technical Indicators**: Intraday VWAP, EMA(9), EMA(21), and RSI(14).

5. **Market Intelligence & Accuracy Layer ([market_intelligence.py](file:///c:/Users/Aivot/Downloads/Aryan/market_intelligence.py))**:
   - **India VIX Live Tracking**: Classifies volatility regimes (Low, Optimal, Elevated, Extreme Panic) and filters out options during Vega crush.
   - **Top 3 Heavyweights Driver Check**: Live tracking of **Reliance, HDFC Bank, ICICI Bank** (>31% index influence) to block false breakout traps.
   - **Time-of-Day Session Filter**: Protects capital by enforcing strict 80%+ confluence during the **11:30 AM - 1:15 PM Midday Theta Chop Zone**.

6. **⚡ Fast-Trigger Multi-Factor Algorithmic Strategy**:
   - Synthesizes Price Action, MTF alignment, Live Derivatives OI, Breaking News, VIX, and Heavyweights.
   - **Move-Fast Priority**: When breaking news or sudden OI velocity occurs, the algo immediately fires **`⚡ FAST_BUY_CE`** or **`⚡ FAST_BUY_PE`** with elevated confluence before option premiums explode.

7. **Paper Trading with Dynamic Breakeven & Trailing Stop-Loss**:
   - Simulated order execution with customizable virtual capital (₹1,00,000 default).
   - **Cost Lock (Breakeven)**: At **+15% profit**, Stop-Loss automatically moves to entry price (**₹0 risk trade**).
   - **Profit Trailing**: At **+25% profit**, locks in +15%; at **+35% profit**, locks in +25% and extends target to **+50%**.

8. **Institutional NSE Stock Price Predictor ([stock.py](file:///c:/Users/Aivot/Downloads/Aryan/stock.py))**:
   - **Live NSE Website Data**: Directly extracts real-time LTP, VWAP, Delivery % (`deliveryToTradedQuantity`), Delivery Volume, and 52W High/Low.
   - **Institutional Accumulation**: High delivery % (>50%) with volume surge flags genuine institutional buying vs day trading churn.
   - **Technical Indicators**: 20/50/200 EMAs, 14-day RSI, 14-day ATR, Relative Volume (RVOL), and Classical Floor Pivot targets ($R_1, R_2, S_1, S_2$).
   - **Company News Sentiment**: Searches verified news sources for quarterly earnings, deals, and regulatory probes.
   - **Price Target Projections**: Calculates **Target 1 (Conservative)**, **Target 2 (Momentum)**, and dynamic **Stop-Loss**.
   - **Stock Scanner**: `python stock.py --scan` scans top NIFTY heavyweights and ranks them by prediction score.

---

## 📂 Project Structure

```text
Aryan/
├── stock.py               # NSE Stock Price Predictor & Quant Target Forecaster (Any NSE Stock)
├── chart_patterns.py      # Real-time Multi-Timeframe (15m + 5m) Chart Pattern engine (OHLCV)
├── market_intelligence.py # India VIX, Heavyweights (Reliance/HDFC/ICICI) & Time-of-Day Filter
├── news_sentiment.py      # Live Indian market news sentiment & breaking catalyst engine
├── oi_analyzer.py         # PCR, Max Pain, Support/Resistance & Tick-to-Tick OI Velocity
├── strategy.py            # High-accuracy confluence strategy + ⚡ Fast-Trigger Execution Engine
├── main.py                # NIFTY 50 live console dashboard & execution loop (NSE equity)
├── nse_fetcher.py         # Live NSE option chain fetcher (browser TLS impersonation)
├── dhan_fetcher.py        # DhanHQ API direct connector
├── paper_trader.py        # Virtual execution, Breakeven Lock, Trailing SL, RMS & P&L tracker
├── requirements.txt       # Python dependencies
└── README.md              # Documentation & usage guide
```

---

## ⚡ Quick Start

### 🌐 1. Launch QuantEdge Modern Web Terminal (News + Options + Stocks)
Launch the comprehensive dark-mode financial terminal featuring **3 dedicated tabs**:
```powershell
python server.py
```
Open **[http://127.0.0.1:5000](http://127.0.0.1:5000)** in your browser:
- **Tab 1: 📰 NSE Breaking News**: Real-time official corporate announcements, dividends, board meetings, and results directly from the NSE India website with direct official PDF links.
- **Tab 2: ⚡ Option Trading**: Real-time NIFTY Option Chain ladder, Put-Call Ratio (PCR), Max Pain, India VIX, AI Algo Signals (`BUY CE` / `BUY PE`), and virtual paper trading.
- **Tab 3: 📊 Stocks & Predictions**: Instant stock search & sector watchlists, Multi-Horizon Price Targets (⚡ Short-Term 1-3d, 📈 Mid-Term 1-3w, 🚀 Long-Term 1-6m), F&O Buildup, Supertrend, Fibonacci Golden Pocket, and 1-click historical backtesting.

---

### 2. Run NIFTY 50 Live Algo Console (Market Hours: 9:15 AM - 3:30 PM IST)
# High-speed live options loop (refreshes option chain every 3 seconds):
python main.py --fast

# Custom high-frequency refresh interval (e.g. every 2 seconds):
python main.py --interval 2

# Standard live loop (default 5s refresh):
python main.py

# Single fast snapshot check
python main.py --once --fast

# Force simulation / demo mode
python main.py --demo
```

### 3. Run NSE Stock Price Predictor & Quant Scanner (Any NSE Stock)
```powershell
# Predict any single stock (positional or flag):
python stock.py IRFC
python stock.py RELIANCE
python stock.py TCS
python stock.py ZOMATO
# Or using the Windows batch shortcut:
.\stock IRFC

# Scan ALL 50 NIFTY stocks in parallel:
python stock.py --all

# Scan by specific market sector:
python stock.py it          # TCS, INFY, HCLTECH, WIPRO, TECHM, COFORGE...
python stock.py railways    # IRFC, RVNL, IRCTC, RAILTEL, TITAGARH...
python stock.py banking     # HDFCBANK, ICICIBANK, SBIN, KOTAKBANK, AXISBANK...
python stock.py defense     # HAL, BEL, BDL, MAZDOCK, COCHINSHIP...
python stock.py auto        # TATAMOTORS, MARUTI, M&M, BAJAJ-AUTO, TVSMOTOR...
python stock.py energy      # RELIANCE, NTPC, ONGC, COALINDIA, TATAPOWER...

# Run Historical Backtest on any stock (Past 2 Years Walk-Forward Simulation):
python stock.py TCS --backtest
python stock.py RELIANCE --backtest
python stock.py IRFC --backtest

# Interactive prompt mode:
python stock.py
```

#### 🧠 Built-in Stock Analytics & Prediction Engines:
- **🎯 Multi-Horizon Targets (Short / Mid / Long-Term)**:
  - ⚡ **Short-Term (1-3 Days)**: Floor Pivot $R_1 / S_1$, Intraday VWAP, and ATR.
  - 📈 **Mid-Term (1-3 Weeks)**: Classical Resistance $R_2$, Daily Supertrend (10, 3), and Fibonacci $1.272$ Extension.
  - 🚀 **Long-Term (1-6 Months)**: Fibonacci $1.618$ Extension, 52-Week High/Low breakout, and 200-Day EMA.
- **📐 Chart Patterns & Fibonacci Golden Pocket**:
  - Automatically identifies Candlestick Reversals (*Hammer, Bullish/Bearish Engulfing, Morning/Evening Star, Double Bottom/Top*).
  - Calculates $0.50$ and $0.618$ **Fibonacci Golden Pocket** retracement support floors.
- **🧪 Historical Backtesting Engine (`--backtest`)**:
  - Runs walk-forward multi-year simulations to report exact historical **Win Rate %**, **Profit Factor**, and **Alpha vs Buy-and-Hold**.
- **🏛️ Fundamental Valuation & Safety Filter**:
  - Fetches live **Stock P/E vs Sector P/E**, Market Capitalization, Free Float, and Impact Cost liquidity grades directly from NSE.
- **⚡ F&O Derivative Intelligence**: Real-time Futures OI Buildup (`Long Buildup`, `Short Covering`, `Short Buildup`, `Long Unwinding`), Stock Option Chain PCR, Max Pain Strike, Call Wall Resistance, and Put Wall Support. Gracefully handles cash-only stocks.
- **📦 Institutional Delivery Spikes**: Identifies true institutional accumulation (>50% delivery volume) vs speculative retail day-trading churn.
- **🕯️ Quant Technicals**: Canonical Supertrend (10, 3), Bollinger Bands Volatility Squeeze Breakout, 20/50/200 EMAs, 14-day RSI, ATR Volatility, and Floor Pivots.
- **🎯 Relative Strength (RS vs NIFTY 50)**: Benchmarks 5-day and 20-day returns against NIFTY 50 to isolate institutional leaders vs market laggards.
- **📅 Multi-Timeframe (MTF) Alignment**: Evaluates Weekly Macro 20/50 EMA trends against Daily action to eliminate counter-trend traps.
- **📰 Company News & Breaking Catalysts**: Scans live Google News RSS for earnings beats, order wins, acquisitions, and regulatory probes.



---

## 📊 How to Read the Live Dashboard

| Metric | Meaning & Trading Signal |
| :--- | :--- |
| **PCR > 1.25** | **Bullish** — Put writers dominate; strong underlying support. |
| **PCR < 0.80** | **Bearish** — Call writers dominate; heavy resistance. |
| **Max Pain** | The strike price towards which price tends to gravitate near expiry. |
| **Support Strike** | The strike with the highest Put OI (floor price). |
| **Resistance Strike**| The strike with the highest Call OI (ceiling price). |
| **Long Buildup** | Price Up + OI Up (Fresh buying momentum). |
| **Short Covering** | Price Up + OI Down (Call writers exiting positions — fast rally). |

---

## 💡 Live Execution & Broker APIs

When you are ready to switch from Paper Trading to real automated order execution:
- **Dhan Trading API (Free)**: Dhan provides 100% free **Order Execution** APIs for account holders (zero monthly charge for placing/canceling orders).
- **Dhan Data API (₹499/mo)**: Dhan charges ₹499/mo for exchange-streamed live tick data feeds.
- **100% Free Built-in Alternative**: This project uses free live feeds directly (Yahoo Finance real-time 1m chart for MCX Crude Oil, and NSE web scraper for NIFTY 50), so you **do not need to pay the ₹499/mo fee** to run live algo trading, signals, and paper execution!
- You can plug in `dhanhq` python library inside [`paper_trader.py`](paper_trader.py) to send orders straight to your Dhan trading account using the free Trading API.
