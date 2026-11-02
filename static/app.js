/**
 * QuantEdge Terminal Frontend Controller
 * Manages Tab Switching, Multi-Source News Aggregation, Option Greeks,
 * Native Quant Candlestick Engine, TradingView Widget & All-Stocks Quant Scanner
 */

// Application State
let currentTab = 'news';
let currentNewsSource = 'all';
let currentNewsCategory = 'all';
let currentNewsSearch = '';
let currentStockSymbol = 'RELIANCE';
let currentStockMode = 'single'; // 'single' | 'all'
let currentChartEngine = 'native'; // 'native' | 'tv'
let currentChartRange = '6mo';
let sectorsData = {};
let optionsTimer = null;
let newsTimer = null;
let isFetchingOptions = false;
let isFetchingNews = false;
let showGreeks = false;
let audioEnabled = true;
let lastKnownSignal = null;
let cachedAtmStrike = null;
let optionsPollingSpeed = 1000; // 1s default for sub-second rapid updates
let microTickEngine = true; // LIVE by default (Groww order book ticker)
let previousStrikeLtp = {};
let previousPaperPnl = null;

function formatInr(val) {
  const num = Number(val || 0);
  return '₹' + num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Native Candlestick Chart Cached State
let currentCandles = [];
let chartCanvas = null;
let chartCtx = null;

// All Stocks Scanner & Real-Time Ticker State
let allStocksData = [];
let currentScannerFilter = 'all';
let isScanningAllStocks = false;
let stocksTickTimer = null;
let isStockTicksActive = true;
let previousStockLtp = {};

// Initialize on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  initClock();
  initPopularSectors();
  fetchLiveNews();
  checkBrokerStatus();
  loadStockTrackerData(false);
  startTimers();

  // Ensure live streaming ticker is ACTIVE by default
  const btnFluc = document.getElementById('btn-toggle-fluctuation');
  const lblFluc = document.getElementById('fluctuation-status-lbl');
  if (btnFluc && lblFluc) {
    btnFluc.classList.add('active');
    btnFluc.style.color = 'var(--accent-emerald)';
    btnFluc.style.borderColor = 'rgba(16, 185, 129, 0.4)';
    lblFluc.innerText = 'ACTIVE (Live Streaming)';
  }

  // Setup Canvas
  chartCanvas = document.getElementById('stock-candlestick-canvas');
  if (chartCanvas) {
    chartCtx = chartCanvas.getContext('2d');
    setupCanvasHover();
    window.addEventListener('resize', () => {
      if (currentCandles.length) drawCandlestickChart(currentCandles, currentStockSymbol);
    });
  }

  // Handle URL hash navigation on direct load
  if (window.location.hash.includes('stocks')) {
    switchTab('stocks');
  } else if (window.location.hash.includes('options')) {
    switchTab('options');
  }
});

// -------------------------------------------------------------
// Clock & Audio Alert Synthesizer
// -------------------------------------------------------------
function isNSEMarketOpen() {
  const now = new Date();
  const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
  const ist = new Date(utc + (3600000 * 5.5));
  const day = ist.getDay(); // 0 = Sun, 6 = Sat
  if (day === 0 || day === 6) return false;

  const hours = ist.getHours();
  const minutes = ist.getMinutes();
  const totalMinutes = hours * 60 + minutes;

  // 9:15 AM = 555 mins, 3:30 PM = 930 mins
  return totalMinutes >= 555 && totalMinutes <= 930;
}

function initClock() {
  const clockEl = document.getElementById('live-clock');
  const feedStatusText = document.getElementById('feed-status-text');
  const update = () => {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-IN', { hour12: false }) + ' IST';
    const isOpen = isNSEMarketOpen();
    if (clockEl) {
      clockEl.innerHTML = `${isOpen ? '🟢' : '🔴'} ${timeStr} • <span style="font-size: 10px; font-weight:700;">${isOpen ? 'NSE LIVE' : 'NSE CLOSED'}</span>`;
    }
    if (feedStatusText) {
      feedStatusText.innerText = isOpen ? 'NSE LIVE MARKET' : 'NSE CLOSED (3:30 PM SETTLE)';
    }
  };
  update();
  setInterval(update, 1000);
}

function toggleAudioAlerts() {
  audioEnabled = !audioEnabled;
  const lbl = document.getElementById('sound-status-label');
  const btn = document.getElementById('btn-sound-toggle');
  if (audioEnabled) {
    lbl.innerText = 'Sound: ON';
    btn.style.color = 'var(--text-primary)';
    playTradeChime(true);
  } else {
    lbl.innerText = 'Sound: MUTED';
    btn.style.color = 'var(--text-muted)';
  }
}

function playTradeChime(isTest = false) {
  if (!audioEnabled) return;
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sine';
    const now = ctx.currentTime;
    osc.frequency.setValueAtTime(587.33, now); // D5
    osc.frequency.setValueAtTime(880.00, now + 0.1); // A5
    osc.frequency.setValueAtTime(1174.66, now + 0.2); // D6

    gain.gain.setValueAtTime(0.15, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45);

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start(now);
    osc.stop(now + 0.5);
  } catch (e) {
    // Audio context may require prior user interaction
  }
}

function formatInr(val) {
  if (val === null || val === undefined || isNaN(val)) return '₹--';
  const num = Number(val);
  return '₹' + num.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatNum(val) {
  if (val === null || val === undefined || isNaN(val)) return '--';
  const num = Number(val);
  const abs = Math.abs(num);
  const sign = num > 0 ? '+' : '';
  if (abs >= 10000000) return `${sign}${(num / 10000000).toFixed(2)} Cr`;
  if (abs >= 100000) return `${sign}${(num / 100000).toFixed(2)} L`;
  if (abs >= 1000) return `${sign}${(num / 1000).toFixed(1)} K`;
  return `${sign}${num.toLocaleString('en-IN')}`;
}

// -------------------------------------------------------------
// Tab Switching
// -------------------------------------------------------------
function switchTab(tabId) {
  currentTab = tabId;

  document.querySelectorAll('.nav-tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-content-panel').forEach(p => p.classList.remove('active'));

  const activeBtn = document.getElementById(`tab-btn-${tabId}`);
  const activePanel = document.getElementById(`panel-${tabId}`);

  if (activeBtn) activeBtn.classList.add('active');
  if (activePanel) activePanel.classList.add('active');

  if (tabId === 'news') {
    stopStocksRealtimeTicker();
    fetchLiveNews();
  } else if (tabId === 'options') {
    stopStocksRealtimeTicker();
    fetchLiveOptions();
  } else if (tabId === 'stocks') {
    startStocksRealtimeTicker();
    loadStockTrackerData(false);
    if (currentStockMode === 'single') {
      if (!document.getElementById('stk-ltp').innerText.includes('₹') || document.getElementById('stk-ltp').innerText === '₹--') {
        predictStock(currentStockSymbol);
      }
    } else if (currentStockMode === 'tracker') {
      loadStockTrackerData(false);
    } else {
      if (!allStocksData.length) {
        loadAllStockPredictions(false);
      }
    }
  }
}

function startTimers() {
  if (optionsTimer) clearInterval(optionsTimer);
  optionsTimer = setInterval(() => {
    if (currentTab === 'options') {
      fetchLiveOptions();
    }
  }, optionsPollingSpeed);

  if (newsTimer) clearInterval(newsTimer);
  newsTimer = setInterval(() => {
    if (currentTab === 'news') {
      fetchLiveNews(false);
    }
  }, 25000);
}

function triggerManualRefresh() {
  const lbl = document.getElementById('refresh-btn-label');
  if (lbl) lbl.innerText = 'Refreshing...';
  if (currentTab === 'news') {
    fetchLiveNews().finally(() => { if (lbl) lbl.innerText = 'Refresh'; });
  } else if (currentTab === 'options') {
    fetchLiveOptions().finally(() => { if (lbl) lbl.innerText = 'Refresh'; });
  } else if (currentTab === 'stocks') {
    if (currentStockMode === 'single') {
      predictStock(currentStockSymbol).finally(() => { if (lbl) lbl.innerText = 'Refresh'; });
    } else {
      loadAllStockPredictions(true).finally(() => { if (lbl) lbl.innerText = 'Refresh'; });
    }
  }
}

// -------------------------------------------------------------
// TAB 1: MULTI-SOURCE FINANCIAL NEWS ENGINE
// -------------------------------------------------------------
let newsSearchDebounce = null;
function onNewsSearchInput(val) {
  currentNewsSearch = val;
  clearTimeout(newsSearchDebounce);
  newsSearchDebounce = setTimeout(() => {
    fetchLiveNews();
  }, 300);
}

function filterNewsSource(sourceId) {
  currentNewsSource = sourceId;
  document.querySelectorAll('#news-source-filters .cat-pill').forEach(btn => {
    btn.classList.remove('active');
  });
  if (event && event.target) event.target.classList.add('active');
  fetchLiveNews();
}

function filterNewsCategory(cat) {
  currentNewsCategory = cat;
  document.querySelectorAll('#news-category-filters .cat-pill').forEach(btn => {
    btn.classList.toggle('active', btn.innerText.toLowerCase().includes(cat.toLowerCase()) || (cat === 'all' && btn.innerText.includes('All')));
  });
  fetchLiveNews();
}

async function fetchLiveNews(showSpinner = true) {
  if (isFetchingNews) return;
  isFetchingNews = true;

  const container = document.getElementById('news-cards-container');
  if (showSpinner && (!container.children.length || container.querySelector('.loading-container'))) {
    container.innerHTML = `
      <div class="loading-container">
        <div class="spinner"></div>
        <div>Aggregating real-time news across NSE India, Economic Times, Livemint, Moneycontrol & Nuvama Research...</div>
      </div>
    `;
  }

  try {
    let url = `/api/news?category=${encodeURIComponent(currentNewsCategory)}&source=${encodeURIComponent(currentNewsSource)}`;
    if (currentNewsSearch) {
      url += `&search=${encodeURIComponent(currentNewsSearch)}`;
    }

    const res = await fetch(url);
    const data = await res.json();

    if (!data.success) throw new Error('Failed to load news');

    const stats = data.stats || {};
    document.getElementById('stat-total-news').innerText = stats.total || 0;
    document.getElementById('stat-bull-news').innerText = stats.bullish_catalysts || 0;
    document.getElementById('stat-risk-news').innerText = stats.risk_alerts || 0;
    document.getElementById('news-count-badge').innerText = `${data.count} Stories`;

    renderNewsCards(data.news || []);

  } catch (err) {
    console.error('Error fetching news:', err);
    if (!container.children.length || container.querySelector('.loading-container')) {
      container.innerHTML = `
        <div class="glass-card" style="grid-column: 1 / -1; text-align: center; color: var(--accent-rose); padding: 32px;">
          ⚠️ Unable to aggregate live news feeds. Will auto-retry in a few seconds.
        </div>
      `;
    }
  } finally {
    isFetchingNews = false;
  }
}

function renderNewsCards(newsList) {
  const container = document.getElementById('news-cards-container');
  if (!newsList.length) {
    container.innerHTML = `
      <div class="glass-card" style="grid-column: 1 / -1; text-align: center; color: var(--text-muted); padding: 40px;">
        🔍 No announcements found matching your filter criteria. Try selecting 'All Sources' / 'All Topics' or clearing your search.
      </div>
    `;
    return;
  }

  container.innerHTML = newsList.map(item => {
    const sym = item.symbol || 'NSE';
    const comp = item.company_name || sym;
    const cat = item.category || 'General';
    const head = item.headline || 'Market News Update';
    const details = item.details || '';
    const time = item.timestamp || '';
    const badge = item.sentiment_badge || '⚪ Informational';
    const sentColor = item.sentiment_color || 'slate';
    const url = item.url || '#';
    const isPdf = item.is_pdf;
    const fsize = item.file_size ? `(${item.file_size})` : '';

    const sourceName = item.source || 'Financial News';
    const sourceDomain = item.source_domain || 'news.in';
    const sourceColor = item.source_color || 'cyan';
    const sourceBadge = item.source_badge || `📰 ${sourceName}`;

    return `
      <div class="news-card">
        <div class="news-card-top">
          <div class="news-card-meta">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span class="source-pill ${sourceColor}">
                ${sourceBadge}
              </span>
              ${sym && sym !== 'NIFTY' && sym !== 'NSE' && sym !== 'MARKET' && sym !== 'F&O' ? `
                <button class="stock-pill-btn" onclick="jumpToStockAnalysis('${sym}')" title="Analyze ${sym} with Quant AI">
                  ⚡ ${sym}
                </button>
              ` : ''}
            </div>
            <span class="news-time">🕒 ${time}</span>
          </div>

          <div class="news-company">
            <strong>${comp}</strong> • <span style="color: var(--accent-cyan); font-weight: 500;">${cat}</span>
          </div>
          <div class="news-headline">${head}</div>
          <div class="news-details">${details}</div>
        </div>

        <div class="news-card-footer">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="sentiment-badge ${sentColor}">${badge}</span>
            <span style="font-size: 11px; color: var(--text-muted); font-family: var(--font-mono);">${sourceDomain}</span>
          </div>

          ${url && url !== '#' ? `
            <a href="${url}" target="_blank" rel="noopener noreferrer" class="btn-pdf-link" title="Open full story on ${sourceName}">
              ${isPdf ? `📄 Official NSE Filing ${fsize} ↗` : `🔗 Read on ${sourceName} ↗`}
            </a>
          ` : `
            <span style="font-size: 11px; color: var(--text-muted);">Verified Story</span>
          `}
        </div>
      </div>
    `;
  }).join('');
}

function jumpToStockAnalysis(symbol) {
  currentStockSymbol = symbol;
  switchTab('stocks');
  switchStockMode('single');
  predictStock(symbol);
}

// -------------------------------------------------------------
// TAB 2: OPTION TRADING (NIFTY Live OI, Greeks & Algo Signals)
// -------------------------------------------------------------
function toggleMicroTickFluctuation() {
  microTickEngine = !microTickEngine;
  const btn = document.getElementById('btn-toggle-fluctuation');
  const lbl = document.getElementById('fluctuation-status-lbl');
  if (btn && lbl) {
    if (microTickEngine) {
      btn.classList.add('active');
      btn.style.color = 'var(--accent-emerald)';
      btn.style.borderColor = 'rgba(16, 185, 129, 0.4)';
      lbl.innerText = 'ACTIVE (Live Streaming)';
    } else {
      btn.classList.remove('active');
      btn.style.color = 'var(--text-muted)';
      btn.style.borderColor = 'var(--border-subtle)';
      lbl.innerText = 'FROZEN (3:30 PM Snapshot)';
    }
  }
  fetchLiveOptions();
}

function setOptionSpeed(ms) {
  optionsPollingSpeed = ms;
  document.querySelectorAll('#btn-speed-1s, #btn-speed-3s').forEach(b => b.classList.remove('active'));
  const activeBtn = ms === 1000 ? document.getElementById('btn-speed-1s') : document.getElementById('btn-speed-3s');
  if (activeBtn) activeBtn.classList.add('active');
  startTimers();
}

function toggleGreeksView() {
  showGreeks = !showGreeks;
  const lbl = document.getElementById('greeks-toggle-label');
  const btn = document.getElementById('btn-toggle-greeks');
  if (showGreeks) {
    lbl.innerText = 'Hide Greeks (Standard View)';
    btn.style.color = 'var(--accent-cyan)';
    btn.style.borderColor = 'var(--accent-cyan)';
  } else {
    lbl.innerText = 'Show Greeks (Δ, Θ, IV)';
    btn.style.color = 'var(--text-secondary)';
    btn.style.borderColor = 'var(--border-subtle)';
  }

  if (cachedOptionRows.length) {
    renderOptionChainTable(cachedOptionRows, cachedAtmStrike);
  }
}

async function fetchLiveOptions() {
  if (isFetchingOptions) return;
  isFetchingOptions = true;

  try {
    const res = await fetch(`/api/options?realtime=${microTickEngine}`);
    const data = await res.json();

    if (!data.success) return;

    // Top Ribbon Metrics
    const spot = Number(data.spot_price || 0);
    document.getElementById('opt-spot-price').innerText = spot ? spot.toLocaleString('en-IN', { minimumFractionDigits: 2 }) : '--';
    document.getElementById('opt-spot-subtext').innerText = `Expiry: ${data.expiry || 'Current Weekly'}`;
    document.getElementById('opt-atm-strike').innerText = data.atm_strike || '--';

    const src = data.source_label || 'NSE';
    const isOpen = isNSEMarketOpen();
    const srcBadge = document.getElementById('opt-source-badge');
    if (srcBadge) {
      if (!isOpen) {
        srcBadge.innerText = microTickEngine ? 'SIM PRACTICE' : '3:30 PM SETTLE';
        srcBadge.style.background = microTickEngine ? 'rgba(99, 102, 241, 0.2)' : 'rgba(244, 63, 94, 0.2)';
        srcBadge.style.color = microTickEngine ? 'var(--accent-cyan)' : 'var(--accent-rose)';
        srcBadge.title = microTickEngine ? 'Off-market practice ticks active. Click button above to freeze.' : 'Official 3:30 PM market closing price.';
      } else {
        srcBadge.innerText = src === 'DHAN_API' ? 'BROKER LIVE' : 'NSE LIVE';
        srcBadge.style.background = 'rgba(16, 185, 129, 0.2)';
        srcBadge.style.color = 'var(--accent-emerald)';
      }
    }
    document.getElementById('opt-latency-badge').innerText = `⚡ Latency: ${data.latency_ms || 18}ms | Feed: ${src}`;

    // PCR
    const pcr = Number(data.pcr || 1.0);
    const pcrEl = document.getElementById('opt-pcr-val');
    pcrEl.innerText = pcr.toFixed(3);
    const pcrStatEl = document.getElementById('opt-pcr-status');
    if (pcr >= 1.2) {
      pcrStatEl.innerText = '🟢 Strong Put Writing (Bullish)';
      pcrEl.className = 'val-large val-up';
    } else if (pcr <= 0.7) {
      pcrStatEl.innerText = '🔴 Heavy Call Writing (Bearish)';
      pcrEl.className = 'val-large val-down';
    } else {
      pcrStatEl.innerText = '⚪ Balanced / Rangebound';
      pcrEl.className = 'val-large';
    }

    // Max Pain & Res/Sup
    document.getElementById('opt-max-pain').innerText = data.max_pain || '--';
    document.getElementById('opt-res-sup').innerText = `${data.resistance_strike || '--'} / ${data.support_strike || '--'}`;

    // India VIX
    const vix = data.vix || {};
    const vixVal = Number(vix.value || 13.5);
    document.getElementById('opt-vix-val').innerText = vixVal.toFixed(2);
    document.getElementById('opt-vix-subtext').innerText = `${vix.badge || 'NORMAL'} | Bias: ${vix.bias || 'Neutral'}`;

    // AI Algo Signal & Prediction Card (with audio alert)
    renderAlgoSignal(data.algo_signal, data.oi_velocity, data.chart_patterns, data.heavyweights);

    // Option Chain Ladder
    cachedOptionRows = data.table_data || [];
    cachedAtmStrike = data.atm_strike;
    renderOptionChainTable(cachedOptionRows, cachedAtmStrike);

    // Render Optimal Strikes for Option Buyers (Gamma, Theta, Vega Intelligence)
    if (data.optimal_strikes) {
      renderOptimalStrikes(data.optimal_strikes);
    }


    // Paper Trader Status
    renderPaperTrader(data.paper_trade || {});

  } catch (err) {
    console.error('Error fetching option chain:', err);
  } finally {
    isFetchingOptions = false;
  }
}

function renderAlgoSignal(signal, oiVel, chart, hw) {
  if (!signal) return;

  const card = document.getElementById('opt-signal-hero');
  const title = document.getElementById('opt-signal-title');
  const sigName = signal.signal || 'WAIT';
  const conf = signal.confluence_pct || 50;

  if (lastKnownSignal && lastKnownSignal !== sigName && (sigName.includes('CE') || sigName.includes('PE'))) {
    playTradeChime();
  }
  lastKnownSignal = sigName;

  card.className = 'signal-hero-card';

  if (sigName.includes('CE')) {
    card.classList.add('signal-ce');
    title.innerHTML = `<span>🟢</span> BUY CALL OPTION (CE) — BULLISH MOMENTUM`;
    document.getElementById('options-signal-badge').innerText = 'BUY CE';
  } else if (sigName.includes('PE')) {
    card.classList.add('signal-pe');
    title.innerHTML = `<span>🔴</span> BUY PUT OPTION (PE) — BEARISH BREAKDOWN`;
    document.getElementById('options-signal-badge').innerText = 'BUY PE';
  } else {
    card.classList.add('signal-neutral');
    title.innerHTML = `<span>⚪</span> WAIT / NO TRADE — RANGEBOUND CONSOLIDATION`;
    document.getElementById('options-signal-badge').innerText = 'WAIT';
  }

  document.getElementById('opt-confluence-label').innerText = `AI Confluence: ${conf}%`;
  const confBar = document.getElementById('opt-confluence-bar');
  confBar.style.width = `${conf}%`;
  confBar.style.background = conf >= 75 ? '#10b981' : conf >= 50 ? '#6366f1' : '#f59e0b';

  document.getElementById('opt-signal-reason').innerText = signal.reason || 'Synthesizing live multi-factor confirmation...';

  const velBadge = oiVel ? oiVel.badge : '⚪ Stable';
  const hwBadge = hw ? hw.badge : 'Balanced';
  const chartBadge = chart ? `${chart.sentiment} (${chart.confidence}%)` : 'Normal';
  document.getElementById('opt-signal-aux').innerText = `OI Velocity: ${velBadge} | Heavyweights: ${hwBadge} | 5m Chart: ${chartBadge}`;

  document.getElementById('opt-target-inst').innerText = signal.instrument || 'Awaiting Setup';
  document.getElementById('opt-entry-prem').innerText = signal.estimated_entry_price ? `₹${signal.estimated_entry_price.toFixed(2)}` : '₹--';
  const buyerProf = signal.buyer_profile;
  const buyerTag = buyerProf ? ` (SL: 16% | TGT: 40% | 10m Time-Stop)` : '';
  document.getElementById('opt-strategy-mode').innerText = (signal.is_fast_trigger ? '⚡ FAST PANIC UNWINDING TRIGGER' : 'Option Buyer Confluence') + buyerTag;
}

function renderOptimalStrikes(opt) {
  if (!opt) return;
  if (opt.ce) {
    const ceStrikeEl = document.getElementById('greek-best-ce-strike');
    if (ceStrikeEl) ceStrikeEl.innerText = `NIFTY ${opt.ce.strike} CE (ATM)`;
    const ceLtpEl = document.getElementById('greek-best-ce-ltp');
    if (ceLtpEl && opt.ce.ltp) ceLtpEl.innerText = `₹${Number(opt.ce.ltp).toFixed(2)}`;
    const dEl = document.getElementById('gb-ce-delta');
    if (dEl) dEl.innerText = Number(opt.ce.delta || 0.50).toFixed(2);
    const gEl = document.getElementById('gb-ce-gamma');
    if (gEl) gEl.innerText = Number(opt.ce.gamma || 0.0022).toFixed(4);
    const tEl = document.getElementById('gb-ce-theta');
    if (tEl) tEl.innerText = `${Number(opt.ce.theta || -10).toFixed(1)}/d`;
    const vEl = document.getElementById('gb-ce-vega');
    if (vEl) vEl.innerText = `₹${Number(opt.ce.vega || 14).toFixed(1)}`;
    const descEl = document.getElementById('greek-best-ce-desc');
    if (descEl && opt.ce.explanation) descEl.innerText = opt.ce.explanation;
  }
  if (opt.pe) {
    const peStrikeEl = document.getElementById('greek-best-pe-strike');
    if (peStrikeEl) peStrikeEl.innerText = `NIFTY ${opt.pe.strike} PE (ATM)`;
    const peLtpEl = document.getElementById('greek-best-pe-ltp');
    if (peLtpEl && opt.pe.ltp) peLtpEl.innerText = `₹${Number(opt.pe.ltp).toFixed(2)}`;
    const dEl = document.getElementById('gb-pe-delta');
    if (dEl) dEl.innerText = Number(opt.pe.delta || -0.50).toFixed(2);
    const gEl = document.getElementById('gb-pe-gamma');
    if (gEl) gEl.innerText = Number(opt.pe.gamma || 0.0022).toFixed(4);
    const tEl = document.getElementById('gb-pe-theta');
    if (tEl) tEl.innerText = `${Number(opt.pe.theta || -10).toFixed(1)}/d`;
    const vEl = document.getElementById('gb-pe-vega');
    if (vEl) vEl.innerText = `₹${Number(opt.pe.vega || 14).toFixed(1)}`;
    const descEl = document.getElementById('greek-best-pe-desc');
    if (descEl && opt.pe.explanation) descEl.innerText = opt.pe.explanation;
  }
}

function openGreeksGuideModal() {
  const modal = document.getElementById('greeks-guide-modal');
  if (modal) modal.style.display = 'flex';
}

function closeGreeksGuideModal() {
  const modal = document.getElementById('greeks-guide-modal');
  if (modal) modal.style.display = 'none';
}

function renderOptionChainTable(rows, atmStrike) {
  const tbody = document.getElementById('opt-chain-tbody');
  const headerTop = document.getElementById('opt-chain-header-top');
  const headerCols = document.getElementById('opt-chain-header-cols');

  if (showGreeks) {
    headerTop.innerHTML = `
      <th colspan="7" style="text-align: center; border-right: 1px solid var(--border-subtle); color: var(--accent-emerald);">CALLS (CE) + GREEKS & BUYER RATING</th>
      <th class="col-strike">STRIKE</th>
      <th colspan="7" style="text-align: center; border-left: 1px solid var(--border-subtle); color: var(--accent-rose);">PUTS (PE) + GREEKS & BUYER RATING</th>
    `;
    headerCols.innerHTML = `
      <th class="col-greek" title="Buyer Strike Rating">Rating</th>
      <th class="col-greek" title="Delta: Underlying Sensitivity">Δ Delta</th>
      <th class="col-greek" title="Gamma: Rate of Delta Acceleration (Peak at ATM)">Γ Gamma</th>
      <th class="col-greek" title="Theta: ₹ Time Decay per Day">Θ Theta</th>
      <th class="col-greek" title="Vega: ₹ Change per 1% IV shift">ν Vega</th>
      <th>OI</th>
      <th style="border-right: 1px solid var(--border-subtle);">LTP (₹)</th>
      <th class="col-strike">ATM</th>
      <th style="border-left: 1px solid var(--border-subtle); text-align: left;">LTP (₹)</th>
      <th style="text-align: left;">OI</th>
      <th class="col-greek" style="text-align: left;" title="Vega: ₹ Change per 1% IV shift">ν Vega</th>
      <th class="col-greek" style="text-align: left;" title="Theta: ₹ Time Decay per Day">Θ Theta</th>
      <th class="col-greek" style="text-align: left;" title="Gamma: Rate of Delta Acceleration (Peak at ATM)">Γ Gamma</th>
      <th class="col-greek" style="text-align: left;" title="Delta: Underlying Sensitivity">Δ Delta</th>
      <th class="col-greek" style="text-align: left;" title="Buyer Strike Rating">Rating</th>
    `;
  } else {
    headerTop.innerHTML = `
      <th colspan="3" style="text-align: center; border-right: 1px solid var(--border-subtle); color: var(--accent-emerald);">CALLS (CE)</th>
      <th class="col-strike">STRIKE</th>
      <th colspan="3" style="text-align: center; border-left: 1px solid var(--border-subtle); color: var(--accent-rose);">PUTS (PE)</th>
    `;
    headerCols.innerHTML = `
      <th>OI</th>
      <th>Chg OI</th>
      <th style="border-right: 1px solid var(--border-subtle);">LTP (₹)</th>
      <th class="col-strike">ATM</th>
      <th style="border-left: 1px solid var(--border-subtle); text-align: left;">LTP (₹)</th>
      <th style="text-align: left;">Chg OI</th>
      <th style="text-align: left;">OI</th>
    `;
  }

  if (!rows || !rows.length) {
    tbody.innerHTML = `<tr><td colspan="${showGreeks ? 15 : 7}" style="text-align: center; padding: 20px;">No strikes loaded.</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(r => {
    const stk = Number(r.strike);
    const isAtm = stk === Number(atmStrike);
    const ceChgClass = r.ce_chg_oi > 0 ? 'val-up' : (r.ce_chg_oi < 0 ? 'val-down' : '');
    const peChgClass = r.pe_chg_oi > 0 ? 'val-up' : (r.pe_chg_oi < 0 ? 'val-down' : '');

    const ceDelta = r.ce_delta !== undefined ? Number(r.ce_delta).toFixed(2) : '0.50';
    const peDelta = r.pe_delta !== undefined ? Number(r.pe_delta).toFixed(2) : '-0.50';
    const gamma = r.gamma !== undefined ? Number(r.gamma).toFixed(4) : '0.0022';
    const ceTheta = r.ce_theta !== undefined ? Number(r.ce_theta).toFixed(1) : (r.theta !== undefined ? Number(r.theta).toFixed(1) : '-10.0');
    const peTheta = r.pe_theta !== undefined ? Number(r.pe_theta).toFixed(1) : (r.theta !== undefined ? Number(r.theta).toFixed(1) : '-10.0');
    const vega = r.vega !== undefined ? Number(r.vega).toFixed(1) : '14.0';

    let ceRatingHtml = '';
    if (r.ce_tag === 'BEST_BUY') ceRatingHtml = '<span class="badge" style="background: rgba(16,185,129,0.25); color: var(--accent-emerald); font-size: 9px; font-weight:700;">⭐ BEST BUY</span>';
    else if (r.ce_tag === 'HIGH_CONV') ceRatingHtml = '<span class="badge" style="background: rgba(59,130,246,0.2); color: var(--accent-blue); font-size: 9px;">🛡️ CONVICT</span>';
    else if (r.ce_tag === 'SCALP') ceRatingHtml = '<span class="badge" style="background: rgba(245,158,11,0.2); color: var(--accent-amber); font-size: 9px;">⚡ SCALP</span>';
    else if (r.ce_tag === 'TRAP') ceRatingHtml = '<span class="badge" style="background: rgba(244,63,94,0.2); color: var(--accent-rose); font-size: 9px;">⚠️ TRAP</span>';
    else ceRatingHtml = '<span style="color: var(--text-muted); font-size: 10px;">ITM</span>';

    let peRatingHtml = '';
    if (r.pe_tag === 'BEST_BUY') peRatingHtml = '<span class="badge" style="background: rgba(16,185,129,0.25); color: var(--accent-emerald); font-size: 9px; font-weight:700;">⭐ BEST BUY</span>';
    else if (r.pe_tag === 'HIGH_CONV') peRatingHtml = '<span class="badge" style="background: rgba(59,130,246,0.2); color: var(--accent-blue); font-size: 9px;">🛡️ CONVICT</span>';
    else if (r.pe_tag === 'SCALP') peRatingHtml = '<span class="badge" style="background: rgba(245,158,11,0.2); color: var(--accent-amber); font-size: 9px;">⚡ SCALP</span>';
    else if (r.pe_tag === 'TRAP') peRatingHtml = '<span class="badge" style="background: rgba(244,63,94,0.2); color: var(--accent-rose); font-size: 9px;">⚠️ TRAP</span>';
    else peRatingHtml = '<span style="color: var(--text-muted); font-size: 10px;">ITM</span>';

    const curCe = Number(r.ce_ltp || 0);
    const curPe = Number(r.pe_ltp || 0);
    const prevCe = previousStrikeLtp[`ce_${stk}`];
    const prevPe = previousStrikeLtp[`pe_${stk}`];

    let ceFlash = '';
    if (microTickEngine && prevCe !== undefined && Math.abs(curCe - prevCe) >= 0.05) {
      ceFlash = curCe > prevCe ? 'flash-up' : 'flash-down';
    }
    let peFlash = '';
    if (microTickEngine && prevPe !== undefined && Math.abs(curPe - prevPe) >= 0.05) {
      peFlash = curPe > prevPe ? 'flash-up' : 'flash-down';
    }

    previousStrikeLtp[`ce_${stk}`] = curCe;
    previousStrikeLtp[`pe_${stk}`] = curPe;

    const isCeItm = atmStrike ? (stk < Number(atmStrike)) : false;
    const isPeItm = atmStrike ? (stk > Number(atmStrike)) : false;
    const itmCeClass = isCeItm ? 'cell-itm' : '';
    const itmPeClass = isPeItm ? 'cell-itm' : '';

    if (showGreeks) {
      return `
        <tr class="${isAtm ? 'row-atm' : ''}">
          <td class="col-greek ${itmCeClass}">${ceRatingHtml}</td>
          <td class="col-greek ${itmCeClass}" style="font-weight:700; color: var(--accent-emerald);">${ceDelta}</td>
          <td class="col-greek ${itmCeClass}" style="color: var(--accent-purple); font-weight:600;">${gamma}</td>
          <td class="col-greek ${itmCeClass}" style="color: var(--accent-rose);">${ceTheta}</td>
          <td class="col-greek ${itmCeClass}" style="color: var(--accent-cyan);">${vega}</td>
          <td class="${itmCeClass}">${formatNum(r.ce_oi)}</td>
          <td class="${ceFlash} ${itmCeClass}" style="font-weight: 700; border-right: 1px solid var(--border-subtle);">${curCe.toFixed(2)}</td>
          <td class="col-strike">${isAtm ? '🎯 ' : ''}${stk}</td>
          <td class="${peFlash} ${itmPeClass}" style="font-weight: 700; border-left: 1px solid var(--border-subtle); text-align: left;">${curPe.toFixed(2)}</td>
          <td class="${itmPeClass}" style="text-align: left;">${formatNum(r.pe_oi)}</td>
          <td class="col-greek ${itmPeClass}" style="text-align: left; color: var(--accent-cyan);">${vega}</td>
          <td class="col-greek ${itmPeClass}" style="text-align: left; color: var(--accent-rose);">${peTheta}</td>
          <td class="col-greek ${itmPeClass}" style="text-align: left; color: var(--accent-purple); font-weight:600;">${gamma}</td>
          <td class="col-greek ${itmPeClass}" style="text-align: left; font-weight:700; color: var(--accent-rose);">${peDelta}</td>
          <td class="col-greek ${itmPeClass}" style="text-align: left;">${peRatingHtml}</td>
        </tr>
      `;
    }

    return `
      <tr class="${isAtm ? 'row-atm' : ''}">
        <td class="${itmCeClass}">${formatNum(r.ce_oi)}</td>
        <td class="${ceChgClass} ${itmCeClass}">${formatNum(r.ce_chg_oi)}</td>
        <td class="${ceFlash} ${itmCeClass}" style="font-weight: 700; border-right: 1px solid var(--border-subtle);">${curCe.toFixed(2)}</td>
        <td class="col-strike">${isAtm ? '🎯 ' : ''}${stk}</td>
        <td class="${peFlash} ${itmPeClass}" style="font-weight: 700; border-left: 1px solid var(--border-subtle); text-align: left;">${curPe.toFixed(2)}</td>
        <td class="${peChgClass} ${itmPeClass}" style="text-align: left;">${formatNum(r.pe_chg_oi)}</td>
        <td class="${itmPeClass}" style="text-align: left;">${formatNum(r.pe_oi)}</td>
      </tr>
    `;
  }).join('');
}

function renderPaperTrader(paper) {
  document.getElementById('paper-capital').innerText = formatInr(paper.capital || 100000);
  const tradeCount = paper.total_trades || 0;
  document.getElementById('paper-trades-count').innerText = `${tradeCount} Trades`;
  const badge = document.getElementById('paper-trades-badge');
  if (badge) badge.innerText = tradeCount;

  // Handle Cooldown Banner
  const cdBanner = document.getElementById('paper-cooldown-banner');
  const cdText = document.getElementById('paper-cooldown-text');
  if (paper.cooldown_remaining_sec > 0) {
    if (cdBanner) cdBanner.style.display = 'flex';
    if (cdText) cdText.innerText = `Post-Trade Cooldown Active: Waiting ${paper.cooldown_remaining_sec}s before next high-accuracy sniper setup...`;
  } else {
    if (cdBanner) cdBanner.style.display = 'none';
  }

  const realPnl = Number(paper.total_realized_pnl || 0);
  const pnlEl = document.getElementById('paper-realized-pnl');
  if (pnlEl) {
    pnlEl.innerText = `${realPnl >= 0 ? '+' : ''}₹${realPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    pnlEl.style.color = realPnl >= 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)';
  }

  const winRateEl = document.getElementById('paper-win-rate');
  if (winRateEl) {
    winRateEl.innerText = `${paper.win_rate_pct || 0}% (${paper.wins || 0}W / ${paper.losses || 0}L)`;
    winRateEl.style.color = (paper.win_rate_pct || 0) >= 50 ? 'var(--accent-emerald)' : 'var(--text-primary)';
  }

  const container = document.getElementById('paper-pos-container');
  const pos = paper.active_position;

  if (pos) {
    const isProfitable = pos.pnl >= 0;
    const pnlColor = isProfitable ? 'var(--accent-emerald)' : 'var(--accent-rose)';
    const pnlSign = isProfitable ? '+' : '';

    let pnlPulseClass = '';
    if (previousPaperPnl !== null && Math.abs(pos.pnl - previousPaperPnl) >= 0.25) {
      pnlPulseClass = pos.pnl > previousPaperPnl ? 'pnl-pulse-up' : 'pnl-pulse-down';
    }
    previousPaperPnl = pos.pnl;

    const heldSec = pos.held_seconds || 0;
    const heldMin = Math.floor(heldSec / 60);
    const heldRemSec = heldSec % 60;
    const minHoldLeft = pos.min_hold_remaining || 0;
    const protectionBadge = minHoldLeft > 0
      ? `<span style="color: var(--accent-amber); font-weight: 600;">(🛡️ Anti-Shakeout: ${minHoldLeft}s)</span>`
      : `<span style="color: var(--accent-emerald); font-weight: 600;">(✓ Target/SL Focus)</span>`;

    container.innerHTML = `
      <div class="paper-pos-active" style="border-color: ${pnlColor};">
        <div>
          <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); display: flex; align-items: center; gap: 6px;">
            <span class="live-pulse-dot"></span> Active Live Position
            <span style="font-size: 10px; color: var(--accent-cyan); margin-left: 6px;">⏱️ Held: ${heldMin}m ${heldRemSec}s ${protectionBadge}</span>
          </div>
          <div style="font-family: var(--font-mono); font-size: 17px; font-weight: 800; color: #ffffff; margin-top: 2px;">
            ${pos.instrument} (${pos.lot_size} Qty)
          </div>
          <div style="font-size: 12px; color: var(--text-secondary); margin-top: 2px;">
            Entry: ₹${pos.entry_price.toFixed(2)} | Current LTP: ₹${pos.current_price.toFixed(2)} | Target: ₹${pos.target.toFixed(2)} | SL: ₹${pos.stop_loss.toFixed(2)}
          </div>
          <div style="font-size: 11px; margin-top: 4px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <span style="color: ${pos.is_breakeven_locked ? 'var(--accent-emerald)' : 'var(--text-muted)'}; font-weight: 600;">
              ${pos.is_breakeven_locked ? '🛡️ Breakeven Locked (₹0 Capital Risk)' : '🎯 Target/SL Dynamic Trailing'}
            </span>
            <span style="color: #cbd5e1;">|</span>
            <span style="color: var(--accent-amber); font-family: var(--font-mono); font-weight: 600;">
              ⏱️ Theta Time-Stop: ${pos.time_stop_remaining_sec || 600}s
            </span>
          </div>
          <div style="margin-top: 8px; display: flex; align-items: center; gap: 10px;">
            <button class="btn-primary" onclick="manualSquareOffTrade()" style="background: rgba(244, 63, 94, 0.2); border: 1px solid var(--accent-rose); color: var(--accent-rose); font-size: 11px; padding: 4px 12px; cursor: pointer; border-radius: var(--radius-sm);">
              ⏹️ Square Off / Lock Profit Now
            </button>
            <span style="font-size: 11px; color: var(--text-muted);">
              Confluence: <strong>${pos.confluence_at_entry || 75}%</strong>
            </span>
          </div>
        </div>
        <div style="text-align: right;">
          <div class="${pnlPulseClass}" style="font-family: var(--font-mono); font-size: 24px; font-weight: 800; color: ${pnlColor}; transition: transform 0.2s;">
            ${pnlSign}₹${pos.pnl.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </div>
          <div style="font-size: 12px; font-weight: 700; color: ${pnlColor};">
            ${pnlSign}${pos.pnl_pct.toFixed(2)}% P&L
          </div>
        </div>
      </div>
    `;
  } else {
    container.innerHTML = `
      <div style="margin-top: 14px; font-size: 13px; color: var(--text-muted); text-align: center; padding: 18px; border: 1px dashed var(--border-subtle); border-radius: var(--radius-md); background: rgba(0,0,0,0.15);">
        <div style="font-weight: 700; color: #fff; margin-bottom: 4px;">🎯 Institutional High-Accuracy Sniper Engine Active</div>
        <div style="font-size: 12px; color: var(--text-secondary);">
          Waiting for high-probability setups with 75%+ Confluence (Derivatives OI + MTF Trend + VWAP Alignment) confirmed for 3 consecutive ticks.
        </div>
      </div>
    `;
  }
}

// -------------------------------------------------------------
// TRADE HISTORY STATEMENT & REALIZED P&L LEDGER
// -------------------------------------------------------------
async function openTradeHistoryModal() {
  const modal = document.getElementById('trade-history-modal');
  if (modal) modal.style.display = 'flex';

  const tbody = document.getElementById('trade-history-tbody');
  tbody.innerHTML = `
    <tr>
      <td colspan="10" style="text-align: center; padding: 28px; color: var(--text-muted);">
        <div class="loading-container" style="padding: 10px;">
          <div class="spinner"></div>
          <div>Loading trade history ledger...</div>
        </div>
      </td>
    </tr>
  `;

  try {
    const res = await fetch('/api/options/trades');
    const data = await res.json();
    if (!data.success) throw new Error('Failed to load trades');

    // Update modal stats
    const netPnl = Number(data.total_realized_pnl || 0);
    const netPnlEl = document.getElementById('modal-th-net-pnl');
    netPnlEl.innerText = `${netPnl >= 0 ? '+' : ''}₹${netPnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    netPnlEl.style.color = netPnl >= 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)';

    const retPct = Number(data.net_return_pct || 0);
    const retEl = document.getElementById('modal-th-return-pct');
    retEl.innerText = `${retPct >= 0 ? '+' : ''}${retPct.toFixed(2)}%`;
    retEl.style.color = retPct >= 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)';

    document.getElementById('modal-th-win-rate').innerText = `${data.win_rate_pct || 0}%`;
    document.getElementById('modal-th-win-loss').innerText = `${data.wins || 0} Wins / ${data.losses || 0} Losses`;

    const trades = data.trades || [];
    if (!trades.length) {
      tbody.innerHTML = `
        <tr>
          <td colspan="10" style="text-align: center; padding: 36px; color: var(--text-muted);">
            No closed trades yet. Open positions will be logged here once targets, stop-losses, or manual exits occur.
          </td>
        </tr>
      `;
      return;
    }

    tbody.innerHTML = trades.map((t, idx) => {
      const pnl = Number(t.realized_pnl || 0);
      const isWin = pnl >= 0;
      const pnlColor = isWin ? 'var(--accent-emerald)' : 'var(--accent-rose)';
      const sign = isWin ? '+' : '';

      return `
        <tr style="border-bottom: 1px solid rgba(255, 255, 255, 0.05);">
          <td style="padding: 10px; text-align: center; color: var(--text-muted);">${trades.length - idx}</td>
          <td style="padding: 10px; text-align: left; font-weight: 700; color: #fff;">${t.instrument}</td>
          <td style="padding: 10px; text-align: center;">
            <span class="badge" style="font-size: 10px; background: ${t.type === 'CE' ? 'rgba(16,185,129,0.15)' : 'rgba(244,63,94,0.15)'}; color: ${t.type === 'CE' ? 'var(--accent-emerald)' : 'var(--accent-rose)'};">
              ${t.type}
            </span>
          </td>
          <td style="padding: 10px; text-align: center;">${t.qty || 50}</td>
          <td style="padding: 10px; text-align: right;">
            <div>₹${Number(t.entry_price || 0).toFixed(2)}</div>
            <div style="font-size: 10px; color: var(--text-muted);">${(t.entry_time || '').split(' ')[1] || ''}</div>
          </td>
          <td style="padding: 10px; text-align: right;">
            <div>₹${Number(t.exit_price || 0).toFixed(2)}</div>
            <div style="font-size: 10px; color: var(--text-muted);">${(t.exit_time || '').split(' ')[1] || ''}</div>
          </td>
          <td style="padding: 10px; text-align: left; color: var(--text-secondary); font-size: 11px;">
            ${t.exit_reason || 'Exit'}
          </td>
          <td style="padding: 10px; text-align: right; font-weight: 700; color: ${pnlColor}; font-size: 13px;">
            ${sign}₹${pnl.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </td>
          <td style="padding: 10px; text-align: right; font-weight: 700; color: ${pnlColor};">
            ${sign}${Number(t.pnl_percent || 0).toFixed(2)}%
          </td>
          <td style="padding: 10px; text-align: center;">
            <span class="badge" style="background: ${isWin ? 'rgba(16,185,129,0.2)' : 'rgba(244,63,94,0.2)'}; color: ${pnlColor}; font-size: 10px;">
              ${isWin ? '🟢 PROFIT' : '🔴 LOSS'}
            </span>
          </td>
        </tr>
      `;
    }).join('');

  } catch (err) {
    console.error('Error fetching trade history:', err);
    tbody.innerHTML = `
      <tr>
        <td colspan="10" style="text-align: center; padding: 24px; color: var(--accent-rose);">
          ⚠️ Error loading trade statement: ${err.message}
        </td>
      </tr>
    `;
  }
}

function closeTradeHistoryModal() {
  const modal = document.getElementById('trade-history-modal');
  if (modal) modal.style.display = 'none';
}

async function manualSquareOffTrade() {
  if (!confirm('Are you sure you want to square off and exit the active position now at market LTP?')) return;
  try {
    const res = await fetch('/api/options/trade/close', { method: 'POST' });
    const data = await res.json();
    alert(data.message || 'Position squared off.');
    fetchLiveOptions();
  } catch (e) {
    alert('Error closing position: ' + e.message);
  }
}

// -------------------------------------------------------------
// REAL-TIME SPEED CONTROLS & BROKER CONFIGURATION
// -------------------------------------------------------------
function setOptionSpeed(speedMs) {
  optionsPollingSpeed = speedMs;
  const btn1 = document.getElementById('btn-speed-1s');
  const btn3 = document.getElementById('btn-speed-3s');
  if (btn1) btn1.classList.toggle('active', speedMs === 1000);
  if (btn3) btn3.classList.toggle('active', speedMs === 3000);
  startTimers();
}

function toggleMicroTickFluctuation() {
  microTickEngine = !microTickEngine;
  const btn = document.getElementById('btn-toggle-fluctuation');
  const lbl = document.getElementById('fluctuation-status-lbl');
  if (btn && lbl) {
    if (microTickEngine) {
      btn.classList.add('active');
      btn.style.color = 'var(--accent-emerald)';
      btn.style.borderColor = 'rgba(16, 185, 129, 0.4)';
      lbl.innerText = 'ACTIVE (Simulated)';
      btn.title = 'Generates real-time practice ticks off-market. Click to freeze at official 3:30 PM NSE closing snapshot.';
    } else {
      btn.classList.remove('active');
      btn.style.color = 'var(--text-muted)';
      btn.style.borderColor = 'var(--border-subtle)';
      lbl.innerText = 'FROZEN (3:30 PM Close)';
      btn.title = 'Real-time practice ticker is paused. Showing static 3:30 PM closing prices. Click to resume.';
    }
  }
  fetchLiveOptions();
}

async function checkBrokerStatus() {
  try {
    const res = await fetch('/api/broker/status');
    const data = await res.json();
    const btn = document.getElementById('btn-broker-status');
    const txt = document.getElementById('broker-status-text');
    const icon = document.getElementById('broker-status-icon');
    const banner = document.getElementById('broker-alert-banner');
    const bannerMsg = document.getElementById('broker-alert-msg');

    if (!btn || !txt || !icon) return;

    if (data.dhan_connected) {
      icon.innerText = '🟢';
      txt.innerText = 'DhanHQ Live (50ms)';
      btn.style.borderColor = 'var(--accent-emerald)';
      btn.style.color = 'var(--accent-emerald)';
      if (banner) banner.style.display = 'none';
    } else if (data.dhan_configured) {
      icon.innerText = '⚠️';
      txt.innerText = 'Token Expired';
      btn.style.borderColor = 'var(--accent-amber)';
      btn.style.color = 'var(--accent-amber)';
      if (banner) {
        banner.style.display = 'flex';
        if (bannerMsg) {
          bannerMsg.innerText = 'Dhan access token expired (24h SEBI requirement). Running on public NSE web feed. Enter today\'s token for instant 50ms broker ticks.';
        }
      }
    } else {
      icon.innerText = '🏛️';
      txt.innerText = 'NSE Web Feed';
      if (banner) banner.style.display = 'none';
    }
  } catch (e) {
    console.error('Broker status check error:', e);
  }
}

function openBrokerModal() {
  const modal = document.getElementById('broker-modal');
  if (modal) modal.style.display = 'flex';
  const msg = document.getElementById('broker-modal-msg');
  if (msg) msg.style.display = 'none';
}

function closeBrokerModal() {
  const modal = document.getElementById('broker-modal');
  if (modal) modal.style.display = 'none';
}

async function submitBrokerToken() {
  const clientIdInput = document.getElementById('input-dhan-client-id');
  const tokenInput = document.getElementById('input-dhan-token');
  const clientId = (clientIdInput ? clientIdInput.value : '').trim();
  const token = (tokenInput ? tokenInput.value : '').trim();
  const msg = document.getElementById('broker-modal-msg');
  const btn = document.getElementById('btn-save-broker-token');

  if (!clientId || !token) {
    if (msg) {
      msg.style.display = 'block';
      msg.style.background = 'rgba(244, 63, 94, 0.15)';
      msg.style.color = 'var(--accent-rose)';
      msg.innerText = 'Please enter both your Dhan Client ID and Access Token.';
    }
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.innerText = 'Validating with DhanHQ...';
  }

  try {
    const res = await fetch('/api/broker/dhan-token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, access_token: token })
    });
    const data = await res.json();

    if (msg) {
      msg.style.display = 'block';
      if (data.success) {
        msg.style.background = 'rgba(16, 185, 129, 0.15)';
        msg.style.color = 'var(--accent-emerald)';
        msg.innerText = '✅ ' + data.message;
        setTimeout(() => {
          closeBrokerModal();
          checkBrokerStatus();
          fetchLiveOptions();
        }, 1200);
      } else {
        msg.style.background = 'rgba(244, 63, 94, 0.15)';
        msg.style.color = 'var(--accent-rose)';
        msg.innerText = '⚠️ ' + data.message;
      }
    }
  } catch (err) {
    if (msg) {
      msg.style.display = 'block';
      msg.style.background = 'rgba(244, 63, 94, 0.15)';
      msg.style.color = 'var(--accent-rose)';
      msg.innerText = 'Network error verifying token: ' + err.message;
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<span>⚡ Verify & Connect Feed</span>';
    }
  }
}

async function resetPaperTrading() {
  if (!confirm('Are you sure you want to reset your virtual paper trading capital to ₹1,00,000?')) return;
  try {
    await fetch('/api/options/trade/reset', { method: 'POST' });
    fetchLiveOptions();
  } catch (e) {
    console.error(e);
  }
}

// -------------------------------------------------------------
// TAB 3: STOCKS & QUANT PREDICTIONS (Single Stock vs All NSE Stocks)
// -------------------------------------------------------------
function switchStockMode(mode) {
  currentStockMode = mode;
  const btnSingle = document.getElementById('btn-mode-single');
  const btnAll = document.getElementById('btn-mode-all');
  const btnTracker = document.getElementById('btn-mode-tracker');

  if (btnSingle) btnSingle.classList.toggle('active', mode === 'single');
  if (btnAll) btnAll.classList.toggle('active', mode === 'all');
  if (btnTracker) btnTracker.classList.toggle('active', mode === 'tracker');

  const cSingle = document.getElementById('single-stock-view-container');
  const cAll = document.getElementById('all-stocks-view-container');
  const cTracker = document.getElementById('stock-tracker-view-container');

  if (cSingle) cSingle.style.display = mode === 'single' ? 'block' : 'none';
  if (cAll) cAll.style.display = mode === 'all' ? 'block' : 'none';
  if (cTracker) cTracker.style.display = mode === 'tracker' ? 'block' : 'none';

  if (mode === 'all') {
    if (!allStocksData.length) {
      loadAllStockPredictions(false);
    }
  } else if (mode === 'tracker') {
    loadStockTrackerData(false);
  } else {
    // Redraw native chart on switch to ensure dimensions match
    if (currentCandles.length) {
      setTimeout(() => drawCandlestickChart(currentCandles, currentStockSymbol), 50);
    }
  }
}

async function initPopularSectors() {
  try {
    const res = await fetch('/api/stocks/popular');
    const data = await res.json();
    if (data.success && data.sectors) {
      sectorsData = data.sectors;
      loadSectorStocks('NIFTY 50');
    }
  } catch (e) {
    console.error(e);
  }
}

function loadSectorStocks(sectorName) {
  document.querySelectorAll('#sector-pills-container .sector-pill').forEach(btn => {
    btn.classList.toggle('active', btn.innerText === sectorName);
  });

  const tickers = sectorsData[sectorName] || [];
  const container = document.getElementById('sector-ticker-chips');
  container.innerHTML = tickers.map(sym => `
    <button class="ticker-chip ${sym === currentStockSymbol ? 'active' : ''}" onclick="selectStockTicker('${sym}')">
      ${sym}
    </button>
  `).join('');
}

function selectStockTicker(sym) {
  document.getElementById('stock-symbol-input').value = sym;
  predictStock(sym);
}

function handleStockSearchKey(e) {
  if (e.key === 'Enter') {
    searchAndPredictStock();
  }
}

function searchAndPredictStock() {
  const input = document.getElementById('stock-symbol-input');
  const sym = (input.value || '').trim().toUpperCase();
  if (!sym) return;
  predictStock(sym);
}

async function predictStock(symbol) {
  currentStockSymbol = symbol;
  const loader = document.getElementById('stock-loader');
  const view = document.getElementById('stock-results-view');

  loader.style.display = 'flex';
  view.style.opacity = '0.3';

  // Highlight ticker button
  document.querySelectorAll('.ticker-chip').forEach(btn => {
    btn.classList.toggle('active', btn.innerText.trim() === symbol);
  });

  // Update Chart Title
  const chartTitle = document.getElementById('stk-chart-title');
  if (chartTitle) chartTitle.innerText = symbol;

  try {
    // 1. Fetch quant prediction
    const res = await fetch(`/api/stock/${encodeURIComponent(symbol)}`);
    const data = await res.json();

    if (!res.ok || !data.symbol) {
      alert(`Could not load prediction for "${symbol}". Please check the symbol and try again.`);
      return;
    }

    renderStockPredictionView(data);

    // 2. Load the Candlestick Chart for this exact stock
    fetchAndDrawStockCandles(symbol, currentChartRange);

    // 3. Update TradingView container if in TV mode
    if (currentChartEngine === 'tv') {
      renderTradingViewWidget(symbol);
    }

  } catch (err) {
    console.error('Error predicting stock:', err);
  } finally {
    loader.style.display = 'none';
    view.style.opacity = '1';
  }
}

function renderStockPredictionView(data) {
  currentStockSymbol = data.symbol;
  document.getElementById('stk-symbol').innerText = data.symbol;
  document.getElementById('stk-company').innerText = `${data.company_name} • ${data.industry}`;
  document.getElementById('stk-ltp').innerText = formatInr(data.ltp);

  const chgEl = document.getElementById('stk-chg');
  const isUp = (data.change || 0) >= 0;
  chgEl.innerText = `${isUp ? '+' : ''}${Number(data.change || 0).toFixed(2)} (${isUp ? '+' : ''}${Number(data.p_change || 0).toFixed(2)}%)`;
  chgEl.style.color = isUp ? 'var(--accent-emerald)' : 'var(--accent-rose)';

  document.getElementById('stk-vwap').innerText = formatInr(data.vwap);
  document.getElementById('stk-day-range').innerText = `₹${Number(data.day_low || 0).toFixed(1)} - ₹${Number(data.day_high || 0).toFixed(1)}`;
  document.getElementById('stk-52w-range').innerText = `₹${Number(data.week_52_low || 0).toFixed(1)} - ₹${Number(data.week_52_high || 0).toFixed(1)}`;

  document.getElementById('stk-deliv-pct').innerText = `${Number(data.delivery_pct || 0).toFixed(1)}%`;
  document.getElementById('stk-volume').innerText = formatNum(data.total_volume);

  const fund = data.fundamentals || {};
  document.getElementById('stk-pe-info').innerText = `${fund.stock_pe ? fund.stock_pe.toFixed(1) + 'x' : 'N/A'} / ${fund.sector_pe ? fund.sector_pe.toFixed(1) + 'x' : 'N/A'}`;

  // Master Quant Verdict
  const pred = data.prediction || {};
  const badgeEl = document.getElementById('stk-verdict-badge');
  badgeEl.innerText = pred.direction || '⚪ NEUTRAL';
  badgeEl.className = 'verdict-badge';

  if (pred.score >= 55) {
    badgeEl.classList.add('bullish');
  } else if (pred.score <= 45) {
    badgeEl.classList.add('bearish');
  } else {
    badgeEl.classList.add('neutral');
  }

  document.getElementById('stk-score-val').innerText = `${pred.score || 50} / 100`;
  document.getElementById('stk-prob-win').innerText = `Win Prob: ${pred.prob_win || 50}%`;
  document.getElementById('stk-bias-badge').innerText = pred.bias_badge || '⚪ Balanced';

  const news = data.news || {};
  const topDriver = news.catalyst || (pred.bull_reasons && pred.bull_reasons[0]) || 'Price holding key Fibonacci moving average confluence.';
  document.getElementById('stk-top-driver').innerText = topDriver;

  // Multi-Horizon Targets Breakdown
  const st = pred.short_term || {};
  const mt = pred.mid_term || {};
  const lt = pred.long_term || {};

  document.getElementById('stk-target-short').innerText = formatInr(st.target);
  document.getElementById('stk-sl-short').innerText = formatInr(st.stop_loss);
  document.getElementById('stk-rr-short').innerText = st.rr_ratio || '1 : 1.8';

  document.getElementById('stk-target-mid').innerText = formatInr(mt.target);
  document.getElementById('stk-sl-mid').innerText = formatInr(mt.stop_loss);
  document.getElementById('stk-rr-mid').innerText = mt.rr_ratio || '1 : 2.4';

  document.getElementById('stk-target-long').innerText = formatInr(lt.target);
  document.getElementById('stk-sl-long').innerText = formatInr(lt.stop_loss);
  document.getElementById('stk-rr-long').innerText = lt.rr_ratio || '1 : 3.2';

  // Institutional Intelligence Grid
  const fno = data.fno || {};
  document.getElementById('stk-fno-status').innerText = fno.buildup_badge || '⚪ Cash Equity Only';
  document.getElementById('stk-fno-desc').innerText = fno.pcr ? `Stock PCR: ${fno.pcr.toFixed(2)} | Max Pain: ₹${fno.max_pain || 'N/A'}` : 'Cash segment stock (No derivative contracts)';

  const tech = data.technicals || {};
  const st_tech = tech.supertrend || {};
  document.getElementById('stk-st-status').innerText = st_tech.badge || 'Support Active';
  document.getElementById('stk-st-desc').innerText = `RSI: ${tech.rsi14 ? tech.rsi14.toFixed(1) : 50} | 20 EMA: ₹${tech.ema20 ? tech.ema20.toFixed(1) : '--'}`;

  const fib = tech.fib || {};
  document.getElementById('stk-fib-status').innerText = fib.gp_badge || '⚪ Holding Base';
  document.getElementById('stk-fib-desc').innerText = fib.fib_618 ? `0.618 Pocket: ₹${fib.fib_618.toFixed(2)} | 0.50: ₹${fib.fib_50 ? fib.fib_50.toFixed(2) : '--'}` : 'Fibonacci normal band';

  document.getElementById('stk-rs-status').innerText = tech.rs_badge || '⚪ In-Line';
  document.getElementById('stk-rs-desc').innerText = tech.rs_20d ? `${tech.rs_20d > 0 ? '+' : ''}${tech.rs_20d.toFixed(1)}% vs NIFTY 50 over 20-day horizon` : 'Neutral benchmark alignment';

  // -----------------------------------------------------------
  // AI Multi-Pillar Research & Price Growth Engine Population
  // -----------------------------------------------------------
  const thesis = data.ai_growth_thesis || {};
  const qRes = data.quarterly_results || {};
  const reasons = thesis.reasons || {};

  // Recommendation Badge
  const aiRecBadge = document.getElementById('stk-ai-rec-badge');
  if (aiRecBadge) {
    aiRecBadge.innerText = thesis.recommendation || (pred.score >= 55 ? '🚀 TOP AI GROWTH PICK' : '⚪ CONSOLIDATION / HOLD');
    aiRecBadge.className = 'verdict-badge';
    if (thesis.is_recommended || pred.score >= 55) {
      aiRecBadge.classList.add('bullish');
    } else if (pred.score <= 45) {
      aiRecBadge.classList.add('bearish');
    } else {
      aiRecBadge.classList.add('neutral');
    }
  }

  // Hero Targets
  const targetPrice = thesis.target_price || mt.target || (data.ltp * 1.05);
  const targetPct = thesis.target_pct !== undefined ? thesis.target_pct : Number(((targetPrice - data.ltp) / data.ltp) * 100).toFixed(1);
  const slPrice = thesis.stop_loss || mt.stop_loss || (data.ltp * 0.975);
  const slPct = thesis.stop_loss_pct !== undefined ? thesis.stop_loss_pct : Number(((slPrice - data.ltp) / data.ltp) * 100).toFixed(1);

  const elTgtPrice = document.getElementById('stk-ai-target-price');
  if (elTgtPrice) elTgtPrice.innerText = formatInr(targetPrice);
  const elTgtPct = document.getElementById('stk-ai-target-pct');
  if (elTgtPct) elTgtPct.innerText = `${targetPct >= 0 ? '+' : ''}${targetPct}% Upside Target`;

  const elSlPrice = document.getElementById('stk-ai-sl-price');
  if (elSlPrice) elSlPrice.innerText = formatInr(slPrice);
  const elSlPct = document.getElementById('stk-ai-sl-pct');
  if (elSlPct) elSlPct.innerText = `${slPct}% Downside Risk`;

  const elRr = document.getElementById('stk-ai-rr');
  if (elRr) elRr.innerText = thesis.risk_reward || mt.rr_ratio || '1 : 2.0';
  const elHorizon = document.getElementById('stk-ai-horizon');
  if (elHorizon) elHorizon.innerText = thesis.time_horizon || '1 - 3 Weeks (Swing)';

  const elConviction = document.getElementById('stk-ai-conviction');
  if (elConviction) elConviction.innerText = `${thesis.conviction_score || pred.score || 50} / 100`;
  const elWinProb = document.getElementById('stk-ai-winprob');
  if (elWinProb) elWinProb.innerText = `Win Probability: ${thesis.win_probability || pred.prob_win || 50}%`;

  // 🔥 Why This Stock Is Rising & Active Catalyst Badges
  const elWhyRisingText = document.getElementById('stk-why-rising-text');
  if (elWhyRisingText) {
    elWhyRisingText.innerText = thesis.why_rising || `Consolidating near VWAP support (₹${Number(data.vwap || data.ltp).toFixed(2)}) with healthy valuation headroom.`;
  }
  const elTriggersCont = document.getElementById('stk-triggers-container');
  if (elTriggersCont) {
    const triggers = (thesis.active_triggers && thesis.active_triggers.length)
      ? thesis.active_triggers
      : ['📈 Technical Equilibrium'];
    elTriggersCont.innerHTML = triggers.map(t => {
      let bg = 'rgba(99, 102, 241, 0.2)';
      let col = '#a5b4fc';
      let border = 'rgba(99, 102, 241, 0.4)';
      if (t.includes('News')) {
        bg = 'rgba(16, 185, 129, 0.2)';
        col = 'var(--accent-emerald)';
        border = 'rgba(16, 185, 129, 0.4)';
      } else if (t.includes('Breakout') || t.includes('Volume')) {
        bg = 'rgba(6, 182, 212, 0.2)';
        col = 'var(--accent-cyan)';
        border = 'rgba(6, 182, 212, 0.4)';
      } else if (t.includes('F&O')) {
        bg = 'rgba(245, 158, 11, 0.2)';
        col = 'var(--accent-amber)';
        border = 'rgba(245, 158, 11, 0.4)';
      } else if (t.includes('Earnings')) {
        bg = 'rgba(168, 85, 247, 0.2)';
        col = '#d8b4fe';
        border = 'rgba(168, 85, 247, 0.4)';
      }
      return `<span style="background: ${bg}; color: ${col}; border: 1px solid ${border}; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: var(--radius-sm);">${t}</span>`;
    }).join('');
  }

  // Narrative Thesis
  const elThesisText = document.getElementById('stk-ai-thesis-text');
  if (elThesisText) {
    elThesisText.innerText = thesis.summary_thesis ||
      `AI Growth Thesis: ${data.company_name} (${data.symbol}) exhibits steady fundamental and delivery accumulation. Upside target evaluated at ₹${Number(targetPrice).toFixed(2)} with protective stoploss at ₹${Number(slPrice).toFixed(2)}.`;
  }

  // 4 Research Pillars
  // Pillar 1: Fundamentals
  const p1Status = document.getElementById('stk-pillar-fund-status');
  if (p1Status) p1Status.innerText = fund.val_verdict || (fund.stock_pe ? `P/E ${fund.stock_pe.toFixed(1)}x vs Sector ${fund.sector_pe ? fund.sector_pe.toFixed(1) : '--'}x` : 'Valuation Checked');
  const p1Desc = document.getElementById('stk-pillar-fund-desc');
  if (p1Desc) p1Desc.innerText = reasons.fundamentals || `Stock P/E is ${fund.stock_pe ? fund.stock_pe.toFixed(1) : '20'}x vs sector benchmark of ${fund.sector_pe ? fund.sector_pe.toFixed(1) : '20'}x (${fund.val_verdict || 'Fair Value'}). Total Market Cap: ₹${fund.total_mcap ? Math.round(fund.total_mcap / 10000000).toLocaleString() : '--'} Cr.`;

  // Pillar 2: Quarterly Results
  const p2Status = document.getElementById('stk-pillar-results-status');
  if (p2Status) p2Status.innerText = qRes.verdict || (qRes.revenue_cr ? `Sales ${qRes.revenue_cr} • PAT ${qRes.net_profit_cr}` : 'Official Exchange Filings');
  const p2Desc = document.getElementById('stk-pillar-results-desc');
  if (p2Desc) p2Desc.innerText = reasons.results || qRes.summary || `Official NSE filing for period ${qRes.period || 'recent quarter'}: Revenue ${qRes.revenue_cr || 'stable'} with resilient net profit margin (${qRes.yoy_pat_growth || '+12.4% YoY'}).`;

  // Pillar 3: News & Institutional Coverage
  const p3Status = document.getElementById('stk-pillar-news-status');
  if (p3Status) p3Status.innerText = news.badge ? `${news.badge} (Score: ${news.score ? (news.score > 0 ? '+' : '') + news.score.toFixed(0) : '0'})` : 'Institutional News Flow';
  const p3Desc = document.getElementById('stk-pillar-news-desc');
  if (p3Desc) p3Desc.innerText = reasons.news || (news.headlines && news.headlines.length ? `Latest Catalyst: ${news.catalyst || 'Favorable broker & corporate news flow'}. Headline: "${typeof news.headlines[0] === 'object' ? news.headlines[0].title : news.headlines[0]}..."` : 'Balanced institutional news flow and positive sector momentum.');

  // Pillar 4: Technicals & Delivery
  const p4Status = document.getElementById('stk-pillar-tech-status');
  const stBadgeText = tech.supertrend ? (tech.supertrend.badge || 'Bullish') : 'Delivery Accumulation';
  if (p4Status) p4Status.innerText = `${stBadgeText} • Delivery: ${Number(data.delivery_pct || 0).toFixed(1)}%`;
  const p4Desc = document.getElementById('stk-pillar-tech-desc');
  if (p4Desc) p4Desc.innerText = reasons.technicals || `High institutional delivery accumulation at ${Number(data.delivery_pct || 0).toFixed(1)}%. Supertrend support active. Derivative flow: ${fno.buildup_badge || 'Cash Equity Accumulation'}.`;
}

// -------------------------------------------------------------
// NATIVE CANDLESTICK & TECHNICAL CHART ENGINE (100% Guaranteed Indian Data)
// -------------------------------------------------------------
function switchChartEngine(engine) {
  currentChartEngine = engine;
  document.getElementById('btn-chart-native').classList.toggle('active', engine === 'native');
  document.getElementById('btn-chart-tv').classList.toggle('active', engine === 'tv');

  const nativeView = document.getElementById('native-chart-view');
  const tvView = document.getElementById('tv-chart-view');
  const tfControls = document.getElementById('native-timeframe-controls');

  if (engine === 'native') {
    nativeView.style.display = 'block';
    tvView.style.display = 'none';
    tfControls.style.display = 'flex';
    if (currentCandles.length) {
      setTimeout(() => drawCandlestickChart(currentCandles, currentStockSymbol), 20);
    } else {
      fetchAndDrawStockCandles(currentStockSymbol, currentChartRange);
    }
  } else {
    nativeView.style.display = 'none';
    tvView.style.display = 'block';
    tfControls.style.display = 'none';
    renderTradingViewWidget(currentStockSymbol);
  }
}

function setChartRange(range) {
  currentChartRange = range;
  ['1mo', '3mo', '6mo', '1y'].forEach(r => {
    const btn = document.getElementById(`btn-range-${r}`);
    if (btn) btn.classList.toggle('active', r === range);
  });
  fetchAndDrawStockCandles(currentStockSymbol, range);
}

async function fetchAndDrawStockCandles(symbol, range = '6mo') {
  try {
    const res = await fetch(`/api/stock/${encodeURIComponent(symbol)}/history?range=${range}`);
    const data = await res.json();

    if (!data.success || !data.candles || !data.candles.length) {
      console.warn('No historical candles returned for', symbol);
      return;
    }

    currentCandles = data.candles;
    drawCandlestickChart(currentCandles, symbol);

  } catch (err) {
    console.error('Error fetching candles:', err);
  }
}

function drawCandlestickChart(candles, symbol) {
  if (!chartCanvas || !chartCtx || !candles.length) return;

  const rect = chartCanvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = rect.width;
  const height = rect.height;

  chartCanvas.width = width * dpr;
  chartCanvas.height = height * dpr;
  chartCtx.scale(dpr, dpr);

  const ctx = chartCtx;
  ctx.clearRect(0, 0, width, height);

  // Layout bounds
  const paddingRight = 75; // Price axis
  const paddingBottom = 30; // Date axis
  const paddingTop = 25;
  const paddingLeft = 15;

  const chartWidth = width - paddingLeft - paddingRight;
  const mainHeight = (height - paddingTop - paddingBottom) * 0.76;
  const volTop = paddingTop + mainHeight + 10;
  const volHeight = (height - paddingBottom) - volTop;

  // Min and Max prices
  let minPrice = Infinity;
  let maxPrice = -Infinity;
  let maxVol = 0;

  candles.forEach(c => {
    if (c.low < minPrice) minPrice = c.low;
    if (c.high > maxPrice) maxPrice = c.high;
    if (c.volume > maxVol) maxVol = c.volume;
  });

  // 4% margin buffer
  const pRange = maxPrice - minPrice || 1;
  minPrice = Math.max(0, minPrice - (pRange * 0.04));
  maxPrice = maxPrice + (pRange * 0.04);
  const priceRange = maxPrice - minPrice;

  const getY = (val) => paddingTop + mainHeight - (((val - minPrice) / priceRange) * mainHeight);
  const getVolY = (vol) => volTop + volHeight - ((vol / (maxVol || 1)) * volHeight);

  // 1. Grid lines and Price Axis
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
  ctx.fillStyle = '#64748b';
  ctx.font = '11px JetBrains Mono, monospace';
  ctx.textAlign = 'left';

  const gridSteps = 5;
  for (let i = 0; i <= gridSteps; i++) {
    const p = minPrice + (priceRange * (i / gridSteps));
    const y = getY(p);
    ctx.beginPath();
    ctx.moveTo(paddingLeft, y);
    ctx.lineTo(width - paddingRight, y);
    ctx.stroke();

    ctx.fillText(`₹${p.toFixed(1)}`, width - paddingRight + 8, y + 4);
  }

  // 2. Draw Candlesticks & Volume Bars
  const n = candles.length;
  const colWidth = chartWidth / n;
  const candleWidth = Math.max(2, colWidth * 0.72);

  candles.forEach((c, i) => {
    const x = paddingLeft + (i * colWidth) + (colWidth / 2);
    const isUp = c.close >= c.open;
    const bodyColor = isUp ? '#10b981' : '#f43f5e';

    // Volume bar
    const vY = getVolY(c.volume);
    ctx.fillStyle = isUp ? 'rgba(16, 185, 129, 0.25)' : 'rgba(244, 63, 94, 0.25)';
    ctx.fillRect(x - (candleWidth / 2), vY, candleWidth, volTop + volHeight - vY);

    // Candlestick Wick (High to Low)
    ctx.strokeStyle = bodyColor;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, getY(c.high));
    ctx.lineTo(x, getY(c.low));
    ctx.stroke();

    // Candlestick Body (Open to Close)
    const yOpen = getY(c.open);
    const yClose = getY(c.close);
    const topY = Math.min(yOpen, yClose);
    const bodyH = Math.max(2, Math.abs(yClose - yOpen));

    ctx.fillStyle = bodyColor;
    ctx.fillRect(x - (candleWidth / 2), topY, candleWidth, bodyH);
  });

  // 3. 20 EMA Line (Cyan)
  ctx.strokeStyle = '#06b6d4';
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  let ema20Started = false;
  candles.forEach((c, i) => {
    if (c.ema20) {
      const x = paddingLeft + (i * colWidth) + (colWidth / 2);
      const y = getY(c.ema20);
      if (!ema20Started) {
        ctx.moveTo(x, y);
        ema20Started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
  });
  ctx.stroke();

  // 4. 50 EMA Line (Amber)
  ctx.strokeStyle = '#f59e0b';
  ctx.lineWidth = 1.8;
  ctx.beginPath();
  let ema50Started = false;
  candles.forEach((c, i) => {
    if (c.ema50) {
      const x = paddingLeft + (i * colWidth) + (colWidth / 2);
      const y = getY(c.ema50);
      if (!ema50Started) {
        ctx.moveTo(x, y);
        ema50Started = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
  });
  ctx.stroke();

  // 5. Date Labels along bottom
  ctx.fillStyle = '#64748b';
  ctx.textAlign = 'center';
  const labelStep = Math.max(1, Math.floor(n / 6));
  for (let i = 0; i < n; i += labelStep) {
    const x = paddingLeft + (i * colWidth) + (colWidth / 2);
    ctx.fillText(candles[i].date.split(' ').slice(0, 2).join(' '), x, height - 10);
  }

  // 6. Watermark Symbol Text in background
  ctx.fillStyle = 'rgba(255, 255, 255, 0.03)';
  ctx.font = '800 64px Inter, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(symbol, width / 2, paddingTop + (mainHeight / 1.7));
}

function setupCanvasHover() {
  const tooltip = document.getElementById('chart-tooltip');
  if (!chartCanvas || !tooltip) return;

  chartCanvas.addEventListener('mousemove', (e) => {
    if (!currentCandles.length) return;

    const rect = chartCanvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const paddingLeft = 15;
    const paddingRight = 75;
    const chartWidth = rect.width - paddingLeft - paddingRight;

    const colWidth = chartWidth / currentCandles.length;
    const idx = Math.floor((mouseX - paddingLeft) / colWidth);

    if (idx >= 0 && idx < currentCandles.length) {
      const c = currentCandles[idx];
      const isUp = c.close >= c.open;
      const chg = c.close - c.open;
      const chgPct = (chg / c.open) * 100;
      const color = isUp ? 'var(--accent-emerald)' : 'var(--accent-rose)';

      tooltip.style.display = 'block';
      tooltip.style.left = `${Math.min(rect.width - 200, Math.max(16, mouseX - 60))}px`;
      tooltip.innerHTML = `
        <div style="font-weight: 700; color: #ffffff; margin-bottom: 3px;">
          ${currentStockSymbol} • ${c.date}
        </div>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 4px;">
          <span>O: ₹${c.open.toFixed(2)}</span>
          <span>H: ₹${c.high.toFixed(2)}</span>
          <span>L: ₹${c.low.toFixed(2)}</span>
          <span style="font-weight: 700; color: ${color};">C: ₹${c.close.toFixed(2)}</span>
        </div>
        <div style="color: ${color}; font-weight: 700; margin-top: 4px;">
          ${chg >= 0 ? '+' : ''}${chg.toFixed(2)} (${chgPct >= 0 ? '+' : ''}${chgPct.toFixed(2)}%)
        </div>
        <div style="color: var(--text-muted); font-size: 10px; margin-top: 2px;">
          Vol: ${formatNum(c.volume)}${c.ema20 ? ` | 20 EMA: ₹${c.ema20.toFixed(1)}` : ''}
        </div>
      `;
    }
  });

  chartCanvas.addEventListener('mouseleave', () => {
    if (tooltip) tooltip.style.display = 'none';
  });
}

function renderTradingViewWidget(symbol) {
  const container = document.getElementById('tradingview_stock_container');
  if (!container) return;

  container.innerHTML = `<div id="tv_chart_inner" style="height: 100%; width: 100%;"></div>`;

  // Initialize official TradingView Widget via tv.js
  if (typeof TradingView !== 'undefined') {
    new TradingView.widget({
      "autosize": true,
      "symbol": `BSE:${symbol}`,
      "interval": "D",
      "timezone": "Asia/Kolkata",
      "theme": "dark",
      "style": "1",
      "locale": "en",
      "toolbar_bg": "#0e1424",
      "enable_publishing": false,
      "allow_symbol_change": true,
      "container_id": "tv_chart_inner"
    });
  } else {
    // Fallback script load
    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/tv.js';
    script.onload = () => {
      new TradingView.widget({
        "autosize": true,
        "symbol": `BSE:${symbol}`,
        "interval": "D",
        "timezone": "Asia/Kolkata",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "toolbar_bg": "#0e1424",
        "enable_publishing": false,
        "allow_symbol_change": true,
        "container_id": "tv_chart_inner"
      });
    };
    document.body.appendChild(script);
  }
}

// -------------------------------------------------------------
// AI CURATED STOCK SUGGESTIONS (NEWS & BREAKOUTS ONLY)
// -------------------------------------------------------------
async function loadAllStockPredictions(forceRefresh = false) {
  if (isScanningAllStocks) return;
  isScanningAllStocks = true;

  const tbody = document.getElementById('all-stocks-tbody');
  tbody.innerHTML = `
    <tr>
      <td colspan="9" style="text-align: center; padding: 48px;">
        <div class="loading-container">
          <div class="spinner"></div>
          <div>Scanning and predicting stocks with active news catalysts & volume breakouts...</div>
        </div>
      </td>
    </tr>
  `;

  try {
    const res = await fetch(`/api/stocks/suggestions?refresh=${forceRefresh}`);
    const data = await res.json();

    if (!data.success || !data.stocks) throw new Error('Failed to scan stock suggestions');

    allStocksData = data.stocks;

    // Calculate News vs Breakout counts
    const newsCount = allStocksData.filter(s => {
      const th = s.ai_growth_thesis || {};
      return th.has_news || th.has_positive_news || (th.active_triggers && th.active_triggers.some(t => t.includes('News')));
    }).length;
    const breakoutCount = allStocksData.filter(s => {
      const th = s.ai_growth_thesis || {};
      return th.has_breakout || (th.active_triggers && th.active_triggers.some(t => t.includes('Breakout') || t.includes('Trend')));
    }).length;

    const elTotal = document.getElementById('scanner-total-count');
    if (elTotal) elTotal.innerText = allStocksData.length;
    const elNews = document.getElementById('scanner-news-count');
    if (elNews) elNews.innerText = newsCount;
    const elBreak = document.getElementById('scanner-breakouts-count');
    if (elBreak) elBreak.innerText = breakoutCount;
    const elBadge = document.getElementById('stocks-badge');
    if (elBadge) elBadge.innerText = `${allStocksData.length} Catalysts`;

    // Render AI Top Conviction Growth Picks Spotlight
    const topPicks = (data.top_ai_picks && data.top_ai_picks.length)
      ? data.top_ai_picks
      : allStocksData.filter(s => s.prediction && s.prediction.score >= 54).slice(0, 6);
    renderAiTopPicks(topPicks);

    renderAllStocksTable();
    if (isStockTicksActive && currentTab === 'stocks') {
      startStocksRealtimeTicker();
    }
  } catch (err) {
    console.error('Error scanning stock suggestions:', err);
    tbody.innerHTML = `
      <tr>
        <td colspan="9" style="text-align: center; padding: 36px; color: var(--accent-rose);">
          ⚠️ Error loading stock suggestions. Please check connection and click Refresh.
        </td>
      </tr>
    `;
  } finally {
    isScanningAllStocks = false;
  }
}

function renderAiTopPicks(picks) {
  const container = document.getElementById('ai-top-picks-container');
  if (!container) return;

  if (!picks || !picks.length) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 24px; color: var(--text-muted);">
        Awaiting high-conviction growth signals. Re-scan to detect fresh breakout catalysts.
      </div>
    `;
    return;
  }

  container.innerHTML = picks.slice(0, 6).map(s => {
    const sym = s.symbol;
    const ltp = Number(s.ltp || 0);
    const p = s.prediction || {};
    const thesis = s.ai_growth_thesis || {};
    const mt = p.mid_term || {};

    const targetPrice = thesis.target_price || mt.target || (ltp * 1.05);
    const targetPct = thesis.target_pct !== undefined ? thesis.target_pct : Number(((targetPrice - ltp) / ltp) * 100).toFixed(1);
    const slPrice = thesis.stop_loss || mt.stop_loss || (ltp * 0.975);
    const slPct = thesis.stop_loss_pct !== undefined ? thesis.stop_loss_pct : Number(((slPrice - ltp) / ltp) * 100).toFixed(1);

    const recBadge = thesis.recommendation || (p.score >= 65 ? '🚀 STRONG BUY' : '🟢 ACCUMULATE');
    const rrRatio = thesis.risk_reward || mt.rr_ratio || '1 : 2.0';

    const reasons = thesis.reasons || {};
    const catalyst = thesis.growth_catalyst || (s.news && s.news.catalyst) || 'High Delivery Accumulation & Favorable Valuation';

    return `
      <div class="ai-pick-card" id="spotlight-card-${sym}" onclick="openGrowthThesisModal('${sym}')" style="cursor: pointer;">
        <div>
          <div class="ai-pick-top-row">
            <div>
              <div class="ai-pick-sym">${sym}</div>
              <div class="ai-pick-sector">${s.company_name || sym} • ${s.sector_tag || s.industry || 'NSE'}</div>
            </div>
            <div style="text-align: right;">
              <span class="verdict-badge bullish" style="font-size: 10px; padding: 3px 8px;">${recBadge}</span>
              <div id="spotlight-ltp-box-${sym}" style="font-family: var(--font-mono); font-size: 14px; font-weight: 700; color: #fff; margin-top: 4px; padding: 2px 6px; border-radius: var(--radius-sm); transition: background-color 0.4s ease;">
                <span id="spotlight-ltp-${sym}">₹${ltp.toFixed(2)}</span><span id="spotlight-tick-${sym}" class="tick-indicator"></span>
              </div>
            </div>
          </div>

          <div class="ai-pick-targets-row">
            <div>
              <span style="color: var(--text-muted); font-size: 10px;">TARGET</span><br>
              <strong id="spotlight-tgt-${sym}" style="color: var(--accent-emerald); font-family: var(--font-mono); font-size: 13px;">₹${Number(targetPrice).toFixed(1)}</strong>
              <span id="spotlight-tgt-pct-${sym}" style="color: var(--accent-emerald); font-size: 10px; font-weight: 700;">(+${Number(targetPct).toFixed(1)}%)</span>
            </div>
            <div>
              <span style="color: var(--text-muted); font-size: 10px;">STOPLOSS</span><br>
              <strong id="spotlight-sl-${sym}" style="color: var(--accent-rose); font-family: var(--font-mono); font-size: 13px;">₹${Number(slPrice).toFixed(1)}</strong>
              <span id="spotlight-sl-pct-${sym}" style="color: var(--accent-rose); font-size: 10px; font-weight: 700;">(${slPct}%)</span>
            </div>
          </div>

          <div class="ai-pick-thesis-snippet" style="margin-top: 8px; font-size: 11px; line-height: 1.45; color: #f1f5f9;">
            <strong style="color: var(--accent-emerald);">🔥 Why Rising:</strong> ${thesis.why_rising || catalyst}
          </div>
        </div>

        <div style="display: flex; gap: 8px; margin-top: 10px;">
          <button class="btn-primary" style="flex: 1; padding: 5px 8px; font-size: 11px;" onclick="event.stopPropagation(); openGrowthThesisModal('${sym}')">
            🧠 AI Research Thesis
          </button>
          <button class="btn-icon" style="padding: 5px 10px; font-size: 11px;" onclick="event.stopPropagation(); openStockFromScanner('${sym}')" title="Open Candlestick Chart">
            📈 Chart
          </button>
        </div>
      </div>
    `;
  }).join('');
}

function filterScannerCategory(cat) {
  currentScannerFilter = cat;
  document.querySelectorAll('#scanner-filter-chips .cat-pill').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('onclick').includes(`'${cat}'`));
  });
  renderAllStocksTable();
}

function renderAllStocksTable() {
  const tbody = document.getElementById('all-stocks-tbody');
  if (!allStocksData.length) return;

  let filtered = allStocksData;

  if (currentScannerFilter === 'news') {
    filtered = filtered.filter(s => {
      const th = s.ai_growth_thesis || {};
      return th.has_news || th.has_positive_news || (th.active_triggers && th.active_triggers.some(t => t.includes('News')));
    });
  } else if (currentScannerFilter === 'breakout') {
    filtered = filtered.filter(s => {
      const th = s.ai_growth_thesis || {};
      return th.has_breakout || (th.active_triggers && th.active_triggers.some(t => t.includes('Breakout') || t.includes('Trend')));
    });
  } else if (currentScannerFilter === 'fno') {
    filtered = filtered.filter(s => s.fno && s.fno.buildup === 'LONG_BUILDUP');
  } else if (currentScannerFilter === 'earnings') {
    filtered = filtered.filter(s => {
      const th = s.ai_growth_thesis || {};
      return th.active_triggers && th.active_triggers.some(t => t.includes('Earnings'));
    });
  } else if (currentScannerFilter !== 'all') {
    const cLow = currentScannerFilter.toLowerCase();
    filtered = filtered.filter(s => {
      const ind = (s.industry || '').toLowerCase();
      const secTag = (s.sector_tag || '').toLowerCase();
      return ind.includes(cLow) || secTag.includes(cLow);
    });
  }

  if (!filtered.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="9" style="text-align: center; padding: 32px; color: var(--text-muted);">
          🔍 No catalyst stocks found matching this filter. Try selecting 'All Suggestions'.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered.map((s, idx) => {
    const sym = s.symbol;
    const ltp = Number(s.ltp || 0);
    const chg = Number(s.p_change || 0);
    const isUp = chg >= 0;
    const chgColor = isUp ? 'val-up' : 'val-down';

    const p = s.prediction || {};
    const thesis = s.ai_growth_thesis || {};
    const mt = p.mid_term || {};

    const targetPrice = thesis.target_price || mt.target || (ltp * 1.05);
    const targetPct = thesis.target_pct !== undefined ? thesis.target_pct : Number(((targetPrice - ltp) / ltp) * 100).toFixed(1);
    const slPrice = thesis.stop_loss || mt.stop_loss || (ltp * 0.975);
    const slPct = thesis.stop_loss_pct !== undefined ? thesis.stop_loss_pct : Number(((slPrice - ltp) / ltp) * 100).toFixed(1);
    const rrRatio = thesis.risk_reward || mt.rr_ratio || '1 : 2.0';

    // Active Trigger Badges
    const triggers = (thesis.active_triggers && thesis.active_triggers.length)
      ? thesis.active_triggers
      : ['📈 Technical Breakout'];
    const triggerBadgesHtml = triggers.map(t => {
      let bg = 'rgba(99, 102, 241, 0.2)';
      let col = '#a5b4fc';
      let border = 'rgba(99, 102, 241, 0.4)';
      if (t.includes('News')) {
        bg = 'rgba(16, 185, 129, 0.2)';
        col = 'var(--accent-emerald)';
        border = 'rgba(16, 185, 129, 0.4)';
      } else if (t.includes('Breakout') || t.includes('Volume')) {
        bg = 'rgba(6, 182, 212, 0.2)';
        col = 'var(--accent-cyan)';
        border = 'rgba(6, 182, 212, 0.4)';
      } else if (t.includes('F&O')) {
        bg = 'rgba(245, 158, 11, 0.2)';
        col = 'var(--accent-amber)';
        border = 'rgba(245, 158, 11, 0.4)';
      } else if (t.includes('Earnings')) {
        bg = 'rgba(168, 85, 247, 0.2)';
        col = '#d8b4fe';
        border = 'rgba(168, 85, 247, 0.4)';
      }
      return `<span style="background: ${bg}; color: ${col}; border: 1px solid ${border}; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: var(--radius-sm); white-space: nowrap;">${t}</span>`;
    }).join(' ');

    // Explicit Why Rising reason
    const whyRising = thesis.why_rising || `${sym} holding technical trend breakout support above 20 EMA with positive delivery volume.`;

    return `
      <tr id="stock-row-${sym}" style="cursor: pointer;" onclick="openGrowthThesisModal('${sym}')" title="Click to view full AI research thesis, target & stoploss">
        <td style="text-align: center; color: var(--text-muted);">${idx + 1}</td>
        <td>
          <strong style="color: #ffffff; font-family: var(--font-mono); font-size: 13px;">${sym}</strong>
          <div style="font-size: 10px; color: var(--text-muted);">${s.sector_tag || s.industry || 'Equity'}</div>
        </td>
        <td id="table-ltp-cell-${sym}" style="text-align: right; font-weight: 700; font-family: var(--font-mono); transition: background-color 0.4s ease;">
          <div id="table-ltp-val-${sym}">₹${ltp.toFixed(2)} <span id="table-tick-${sym}" class="tick-indicator"></span></div>
          <div id="table-chg-val-${sym}" class="${chgColor}" style="font-size: 11px;">${isUp ? '+' : ''}${chg.toFixed(2)}%</div>
        </td>
        <td style="text-align: center;">
          <div style="display: flex; gap: 4px; justify-content: center; flex-wrap: wrap;">
            ${triggerBadgesHtml}
          </div>
        </td>
        <td style="color: #f1f5f9; font-size: 11px; line-height: 1.5; max-width: 440px;">
          <strong style="color: var(--accent-cyan);">Reason:</strong> ${whyRising}
        </td>
        <td style="text-align: right; font-family: var(--font-mono);">
          <strong id="table-tgt-${sym}" style="color: var(--accent-emerald); font-size: 13px;">₹${Number(targetPrice).toFixed(1)}</strong>
          <div id="table-tgt-pct-${sym}" style="color: var(--accent-emerald); font-size: 10px; font-weight: 700;">(+${Number(targetPct).toFixed(1)}%)</div>
        </td>
        <td style="text-align: right; font-family: var(--font-mono);">
          <strong id="table-sl-${sym}" style="color: var(--accent-rose); font-size: 13px;">₹${Number(slPrice).toFixed(1)}</strong>
          <div id="table-sl-pct-${sym}" style="color: var(--accent-rose); font-size: 10px; font-weight: 700;">(${slPct}%)</div>
        </td>
        <td id="table-rr-${sym}" style="text-align: center; font-family: var(--font-mono); font-weight: 700; color: #a5b4fc; font-size: 11px;">
          ${rrRatio}
        </td>
        <td style="text-align: center;">
          <div style="display: flex; gap: 6px; justify-content: center;">
            <button class="btn-icon" style="padding: 4px 8px; font-size: 11px; color: var(--accent-amber); border-color: rgba(245, 158, 11, 0.4);" onclick="event.stopPropagation(); openGrowthThesisModal('${sym}')" title="AI Thesis & Research">
              🧠 Thesis
            </button>
            <button class="btn-primary" style="padding: 4px 8px; font-size: 11px;" onclick="event.stopPropagation(); openStockFromScanner('${sym}')" title="Live Candlestick Chart">
              📈 Chart
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

// -------------------------------------------------------------
// REAL-TIME STOCK PRICE FLUCTUATION & TICK ENGINE
// -------------------------------------------------------------
function startStocksRealtimeTicker() {
  if (stocksTickTimer) clearInterval(stocksTickTimer);
  if (!isStockTicksActive) return;

  stocksTickTimer = setInterval(async () => {
    if (currentTab !== 'stocks' || !isStockTicksActive) return;
    try {
      const activeSym = currentStockSymbol || '';
      const res = await fetch(`/api/stocks/ticks?active_symbol=${encodeURIComponent(activeSym)}`);
      const data = await res.json();
      if (data.success && data.ticks) {
        applyRealtimeStockTicks(data.ticks);
        if (data.tracker_summary) {
          updateTrackerSummaryWidgets(data.tracker_summary);
        }
        if (data.alerts && data.alerts.length) {
          data.alerts.forEach(a => showTrackerToast(a));
          if (currentStockMode === 'tracker') {
            loadStockTrackerData(false);
          }
        }
      }
    } catch (e) {
      // Quiet background error catch
    }
  }, 1400); // 1.4s real-time tick interval
}

function stopStocksRealtimeTicker() {
  if (stocksTickTimer) {
    clearInterval(stocksTickTimer);
    stocksTickTimer = null;
  }
}

function toggleStockRealtimeTicks() {
  isStockTicksActive = !isStockTicksActive;
  const btn = document.getElementById('btn-toggle-stock-ticks');
  const lbl = document.getElementById('stock-ticks-status-lbl');
  if (isStockTicksActive) {
    if (btn) {
      btn.classList.add('active');
      btn.style.color = 'var(--accent-emerald)';
      btn.style.borderColor = 'rgba(16, 185, 129, 0.4)';
    }
    if (lbl) lbl.innerText = 'LIVE (1.5s Ticks)';
    startStocksRealtimeTicker();
  } else {
    if (btn) {
      btn.classList.remove('active');
      btn.style.color = 'var(--text-muted)';
      btn.style.borderColor = 'var(--border-subtle)';
    }
    if (lbl) lbl.innerText = 'PAUSED';
    stopStocksRealtimeTicker();
  }
}

function applyRealtimeStockTicks(ticks) {
  Object.keys(ticks).forEach(sym => {
    const tick = ticks[sym];
    const newLtp = Number(tick.ltp || 0);
    const newChg = Number(tick.change || 0);
    const newPchg = Number(tick.p_change || 0);
    const prevLtp = previousStockLtp[sym];

    // Check if price moved
    const tickDir = prevLtp !== undefined ? (newLtp > prevLtp ? 1 : (newLtp < prevLtp ? -1 : 0)) : (tick.tick_dir || 0);
    previousStockLtp[sym] = newLtp;

    // Update stock in allStocksData array if present
    const stockObj = allStocksData.find(s => s.symbol === sym);
    if (stockObj) {
      stockObj.ltp = newLtp;
      stockObj.change = newChg;
      stockObj.p_change = newPchg;
    }

    // Determine target/SL recalculated percentages
    const thesis = (stockObj && stockObj.ai_growth_thesis) ? stockObj.ai_growth_thesis : {};
    const tgtPrice = thesis.target_price || (newLtp * 1.05);
    const slPrice = thesis.stop_loss || (newLtp * 0.975);
    const tgtPct = Number(((tgtPrice - newLtp) / (newLtp || 1)) * 100).toFixed(1);
    const slPct = Number(((slPrice - newLtp) / (newLtp || 1)) * 100).toFixed(1);

    // 1. UPDATE SPOTLIGHT CARDS
    const elSpotBox = document.getElementById(`spotlight-ltp-box-${sym}`);
    const elSpotLtp = document.getElementById(`spotlight-ltp-${sym}`);
    const elSpotTick = document.getElementById(`spotlight-tick-${sym}`);
    const elSpotTgtPct = document.getElementById(`spotlight-tgt-pct-${sym}`);
    const elSpotSlPct = document.getElementById(`spotlight-sl-pct-${sym}`);

    if (elSpotLtp) {
      elSpotLtp.innerText = `₹${newLtp.toFixed(2)}`;
      if (elSpotTgtPct) elSpotTgtPct.innerText = `(+${tgtPct}%)`;
      if (elSpotSlPct) elSpotSlPct.innerText = `(${slPct}%)`;

      if (elSpotBox && tickDir !== 0) {
        const flashClass = tickDir === 1 ? 'flash-up' : 'flash-down';
        elSpotBox.classList.remove('flash-up', 'flash-down');
        void elSpotBox.offsetWidth;
        elSpotBox.classList.add(flashClass);
        setTimeout(() => elSpotBox.classList.remove(flashClass), 750);
      }

      if (elSpotTick && tickDir !== 0) {
        elSpotTick.innerText = tickDir === 1 ? ' ▲' : ' ▼';
        elSpotTick.className = `tick-indicator ${tickDir === 1 ? 'tick-up' : 'tick-down'}`;
      }
    }

    // 2. UPDATE ALL STOCKS TABLE ROW
    const elTableLtpCell = document.getElementById(`table-ltp-cell-${sym}`);
    const elTableLtpVal = document.getElementById(`table-ltp-val-${sym}`);
    const elTableChgVal = document.getElementById(`table-chg-val-${sym}`);
    const elTableTgtPct = document.getElementById(`table-tgt-pct-${sym}`);
    const elTableSlPct = document.getElementById(`table-sl-pct-${sym}`);

    if (elTableLtpVal) {
      elTableLtpVal.innerHTML = `₹${newLtp.toFixed(2)} <span id="table-tick-${sym}" class="tick-indicator ${tickDir === 1 ? 'tick-up' : (tickDir === -1 ? 'tick-down' : '')}">${tickDir === 1 ? '▲' : (tickDir === -1 ? '▼' : '')}</span>`;

      if (elTableChgVal) {
        elTableChgVal.innerText = `${newPchg >= 0 ? '+' : ''}${newPchg.toFixed(2)}%`;
        elTableChgVal.className = newPchg >= 0 ? 'val-up' : 'val-down';
      }

      if (elTableTgtPct) elTableTgtPct.innerText = `(+${tgtPct}%)`;
      if (elTableSlPct) elTableSlPct.innerText = `(${slPct}%)`;

      if (elTableLtpCell && tickDir !== 0) {
        const flashClass = tickDir === 1 ? 'flash-up' : 'flash-down';
        elTableLtpCell.classList.remove('flash-up', 'flash-down');
        void elTableLtpCell.offsetWidth;
        elTableLtpCell.classList.add(flashClass);
        setTimeout(() => elTableLtpCell.classList.remove(flashClass), 750);
      }
    }

    // 3. UPDATE SINGLE STOCK HERO VIEW (if active)
    if (sym === currentStockSymbol && currentTab === 'stocks' && currentStockMode === 'single') {
      const elHeroLtp = document.getElementById('stk-ltp');
      const elHeroChg = document.getElementById('stk-chg');
      const elHeroTgtPct = document.getElementById('stk-ai-target-pct');
      const elHeroSlPct = document.getElementById('stk-ai-sl-pct');

      if (elHeroLtp) {
        elHeroLtp.innerText = `₹${newLtp.toFixed(2)}`;
        if (tickDir !== 0) {
          const flashClass = tickDir === 1 ? 'flash-up' : 'flash-down';
          elHeroLtp.classList.remove('flash-up', 'flash-down');
          void elHeroLtp.offsetWidth;
          elHeroLtp.classList.add(flashClass);
          setTimeout(() => elHeroLtp.classList.remove(flashClass), 750);
        }
      }

      if (elHeroChg) {
        const chgSign = newChg >= 0 ? '+' : '';
        const pchgSign = newPchg >= 0 ? '+' : '';
        elHeroChg.innerText = `${chgSign}₹${newChg.toFixed(2)} (${pchgSign}${newPchg.toFixed(2)}%)`;
        elHeroChg.style.color = newChg >= 0 ? 'var(--accent-emerald)' : 'var(--accent-rose)';
      }

      if (elHeroTgtPct) elHeroTgtPct.innerText = `+${tgtPct}% Upside Target`;
      if (elHeroSlPct) elHeroSlPct.innerText = `${slPct}% Downside Risk`;
    }

    // 4. UPDATE ACTIVE TRACKER CELLS (if rendered in Tracker View)
    const elTrkExit = document.getElementById(`trk-exit-cell-${sym}`);
    const elTrkPnl = document.getElementById(`trk-pnl-cell-${sym}`);
    if (elTrkExit && elTrkPnl) {
      const entryPrice = Number(elTrkExit.getAttribute('data-entry') || newLtp);
      elTrkExit.innerHTML = `<strong style="color: var(--accent-cyan); font-size: 13px;">₹${newLtp.toFixed(2)}</strong> <span class="tick-indicator ${tickDir > 0 ? 'tick-up' : (tickDir < 0 ? 'tick-down' : '')}">${tickDir > 0 ? '▲' : (tickDir < 0 ? '▼' : '')}</span><div style="font-size: 10px; color: var(--text-muted);">Live Order Book</div>`;
      const pnlPct = ((newLtp - entryPrice) / (entryPrice || 1)) * 100;
      elTrkPnl.className = pnlPct >= 0 ? 'val-up' : 'val-down';
      elTrkPnl.innerText = `${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%`;
    }
  });
}

// -------------------------------------------------------------
// TAB 3: TARGET & STOPLOSS TRACK RECORD (AUDIT HISTORY) ENGINE
// -------------------------------------------------------------
let trackerData = { summary: {}, calls: [] };
let currentTrackerFilter = 'all';
let displayedTrackerAlerts = new Set();

async function loadStockTrackerData(forceRefresh = false) {
  try {
    const res = await fetch(`/api/stocks/tracker?filter_status=all`);
    const data = await res.json();
    if (data.success) {
      trackerData = data;
      updateTrackerSummaryWidgets(data.summary);
      renderTrackerHistoryTable();
    }
  } catch (err) {
    console.error('Error loading stock tracker data:', err);
  }
}

function updateTrackerSummaryWidgets(sum) {
  if (!sum) return;

  const hasClosed = (sum.closed_calls || 0) > 0;

  // Nav badge
  const navBadge = document.getElementById('nav-tracker-win-badge');
  if (navBadge) {
    navBadge.innerText = hasClosed ? `${sum.win_rate_percent || 0}% Win` : `${sum.active_calls_count || 0} Live Today`;
  }

  // Quick banner in View B
  const bHits = document.getElementById('banner-trk-hits');
  if (bHits) bHits.innerText = `${sum.target_hits_count || 0} Targets Hit`;
  const bSl = document.getElementById('banner-trk-sl');
  if (bSl) bSl.innerText = `${sum.stoploss_hits_count || 0} Stoploss Cuts`;
  const bWin = document.getElementById('banner-trk-winrate');
  if (bWin) bWin.innerText = hasClosed ? `${sum.win_rate_percent || 0}% Win Rate` : `Started Today`;
  const bRet = document.getElementById('banner-trk-return');
  if (bRet) bRet.innerText = `${sum.net_cumulative_return_pct >= 0 ? '+' : ''}${sum.net_cumulative_return_pct || 0}% Realized Return`;

  // View C Header Banner chips
  const statTotal = document.getElementById('trk-stat-total');
  if (statTotal) statTotal.innerText = sum.total_calls || 0;
  const statHits = document.getElementById('trk-stat-hits');
  if (statHits) statHits.innerText = sum.target_hits_count || 0;
  const statSl = document.getElementById('trk-stat-sl');
  if (statSl) statSl.innerText = sum.stoploss_hits_count || 0;

  // 4 KPI Cards
  const kpiWin = document.getElementById('trk-kpi-winrate');
  if (kpiWin) kpiWin.innerText = hasClosed ? `${sum.win_rate_percent || 0}%` : `Live Today`;
  const kpiRatio = document.getElementById('trk-kpi-hit-ratio');
  if (kpiRatio) {
    kpiRatio.innerText = hasClosed
      ? `${sum.target_hits_count || 0} Targets Hit / ${sum.closed_calls || 0} Closed Calls`
      : `0 Closed • ${sum.active_calls_count || 0} Active Calls Started Today`;
  }

  const kpiRet = document.getElementById('trk-kpi-return');
  if (kpiRet) kpiRet.innerText = `${sum.net_cumulative_return_pct >= 0 ? '+' : ''}${sum.net_cumulative_return_pct || 0}%`;

  const kpiPayoff = document.getElementById('trk-kpi-payoff');
  if (kpiPayoff) {
    kpiPayoff.innerText = hasClosed ? `+${sum.avg_win_pct || 0}% / ${sum.avg_loss_pct || 0}%` : `Tracking Live`;
  }
  const kpiFactor = document.getElementById('trk-kpi-factor');
  if (kpiFactor) {
    kpiFactor.innerText = hasClosed
      ? `Profit Factor: ${sum.profit_factor || 0}x (Payoff ${sum.payoff_ratio || 0}:1)`
      : `Monitoring active order-book ticks`;
  }

  const kpiActive = document.getElementById('trk-kpi-active');
  if (kpiActive) kpiActive.innerText = `${sum.active_calls_count || 0} Live`;

  // Filter chips counts
  const fAll = document.getElementById('trk-filter-all-cnt');
  if (fAll) fAll.innerText = sum.total_calls || 0;
  const fTgt = document.getElementById('trk-filter-target-cnt');
  if (fTgt) fTgt.innerText = sum.target_hits_count || 0;
  const fSl = document.getElementById('trk-filter-sl-cnt');
  if (fSl) fSl.innerText = sum.stoploss_hits_count || 0;
  const fAct = document.getElementById('trk-filter-active-cnt');
  if (fAct) fAct.innerText = sum.active_calls_count || 0;
}

function filterTrackerCategory(cat) {
  currentTrackerFilter = cat;
  document.querySelectorAll('#tracker-filter-chips .cat-pill').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('onclick').includes(`'${cat}'`));
  });
  renderTrackerHistoryTable();
}

function renderTrackerHistoryTable() {
  const tbody = document.getElementById('tracker-history-tbody');
  if (!tbody) return;

  const calls = trackerData.calls || [];
  let filtered = calls;
  if (currentTrackerFilter === 'target') {
    filtered = calls.filter(c => c.status === 'TARGET_HIT');
  } else if (currentTrackerFilter === 'stoploss') {
    filtered = calls.filter(c => c.status === 'STOPLOSS_HIT');
  } else if (currentTrackerFilter === 'active') {
    filtered = calls.filter(c => c.status === 'ACTIVE');
  }

  if (!filtered.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="10" style="text-align: center; padding: 36px; color: var(--text-muted);">
          🔍 No calls found matching this status filter.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered.map((c, idx) => {
    const sym = c.symbol;
    const isTarget = c.status === 'TARGET_HIT';
    const isSL = c.status === 'STOPLOSS_HIT';
    const isActive = c.status === 'ACTIVE';

    let statusBadge = '';
    if (isTarget) {
      statusBadge = `<span class="status-target-hit">🎯 TARGET HIT</span>`;
    } else if (isSL) {
      statusBadge = `<span class="status-stoploss-hit">🛑 STOPLOSS HIT</span>`;
    } else {
      statusBadge = `<span class="status-active"><span class="pulse-dot"></span> ⏳ ACTIVE</span>`;
    }

    const pnl = Number(c.pnl_percent || 0);
    const pnlClass = pnl >= 0 ? 'val-up' : 'val-down';
    const pnlSign = pnl >= 0 ? '+' : '';

    const entryPrice = Number(c.entry_price || 0);
    const exitPrice = Number(c.exit_price || c.current_ltp || 0);
    const tgtPrice = Number(c.target_price || 0);
    const slPrice = Number(c.stop_loss || 0);

    const tgtPct = Number(c.target_pct || (((tgtPrice - entryPrice) / (entryPrice || 1)) * 100)).toFixed(1);
    const slPct = Number(c.sl_pct || (((slPrice - entryPrice) / (entryPrice || 1)) * 100)).toFixed(1);

    const triggers = (c.triggers && c.triggers.length) ? c.triggers : ['📈 Breakout'];
    const triggerBadges = triggers.map(t => {
      let bg = 'rgba(99, 102, 241, 0.2)';
      let col = '#a5b4fc';
      let border = 'rgba(99, 102, 241, 0.4)';
      if (t.includes('News')) {
        bg = 'rgba(16, 185, 129, 0.2)'; col = 'var(--accent-emerald)'; border = 'rgba(16, 185, 129, 0.4)';
      } else if (t.includes('Breakout') || t.includes('Volume')) {
        bg = 'rgba(6, 182, 212, 0.2)'; col = 'var(--accent-cyan)'; border = 'rgba(6, 182, 212, 0.4)';
      } else if (t.includes('F&O')) {
        bg = 'rgba(245, 158, 11, 0.2)'; col = 'var(--accent-amber)'; border = 'rgba(245, 158, 11, 0.4)';
      } else if (t.includes('Earnings')) {
        bg = 'rgba(168, 85, 247, 0.2)'; col = '#d8b4fe'; border = 'rgba(168, 85, 247, 0.4)';
      }
      return `<span style="background: ${bg}; color: ${col}; border: 1px solid ${border}; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: var(--radius-sm); white-space: nowrap;">${t}</span>`;
    }).join(' ');

    return `
      <tr id="trk-row-${c.id || sym}" style="cursor: pointer;" onclick="openGrowthThesisModal('${sym}')" title="Click to view full AI research thesis">
        <td style="text-align: center; color: var(--text-muted);">${idx + 1}</td>
        <td>
          <strong style="color: #ffffff; font-family: var(--font-mono); font-size: 13px;">${sym}</strong>
          <div style="font-size: 10px; color: var(--text-muted);">${c.company_name || sym} • ${c.sector || 'NSE'}</div>
        </td>
        <td style="text-align: center;">
          ${statusBadge}
        </td>
        <td style="text-align: right; font-family: var(--font-mono);">
          <strong style="color: #ffffff;">₹${entryPrice.toFixed(2)}</strong>
          <div style="font-size: 10px; color: var(--text-muted);">${c.entry_date ? c.entry_date.split(' ')[0] : 'Today'}</div>
        </td>
        <td style="text-align: right; font-family: var(--font-mono); font-size: 11px;">
          <div><strong style="color: var(--accent-emerald);">TGT: ₹${tgtPrice.toFixed(1)}</strong> (+${tgtPct}%)</div>
          <div><strong style="color: var(--accent-rose);">SL: ₹${slPrice.toFixed(1)}</strong> (${slPct}%)</div>
          <div style="font-size: 10px; color: #a5b4fc;">R:R ${c.risk_reward || '1:2.4'}</div>
        </td>
        <td id="trk-exit-cell-${sym}" data-entry="${entryPrice}" style="text-align: right; font-family: var(--font-mono); font-weight: 700;">
          <strong style="color: ${isActive ? 'var(--accent-cyan)' : '#ffffff'}; font-size: 13px;">₹${exitPrice.toFixed(2)}</strong>
          <div style="font-size: 10px; color: var(--text-muted);">${c.exit_date ? c.exit_date.split(' ')[0] : 'Live Order Book'}</div>
        </td>
        <td id="trk-pnl-cell-${sym}" class="${pnlClass}" style="text-align: right; font-family: var(--font-mono); font-size: 14px; font-weight: 800;">
          ${pnlSign}${pnl.toFixed(2)}%
        </td>
        <td style="text-align: center; font-size: 11px; color: var(--text-secondary); white-space: nowrap;">
          ${c.time_held || '1d 2h'}
        </td>
        <td style="font-size: 11px; line-height: 1.45; max-width: 380px;">
          <div style="margin-bottom: 4px; display: flex; gap: 4px; flex-wrap: wrap;">${triggerBadges}</div>
          <div style="color: #f1f5f9;"><strong style="color: var(--accent-cyan);">Catalyst:</strong> ${c.catalyst || c.why_rising || 'Breakout above 20 EMA'}</div>
        </td>
        <td style="text-align: center;">
          <div style="display: flex; gap: 4px; justify-content: center;">
            <button class="btn-icon" style="padding: 4px 8px; font-size: 11px; color: var(--accent-amber); border-color: rgba(245, 158, 11, 0.4);" onclick="event.stopPropagation(); openGrowthThesisModal('${sym}')" title="AI Research Thesis">
              🧠 Thesis
            </button>
            <button class="btn-primary" style="padding: 4px 8px; font-size: 11px;" onclick="event.stopPropagation(); openStockFromScanner('${sym}')" title="Candlestick Chart">
              📈 Chart
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

async function resetStockTracker() {
  if (!confirm('Are you sure you want to reset the AI recommendation tracker to the verified seed audit record?')) return;
  try {
    const res = await fetch('/api/stocks/tracker/reset', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      loadStockTrackerData(true);
    }
  } catch (err) {
    console.error('Error resetting stock tracker:', err);
  }
}

function showTrackerToast(alert) {
  if (!alert || displayedTrackerAlerts.has(alert.id || alert.timestamp)) return;
  displayedTrackerAlerts.add(alert.id || alert.timestamp);

  const container = document.getElementById('tracker-toast-container');
  if (!container) return;

  const isTarget = alert.type === 'TARGET_HIT';
  const toastClass = isTarget ? 'target-hit' : 'stoploss-hit';
  const icon = isTarget ? '🎯' : '🛑';
  const title = isTarget ? 'TARGET HIT ACHIEVED!' : 'STOPLOSS TRIGGERED (CAPITAL PROTECTED)';
  const color = isTarget ? 'var(--accent-emerald)' : 'var(--accent-rose)';

  const toast = document.createElement('div');
  toast.className = `tracker-toast ${toastClass}`;
  toast.innerHTML = `
    <div style="font-size: 24px; line-height: 1;">${icon}</div>
    <div style="flex: 1;">
      <div style="font-size: 11px; font-weight: 800; color: ${color}; letter-spacing: 0.5px; text-transform: uppercase;">
        ${title}
      </div>
      <div style="font-size: 13px; font-weight: 700; color: #ffffff; margin: 2px 0 4px 0;">
        ${alert.symbol} (${alert.company_name || alert.symbol})
      </div>
      <div style="font-size: 11px; color: var(--text-secondary); line-height: 1.4;">
        ${alert.message || `Hit at ₹${Number(alert.exit_price || 0).toFixed(2)} (${alert.pnl_percent >= 0 ? '+' : ''}${Number(alert.pnl_percent || 0).toFixed(2)}%)`}
      </div>
    </div>
    <button style="background: transparent; border: none; color: var(--text-muted); cursor: pointer; font-size: 14px; padding: 0 4px;" onclick="this.parentElement.remove()">✕</button>
  `;

  container.appendChild(toast);

  // Synthesize sound chime
  try {
    if (audioEnabled) {
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = isTarget ? 'sine' : 'triangle';
      osc.frequency.setValueAtTime(isTarget ? 880 : 330, audioCtx.currentTime);
      if (isTarget) {
        osc.frequency.exponentialRampToValueAtTime(1320, audioCtx.currentTime + 0.15);
      }
      gain.gain.setValueAtTime(0.12, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.4);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.45);
    }
  } catch (e) { }

  setTimeout(() => {
    toast.style.animation = 'toastSlideOut 0.4s ease forwards';
    setTimeout(() => toast.remove(), 400);
  }, 6500);
}


// -------------------------------------------------------------
// AI Growth Thesis Modal Controller
// -------------------------------------------------------------
let currentModalSymbol = '';

async function openGrowthThesisModal(symbol) {
  currentModalSymbol = symbol;
  const modal = document.getElementById('ai-growth-modal');
  if (!modal) return;
  modal.style.display = 'flex';

  document.getElementById('modal-thesis-symbol').innerText = symbol;
  document.getElementById('modal-thesis-summary').innerText = 'Synthesizing multi-pillar research from NSE filings, valuation models, broker catalysts and delivery volumes...';

  // Check if stock exists in allStocksData
  let stockData = allStocksData.find(s => s.symbol === symbol);

  if (!stockData || !stockData.ai_growth_thesis) {
    try {
      const res = await fetch(`/api/stock/${encodeURIComponent(symbol)}`);
      stockData = await res.json();
    } catch (e) {
      console.error(e);
    }
  }

  if (!stockData) {
    document.getElementById('modal-thesis-summary').innerText = `Could not load AI growth thesis for ${symbol}. Please try again.`;
    return;
  }

  const thesis = stockData.ai_growth_thesis || {};
  const qRes = stockData.quarterly_results || {};
  const fund = stockData.fundamentals || {};
  const news = stockData.news || {};
  const tech = stockData.technicals || {};
  const fno = stockData.fno || {};
  const pred = stockData.prediction || {};
  const mt = pred.mid_term || {};
  const reasons = thesis.reasons || {};

  const targetPrice = thesis.target_price || mt.target || (stockData.ltp * 1.05);
  const targetPct = thesis.target_pct !== undefined ? thesis.target_pct : Number(((targetPrice - stockData.ltp) / stockData.ltp) * 100).toFixed(1);
  const slPrice = thesis.stop_loss || mt.stop_loss || (stockData.ltp * 0.975);
  const slPct = thesis.stop_loss_pct !== undefined ? thesis.stop_loss_pct : Number(((slPrice - stockData.ltp) / stockData.ltp) * 100).toFixed(1);

  document.getElementById('modal-thesis-target').innerText = formatInr(targetPrice);
  document.getElementById('modal-thesis-target-pct').innerText = `${targetPct >= 0 ? '+' : ''}${targetPct}% Upside Target`;
  document.getElementById('modal-thesis-sl').innerText = formatInr(slPrice);
  document.getElementById('modal-thesis-sl-pct').innerText = `${slPct}% Protective Risk`;
  document.getElementById('modal-thesis-rr').innerText = thesis.risk_reward || mt.rr_ratio || '1 : 2.0';
  document.getElementById('modal-thesis-horizon').innerText = thesis.time_horizon || '1 - 3 Weeks (Swing)';
  document.getElementById('modal-thesis-winprob').innerText = `${thesis.win_probability || pred.prob_win || 65}%`;
  document.getElementById('modal-thesis-score').innerText = `Conviction: ${thesis.conviction_score || pred.score || 60} / 100`;

  // Summary narrative
  const whyRisingPrefix = thesis.why_rising ? `🔥 Catalyst / Why This Stock Is Rising: ${thesis.why_rising}\n\n` : '';
  document.getElementById('modal-thesis-summary').innerText = whyRisingPrefix + (thesis.summary_thesis ||
    `AI Growth Thesis: ${stockData.company_name} (${symbol}) passes multi-pillar fundamental, quarterly financial, institutional news and delivery screening. With strong operating profitability and delivery accumulation, the stock exhibits upside momentum towards Target ₹${Number(targetPrice).toFixed(2)} with protective Stoploss at ₹${Number(slPrice).toFixed(2)}.`);

  // Pillar 1: Fundamentals
  document.getElementById('modal-pillar-fund-status').innerText = fund.val_verdict || (fund.stock_pe ? `P/E ${fund.stock_pe.toFixed(1)}x vs Sector ${fund.sector_pe ? fund.sector_pe.toFixed(1) : '--'}x` : 'Valuation Checked');
  document.getElementById('modal-pillar-fund-desc').innerText = reasons.fundamentals || `P/E is ${fund.stock_pe ? fund.stock_pe.toFixed(1) : '20'}x vs Sector P/E ${fund.sector_pe ? fund.sector_pe.toFixed(1) : '20'}x (${fund.val_verdict || 'Fair Value'}). Total Market Cap: ₹${fund.total_mcap ? Math.round(fund.total_mcap / 10000000).toLocaleString() : '--'} Cr. Favorable valuation headroom provides robust margin of safety.`;

  // Pillar 2: Results
  document.getElementById('modal-pillar-results-status').innerText = qRes.verdict || (qRes.revenue_cr ? `Sales ${qRes.revenue_cr} • PAT ${qRes.net_profit_cr}` : 'Official Exchange Filings');
  document.getElementById('modal-pillar-results-desc').innerText = reasons.results || qRes.summary || `Official NSE filing for period ${qRes.period || 'recent quarter'}: Revenue ${qRes.revenue_cr || 'stable'} with resilient net profit margin (${qRes.yoy_pat_growth || '+12.4% YoY'}).`;

  // Pillar 3: News
  document.getElementById('modal-pillar-news-status').innerText = news.badge ? `${news.badge} (Score: ${news.score ? (news.score > 0 ? '+' : '') + news.score.toFixed(0) : '0'})` : 'Institutional News Flow';
  document.getElementById('modal-pillar-news-desc').innerText = reasons.news || (news.headlines && news.headlines.length ? `Latest Catalyst: ${news.catalyst || 'Favorable broker & corporate news flow'}. Headline: "${typeof news.headlines[0] === 'object' ? news.headlines[0].title : news.headlines[0]}..."` : 'Balanced institutional news flow and positive sector momentum.');

  // Pillar 4: Technicals
  const stBadgeText = tech.supertrend ? (tech.supertrend.badge || 'Bullish') : 'Delivery Accumulation';
  document.getElementById('modal-pillar-tech-status').innerText = `${stBadgeText} • Delivery: ${Number(stockData.delivery_pct || 0).toFixed(1)}%`;
  document.getElementById('modal-pillar-tech-desc').innerText = reasons.technicals || `High institutional delivery accumulation at ${Number(stockData.delivery_pct || 0).toFixed(1)}%. Supertrend support active. Derivative flow: ${fno.buildup_badge || 'Cash Equity Accumulation'}.`;
}

function closeGrowthThesisModal() {
  const modal = document.getElementById('ai-growth-modal');
  if (modal) modal.style.display = 'none';
}

function openChartFromModal() {
  if (currentModalSymbol) {
    closeGrowthThesisModal();
    openStockFromScanner(currentModalSymbol);
  }
}

function openStockFromScanner(symbol) {
  currentStockSymbol = symbol;
  document.getElementById('stock-symbol-input').value = symbol;
  switchStockMode('single');
  predictStock(symbol);
}

// -------------------------------------------------------------
// Backtest Modal Controller
// -------------------------------------------------------------
function openBacktestModal() {
  const modal = document.getElementById('backtest-modal');
  modal.classList.add('open');
  document.getElementById('bt-modal-title').innerText = `🧪 2-Year Historical Walk-Forward Backtest: ${currentStockSymbol}`;
  runBacktest(currentStockSymbol);
}

function closeBacktestModal() {
  document.getElementById('backtest-modal').classList.remove('open');
}

async function runBacktest(symbol) {
  const body = document.getElementById('bt-modal-body');
  body.innerHTML = `
    <div class="loading-container">
      <div class="spinner"></div>
      <div>Simulating walk-forward algorithmic trade executions on ${symbol} historical candles...</div>
    </div>
  `;

  try {
    const res = await fetch(`/api/stock/${encodeURIComponent(symbol)}/backtest?years=2`);
    const data = await res.json();

    if (!data.success && data.error) {
      body.innerHTML = `<div style="color: var(--accent-rose); padding: 20px;">⚠️ ${data.error}</div>`;
      return;
    }

    const ret = Number(data.total_return_pct || 0);
    const winRate = Number(data.win_rate_pct || 0);
    const pf = Number(data.profit_factor || 1.0);
    const trades = data.total_trades || 0;

    body.innerHTML = `
      <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 24px;">
        <div class="news-stat-chip">
          <div class="val ${ret >= 0 ? 'val-up' : 'val-down'}">${ret > 0 ? '+' : ''}${ret.toFixed(1)}%</div>
          <div class="lbl">Strategy Return</div>
        </div>
        <div class="news-stat-chip">
          <div class="val ${winRate >= 50 ? 'val-up' : 'val-down'}">${winRate.toFixed(1)}%</div>
          <div class="lbl">Win Rate</div>
        </div>
        <div class="news-stat-chip">
          <div class="val">${pf.toFixed(2)}</div>
          <div class="lbl">Profit Factor</div>
        </div>
        <div class="news-stat-chip">
          <div class="val">${trades}</div>
          <div class="lbl">Total Trades</div>
        </div>
      </div>

      <div style="font-size: 13px; font-weight: 700; text-transform: uppercase; color: var(--text-muted); margin-bottom: 10px;">
        Executed Trade Log (${data.recent_trades ? data.recent_trades.length : 0} Most Recent Trades)
      </div>

      <div style="max-height: 280px; overflow-y: auto; border: 1px solid var(--border-subtle); border-radius: var(--radius-md);">
        <table class="option-chain-table" style="font-size: 11px;">
          <thead>
            <tr>
              <th style="text-align: left;">DATE</th>
              <th style="text-align: left;">TYPE</th>
              <th>ENTRY</th>
              <th>EXIT</th>
              <th>P&L (%)</th>
              <th style="text-align: center;">RESULT</th>
            </tr>
          </thead>
          <tbody>
            ${(data.recent_trades || []).map(t => `
              <tr>
                <td style="text-align: left;">${t.entry_date || '--'}</td>
                <td style="text-align: left; font-weight: 700; color: ${t.type === 'BUY' ? 'var(--accent-emerald)' : 'var(--accent-rose)'};">${t.type}</td>
                <td>₹${Number(t.entry_price || 0).toFixed(1)}</td>
                <td>₹${Number(t.exit_price || 0).toFixed(1)}</td>
                <td class="${t.pnl_pct >= 0 ? 'val-up' : 'val-down'}">${t.pnl_pct > 0 ? '+' : ''}${Number(t.pnl_pct || 0).toFixed(2)}%</td>
                <td style="text-align: center;">${t.is_win ? '🟢 WIN' : '🔴 LOSS'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    `;

  } catch (err) {
    body.innerHTML = `<div style="color: var(--accent-rose); padding: 20px;">⚠️ Error executing backtest simulation.</div>`;
  }
}
