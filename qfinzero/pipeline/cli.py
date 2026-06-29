"""``qfz-data`` — the data-pipeline command line.

    qfz-data status                          # what raw data exists + conversion state
    qfz-data convert --market us --asset stock --resolution daily [--start --end]
    qfz-data convert --market us --all       # us stocks+options+rates+corp-actions
    qfz-data convert --market cn --all       # cn A-shares + corp-actions
    qfz-data convert --all                   # everything
    qfz-data validate                        # schema / freshness checks
"""

from __future__ import annotations

import argparse
import json
import sys

from .convert import Converter, now_iso
from .paths import resolve
from . import registry


def _print_status(args) -> int:
    data = registry.scan(resolve(args.massive, args.tushare, args.storage))
    if args.json:
        print(json.dumps(data, indent=2, default=str))
        return 0
    raw, store = data["raw"], data["storage"]
    print("\nRAW SOURCES (read in place)")
    m = raw["massive"]
    print(f"  massive  {m['root']}")
    for k in ("stock_daily", "stock_minute", "option_day", "option_minute"):
        r = m[k]
        rng = f"{r.get('start','?')} .. {r.get('end','?')} ({r['files']} files)" if r.get("present") else "—"
        print(f"    {k:14} {rng}")
    print(f"    rates          {'present' if m['rates']['present'] else '—'}")
    print(f"    corp actions   {m['splits_files']} split files, {m['dividends_files']} dividend files")
    t = raw["tushare"]
    print(f"  tushare  {t['root']}")
    cn = t["cn_daily"]
    rng = f"{cn.get('start','?')} .. {cn.get('end','?')}" if cn.get("present") else "—"
    print(f"    cn_daily       {rng} ({cn.get('symbols',0)} symbols)")
    print(f"    cn dividends   {t['cn_dividend_files']} files")

    print(f"\nUPQ STORAGE  {store['root']}")
    for k in ("stock_daily", "stock_minute", "option_day", "option_minute"):
        s = store[k]
        rng = f"{s.get('start','?')} .. {s.get('end','?')}" if s["partitions"] else "—"
        print(f"    {k:14} {s['partitions']:5d} partitions  {rng}")
    for single in ("rates/rates.parquet", "corporate_actions/corporate_actions.parquet",
                   "dividends/dividends.parquet"):
        print(f"    {single:42} {'✓' if store[single] else '—'}")
    print()
    return 0


def _do_convert(args) -> int:
    paths = resolve(args.massive, args.tushare, args.storage)
    print(f"[{now_iso()}] converting -> {paths.storage}")
    with Converter(paths, threads=args.threads) as cv:
        results = []
        market = args.market
        do_all = args.all
        want = set(([args.asset] if args.asset else []))

        def want_asset(a):
            return do_all or a in want

        if market in (None, "us"):
            if want_asset("stock"):
                if args.resolution in (None, "daily"):
                    results.append(cv.convert_us_stock_daily(args.start, args.end, args.force))
                if args.resolution in (None, "minute"):
                    results.append(cv.convert_us_stock_minute(args.start, args.end, args.force))
            if want_asset("option"):
                if args.resolution in (None, "daily"):
                    results.append(cv.convert_us_option_day(args.start, args.end, args.force))
                if args.resolution in (None, "minute"):
                    results.append(cv.convert_us_option_minute(args.start, args.end, args.force))
            if want_asset("rates"):
                results.append(cv.convert_rates(args.force))
        if market in (None, "cn"):
            if want_asset("stock"):
                results.append(cv.convert_cn_stock_daily(args.start, args.end, args.force))

        # corporate actions last (derives dividend ratios from converted stock_daily)
        if do_all or "corp" in want or args.asset is None and args.corp_actions:
            results.append(cv.convert_corporate_actions(
                include_massive=market in (None, "us"),
                include_tushare=market in (None, "cn"),
            ))

        print("\nRESULTS")
        for r in results:
            print("  " + r.log())
    print(f"\n[{now_iso()}] done")
    return 0


def _do_validate(args) -> int:
    from .engine import _lit, connect
    paths = resolve(args.massive, args.tushare, args.storage)
    con = connect()
    ok = True
    print("\nVALIDATION")
    for store in ("stock_daily", "stock_minute", "option_day", "option_minute"):
        glob = _lit(paths.store(store) / "trade_date=*" / "*.parquet")
        try:
            n, ndates = con.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT trade_date) FROM read_parquet('{glob}')"
            ).fetchone()
            print(f"  {store:14} rows={n:>12,}  dates={ndates}")
        except Exception as e:  # noqa: BLE001
            print(f"  {store:14} (empty / not built)")
    ca = paths.store("corporate_actions") / "corporate_actions.parquet"
    if ca.exists():
        n, nsym = con.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT symbol) FROM read_parquet('{_lit(ca)}')"
        ).fetchone()
        print(f"  corporate_actions rows={n:,} symbols={nsym}")
    con.close()
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="qfz-data", description="QFinZero data pipeline")
    ap.add_argument("--massive", help="override RAW_MASSIVE_DIR")
    ap.add_argument("--tushare", help="override RAW_TUSHARE_DIR")
    ap.add_argument("--storage", help="override STORAGE_ROOT")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="show raw data + conversion state")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_print_status)

    c = sub.add_parser("convert", help="convert raw data into UPQ storage")
    c.add_argument("--market", choices=["us", "cn"], default=None)
    c.add_argument("--asset", choices=["stock", "option", "rates", "corp"], default=None)
    c.add_argument("--resolution", choices=["daily", "minute"], default=None)
    c.add_argument("--start", help="YYYY-MM-DD inclusive")
    c.add_argument("--end", help="YYYY-MM-DD inclusive")
    c.add_argument("--all", action="store_true", help="convert all assets for the market(s)")
    c.add_argument("--corp-actions", action="store_true", help="also build corporate actions")
    c.add_argument("--force", action="store_true", help="reconvert even if unchanged")
    c.add_argument("--threads", type=int, default=None)
    c.set_defaults(func=_do_convert)

    v = sub.add_parser("validate", help="schema / row-count checks on storage")
    v.set_defaults(func=_do_validate)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
