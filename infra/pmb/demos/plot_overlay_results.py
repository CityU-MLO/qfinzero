"""
Plot overlay strategy backtest results.

Generates comparison charts for hedging (spread/protective) and profit increase
(covered call) strategies. Fetches actual stock/ETF daily prices from UPQ
for buy-hold and benchmark curves.

Usage:
    python demos/plot_overlay_results.py [--date 20260319]
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import csv
import json
import glob
from datetime import datetime

import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker


# ── Config ───────────────────────────────────────────────────────────────────

UPQ_BASE = "http://127.0.0.1:19350"
STOCK_QTY = 10_000
CASH_BUFFER_PCT = 0.20
ETF_BENCHMARKS = {"QQQ": "JEPQ", "NVDA": "NVDY"}

# ── Distinct colors for each line ────────────────────────────────────────────

C_SPREAD      = "#2563EB"   # blue
C_PROTECTIVE  = "#DC2626"   # red
C_COVERED     = "#059669"   # green
C_BUYHOLD     = "#1F2937"   # dark gray / near-black
C_ETF         = "#F59E0B"   # amber
C_BUYHOLD_DD  = "#9CA3AF"   # lighter gray for drawdown fill

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "#FAFAFA",
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linestyle": "--",
    "font.size": 11,
    "axes.titlesize": 14,
    "axes.titleweight": "bold",
    "legend.fontsize": 10,
    "figure.dpi": 150,
})


# ── Data loading ─────────────────────────────────────────────────────────────

def load_equity_curve(result_dir: str) -> tuple[list[datetime], list[float]]:
    """Load equity curve CSV → (dates, equities). Deduplicates per day."""
    path = os.path.join(result_dir, "equity_curve.csv")
    dates, equities = [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = row["timestamp"][:10]
            dt = datetime.strptime(ts, "%Y-%m-%d")
            eq = float(row["equity"])
            if dates and dates[-1] == dt:
                equities[-1] = eq
            else:
                dates.append(dt)
                equities.append(eq)
    return dates, equities


def load_summary(result_dir: str) -> dict:
    with open(os.path.join(result_dir, "summary.json")) as f:
        return json.load(f)


def load_trades(result_dir: str) -> list[dict]:
    path = os.path.join(result_dir, "trades.csv")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def fetch_stock_prices(ticker: str, start: str, end: str) -> dict[str, float]:
    """Fetch daily close prices from UPQ → {date_str: close}."""
    try:
        resp = requests.get(f"{UPQ_BASE}/stock/daily", params={
            "tickers": ticker, "start": start, "end": end,
            "fields": "ticker,date,close",
        }, timeout=30)
        if resp.status_code == 200:
            return {r["date"][:10]: r["close"] for r in resp.json()}
    except Exception as e:
        print(f"  [WARN] fetch_stock_prices({ticker}): {e}")
    return {}


def build_buyhold_curve(ticker: str, strategy_dates: list[datetime],
                        initial_equity: float) -> tuple[list[datetime], list[float]]:
    """Build buy-hold equity curve from actual stock prices.

    Buy-hold: buy STOCK_QTY shares on day 1, hold with cash buffer.
    Equity each day = cash_unused + STOCK_QTY × price(day).
    """
    start = strategy_dates[0].strftime("%Y-%m-%d")
    end = strategy_dates[-1].strftime("%Y-%m-%d")
    prices = fetch_stock_prices(ticker, start, end)
    if not prices:
        return [], []

    # Get day-1 price
    day1_price = prices.get(start)
    if day1_price is None:
        sorted_dates = sorted(prices.keys())
        day1_price = prices[sorted_dates[0]] if sorted_dates else None
    if day1_price is None:
        return [], []

    stock_cost = STOCK_QTY * day1_price
    cash_buffer = stock_cost * CASH_BUFFER_PCT
    cash_unused = initial_equity - stock_cost  # ≈ cash_buffer

    dates, equities = [], []
    for dt in strategy_dates:
        ds = dt.strftime("%Y-%m-%d")
        p = prices.get(ds)
        if p is not None:
            eq = cash_unused + STOCK_QTY * p
            dates.append(dt)
            equities.append(eq)

    return dates, equities


def build_etf_curve(etf_ticker: str, strategy_dates: list[datetime],
                    initial_equity: float) -> tuple[list[datetime], list[float]]:
    """Build ETF benchmark equity curve (invest entire initial_equity in ETF)."""
    start = strategy_dates[0].strftime("%Y-%m-%d")
    end = strategy_dates[-1].strftime("%Y-%m-%d")
    prices = fetch_stock_prices(etf_ticker, start, end)
    if not prices:
        return [], []

    sorted_dates = sorted(prices.keys())
    if not sorted_dates:
        return [], []
    day1_price = prices[sorted_dates[0]]
    shares = initial_equity / day1_price

    dates, equities = [], []
    for dt in strategy_dates:
        ds = dt.strftime("%Y-%m-%d")
        p = prices.get(ds)
        if p is not None:
            dates.append(dt)
            equities.append(shares * p)

    return dates, equities


def equity_to_returns(dates, equities):
    """Convert equity series to cumulative return % series."""
    base = equities[0]
    returns = [(eq / base - 1) * 100 for eq in equities]
    return dates, returns


def compute_drawdown(equities):
    """Compute drawdown % series from equity values."""
    peak = equities[0]
    dd = []
    for eq in equities:
        if eq > peak:
            peak = eq
        dd.append((eq / peak - 1) * 100)
    return dd


def final_return_pct(equities):
    return (equities[-1] / equities[0] - 1) * 100 if equities else 0.0


# ── Chart 1: Hedging comparison per ticker ───────────────────────────────────

def plot_hedging_comparison(ticker: str, spread_dir: str, protective_dir: str,
                            out_dir: str):
    """Equity curves + drawdown: spread vs protective vs buy-hold vs ETF."""
    sd, se = load_equity_curve(spread_dir)
    pd_, pe = load_equity_curve(protective_dir)
    ss = load_summary(spread_dir)
    ps = load_summary(protective_dir)

    sd_r, se_r = equity_to_returns(sd, se)
    pd_r, pe_r = equity_to_returns(pd_, pe)

    # Actual buy-hold from UPQ
    bh_dates, bh_eq = build_buyhold_curve(ticker, sd, se[0])
    # ETF benchmark
    etf_ticker = ETF_BENCHMARKS.get(ticker)
    etf_dates, etf_eq = [], []
    if etf_ticker:
        etf_dates, etf_eq = build_etf_curve(etf_ticker, sd, se[0])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), height_ratios=[3, 1],
                                    sharex=True)
    fig.suptitle(f"Overlay Hedging Strategies — {ticker} (2025)", fontsize=16,
                 fontweight="bold", y=0.98)

    # Panel 1: Cumulative returns
    ax1.plot(sd_r, se_r, color=C_SPREAD, linewidth=2.2,
             label=f"Put Spread ({ss['total_return']*100:+.2f}%)")
    ax1.plot(pd_r, pe_r, color=C_PROTECTIVE, linewidth=2.2,
             label=f"Protective Put ({ps['total_return']*100:+.2f}%)")

    if bh_eq:
        bh_d, bh_r = equity_to_returns(bh_dates, bh_eq)
        bh_ret = final_return_pct(bh_eq)
        ax1.plot(bh_d, bh_r, color=C_BUYHOLD, linewidth=2, linestyle="--",
                 label=f"Buy-and-Hold ({bh_ret:+.2f}%)")

    if etf_eq:
        etf_d, etf_r = equity_to_returns(etf_dates, etf_eq)
        etf_ret = final_return_pct(etf_eq)
        ax1.plot(etf_d, etf_r, color=C_ETF, linewidth=1.8, linestyle=":",
                 label=f"{etf_ticker} ({etf_ret:+.2f}%)")

    ax1.set_ylabel("Cumulative Return (%)")
    ax1.legend(loc="upper left", framealpha=0.9)
    ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
    ax1.axhline(0, color="black", linewidth=0.5, alpha=0.3)

    # Panel 2: Drawdown
    dd_spread = compute_drawdown(se)
    dd_prot = compute_drawdown(pe)
    ax2.fill_between(sd, dd_spread, 0, alpha=0.35, color=C_SPREAD,
                      label=f"Spread DD ({ss['max_drawdown']*100:.1f}%)")
    ax2.fill_between(pd_, dd_prot, 0, alpha=0.35, color=C_PROTECTIVE,
                      label=f"Protective DD ({ps['max_drawdown']*100:.1f}%)")
    if bh_eq:
        dd_bh = compute_drawdown(bh_eq)
        ax2.plot(bh_dates, dd_bh, color=C_BUYHOLD, linewidth=1.2, linestyle="--",
                 alpha=0.7, label="Buy-Hold DD")

    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Date")
    ax2.legend(loc="lower left", fontsize=9, framealpha=0.9, ncol=3)
    ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator())

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    path = os.path.join(out_dir, f"hedging_comparison_{ticker.lower()}.png")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ {path}")
    return path


# ── Chart 2: Covered call per ticker ─────────────────────────────────────────

def plot_covered_call(ticker: str, cc_dir: str, out_dir: str):
    """Equity curve + trade markers + buy-hold + ETF for covered call."""
    dates, equities = load_equity_curve(cc_dir)
    summary = load_summary(cc_dir)
    trades = load_trades(cc_dir)

    dates_r, returns = equity_to_returns(dates, equities)

    # Baselines
    bh_dates, bh_eq = build_buyhold_curve(ticker, dates, equities[0])
    etf_ticker = ETF_BENCHMARKS.get(ticker)
    etf_dates, etf_eq = [], []
    if etf_ticker:
        etf_dates, etf_eq = build_etf_curve(etf_ticker, dates, equities[0])

    # Trade markers: option sells
    sell_dates, sell_returns = [], []
    for t in trades:
        if "OPTION" in t.get("instrument_id", "") and t.get("side") == "SELL":
            ts = t["ts"][:10]
            dt = datetime.strptime(ts, "%Y-%m-%d")
            for i, d in enumerate(dates):
                if d >= dt:
                    sell_dates.append(d)
                    sell_returns.append(returns[i])
                    break

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), height_ratios=[3, 1],
                                    sharex=True)
    fig.suptitle(f"Covered Call Strategy — {ticker} (2025)", fontsize=16,
                 fontweight="bold", y=0.98)

    # Panel 1: Returns
    ax1.plot(dates_r, returns, color=C_COVERED, linewidth=2.2,
             label=f"Covered Call ({summary['total_return']*100:+.2f}%)")

    if bh_eq:
        bh_d, bh_r = equity_to_returns(bh_dates, bh_eq)
        bh_ret = final_return_pct(bh_eq)
        ax1.plot(bh_d, bh_r, color=C_BUYHOLD, linewidth=2, linestyle="--",
                 label=f"Buy-and-Hold ({bh_ret:+.2f}%)")

    if etf_eq:
        etf_d, etf_r = equity_to_returns(etf_dates, etf_eq)
        etf_ret = final_return_pct(etf_eq)
        ax1.plot(etf_d, etf_r, color=C_ETF, linewidth=1.8, linestyle=":",
                 label=f"{etf_ticker} ({etf_ret:+.2f}%)")

    if sell_dates:
        ax1.scatter(sell_dates, sell_returns, color="#7C3AED", marker="v",
                    s=25, zorder=5, alpha=0.5, label="Call sold")

    ax1.set_ylabel("Cumulative Return (%)")
    ax1.legend(loc="upper left", framealpha=0.9)
    ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.1f%%"))
    ax1.axhline(0, color="black", linewidth=0.5, alpha=0.3)

    # Panel 2: Drawdown
    dd = compute_drawdown(equities)
    ax2.fill_between(dates, dd, 0, alpha=0.4, color=C_COVERED,
                      label=f"Covered Call DD ({summary['max_drawdown']*100:.1f}%)")
    if bh_eq:
        dd_bh = compute_drawdown(bh_eq)
        ax2.plot(bh_dates, dd_bh, color=C_BUYHOLD, linewidth=1.2, linestyle="--",
                 alpha=0.7, label="Buy-Hold DD")

    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Date")
    ax2.legend(loc="lower left", fontsize=9, framealpha=0.9)
    ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator())

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    path = os.path.join(out_dir, f"covered_call_{ticker.lower()}.png")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ {path}")
    return path


# ── Chart 3: Summary bar chart ───────────────────────────────────────────────

def plot_summary_bars(results: dict, buyhold_returns: dict, etf_returns: dict,
                      out_dir: str):
    """Horizontal bar chart: all strategies + buy-hold + ETF per ticker."""
    # Build rows: group by ticker, add baselines
    rows = []  # (label, return%, dd%, color)
    for ticker in ["QQQ", "NVDA"]:
        # Buy-hold
        if ticker in buyhold_returns:
            rows.append((f"Buy-Hold — {ticker}", buyhold_returns[ticker], 0, C_BUYHOLD))
        # ETF
        etf = ETF_BENCHMARKS.get(ticker)
        if etf and ticker in etf_returns:
            rows.append((f"{etf} — {ticker}", etf_returns[ticker], 0, C_ETF))
        # Strategies
        color_map = {"Spread": C_SPREAD, "Protective": C_PROTECTIVE, "Covered Call": C_COVERED}
        for label, summary in results.items():
            if ticker in label:
                for k, c in color_map.items():
                    if k in label:
                        rows.append((label, summary["total_return"] * 100,
                                     summary["max_drawdown"] * 100, c))
                        break
        # Separator
        rows.append(("", 0, 0, "white"))

    # Remove trailing separator
    if rows and rows[-1][0] == "":
        rows.pop()

    labels = [r[0] for r in rows]
    rets = [r[1] for r in rows]
    dds = [r[2] for r in rows]
    colors = [r[3] for r in rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 8))
    fig.suptitle("Overlay Strategy Comparison — 2025 Backtest (with 100x Multiplier)",
                 fontsize=16, fontweight="bold")

    y = range(len(labels))

    # Returns
    bars1 = ax1.barh(y, rets, color=colors, height=0.65, edgecolor="white", linewidth=0.5)
    ax1.set_yticks(y)
    ax1.set_yticklabels(labels, fontsize=10)
    ax1.set_xlabel("Total Return (%)")
    ax1.set_title("Total Return")
    ax1.axvline(0, color="black", linewidth=0.5)
    for bar, ret, lab in zip(bars1, rets, labels):
        if lab:
            ax1.text(max(bar.get_width(), 0) + 0.5, bar.get_y() + bar.get_height() / 2,
                     f"{ret:+.1f}%", va="center", fontsize=9, fontweight="bold")

    # Drawdowns (only strategies, not baselines)
    bars2 = ax2.barh(y, dds, color=colors, height=0.65, edgecolor="white",
                      linewidth=0.5, alpha=0.75)
    ax2.set_yticks(y)
    ax2.set_yticklabels(labels, fontsize=10)
    ax2.set_xlabel("Max Drawdown (%)")
    ax2.set_title("Max Drawdown")
    for bar, dd, lab in zip(bars2, dds, labels):
        if lab and dd > 0:
            ax2.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                     f"{dd:.1f}%", va="center", fontsize=9, fontweight="bold")

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    path = os.path.join(out_dir, "strategy_comparison_summary.png")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ {path}")
    return path


# ── Chart 4: All equity curves ───────────────────────────────────────────────

def plot_all_equity_curves(all_data: dict, buyhold_curves: dict,
                           etf_curves: dict, out_dir: str):
    """All strategies + baselines, grouped by ticker."""
    fig, (ax_qqq, ax_nvda) = plt.subplots(1, 2, figsize=(18, 8))
    fig.suptitle("Equity Curves — All Overlay Strategies (2025, with 100x Multiplier)",
                 fontsize=16, fontweight="bold")

    style_map = {
        "Spread":      (C_SPREAD,     "-",  2.2),
        "Protective":  (C_PROTECTIVE, "-",  2.2),
        "Covered Call": (C_COVERED,   "-",  2.2),
    }

    axes = {"QQQ": ax_qqq, "NVDA": ax_nvda}

    # Plot baselines first (behind strategies)
    for ticker, ax in axes.items():
        if ticker in buyhold_curves:
            bh_d, bh_eq = buyhold_curves[ticker]
            if bh_eq:
                d, r = equity_to_returns(bh_d, bh_eq)
                ret = final_return_pct(bh_eq)
                ax.plot(d, r, color=C_BUYHOLD, linewidth=2, linestyle="--",
                        label=f"Buy-and-Hold ({ret:+.1f}%)", zorder=1)

        etf = ETF_BENCHMARKS.get(ticker)
        if etf and ticker in etf_curves:
            etf_d, etf_eq = etf_curves[ticker]
            if etf_eq:
                d, r = equity_to_returns(etf_d, etf_eq)
                ret = final_return_pct(etf_eq)
                ax.plot(d, r, color=C_ETF, linewidth=1.8, linestyle=":",
                        label=f"{etf} ({ret:+.1f}%)", zorder=1)

    # Plot strategies
    for label, (result_dir, _) in all_data.items():
        dates, equities = load_equity_curve(result_dir)
        dates_r, returns = equity_to_returns(dates, equities)
        summary = load_summary(result_dir)

        color, ls, lw = C_BUYHOLD, "--", 1.5
        for key, (c, s, w) in style_map.items():
            if key in label:
                color, ls, lw = c, s, w
                break

        display_label = label.split(" — ")[0] + f" ({summary['total_return']*100:+.1f}%)"

        for ticker, ax in axes.items():
            if ticker in label:
                ax.plot(dates_r, returns, color=color, linestyle=ls,
                        linewidth=lw, label=display_label, zorder=2)

    for ticker, ax in axes.items():
        ax.set_title(ticker, fontsize=14, fontweight="bold")
        ax.set_xlabel("Date")
        ax.set_ylabel("Cumulative Return (%)")
        ax.legend(loc="upper left", fontsize=9, framealpha=0.9)
        ax.axhline(0, color="black", linewidth=0.5, alpha=0.3)
        ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    path = os.path.join(out_dir, "all_equity_curves.png")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ {path}")
    return path


# ── Main ─────────────────────────────────────────────────────────────────────

def find_result_dirs(base_dir: str, date_str: str) -> dict:
    dirs = {}
    pattern = os.path.join(base_dir, f"*_{date_str}_*")
    for d in sorted(glob.glob(pattern)):
        name = os.path.basename(d)
        if "hedging_v2_spread_qqq" in name:
            dirs["Spread — QQQ"] = d
        elif "hedging_v2_spread_nvda" in name:
            dirs["Spread — NVDA"] = d
        elif "hedging_v2_protective_qqq" in name:
            dirs["Protective — QQQ"] = d
        elif "hedging_v2_protective_nvda" in name:
            dirs["Protective — NVDA"] = d
        elif "profit_increase_v2_qqq" in name:
            dirs["Covered Call — QQQ"] = d
        elif "profit_increase_v2_nvda" in name:
            dirs["Covered Call — NVDA"] = d
    return dirs


def main():
    parser = argparse.ArgumentParser(description="Plot overlay backtest results")
    parser.add_argument("--date", default="20260319",
                        help="Date string to match result dirs (default: 20260319)")
    parser.add_argument("--results-dir", default="results",
                        help="Base results directory (default: results)")
    args = parser.parse_args()

    base = args.results_dir
    dirs = find_result_dirs(base, args.date)

    if not dirs:
        print(f"No result directories found matching date {args.date} in {base}")
        sys.exit(1)

    print(f"\nFound {len(dirs)} result directories for {args.date}:")
    for label, d in dirs.items():
        summary = load_summary(d)
        print(f"  {label:25s} → return={summary['total_return']*100:+.2f}%  "
              f"dd={summary['max_drawdown']*100:.1f}%  dir={os.path.basename(d)}")

    combined_dir = os.path.join(base, f"figures_{args.date}")
    os.makedirs(combined_dir, exist_ok=True)

    # Pre-fetch baselines for both tickers
    print("\nFetching baselines from UPQ...")
    buyhold_curves = {}
    buyhold_returns = {}
    etf_curves = {}
    etf_returns = {}

    for ticker in ["QQQ", "NVDA"]:
        # Use any strategy's dates/initial equity as reference
        ref_dir = None
        for label, d in dirs.items():
            if ticker in label:
                ref_dir = d
                break
        if ref_dir is None:
            continue

        dates, equities = load_equity_curve(ref_dir)
        initial_eq = equities[0]

        bh_d, bh_eq = build_buyhold_curve(ticker, dates, initial_eq)
        if bh_eq:
            buyhold_curves[ticker] = (bh_d, bh_eq)
            buyhold_returns[ticker] = final_return_pct(bh_eq)
            print(f"  {ticker} Buy-Hold: {buyhold_returns[ticker]:+.2f}%")

        etf = ETF_BENCHMARKS.get(ticker)
        if etf:
            etf_d, etf_eq = build_etf_curve(etf, dates, initial_eq)
            if etf_eq:
                etf_curves[ticker] = (etf_d, etf_eq)
                etf_returns[ticker] = final_return_pct(etf_eq)
                print(f"  {etf}: {etf_returns[ticker]:+.2f}%")

    print(f"\nGenerating charts → {combined_dir}/")

    # 1. Hedging comparison per ticker
    for ticker in ["QQQ", "NVDA"]:
        spread_key = f"Spread — {ticker}"
        prot_key = f"Protective — {ticker}"
        if spread_key in dirs and prot_key in dirs:
            plot_hedging_comparison(ticker, dirs[spread_key], dirs[prot_key],
                                   combined_dir)
            plot_hedging_comparison(ticker, dirs[spread_key], dirs[prot_key],
                                   dirs[spread_key])
            plot_hedging_comparison(ticker, dirs[spread_key], dirs[prot_key],
                                   dirs[prot_key])

    # 2. Covered call per ticker
    for ticker in ["QQQ", "NVDA"]:
        cc_key = f"Covered Call — {ticker}"
        if cc_key in dirs:
            plot_covered_call(ticker, dirs[cc_key], combined_dir)
            plot_covered_call(ticker, dirs[cc_key], dirs[cc_key])

    # 3. Summary bar chart with baselines
    summaries = {label: load_summary(d) for label, d in dirs.items()}
    plot_summary_bars(summaries, buyhold_returns, etf_returns, combined_dir)

    # 4. All equity curves with baselines
    all_data = {label: (d, load_summary(d)) for label, d in dirs.items()}
    plot_all_equity_curves(all_data, buyhold_curves, etf_curves, combined_dir)

    print(f"\nDone. All figures saved to: {combined_dir}/")
    print(f"\nFiles:")
    for f in sorted(os.listdir(combined_dir)):
        if f.endswith(".png"):
            fpath = os.path.join(combined_dir, f)
            size_kb = os.path.getsize(fpath) / 1024
            print(f"  {f:45s} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
