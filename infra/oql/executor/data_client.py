"""
OptionDataClient fetches option chains with greeks from a REST API and
flattens them into a normalized pandas.DataFrame.
"""
import requests
import pandas as pd
from datetime import datetime

class OptionDataClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 19019):
        self.base_url = f"http://{host}:{port}"

    def get_chain_data(self, ticker: str, as_of_date: str):
        """Return (df_chain, spot_price). df_chain contains one row per option contract."""
        params = {
            "ticker": ticker,
            "date": as_of_date,
            "expiry_days": 365,
            "require_greek": 1,
        }
        try:
            print(f"📡 Fetching data from {self.base_url} for {ticker}...")
            resp = requests.get(f"{self.base_url}/query/chain", params=params, timeout=10)
            payload = resp.json()
            if isinstance(payload, dict) and "error" in payload:
                print(f"⚠️ API Error: {payload['error']}")
                return pd.DataFrame(), 0.0

            spot = float((payload.get("meta") or {}).get("center_price", 0.0) or 0.0)

            rows = []
            for opt_type, chains in (payload.get("data") or {}).items():
                for expiry_str, contracts in (chains or {}).items():
                    for c in contracts or []:
                        strike = float(c.get("strike", 0.0) or 0.0)
                        price = float(c.get("close", 0.0) or 0.0)
                        volume = float(c.get("volume", 0.0) or 0.0)
                        row = {
                            "symbol": ticker,
                            "contract_ticker": c.get("ticker"),
                            "type": opt_type,  # 'C' or 'P'
                            "expiry_date": c.get("expiry"),
                            "strike": strike,
                            "price": price,
                            "volume": volume,
                            "delta": c.get("delta"),
                            "gamma": c.get("gamma"),
                            "theta": c.get("theta"),
                            "vega":  c.get("vega"),
                            "iv":    c.get("iv"),
                            "rho":   c.get("rho"),
                        }
                        # Days to expiry
                        try:
                            exp_dt = datetime.strptime(row["expiry_date"], "%Y-%m-%d")
                            curr_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
                            row["dte"] = (exp_dt - curr_dt).days
                        except Exception:
                            row["dte"] = None

                        # Moneyness ratio: spot / strike
                        row["moneyness_ratio"] = (spot / strike) if strike > 0 else 0.0
                        rows.append(row)

            df = pd.DataFrame(rows)
            if not df.empty:
                df = df.dropna(subset=["delta", "price"], how="any")
            return df, spot

        except Exception as e:
            print(f"❌ Connection Failed: {e}")
            return pd.DataFrame(), 0.0
