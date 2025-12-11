"""
OptionDataClient fetches option chains with greeks from a REST API and
flattens them into a normalized pandas.DataFrame.
"""

import requests
import pandas as pd
from datetime import datetime
from typing import Optional


class OptionDataClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 19019):
        self.base_url = f"http://{host}:{port}"

    def get_chain_data(
        self,
        ticker: str,
        as_of_date: str,
        *,
        opt_type: Optional[str] = None,
        expiry_days: int = 365,
        strike_gt: Optional[float] = None,
        strike_lt: Optional[float] = None,
        level: Optional[int] = None,
        require_greek: bool = True,
    ):
        """
        Return (df_chain, spot_price). df_chain contains one row per option contract.

        Parameters
        ----------
        ticker : str
            Underlying symbol, e.g. 'NVDA'.
        as_of_date : str
            Trade date 'YYYY-MM-DD'.
        opt_type : {'c','p',None}, optional
            If 'c' or 'p', filter chain on calls or puts server-side.
            If None, both calls and puts are returned.
        expiry_days : int
            Max days-to-expiry filter for the chain.
        strike_gt : float, optional
            Minimum strike to request from the API.
        strike_lt : float, optional
            Maximum strike to request from the API.
        level : int, optional
            Number of strikes above/below center price (API `level` parameter).
        require_greek : bool
            If True, request server to compute IV/Greeks for all options.
        """
        params = {
            "ticker": ticker,
            "date": as_of_date,
            "expiry_days": int(expiry_days),
            "require_greek": 1 if require_greek else 0,
        }

        if opt_type is not None:
            # API expects 'c' or 'p'
            ot = opt_type.lower()
            if ot in ("c", "p"):
                params["type"] = ot

        if strike_gt is not None:
            params["strike_gt"] = float(strike_gt)
        if strike_lt is not None:
            params["strike_lt"] = float(strike_lt)
        if level is not None:
            params["level"] = int(level)

        try:
            print(f"📡 Fetching data from {self.base_url}/query/chain for {ticker} with params={params}...")
            resp = requests.get(
                f"{self.base_url}/query/chain", params=params, timeout=10
            )
            payload = resp.json()
            if isinstance(payload, dict) and "error" in payload:
                print(f"⚠️ API Error: {payload['error']}")
                return pd.DataFrame(), 0.0

            spot = float((payload.get("meta") or {}).get("center_price", 0.0) or 0.0)

            rows = []
            for opt_type_resp, chains in (payload.get("data") or {}).items():
                for expiry_str, contracts in (chains or {}).items():
                    for c in contracts or []:
                        strike = float(c.get("strike", 0.0) or 0.0)
                        price = float(c.get("close", 0.0) or 0.0)
                        volume = float(c.get("volume", 0.0) or 0.0)
                        row = {
                            "symbol": ticker,
                            "contract_ticker": c.get("ticker"),
                            "type": opt_type_resp,  # 'C' or 'P'
                            "expiry_date": c.get("expiry"),
                            "strike": strike,
                            "price": price,
                            "volume": volume,
                            "delta": c.get("delta"),
                            "gamma": c.get("gamma"),
                            "theta": c.get("theta"),
                            "vega": c.get("vega"),
                            "iv": c.get("iv"),
                            "rho": c.get("rho"),
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
