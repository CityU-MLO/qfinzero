import bisect
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import DATE_FMT
from utils import to_datestr, _strip_prefix, _to_float_or_none
from data_access.options_store import parse_option_ticker, load_option_day
from data_access.prices_store import lookup_stock_price
from data_access.rates_store import get_rates_curve_df, get_rate_lookup
from greeks_utils import (
    greeks_yearfrac,
    greeks_implied_vol,
    greeks_bs_greeks,
    compute_iv_and_greeks_timeseries,
    greeks_build_rate_lookup,
)


# ---------------------------------------------------------------------
# Chain helpers
# ---------------------------------------------------------------------
def _nearest_strikes(strikes: List[float], price: float, level: int) -> List[float]:
    """
    Given a list of strikes and a center price, pick strikes in a symmetric
    window around the price (level on each side).
    """
    if level is None or level <= 0 or not strikes:
        return strikes
    uniq = sorted(set(strikes))
    i = bisect.bisect_left(uniq, price)
    below = uniq[max(0, i - level):i]
    above = uniq[i:i + level]
    return sorted(set(below + above))


def build_chain_json(
    df: pd.DataFrame,
    center_price: Optional[float],
    level: Optional[int],
    include_greeks: bool = False,
) -> Dict[str, Dict[str, List[Dict]]]:
    """
    Convert a raw options DataFrame into a nested JSON-friendly structure:

    {
      "C": {
        "2025-01-17": [ { ... per-contract fields ... }, ... ],
        ...
      },
      "P": {
        "2025-01-17": [ ... ],
        ...
      }
    }

    When include_greeks=True and the columns ['iv','delta','gamma','theta',
    'vega','rho'] are present, these values are attached to each contract
    record (NaNs become null in JSON).
    """
    result: Dict[str, Dict[str, List[Dict]]] = {"C": {}, "P": {}}
    if df is None or df.empty:
        return result

    for t, dft in df.groupby("type"):
        # Normalise group key to 'C' / 'P' if necessary
        t_key = t
        if isinstance(t, str):
            tl = t.strip().lower()
            if tl in ("c", "call"):
                t_key = "C"
            elif tl in ("p", "put"):
                t_key = "P"

        for exp, dfe in dft.groupby("expiry"):
            grp = dfe.sort_values("strike").copy()

            # Level-based strike selection (symmetric around center_price)
            if center_price is not None and level is not None and level > 0:
                keep = _nearest_strikes(grp["strike"].tolist(), center_price, level)
                grp = grp[grp["strike"].isin(keep)]

            payload: List[Dict] = []
            for _, r in grp.iterrows():
                item: Dict[str, Optional[float]] = {
                    "date": pd.to_datetime(r["date"]).strftime(DATE_FMT),
                    "ticker": str(r["ticker"]),
                    "strike": float(r["strike"]),
                    "volume": int(r["volume"]) if pd.notna(r["volume"]) else None,
                    "open": float(r["open"]) if pd.notna(r["open"]) else None,
                    "close": float(r["close"]) if pd.notna(r["close"]) else None,
                    "high": float(r["high"]) if pd.notna(r["high"]) else None,
                    "low": float(r["low"]) if pd.notna(r["low"]) else None,
                    "expiry": pd.to_datetime(r["expiry"]).strftime(DATE_FMT),
                }

                if include_greeks:
                    # Attach IV + greeks if present; map NaNs -> null
                    for gname in ("iv", "delta", "gamma", "theta", "vega", "rho"):
                        if gname in r.index:
                            item[gname] = _to_float_or_none(r[gname])
                        else:
                            item[gname] = None

                payload.append(item)

            result.setdefault(t_key, {})[exp.strftime(DATE_FMT)] = payload

    return result


def attach_iv_and_greeks_to_chain(
    df: pd.DataFrame,
    underlying: str,
    trade_date: pd.Timestamp,
) -> pd.DataFrame:
    """
    Compute per-row implied volatility and Black-Scholes greeks for a snapshot
    option chain and attach the results as new columns.

    This uses the compute_iv_and_greeks_timeseries() helper from
    infra.oql.utils.greeks. If the greeks utilities or the rate curve are not
    available, the input DataFrame is returned unchanged.
    """
    if df is None or df.empty:
        return df

    if compute_iv_and_greeks_timeseries is None or greeks_build_rate_lookup is None:
        # Greeks library not available; return raw chain.
        return df

    dt_norm = trade_date.normalize()
    datestr = to_datestr(dt_norm)

    # Underlying price S for this trade date (as-of).
    spot, _ = lookup_stock_price(underlying, datestr, asof=True)
    if spot is None:
        # Cannot compute greeks without a spot price.
        return df
    S_val = float(spot["close"])

    # Prepare a working copy for the greeks library (so we do not mutate
    # the original chain).
    df_calc = df.copy()

    # Normalize basic fields.
    df_calc["date"] = pd.to_datetime(dt_norm)
    df_calc["expiry"] = pd.to_datetime(df_calc["expiry"]).dt.normalize()
    df_calc["S"] = S_val

    # Map type to 'call' / 'put' for the greeks library.
    def _to_call_put(x):
        if isinstance(x, str):
            xl = x.strip().lower()
            if xl in ("c", "call"):
                return "call"
            if xl in ("p", "put"):
                return "put"
        return x

    df_calc["type"] = df_calc["type"].apply(_to_call_put)

    # Provide a price column name that the helper knows how to use.
    # Priority: bid/ask mid -> option_mid -> option_close -> close.
    if "bid" in df_calc.columns and "ask" in df_calc.columns:
        df_calc["option_mid"] = (df_calc["bid"] + df_calc["ask"]) / 2.0
    elif "option_mid" not in df_calc.columns:
        if "option_close" in df_calc.columns:
            df_calc["option_mid"] = df_calc["option_close"]
        else:
            df_calc["option_mid"] = df_calc["close"]

    curve_df = get_rates_curve_df()

    # Ask the library to compute IV and greeks in place.
    df_enriched = compute_iv_and_greeks_timeseries(df_calc, curve_df)

    # Attach IV + greeks back onto a copy of the original chain (preserving
    # the original 'type' codes 'C' / 'P').
    out = df.copy()
    for col in ("iv", "delta", "gamma", "theta", "vega", "rho"):
        if col in df_enriched.columns:
            out[col] = df_enriched[col]
    return out


def find_option_row_for_ticker(
    contract_ticker: str,
    trade_date: pd.Timestamp,
) -> Tuple[Optional[pd.Series], Optional[pd.DataFrame], Optional[Dict]]:
    """
    Locate the row corresponding to a given OPRA option ticker on a specific
    trade date.

    Returns:
        (row, full_day_df, meta)
            - row:          pandas Series for the contract, or None.
            - full_day_df:  full option chain DataFrame for that date, or None.
            - meta:         parsed OPRA components (underlying, expiry, type, strike).
    """
    try:
        meta = parse_option_ticker(contract_ticker)
    except ValueError:
        return None, None, None

    datestr = to_datestr(trade_date)
    df_day = load_option_day(meta["underlying"], datestr)
    if df_day is None or df_day.empty:
        return None, None, meta

    cand = {
        contract_ticker,
        _strip_prefix(contract_ticker, "O:"),
        f"O:{_strip_prefix(contract_ticker, 'O:')}",
    }
    sub = df_day[df_day["ticker"].isin(cand)]
    if sub.empty:
        return None, df_day, meta

    row = sub.iloc[0]
    return row, df_day, meta


def compute_single_option_iv_and_greeks(
    contract_ticker: str,
    trade_date: pd.Timestamp,
) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Compute implied volatility and Black-Scholes greeks for a single option
    contract on a given trade date.

    The function automatically:
        - parses the OPRA ticker to obtain underlying / expiry / type / strike
        - looks up the option close (or mid) price for that date
        - looks up the underlying's spot/close price (as-of)
        - interpolates the risk-free rate from the Treasury curve
        - runs an IV solver + greeks calculator

    Returns:
        (payload, error_message)
            - payload: dict with iv + greeks and meta fields, or None on error
            - error_message: human-readable message when payload is None
    """
    if (
        greeks_yearfrac is None
        or greeks_build_rate_lookup is None
        or greeks_implied_vol is None
        or greeks_bs_greeks is None
    ):
        return None, "Greeks utilities are not available (infra.oql.utils.greeks import failed)."

    row, _, meta = find_option_row_for_ticker(contract_ticker, trade_date)
    if meta is None:
        return None, f"Invalid OPRA ticker: {contract_ticker}"
    if row is None:
        return None, f"No option data for {contract_ticker} on {to_datestr(trade_date)}."

    datestr = to_datestr(trade_date)

    # Option market price: prefer mid if bid/ask, then 'option_mid', then 'option_close', then 'close'.
    price_source = None
    if (
        "bid" in row.index
        and "ask" in row.index
        and pd.notna(row["bid"])
        and pd.notna(row["ask"])
    ):
        opt_price = float((row["bid"] + row["ask"]) / 2.0)
        price_source = "mid(bid/ask)"
    elif "option_mid" in row.index and pd.notna(row["option_mid"]):
        opt_price = float(row["option_mid"])
        price_source = "option_mid"
    elif "option_close" in row.index and pd.notna(row["option_close"]):
        opt_price = float(row["option_close"])
        price_source = "option_close"
    elif "close" in row.index and pd.notna(row["close"]):
        opt_price = float(row["close"])
        price_source = "close"
    else:
        return None, "No usable option price column (need bid/ask, option_mid, option_close, or close)."

    # Underlying spot/close
    spot_data, spot_asof = lookup_stock_price(meta["underlying"], datestr, asof=True)
    if spot_data is None:
        return None, f"No underlying price for {meta['underlying']} on/before {datestr}."
    S = float(spot_data["close"])

    # Expiry date: use the stored 'expiry' if available; fall back to OPRA meta.
    if "expiry" in row.index and pd.notna(row["expiry"]):
        expiry_ts = pd.to_datetime(row["expiry"]).normalize()
    else:
        expiry_ts = pd.to_datetime(meta["expiry"]).normalize()

    # Time to expiry in years (ACT/365).
    T = greeks_yearfrac(trade_date, expiry_ts)

    # Risk-free rate lookup: piecewise-linear interpolation on curve pillars.
    rate_fn = get_rate_lookup()
    if rate_fn is None:
        return None, "Failed to construct rate lookup from Treasury curve."

    r = float(rate_fn(trade_date, max(T, 1e-6)))

    # Implied volatility (via Brent root finder + Newton fallback).
    is_call = (meta["type"].lower() == "call")
    iv = greeks_implied_vol(
        opt_price, S, float(meta["strike"]), max(T, 1e-6), r, is_call=is_call
    )

    # Greeks at the solved IV (delta/gamma/theta/vega/rho).
    greeks_dict = greeks_bs_greeks(
        S, float(meta["strike"]), max(T, 1e-6), r, iv, is_call=is_call
    )

    payload = {
        "date": datestr,
        "ticker": str(row["ticker"]),
        "underlying": meta["underlying"],
        "expiry": expiry_ts.strftime(DATE_FMT),
        "type": meta["type"],  # 'call' or 'put'
        "strike": float(meta["strike"]),
        "option_price": _to_float_or_none(opt_price),
        "price_source": price_source,
        "underlying_price": _to_float_or_none(S),
        "underlying_price_asof": spot_asof,
        "T": _to_float_or_none(T),
        "rate": _to_float_or_none(r),
        "iv": _to_float_or_none(iv),
        "delta": _to_float_or_none(greeks_dict.get("delta")),
        "gamma": _to_float_or_none(greeks_dict.get("gamma")),
        "theta": _to_float_or_none(greeks_dict.get("theta")),
        "vega": _to_float_or_none(greeks_dict.get("vega")),
        "rho": _to_float_or_none(greeks_dict.get("rho")),
    }
    return payload, None
