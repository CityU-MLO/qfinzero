#!/usr/bin/env python3
"""
Greeks API verification: independently compute BSM Greeks in Python
and compare against UPQ API results.

Run on qlib: python3 verify_greeks_api.py [port]
"""

import json
import math
import sys
import urllib.request

API_BASE = "http://localhost:{port}"


# ─── BSM Math ───


def _erf_approx(x: float) -> float:
    """A&S 7.1.28 erf approximation (max error ~1.5e-7)."""
    if x == 0.0:
        return 0.0
    ax = abs(x)
    t = 1.0 / (1.0 + 0.3275911 * ax)
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    poly = t * (a1 + t * (a2 + t * (a3 + t * (a4 + t * a5))))
    erfc_abs = poly * math.exp(-ax * ax)
    erf_abs = max(0.0, min(1.0, 1.0 - erfc_abs))
    return erf_abs if x > 0 else -erf_abs


def norm_cdf(x: float) -> float:
    """Standard normal CDF: Phi(x) = 0.5 * (1 + erf(x / sqrt(2)))."""
    return 0.5 * (1.0 + _erf_approx(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


def bsm_d1_d2(s, k, t, r, q, sigma):
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma ** 2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    return d1, d2


def bsm_price(s, k, t, r, q, sigma, is_call):
    d1, d2 = bsm_d1_d2(s, k, t, r, q, sigma)
    if is_call:
        return s * math.exp(-q * t) * norm_cdf(d1) - k * math.exp(-r * t) * norm_cdf(d2)
    else:
        return k * math.exp(-r * t) * norm_cdf(-d2) - s * math.exp(-q * t) * norm_cdf(-d1)


def bsm_greeks(s, k, t, r, q, sigma, is_call):
    d1, d2 = bsm_d1_d2(s, k, t, r, q, sigma)
    sqrt_t = math.sqrt(t)
    pdf_d1 = norm_pdf(d1)
    exp_qt = math.exp(-q * t)
    exp_rt = math.exp(-r * t)

    delta = exp_qt * norm_cdf(d1) if is_call else -exp_qt * norm_cdf(-d1)
    gamma = exp_qt * pdf_d1 / (s * sigma * sqrt_t)

    if is_call:
        theta_annual = (
            -s * exp_qt * pdf_d1 * sigma / (2.0 * sqrt_t)
            - r * k * exp_rt * norm_cdf(d2)
            + q * s * exp_qt * norm_cdf(d1)
        )
    else:
        theta_annual = (
            -s * exp_qt * pdf_d1 * sigma / (2.0 * sqrt_t)
            + r * k * exp_rt * norm_cdf(-d2)
            - q * s * exp_qt * norm_cdf(-d1)
        )
    theta = theta_annual / 365.0
    vega = s * exp_qt * pdf_d1 * sqrt_t * 0.01
    rho = (k * t * exp_rt * norm_cdf(d2) * 0.01) if is_call else (-k * t * exp_rt * norm_cdf(-d2) * 0.01)

    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho}


def implied_volatility(market_price, s, k, t, r, q, is_call, tol=1e-10, max_iter=200):
    """Bisection + Newton hybrid IV solver."""
    if market_price <= 0 or s <= 0 or k <= 0 or t <= 0:
        return None

    # Check bracket
    def f(sigma):
        return bsm_price(s, k, t, r, q, sigma, is_call) - market_price

    lo, hi = 0.001, 10.0
    f_lo, f_hi = f(lo), f(hi)
    if f_lo * f_hi > 0:
        return None

    # Bisection (simple, robust)
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if abs(f_mid) < tol or (hi - lo) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid

    return (lo + hi) / 2.0


# ─── Rates Curve ───


def interpolate_rate(curve_points, tenor_years):
    if len(curve_points) == 1:
        return curve_points[0][1]
    if tenor_years <= curve_points[0][0]:
        return curve_points[0][1]
    if tenor_years >= curve_points[-1][0]:
        return curve_points[-1][1]
    for i in range(len(curve_points) - 1):
        t0, r0 = curve_points[i]
        t1, r1 = curve_points[i + 1]
        if t0 <= tenor_years <= t1:
            return r0 + (tenor_years - t0) / (t1 - t0) * (r1 - r0)
    return curve_points[-1][1]


# ─── API ───


def api_get(path):
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(f"{API_BASE}{path}")
    with opener.open(req) as resp:
        return json.loads(resp.read())


# ─── Main ───


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 19350
    global API_BASE
    API_BASE = f"http://localhost:{port}"

    print("=" * 72)
    print(f"UPQ Greeks API Verification (port={port})")
    print("=" * 72)

    # 1. Spot
    spot_data = api_get("/stock/daily?tickers=AAPL&start=2025-12-30&end=2025-12-30")
    spot = spot_data[0]["close"]
    print(f"\nSpot (AAPL 2025-12-30): {spot}")

    # 2. Rates
    rates_data = api_get("/rates/query?start=2025-12-30&end=2025-12-30")
    rates = rates_data[0]
    curve_points = [
        (1.0 / 12.0, rates["yield_1_month"] / 100.0),
        (3.0 / 12.0, rates["yield_3_month"] / 100.0),
        (1.0, rates["yield_1_year"] / 100.0),
        (2.0, rates["yield_2_year"] / 100.0),
        (5.0, rates["yield_5_year"] / 100.0),
        (10.0, rates["yield_10_year"] / 100.0),
        (30.0, rates["yield_30_year"] / 100.0),
    ]
    print(f"Rates curve: {[(t, f'{r:.4f}') for t, r in curve_points]}")

    # 3. T
    from datetime import date, datetime, timezone
    trade_date = date(2025, 12, 30)
    expiry_date = date(2026, 1, 16)
    day_diff = (expiry_date - trade_date).days
    t_years = day_diff / 365.0
    r = interpolate_rate(curve_points, t_years)
    q = 0.0
    print(f"T = {day_diff} days = {t_years:.6f} years")
    print(f"r = {r:.6f} (interpolated)")

    # 4. Day-level chain query with Greeks
    print("\n" + "=" * 72)
    print("Part 1: Day-Level Chain Greeks")
    print("=" * 72)

    api_results = api_get(
        "/option/chain_query?underlying=AAPL&date=2025-12-30"
        "&expiry_min=2026-01-16&expiry_max=2026-01-16"
        "&strike_min=270&strike_max=280&include_greeks=true"
    )

    print(f"API returned {len(api_results)} contracts\n")

    all_pass = True
    tol = 1e-6

    for row in api_results:
        ticker = row["ticker"]
        strike = row["strike"]
        opt_type = row["type"]
        close = row["close"]
        is_call = opt_type == "C"

        api_iv = row["iv"]
        api_greeks = {k: row[k] for k in ["delta", "gamma", "theta", "vega", "rho"]}

        # Python computation
        py_iv = implied_volatility(close, spot, strike, t_years, r, q, is_call)
        if py_iv is None:
            print(f"{ticker} K={strike} {opt_type} close={close}: IV FAILED")
            all_pass = False
            continue

        py_greeks = bsm_greeks(spot, strike, t_years, r, q, py_iv, is_call)

        checks = [
            ("IV", api_iv, py_iv),
            ("delta", api_greeks["delta"], py_greeks["delta"]),
            ("gamma", api_greeks["gamma"], py_greeks["gamma"]),
            ("theta", api_greeks["theta"], py_greeks["theta"]),
            ("vega", api_greeks["vega"], py_greeks["vega"]),
            ("rho", api_greeks["rho"], py_greeks["rho"]),
        ]

        row_pass = True
        print(f"{ticker} K={strike} {opt_type} close={close}")
        for name, api_val, py_val in checks:
            diff = abs(api_val - py_val)
            ok = diff < tol
            tag = "OK" if ok else "FAIL"
            if not ok:
                row_pass = False
                all_pass = False
            print(f"  {name:6s}: API={api_val:+.10f}  Py={py_val:+.10f}  diff={diff:.2e} [{tag}]")
        if row_pass:
            print(f"  >>> ALL MATCH")

    # 5. Minute-level ticker query
    print("\n" + "=" * 72)
    print("Part 2: Minute-Level Ticker Greeks")
    print("=" * 72)

    contract = "O:AAPL260116C00275000"
    minute_results = api_get(
        f"/option/ticker_query?contract={contract}"
        "&start=2025-12-30T14:30:00&end=2025-12-30T15:00:00"
        "&resolution=minute&include_greeks=true"
    )
    print(f"Minute bars: {len(minute_results)}")

    if not minute_results:
        print("No minute data — skipping")
        return all_pass

    # Minute T: computed from nanoseconds
    # Expiry anchor: 2026-01-16 21:00 UTC (Jan = EST, 16:00 ET = 21:00 UTC)
    expiry_anchor_utc = datetime(2026, 1, 16, 21, 0, 0, tzinfo=timezone.utc)
    expiry_anchor_ns = int(expiry_anchor_utc.timestamp() * 1e9)
    strike, is_call = 275.0, True

    minute_pass = True
    for i, mrow in enumerate(minute_results[:10]):
        ws_ns = mrow["window_start"]
        close = mrow["close"]
        api_iv = mrow.get("iv")
        api_delta = mrow.get("delta")
        api_status = mrow.get("greek_status")

        ns_diff = expiry_anchor_ns - ws_ns
        t_min = max(ns_diff / (365.0 * 24.0 * 3600.0 * 1e9), 1.0 / (365.0 * 24.0 * 60.0))
        r_min = interpolate_rate(curve_points, t_min)

        ws_dt = datetime.fromtimestamp(ws_ns / 1e9, tz=timezone.utc)

        if close <= 0 or api_iv is None:
            print(f"  Bar {i} {ws_dt.strftime('%H:%M')} close={close} status={api_status} — skipped")
            continue

        py_iv_m = implied_volatility(close, spot, strike, t_min, r_min, q, is_call)
        if py_iv_m is None:
            print(f"  Bar {i} {ws_dt.strftime('%H:%M')} close={close} Py IV failed, API={api_iv}")
            minute_pass = False
            continue

        py_greeks_m = bsm_greeks(spot, strike, t_min, r_min, q, py_iv_m, is_call)

        iv_diff = abs(api_iv - py_iv_m)
        d_diff = abs(api_delta - py_greeks_m["delta"])
        iv_ok = iv_diff < tol
        d_ok = d_diff < tol
        if not (iv_ok and d_ok):
            minute_pass = False

        tag_iv = "OK" if iv_ok else "FAIL"
        tag_d = "OK" if d_ok else "FAIL"
        print(
            f"  Bar {i:2d} {ws_dt.strftime('%H:%M')} "
            f"close={close:6.2f} "
            f"IV: {api_iv:.8f} vs {py_iv_m:.8f} ({tag_iv}) "
            f"Δ: {api_delta:+.8f} vs {py_greeks_m['delta']:+.8f} ({tag_d})"
        )

    all_pass = all_pass and minute_pass

    # 6. Put-call parity check
    print("\n" + "=" * 72)
    print("Part 3: Put-Call Parity Consistency")
    print("=" * 72)

    parity_pass = True
    # Re-fetch the chain data grouped by strike
    strikes = {}
    for row in api_results:
        k = row["strike"]
        if k not in strikes:
            strikes[k] = {}
        strikes[k][row["type"]] = row

    for k in sorted(strikes.keys()):
        if "C" in strikes[k] and "P" in strikes[k]:
            c = strikes[k]["C"]
            p = strikes[k]["P"]
            # Put-call parity: C - P = S*exp(-qT) - K*exp(-rT)
            lhs = c["close"] - p["close"]
            rhs = spot * math.exp(-q * t_years) - k * math.exp(-r * t_years)
            parity_diff = abs(lhs - rhs)
            # Also check delta parity: delta_call - delta_put ≈ exp(-qT)
            delta_sum = c["delta"] - p["delta"]
            expected_delta_sum = math.exp(-q * t_years)  # = 1.0 when q=0
            delta_parity_diff = abs(delta_sum - expected_delta_sum)

            p_tag = "OK" if parity_diff < 1.0 else "WARN"  # market prices may deviate
            d_tag = "OK" if delta_parity_diff < 0.01 else "FAIL"
            if d_tag == "FAIL":
                parity_pass = False

            print(
                f"  K={k:6.1f}: C-P={lhs:+.2f} vs S-Ke^(-rT)={rhs:+.2f} "
                f"diff={parity_diff:.2f} [{p_tag}]  "
                f"Δc-Δp={delta_sum:.4f} vs {expected_delta_sum:.4f} [{d_tag}]"
            )

    # Summary
    print("\n" + "=" * 72)
    overall = all_pass and parity_pass
    if overall:
        print("OVERALL RESULT: ALL CHECKS PASSED")
    else:
        parts = []
        if not all_pass:
            parts.append("greeks mismatch")
        if not parity_pass:
            parts.append("parity mismatch")
        print(f"OVERALL RESULT: ISSUES FOUND ({', '.join(parts)})")
    print("=" * 72)

    return overall


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
