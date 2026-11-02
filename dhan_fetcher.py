"""
DhanHQ Live Option Chain & Market Data Connector
Direct HTTP API integration with full diagnostic visibility.
"""

import os
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(dotenv_path)


def get_next_thursday() -> str:
    """Calculates the upcoming Thursday expiry date in YYYY-MM-DD format."""
    today = datetime.now()
    days_ahead = (3 - today.weekday()) % 7
    thursday = today + timedelta(days=days_ahead)
    return thursday.strftime("%Y-%m-%d")


class DhanFetcher:
    def __init__(self, client_id: Optional[str] = None, access_token: Optional[str] = None):
        self.client_id = (client_id or os.getenv("DHAN_CLIENT_ID", "")).strip()
        self.access_token = (access_token or os.getenv("DHAN_ACCESS_TOKEN", "")).strip()
        self.base_url = "https://api.dhan.co/v2"
        self.last_error: Optional[str] = None
        
        self.session = requests.Session()
        self.session.headers.update({
            "access-token": self.access_token,
            "client-id": self.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

    def is_configured(self) -> bool:
        """Check if valid credentials are provided."""
        return bool(self.client_id and self.access_token and "YOUR_" not in self.client_id)

    def get_parsed_data(self, target_expiry: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Fetches live NIFTY option chain from DhanHQ API.
        NIFTY 50 Index Security ID is 13, Exchange segment is 'IDX_I'.
        """
        if not self.is_configured():
            self.last_error = "Dhan Client ID or Access Token is missing in .env"
            return None

        under_security_id = 13
        under_exchange_segment = "IDX_I"

        # 1. Fetch available expiry dates
        expiry_dates: List[str] = []
        try:
            exp_url = f"{self.base_url}/optionchain/expirylist"
            exp_payload = {
                "UnderlyingScrip": under_security_id,
                "UnderlyingSeg": under_exchange_segment
            }
            exp_res = self.session.post(exp_url, json=exp_payload, timeout=8)
            
            if exp_res.status_code == 200:
                exp_data = exp_res.json()
                if isinstance(exp_data, dict) and exp_data.get("status") == "success":
                    expiry_dates = exp_data.get("data", [])
                elif isinstance(exp_data, list):
                    expiry_dates = exp_data
            else:
                self.last_error = f"ExpiryList HTTP {exp_res.status_code}: {exp_res.text[:150]}"
        except Exception as e:
            self.last_error = f"ExpiryList connection error: {e}"

        if not target_expiry:
            target_expiry = expiry_dates[0] if expiry_dates else get_next_thursday()

        # 2. Fetch Option Chain
        try:
            oc_url = f"{self.base_url}/optionchain"
            oc_payload = {
                "UnderlyingScrip": under_security_id,
                "UnderlyingSeg": under_exchange_segment,
                "Expiry": target_expiry
            }
            res = self.session.post(oc_url, json=oc_payload, timeout=8)

            if res.status_code != 200:
                self.last_error = f"HTTP {res.status_code}: {res.text[:200]} (Expiry: {target_expiry})"
                return None

            response = res.json()
            if not isinstance(response, dict) or response.get("status") != "success":
                remark = response.get("remarks") or response.get("message") or response.get("error") or str(response)
                self.last_error = f"Dhan API returned: {remark}"
                return None

            data = response.get("data", {})
            spot_price = float(data.get("last_price", 0.0))
            oc = data.get("oc", {})

            strikes_data: List[Dict[str, Any]] = []

            for strike_str, strike_info in oc.items():
                try:
                    strike = float(strike_str)
                except ValueError:
                    continue

                ce = strike_info.get("ce", {})
                pe = strike_info.get("pe", {})

                strikes_data.append({
                    "strike": strike,
                    # CE
                    "ce_oi": ce.get("oi", 0),
                    "ce_chg_oi": ce.get("oi_change", 0),
                    "ce_ltp": float(ce.get("last_price", 0.0)),
                    "ce_volume": ce.get("volume", 0),
                    "ce_iv": float(ce.get("implied_volatility", 0.0)),
                    # PE
                    "pe_oi": pe.get("oi", 0),
                    "pe_chg_oi": pe.get("oi_change", 0),
                    "pe_ltp": float(pe.get("last_price", 0.0)),
                    "pe_volume": pe.get("volume", 0),
                    "pe_iv": float(pe.get("implied_volatility", 0.0)),
                })

            strikes_data.sort(key=lambda x: x["strike"])

            return {
                "symbol": "NIFTY",
                "spot_price": spot_price,
                "timestamp": data.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                "expiry_dates": expiry_dates,
                "current_expiry": target_expiry,
                "strikes": strikes_data,
                "is_simulation": False
            }

        except Exception as e:
            self.last_error = f"Dhan API Exception: {e}"
            return None
