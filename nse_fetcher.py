"""
NSE Option Chain & Live Market Data Fetcher
Fetches live NIFTY option chain, open interest, volume, and spot price directly from NSE India,
using browser-grade TLS session handling (curl_cffi / nsepython) to bypass Akamai WAF blocks.
"""

import time
import random
import warnings
from datetime import datetime
from typing import Dict, Any, Optional, List

# Suppress warnings from underlying libraries
warnings.filterwarnings("ignore")


class NSEFetcher:
    def __init__(self, symbol: str = "NIFTY", use_mock_on_failure: bool = False):
        self.symbol = symbol.upper()
        self.use_mock_on_failure = use_mock_on_failure
        self.last_error: Optional[str] = None
        self._mock_spot = 22950.0
        self._cached_data: Optional[Dict[str, Any]] = None
        self._cache_time: float = 0.0

    def prewarm(self):
        """Pre-warms the session cookies once at startup so the first loop fetch is instantaneous."""
        try:
            from nsepython import nse_optionchain_scrapper
            data = nse_optionchain_scrapper(self.symbol)
            if data and isinstance(data, dict):
                self._cached_data = data
                self._cache_time = time.time()
        except Exception:
            pass

    def fetch_option_chain_raw(self, max_retries: int = 2) -> Optional[Dict[str, Any]]:
        """
        Fetches raw option chain JSON directly from NSE India using browser TLS fingerprinting.
        Returns cached payload if fetched within the last 1.5s to prevent hammering the exchange.
        """
        now = time.time()
        if self._cached_data and (now - self._cache_time) < 1.5:
            return self._cached_data

        for attempt in range(1, max_retries + 1):
            try:
                # 1. Primary method: nsepython with curl_cffi Chrome impersonation (30ms once warmed)
                try:
                    from nsepython import nse_optionchain_scrapper
                    data = nse_optionchain_scrapper(self.symbol)
                    if data and isinstance(data, dict) and "data" in data and len(data["data"]) > 0:
                        self.last_error = None
                        self._cached_data = data
                        self._cache_time = time.time()
                        return data
                except Exception as ex:
                    self.last_error = f"nsepython fetch failed: {ex}"

                # 2. Secondary fallback: Direct curl_cffi session with NextApi endpoint
                try:
                    from curl_cffi import requests as c_requests
                    s = c_requests.Session(impersonate="chrome124")
                    s.headers.update({
                        "Referer": "https://www.nseindia.com/option-chain",
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json, text/plain, */*"
                    })
                    # Use current active NextApi endpoint
                    url = f"https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolDerivativesData&symbol={self.symbol}"
                    res = s.get(url, timeout=5)
                    if res.status_code == 200:
                        json_data = res.json()
                        if "data" in json_data:
                            self._cached_data = json_data
                            self._cache_time = time.time()
                            return json_data
                except Exception as ex2:
                    self.last_error = f"curl_cffi direct fetch failed: {ex2}"

                time.sleep(0.5)
            except Exception as e:
                self.last_error = str(e)
                time.sleep(0.5)

        return self._cached_data if self._cached_data else None

    def get_parsed_data(self, target_expiry: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Parses option chain and returns clean structured data with live strikes, LTP, and OI.
        Falls back to realistic simulation only if enabled and network is completely unreachable.
        """
        raw = self.fetch_option_chain_raw()
        if not raw or not raw.get("data"):
            if self.use_mock_on_failure:
                return self.get_mock_data()
            return None

        raw_data = raw.get("data", [])
        timestamp = raw.get("timestamp", datetime.now().strftime("%d-%b-%Y %H:%M:%S"))

        # Extract all available expiry dates
        expiry_dates: List[str] = []
        for item in raw_data:
            exp = item.get("expiryDate")
            if exp and exp not in expiry_dates:
                expiry_dates.append(exp)

        if not target_expiry and expiry_dates:
            target_expiry = expiry_dates[0]

        strikes_data = []
        spot_price = 0.0

        for item in raw_data:
            if item.get("expiryDate") != target_expiry:
                continue

            try:
                strike = int(float(str(item.get("strikePrice")).strip()))
            except (ValueError, TypeError):
                continue

            ce_data = item.get("CE") or {}
            pe_data = item.get("PE") or {}

            # Find spot price from underlyingValue if not yet set
            if not spot_price:
                val = ce_data.get("underlyingValue") or pe_data.get("underlyingValue")
                if val:
                    spot_price = float(val)

            strikes_data.append({
                "strike": strike,
                "ce_oi": int(ce_data.get("openInterest", 0)),
                "ce_chg_oi": int(ce_data.get("changeinOpenInterest", 0)),
                "ce_ltp": float(ce_data.get("lastPrice", 0.0)),
                "ce_volume": int(ce_data.get("totalTradedVolume", 0)),
                "ce_iv": float(ce_data.get("impliedVolatility", 0.0)),
                "ce_change": float(ce_data.get("change", 0.0)),
                "ce_pchange": float(ce_data.get("pchange", 0.0)),
                "pe_oi": int(pe_data.get("openInterest", 0)),
                "pe_chg_oi": int(pe_data.get("changeinOpenInterest", 0)),
                "pe_ltp": float(pe_data.get("lastPrice", 0.0)),
                "pe_volume": int(pe_data.get("totalTradedVolume", 0)),
                "pe_iv": float(pe_data.get("impliedVolatility", 0.0)),
                "pe_change": float(pe_data.get("change", 0.0)),
                "pe_pchange": float(pe_data.get("pchange", 0.0)),
            })

        strikes_data.sort(key=lambda x: x["strike"])

        if not strikes_data:
            if self.use_mock_on_failure:
                return self.get_mock_data()
            return None

        if not spot_price and strikes_data:
            spot_price = float(strikes_data[len(strikes_data) // 2]["strike"])

        return {
            "symbol": self.symbol,
            "spot_price": spot_price,
            "timestamp": timestamp,
            "expiry_dates": expiry_dates,
            "current_expiry": target_expiry,
            "strikes": strikes_data,
            "is_simulation": False
        }

    def get_mock_data(self) -> Dict[str, Any]:
        """
        Generates simulated NIFTY option chain ticks when markets are closed.
        """
        self._mock_spot += random.choice([-5.0, -2.5, 0.0, 2.5, 5.0])
        spot = round(self._mock_spot, 2)
        atm = round(spot / 50) * 50

        strikes_data = []
        for offset in range(-7, 8):
            strike = int(atm + offset * 50)
            dist = (strike - spot)
            ce_intrinsic = max(0.0, spot - strike)
            pe_intrinsic = max(0.0, strike - spot)
            time_val = max(15.0, 160.0 - abs(dist) * 0.45)

            ce_ltp = round(ce_intrinsic + time_val + random.uniform(-2, 2), 2)
            pe_ltp = round(pe_intrinsic + time_val + random.uniform(-2, 2), 2)

            base_ce_oi = int(120000 + max(0, 100000 - abs(strike - (atm + 100)) * 300))
            base_pe_oi = int(130000 + max(0, 120000 - abs(strike - (atm - 100)) * 300))

            strikes_data.append({
                "strike": strike,
                "ce_oi": base_ce_oi,
                "ce_chg_oi": random.randint(-15000, 25000),
                "ce_ltp": ce_ltp,
                "ce_volume": random.randint(50000, 500000),
                "ce_iv": 13.5,
                "pe_oi": base_pe_oi,
                "pe_chg_oi": random.randint(-10000, 35000),
                "pe_ltp": pe_ltp,
                "pe_volume": random.randint(50000, 500000),
                "pe_iv": 14.0,
            })

        now_str = datetime.now().strftime("%d-%b-%Y %H:%M:%S")
        return {
            "symbol": self.symbol,
            "spot_price": spot,
            "timestamp": now_str,
            "expiry_dates": ["27-Oct-2026", "03-Nov-2026"],
            "current_expiry": "27-Oct-2026",
            "strikes": strikes_data,
            "is_simulation": True
        }


if __name__ == "__main__":
    fetcher = NSEFetcher(symbol="NIFTY", use_mock_on_failure=False)
    print("Testing Live NSE Option Chain Fetcher...")
    result = fetcher.get_parsed_data()
    if result:
        print("Data source: LIVE NSE INDIA WEB FEED")
        print(f"Spot: {result['spot_price']} | Timestamp: {result['timestamp']} | Expiry: {result['current_expiry']}")
        print(f"Total Strikes: {len(result['strikes'])}")
    else:
        print("Failed to fetch live data:", fetcher.last_error)
