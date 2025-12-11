import math
from datetime import datetime
import pandas as pd
import numpy as np
from scipy.stats import norm
from scipy.optimize import newton


# --- Black-Scholes formula ---
def bs_price(S, K, T, r, sigma, option_type="call"):
    """Compute Black-Scholes price for call or put."""
    if T <= 0:
        return max(0.0, (S - K) if option_type == "call" else (K - S))

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option_type == "call":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


# --- Implied volatility solver ---
def implied_volatility(
    option_price, S, K, expiry_date, current_date, r, option_type="call"
):
    """Solve for implied volatility using Newton's method."""
    # expiry_date = pd.to_datetime(expiry_date)
    # current_date = pd.to_datetime(current_date)
    T = (expiry_date - current_date).days / 365.0

    if T <= 0 or S <= 0 or K <= 0:
        return float("nan")

    def objective(sigma):
        return bs_price(S, K, T, r, sigma, option_type) - option_price

    try:
        iv = newton(objective, 0.2, tol=1e-6, maxiter=100)
        return iv if iv > 0 else float("nan")
    except RuntimeError:
        return float("nan")


def implied_vol(option_price, S, K, T, r, option_type="call"):
    if T <= 0 or S <= 0 or K <= 0:
        return np.nan

    def f(sigma):
        return bs_price(S, K, T, r, sigma, option_type) - option_price

    try:
        iv = newton(f, 0.2, tol=1e-6, maxiter=100)
        return iv if iv > 0 else np.nan
    except RuntimeError:
        return np.nan


# ----- Compute IV Series -----
def compute_iv_series(chain_df, underlying_price, current_date, rate=0.05):
    """
    Compute implied volatility for a single expiry level.
    Parameters:
        chain_df: DataFrame with columns ['ticker','strike','close','expiry']
        underlying_price: float, current underlying price
        current_date: datetime
        rate: float, annual risk-free rate
    Returns:
        DataFrame with columns ['ticker','strike','option_type','iv']
    """
    iv_rows = []
    for _, row in chain_df.iterrows():
        ticker = row["ticker"]
        option_type = "call" if "C" in ticker else "put"
        K = float(row["strike"])
        price = float(row["close"])
        expiry = pd.to_datetime(row["expiry"])
        current_date = pd.to_datetime(current_date)

        T = (expiry - current_date).days / 365.0
        iv = implied_vol(price, underlying_price, K, T, rate, option_type)
        iv_rows.append(
            {"ticker": ticker, "strike": K, "option_type": option_type, "iv": iv}
        )
    return pd.DataFrame(iv_rows).sort_values("strike").reset_index(drop=True)


# --- Example usage ---
if __name__ == "__main__":
    # Example: AAPL call option data
    S = 180.00  # current stock price
    K = 185.00  # strike
    r = 0.05  # risk-free rate (5%)
    option_price = 2.50  # close price of the option
    expiry_date = datetime(2025, 11, 15)
    current_date = datetime(2025, 10, 23)
    option_type = "call"

    iv = implied_volatility(
        option_price, S, K, expiry_date, current_date, r, option_type
    )
    print(f"Implied Volatility: {iv:.4f}")

    # Sample chain (same expiry)
    data = {
        "ticker": [
            "O:SPY250113C00497000",
            "O:SPY250113C00499000",
            "O:SPY250113C00500000",
            "O:SPY250113P00500000",
        ],
        "strike": [497, 499, 500, 500],
        "close": [81.27, 78.06, 77.25, 77.00],
        "expiry": ["2025-01-13"] * 4,
    }
    chain = pd.DataFrame(data)

    # Current conditions
    underlying_price = 570.0
    current_date = datetime(2024, 10, 23)
    rate = 0.05

    iv_series = compute_iv_series(chain, underlying_price, current_date, rate)
    print(iv_series)
