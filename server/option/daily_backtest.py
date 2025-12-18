"""
Option Strategy Backtesting Server (Updated)

- Supports multi-leg, multi-direction (buy/sell), multi-expiry spreads
- Uses external Financial Data & Options API (given in the prompt)
- Assumes all legs open on the same date (for now)
- Assumes all legs share the same underlying (for now)

Changes vs previous version:
- Delta is computed from portfolio vs underlying intraday move (no Greek API calls)
- Portfolio value handles shorts as: value = premium - current_price
"""
import logging
logger = logging.getLogger("backtest")
logging.basicConfig(level=logging.INFO)

import traceback

import os
import re
import math
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.encoders import jsonable_encoder


DATE_FMT = "%Y-%m-%d"

BASE_URL = os.getenv("DATA_API_BASE_URL", "http://0.0.0.0:19787")

# -------------------------
# Data models
# -------------------------

class LegInput(BaseModel):
    ticker: str          # option ticker, e.g. O:AAPL260116P00160000
    direction: str       # "buy" or "sell"
    number: int          # qty in shares notion, e.g. 100
    at_price: float      # entry price (premium)
    date: str            # entry date YYYY-MM-DD


@dataclass
class Leg:
    ticker: str
    direction: str
    number: int
    at_price: float
    date: str
    underlying: str
    expiry: str

@dataclass
class LegDailyPoint:
    ticker: str
    direction: str
    number: int
    open: float
    high: float
    low: float
    close: float
    profit_close: float  
    
@dataclass
class SummaryMetrics:
    start_date: str
    end_date: str
    underlying: str
    initial_cost: float
    final_value: float
    final_profit: float
    max_profit: float
    max_loss: float
    max_drawdown: float
    sharpe_ratio: float


@dataclass
class DailyPoint:
    date: str
    open: float
    high: float
    low: float
    close: float
    delta: float
    ret: Optional[float]
    cum_pnl: float
    drawdown: float
    intraday_var: Optional[float]
    legs: List[LegDailyPoint] 


@dataclass
class BacktestResponse:
    summary: SummaryMetrics
    daily: List[DailyPoint]


class BacktestRequest(BaseModel):
    legs: List[LegInput]


# -------------------------
# Helpers
# -------------------------

def parse_option_ticker(ticker: str) -> Tuple[str, str]:
    """
    Parse option ticker like:
      O:AAPL260116P00160000
    -> underlying = AAPL
       expiry     = 2026-01-16
    """
    m = re.match(r"^O:(?P<under>[A-Z0-9\.]+)(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<cp>[CP])(?P<strike>\d{8})$", ticker)
    if not m:
        raise ValueError(f"Invalid option ticker format: {ticker}")
    under = m.group("under")
    yy = int(m.group("yy"))
    mm = int(m.group("mm"))
    dd = int(m.group("dd"))
    expiry = datetime(2000 + yy, mm, dd).strftime(DATE_FMT)
    return under, expiry


def build_legs(legs_in: List[LegInput]) -> List[Leg]:
    """
    Validate and normalize legs.
    """
    if not legs_in:
        raise ValueError("No legs provided")

    legs: List[Leg] = []
    for li in legs_in:
        if li.direction not in ("buy", "sell"):
            raise ValueError(f"Invalid direction: {li.direction}")
        if li.number <= 0:
            raise ValueError(f"Invalid number: {li.number}")
        if li.at_price is None:
            raise ValueError("Missing at_price")
        underlying, expiry = parse_option_ticker(li.ticker)
        legs.append(
            Leg(
                ticker=li.ticker,
                direction=li.direction,
                number=int(li.number),
                at_price=float(li.at_price),
                date=li.date,
                underlying=underlying,
                expiry=expiry,
            )
        )

    # Basic consistency checks
    entry_date = legs[0].date
    under0 = legs[0].underlying
    for leg in legs:
        if leg.date != entry_date:
            raise ValueError("All legs must share the same entry date (for now)")
        if leg.underlying != under0:
            raise ValueError("All legs must share the same underlying (for now)")

    return legs



def get_trading_days() -> List[pd.Timestamp]:
    url = f"{BASE_URL}/collect/trading_days"
    resp = requests.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch trading days: {resp.text}")
    data = resp.json()
    days = [pd.to_datetime(d) for d in data["trading_days"]]
    return sorted(days)


def fetch_option_history(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Returns DataFrame indexed by date with columns ['open','high','low','close'].
    """
    url = f"{BASE_URL}/query/option_history"
    params = {"ticker": ticker, "start_date": start_date, "end_date": end_date}
    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch option history for {ticker}: {resp.text}")
    data = resp.json()
    if data.get("count", 0) == 0:
        raise RuntimeError(f"No option history for {ticker} between {start_date} and {end_date}")
    df = pd.DataFrame(data["history"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    cols = ["open", "high", "low", "close"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"Missing columns {missing} in option_history for {ticker}")
    return df[cols]


def fetch_stock_history(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetch underlying stock OHLC for delta estimation.
    """
    url = f"{BASE_URL}/query/stock_history"
    params = {"ticker": ticker, "start_date": start_date, "end_date": end_date}
    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch stock history for {ticker}: {resp.text}")
    data = resp.json()
    if data.get("count", 0) == 0:
        raise RuntimeError(f"No stock history for {ticker} between {start_date} and {end_date}")
    df = pd.DataFrame(data["history"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    cols = ["open", "high", "low", "close"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"Missing columns {missing} in stock_history for {ticker}")
    return df[cols]


def prepare_leg_ohlc(
    leg: Leg,
    full_calendar: pd.DatetimeIndex,
    hist_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Reindex to full_calendar, forward fill, and set value 0 after expiry.
    """
    df = hist_df.reindex(full_calendar)
    df = df.ffill()

    expiry_dt = pd.to_datetime(leg.expiry)
    # After expiry, option value goes to 0 (simplified; ignores exercise)
    df.loc[df.index > expiry_dt, ["open", "high", "low", "close"]] = 0.0

    return df


def garman_klass_variance(row: pd.Series) -> float:
    """
    Garman-Klass variance estimator from OHLC.
    Returns NaN if inputs are invalid (non-positive).
    """
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    if any(x is None for x in [o, h, l, c]):
        return float("nan")
    if o <= 0 or h <= 0 or l <= 0 or c <= 0:
        return float("nan")
    if h < l:
        return float("nan")

    # GK variance estimator
    log_hl = math.log(h / l)
    log_co = math.log(c / o)
    return 0.5 * (log_hl ** 2) - (2 * math.log(2) - 1) * (log_co ** 2)


def compute_drawdown(close: pd.Series) -> (pd.Series, float):
    """
    Drawdown series and max drawdown based on close values.
    """
    running_max = close.cummax()
    dd = (close - running_max) / running_max
    max_dd = float(dd.min())
    return dd, max_dd


def compute_portfolio_delta(port_ohlc: pd.DataFrame, stock_ohlc: pd.DataFrame) -> pd.Series:
    """
    Approximate delta as dV/dS using daily close-to-close changes.
    If dS is 0, we carry forward previous delta.
    """
    idx = port_ohlc.index
    v = port_ohlc["close"].reindex(idx)
    s = stock_ohlc["close"].reindex(idx)

    dv = v.diff()
    ds = s.diff()

    delta = pd.Series(index=idx, dtype=float)
    prev = 0.0
    for t in idx:
        if pd.isna(dv.loc[t]) or pd.isna(ds.loc[t]) or ds.loc[t] == 0:
            delta.loc[t] = prev
        else:
            prev = float(dv.loc[t] / ds.loc[t])
            delta.loc[t] = prev
    return delta


def compute_sharpe(ret: pd.Series, annualization: int = 252) -> float:
    """
    Simple Sharpe ratio of a return series.
    """
    r = ret.dropna()
    if len(r) < 2:
        return 0.0
    mu = r.mean()
    sig = r.std(ddof=1)
    if sig == 0:
        return 0.0
    return float((mu / sig) * math.sqrt(annualization))


def sanitize_json(obj: Any) -> Any:
    """
    Recursively sanitize objects to be JSON-serializable:
    - Convert NaN/Inf to string tokens
    - Convert numpy scalars to python scalars
    """
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_json(x) for x in obj]

    # numpy scalars -> python scalars
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        obj = float(obj)

    # float special cases
    if isinstance(obj, float):
        if math.isnan(obj):
            return "NA"
        if math.isinf(obj):
            return "inf" if obj > 0 else "-inf"
        # extra safety: extreme magnitudes sometimes show up
        if abs(obj) > 1e308:
            return "inf" if obj > 0 else "-inf"
        return obj

    return obj


# -------------------------
# Core backtest
# -------------------------

def backtest_option_strategy(legs_in: List[LegInput]) -> BacktestResponse:
    # 1. Normalize & validate legs
    legs = build_legs(legs_in)
    entry_date = legs[0].date
    entry_dt = pd.to_datetime(entry_date)
    underlying = legs[0].underlying
    max_expiry = max(pd.to_datetime(leg.expiry) for leg in legs)
    start_date = entry_dt
    end_date = max_expiry

    # 2. Trading calendar
    all_days = get_trading_days()
    calendar = pd.DatetimeIndex([d for d in all_days if start_date <= d <= end_date])
    if len(calendar) == 0:
        raise RuntimeError(f"No trading days between {start_date} and {end_date}")

    # 3. Fetch option history for each leg and prepare per-leg OHLC
    leg_ohlc: Dict[str, pd.DataFrame] = {}
    for leg in legs:
        hist_df = fetch_option_history(leg.ticker, start_date.strftime(DATE_FMT), end_date.strftime(DATE_FMT))
        leg_ohlc[leg.ticker] = prepare_leg_ohlc(leg, calendar, hist_df)

    # 4) Initial cost (net premium at entry; debit > 0, credit < 0)
    #    Convention you already use:
    #      buy  => + qty*price
    #      sell => - qty*price
    initial_cost = 0.0
    for leg in legs:
        sign = 1.0 if leg.direction == "buy" else -1.0
        initial_cost += sign * float(leg.number) * float(leg.at_price)
    
    cash0 = -float(initial_cost)

    # Collateral proxy (used for return scaling, avoids pct_change blow-ups)
    collateral = 0.0
    for leg in legs:
        collateral += abs(float(leg.number) * float(leg.at_price))
    collateral = max(collateral, 1.0)
      
    # 4. Portfolio OHLC (value, not cash-based)
    #    Long:  value = qty * price
    #    Short: value = qty * (entry_premium - current_price)
    #
    # NOTE (bugfix):
    # - For multi-leg strategies, mixing "long as value" + "short as PnL" will make the
    #   portfolio path inconsistent (and can even create impossible bars like high < low).
    # - We instead compute each leg's OHLC PnL relative to its entry price, then SUM them
    #   to get the portfolio OHLC PnL. This naturally handles both buy/sell directions:
    #     * Long PnL  = current_price - entry_price
    #     * Short PnL = entry_price - current_price
    # - To keep the original downstream logic (returns, GK variance, drawdown) stable,
    #   we add a positive constant "base_value" to the PnL OHLC to form a pseudo-value
    #   series. This shift does NOT change PnL/delta, only rescales returns.
    pos_ohlc = pd.DataFrame(index=calendar, columns=["open", "high", "low", "close"], dtype=float)
    pos_ohlc.loc[:, :] = 0.0

    for leg in legs:
        df = leg_ohlc[leg.ticker]
        qty = float(leg.number)

        if leg.direction == "buy":
            pos_ohlc["open"]  += qty * df["open"]
            pos_ohlc["high"]  += qty * df["high"]
            pos_ohlc["low"]   += qty * df["low"]
            pos_ohlc["close"] += qty * df["close"]
        else:
            # short => negative position value
            pos_ohlc["open"]  += (-qty) * df["open"]
            pos_ohlc["close"] += (-qty) * df["close"]
            # flip for OHLC consistency
            pos_ohlc["high"]  += (-qty) * df["low"]   # best (least negative) liability
            pos_ohlc["low"]   += (-qty) * df["high"]  # worst (most negative) liability

    equity_ohlc = pos_ohlc + cash0

    # 6. Underlying stock history for delta
    stock_hist = fetch_stock_history(underlying, start_date.strftime(DATE_FMT), end_date.strftime(DATE_FMT))
    stock_hist = stock_hist.reindex(calendar).ffill()

    # 7. Portfolio delta from dV/dS
    delta_series = compute_portfolio_delta(equity_ohlc, stock_hist)

    # 8. Build close series and PnL
    equity_open0 = float(equity_ohlc["open"].iloc[0])
    equity_close = equity_ohlc["close"].copy()

    cum_pnl = equity_close - equity_open0

    # Daily "return" as Return-on-Collateral: dPnL / collateral
    d_pnl = cum_pnl.diff()
    ret = d_pnl / collateral

    # Drawdown on cum_pnl (ratio form, but stable even when peak=0)
    running_peak = cum_pnl.cummax()
    denom = running_peak.abs().clip(lower=1.0)
    dd = (cum_pnl - running_peak) / denom
    max_dd = float(dd.min()) if len(dd) else 0.0

    sharpe = compute_sharpe(ret)

    # Intraday variance needs positive OHLC for log terms.
    # We compute GK on a shifted equity only for variance (does NOT affect pnl).
    eq_low_min = float(equity_ohlc["low"].min())
    shift_for_var = 1.0 - eq_low_min if eq_low_min < 1.0 else 0.0
    eq_for_var = equity_ohlc + shift_for_var

    intraday_var = pd.Series(index=calendar, dtype=float)
    for d in calendar:
        intraday_var.loc[d] = garman_klass_variance(eq_for_var.loc[d])

    # Summary stats
    max_profit = float(cum_pnl.max()) if len(cum_pnl) else 0.0
    max_loss = float(cum_pnl.min()) if len(cum_pnl) else 0.0
    final_value = float(equity_close.iloc[-1]) if len(equity_close) else 0.0
    final_profit = float(cum_pnl.iloc[-1]) if len(cum_pnl) else 0.0

    # 9. Build response objects
    daily_points: List[DailyPoint] = []
    for d in calendar:
        idx = d

        leg_points: List[LegDailyPoint] = []
        for leg in legs:
            df_leg = leg_ohlc[leg.ticker]
            row = df_leg.loc[idx]
            qty = float(leg.number)
            a = float(leg.at_price)

            # profit at close (floating PnL vs entry)
            if leg.direction == "buy":
                profit_close = qty * (float(row["close"]) - a)
            else:
                profit_close = qty * (a - float(row["close"]))

            leg_points.append(
                LegDailyPoint(
                    ticker=leg.ticker,
                    direction=leg.direction,
                    number=int(leg.number),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    profit_close=float(profit_close),
                )
            )

        daily_points.append(
            DailyPoint(
                date=d.strftime(DATE_FMT),
                open=float(equity_ohlc.loc[d, "open"]),
                high=float(equity_ohlc.loc[d, "high"]),
                low=float(equity_ohlc.loc[d, "low"]),
                close=float(equity_ohlc.loc[d, "close"]),
                delta=float(delta_series.loc[d]),
                ret=None if pd.isna(ret.loc[d]) else float(ret.loc[d]),
                cum_pnl=float(cum_pnl.loc[d]),
                drawdown=float(dd.loc[d]),
                intraday_var=None if pd.isna(intraday_var.loc[d]) else float(intraday_var.loc[d]),
                legs=leg_points,
            )
        )


    summary = SummaryMetrics(
        start_date=start_date.strftime(DATE_FMT),
        end_date=end_date.strftime(DATE_FMT),
        underlying=underlying,
        initial_cost=float(initial_cost),
        final_value=final_value,
        final_profit=final_profit,
        max_profit=max_profit,
        max_loss=max_loss,
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
    )

    return BacktestResponse(summary=summary, daily=daily_points)


# -------------------------
# FastAPI app
# -------------------------

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/backtest/options")
def backtest_options(req: BacktestRequest):
    # try:

    # except ValueError as e:
    #     raise HTTPException(status_code=400, detail=str(e))
    # except RuntimeError as e:
    #     raise HTTPException(status_code=500, detail=str(e))
    # except Exception as e:
    #     raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
    resp = backtest_option_strategy(req.legs)

    payload = jsonable_encoder(resp)     # pydantic -> python types
    payload = sanitize_json(payload)     # fix NaN/Inf/out-of-range
    return JSONResponse(content=payload) # strict JSON-safe
