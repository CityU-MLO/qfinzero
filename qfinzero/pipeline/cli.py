"""``qfz-data`` — the data-pipeline command line.

    qfz-data status                          # what raw data exists + conversion state
    qfz-data convert --market us --asset stock --resolution daily [--start --end]
    qfz-data convert --market us --all       # us stocks+options+rates+corp-actions
    qfz-data convert --market cn --all       # cn A-shares + corp-actions
    qfz-data convert --all                   # everything
    qfz-data convert --vendor databento      # only Databento DBN/parquet files
    qfz-data validate                        # schema / freshness checks
"""

from __future__ import annotations

from pathlib import Path

import argparse
import json
import sys

from .convert import Converter, now_iso
from .paths import resolve
from . import registry


def _print_status(args) -> int:
    data = registry.scan(resolve(args.massive, args.tushare, args.storage, args.databento))
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
    db = raw.get("databento") or {}
    print(f"  databento {db.get('root', '—')}")
    if db.get("present"):
        print(f"    {db['files']} files, {db['convertible_files']} convertible"
              + (f"  ({db['start']} .. {db['end']})" if db.get("start") else ""))
        for g in db.get("groups", []):
            rng = f"{g['start'] or '?'} .. {g['end'] or '?'}"
            flag = "convert" if g["convertible"] else f"skip ({g['role']})"
            print(f"    {g['dataset']:12} {g['schema']:9} {g['files']:5d} files  {rng:24} {flag}")
        if db.get("first_error"):
            print(f"    note: {db['first_error']}")
    else:
        print("    —" + (f" ({db['error']})" if db.get("error") else ""))

    print(f"\nUPQ STORAGE  {store['root']}")
    for k in ("stock_daily", "stock_minute", "option_day", "option_minute",
                  "stock_quote_minute", "option_quote_minute"):
        s = store[k]
        rng = f"{s.get('start','?')} .. {s.get('end','?')}" if s["partitions"] else "—"
        print(f"    {k:14} {s['partitions']:5d} partitions  {rng}")
    for single in ("rates/rates.parquet", "corporate_actions/corporate_actions.parquet",
                   "dividends/dividends.parquet"):
        print(f"    {single:42} {'✓' if store[single] else '—'}")
    dbs = store.get("databento") or {}
    if dbs.get("processed"):
        print(f"    databento parts {dbs['parts']:5d}  dates processed {dbs['start']} .. {dbs['end']}")
    print()
    return 0


def _do_convert(args) -> int:
    paths = resolve(args.massive, args.tushare, args.storage, args.databento)
    print(f"[{now_iso()}] converting -> {paths.storage}")
    with Converter(paths, threads=args.threads) as cv:
        results = []
        market = args.market
        do_all = args.all
        want = set(([args.asset] if args.asset else []))

        vendors = set(args.vendor or ("massive", "tushare", "databento"))

        def want_asset(a):
            return do_all or a in want

        from .convert import default_quote_intervals
        dflt = default_quote_intervals()
        intervals = {"stock": args.stock_quote_interval or args.quote_interval or dflt["stock"],
                     "option": args.option_quote_interval or args.quote_interval or dflt["option"],
                     "future": args.future_quote_interval or args.quote_interval or dflt["future"]}

        if market in (None, "us") and "massive" in vendors:
            if want_asset("stock"):
                if args.resolution in (None, "daily"):
                    results.append(cv.convert_us_stock_daily(args.start, args.end, args.force))
                if args.resolution in (None, "minute"):
                    results.append(cv.convert_us_stock_minute(args.start, args.end, args.force))
                if args.resolution in (None, "quotes"):
                    results.append(cv.convert_us_quotes("stock", args.start, args.end, args.force,
                                                        intervals["stock"]))
            if want_asset("option"):
                if args.resolution in (None, "daily"):
                    results.append(cv.convert_us_option_day(args.start, args.end, args.force))
                if args.resolution in (None, "minute"):
                    results.append(cv.convert_us_option_minute(args.start, args.end, args.force))
                if args.resolution in (None, "quotes"):
                    results.append(cv.convert_us_quotes("option", args.start, args.end, args.force,
                                                        intervals["option"]))
            if want_asset("rates"):
                results.append(cv.convert_rates(args.force))
        if market in (None, "global") and "massive" in vendors:
            if want_asset("crypto"):
                if args.resolution in (None, "daily"):
                    results.append(cv.convert_crypto_daily(args.start, args.end, args.force))
                if args.resolution in (None, "minute"):
                    results.append(cv.convert_crypto_minute(args.start, args.end, args.force))
            if want_asset("fx"):
                if args.resolution in (None, "daily"):
                    results.append(cv.convert_fx_daily(args.start, args.end, args.force))
                if args.resolution in (None, "minute"):
                    results.append(cv.convert_fx_minute(args.start, args.end, args.force))
                if args.resolution in (None, "quotes"):
                    results.append(cv.convert_fx_quotes(args.start, args.end, args.force,
                                                        args.fx_quote_interval or args.quote_interval))
        if market in (None, "us") and "databento" in vendors:
            # Databento fills tickers massive did not write, so it runs after it.
            # ``--vendor databento`` alone means "all Databento assets".
            assets = tuple(a for a in ("stock", "option", "future")
                           if want_asset(a) or (args.asset is None and args.vendor))
            if assets:
                results.append(cv.convert_databento(
                    args.start, args.end, args.force, jobs=args.jobs, assets=assets,
                    quote_interval=intervals))
        if market in (None, "cn") and "tushare" in vendors:
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


def _do_compact(args) -> int:
    from .compact import compact
    paths = resolve(args.massive, args.tushare, args.storage, args.databento)
    stores = [x.strip() for x in args.stores.split(",")] if args.stores else None
    res = compact(paths.storage, stores=stores, older_than_days=args.older_than, dry_run=args.dry_run, on_line=print)
    return 0 if res.get("ok") else 1


def _do_validate(args) -> int:
    from .engine import _lit, connect
    paths = resolve(args.massive, args.tushare, args.storage, args.databento)
    con = connect()
    ok = True
    print("\nVALIDATION")
    for store in ("stock_daily", "stock_minute", "option_day", "option_minute",
                  "stock_quote_minute", "option_quote_minute"):
        glob = _lit(paths.store(store) / "trade_date=*" / "*.parquet")
        try:
            n, ndates = con.execute(
                f"SELECT COUNT(*), COUNT(DISTINCT trade_date) FROM read_parquet('{glob}')"
            ).fetchone()
            print(f"  {store:14} rows={n:>12,}  dates={ndates}")
        except Exception as e:  # noqa: BLE001
            print(f"  {store:14} (empty / not built)")
    nparts = sum(1 for s in ("stock_daily", "stock_minute", "option_day", "option_minute",
                             "stock_quote_minute", "option_quote_minute")
                 for _ in paths.store(s).glob("trade_date=*/part-databento-0000.parquet"))
    if nparts:
        print(f"  databento parts {nparts}")
    ca = paths.store("corporate_actions") / "corporate_actions.parquet"
    if ca.exists():
        n, nsym = con.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT symbol) FROM read_parquet('{_lit(ca)}')"
        ).fetchone()
        print(f"  corporate_actions rows={n:,} symbols={nsym}")
    con.close()
    return 0 if ok else 1


_STATE_GLYPH = {
    "fresh": "✓", "behind": "▲", "missing": "✗",
    "no_raw": "·", "unavailable": "–",
}


def _do_update(args) -> int:
    from ..update import Orchestrator
    paths = resolve(args.massive, args.tushare, args.storage, args.databento)
    orch = Orchestrator(paths=paths)

    if args.status:
        data = orch.status(args.source, args.market)
        if args.json:
            print(json.dumps(data, indent=2, default=str))
            return 0
        _print_update_status(data["sources"])
        return 0

    result = orch.run(
        args.source, market=args.market, since=args.since,
        force=args.force, dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0
    _print_update_result(result)
    return 0


def _print_update_status(sources: list) -> int:
    print("\nUPDATE STATUS  (raw vs converted)")
    print(f"  {'source':16} {'state':12} {'raw_max':12} {'store_max':12} {'lag':>4} {'last run':10}")
    for s in sources:
        g = _STATE_GLYPH.get(s["state"], "?")
        lr = (s.get("last_run") or {}).get("status", "—")
        lag = s["lag_days"] if s["lag_days"] is not None else "—"
        print(f"  {s['id']:16} {g+' '+s['state']:12} {str(s['raw_max'] or '—'):12} "
              f"{str(s['store_max'] or '—'):12} {str(lag):>4} {lr:10}")
    print()
    return 0


def _print_update_result(result: dict) -> int:
    if result.get("dry_run"):
        print("\nUPDATE PLAN  (dry-run — nothing converted)")
        for it in result["plan"]:
            mark = "RUN " if it["will_run"] else "skip"
            print(f"  [{mark}] {it['id']:16} {it['state']:10} ({it['reason']})"
                  f"  raw={it['raw_max'] or '—'} store={it['store_max'] or '—'}")
        runs = sum(1 for it in result["plan"] if it["will_run"])
        print(f"\n  → {runs} source(s) would convert\n")
        return 0
    print(f"\n[{now_iso()}] update results")
    for r in result["results"]:
        if r["status"] == "ok":
            print(f"  ✓ {r['id']:16} partitions={r['partitions']:5d} rows={r['rows']:>12,} "
                  f"({r['duration_s']}s)")
        elif r["status"] == "error":
            print(f"  ✗ {r['id']:16} ERROR: {r['error']}")
        else:
            print(f"  · {r['id']:16} {r['status']} ({r['reason']})")
    print()
    return 0


# ── admin subcommands (config / scan / acquire / schedule / explore / setup) ──

def _emit(data, args) -> int:
    print(json.dumps(data, indent=2, default=str))
    return 0 if (not isinstance(data, dict) or data.get("ok", True)) else 1


def _do_config(args) -> int:
    from ..admin import config_store as cs
    if args.set:
        patch: dict = {}
        for kv in args.set:
            key, _, val = kv.partition("=")
            section, _, leaf = key.strip().partition(".")
            if not leaf:
                print(f"bad --set {kv!r}: expected section.key=value", file=sys.stderr)
                return 2
            patch.setdefault(section, {})[leaf] = val
        cs.update(patch)
    return _emit(cs.masked(), args)


def _do_scan(args) -> int:
    from ..admin import scan
    return _emit(scan.scan(args.provider), args)


def default_scan_roots() -> list[str]:
    """The configured raw libraries plus any extra directories (``index.roots``)."""
    from ..admin import config_store
    cfg = config_store.load()
    d = cfg.get("dirs", {}) or {}
    roots = [d.get(k) for k in ("raw_massive", "raw_databento")]
    roots += list((cfg.get("index", {}) or {}).get("roots") or [])
    return [r for r in dict.fromkeys(roots) if r and Path(r).is_dir()]


def _do_index(args) -> int:
    from ..index import catalog
    paths = resolve(args.massive, args.tushare, args.storage, args.databento)
    roots = args.dirs or default_scan_roots()
    if not roots:
        print("no directories to scan (give some, or set the raw directories in Data setup)")
        return 1
    rep = catalog.scan(roots, paths.storage, symbols=not args.no_symbols, threads=args.threads,
                       on_line=None if args.json else print)
    if args.json:
        return _emit(rep, args)
    print(f"\n{'vendor':10} {'dataset':16} {'schema':15} {'kind':6} {'asset':7} {'res':5} {'files':>7} "
          f"{'GB':>8}  {'range':23} levels / notes")
    for g in rep["groups"]:
        lv = " ".join(f"{k}:{v}" for k, v in sorted(g["levels"].items()) if k)
        notes = "; ".join(f"{n} ({c})" for n, c in sorted(g["notes"].items(), key=lambda kv: -kv[1])[:2])
        scope = "" if g["scope"] == "in" else f" [{g['scope']}]"
        print(f"{(g['vendor'] or '')[:10]:10} {(g['dataset'] or '')[:16]:16} {(g['schema'] or '')[:15]:15} "
              f"{g['kind'][:6]:6} {(g['asset_class'] or '-')[:7]:7} {(g['resolution'] or '-')[:5]:5} "
              f"{g['files']:7,} {g['bytes'] / 1e9:8.2f}  {(g['first'] or '?')} .. {(g['last'] or '?')}  {lv}{scope}"
              + (f"  {notes}" if notes else ""))
    u = rep["unknown"]
    print(f"\nnot market data we know: {u['files']:,} files ({u['bytes'] / 1e9:.2f} GB)"
          + (f", e.g. {u['examples'][0]}" if u["examples"] else ""))
    print(f"{rep['files']:,} files ({rep['read']:,} read, {rep['reused']:,} unchanged) in {rep['elapsed_s']} s -> {rep['index']}")
    return 0


def _do_massive_parquet(args) -> int:
    from ..admin import massive_dl
    root = resolve(args.massive, args.tushare, args.storage, args.databento).massive
    rep = massive_dl.convert_library(Path(root), indices=args.indices or None, workers=args.workers,
                                     delete_csv=args.delete_csv, on_line=None if args.json else print)
    if args.json:
        return _emit(rep, args)
    print(f"\n{rep['files']:,} csv.gz: {rep['converted']:,} converted, {rep['verified']:,} already converted "
          f"(verified), {rep['deleted']:,} csv.gz removed, {rep['failed']:,} failed"
          + (f", {len(rep['unsorted']):,} too large to sort" if rep["unsorted"] else ""))
    return 0 if rep["ok"] else 1


def _do_acquire(args) -> int:
    from ..admin import acquire
    if args.list:
        return _emit({"targets": acquire.targets()}, args)
    on_line = None if args.json else (lambda ln: print(ln))
    params = None
    if args.target == "databento":
        params = {
            "dataset": args.dataset, "schema": args.schema,
            "symbols": args.symbols, "stype_in": args.stype_in,
            "start": args.start, "end": args.end, "max_cost": args.max_cost,
            "out_dir": args.databento,
        }
    res = acquire.acquire(args.target, dry_run=not args.run, prod=args.prod,
                          on_line=on_line, params=params)
    if args.json:
        return _emit(res, args)
    if res.get("error"):
        print(f"[error] {res['error']}")
    rc = f"rc={res.get('returncode')}, " if res.get("returncode") is not None else ""
    print(f"\n[{res.get('target')}] {'ok' if res.get('ok') else 'FAILED'} "
          f"({rc}dry_run={res.get('dry_run')})")
    return 0 if res.get("ok") else 1


def _do_schedule(args) -> int:
    from ..admin import scheduler
    if args.action == "apply":
        return _emit(scheduler.apply(dry_run=args.dry_run), args)
    if args.action == "clear":
        return _emit(scheduler.clear(), args)
    return _emit(scheduler.status(), args)


def _do_explore(args) -> int:
    from ..admin import explore
    if args.symbols:
        data = explore.store_symbols(args.symbols, limit=args.limit, start=args.start, end=args.end)
    else:
        data = explore.overview()
    return _emit(data, args)


def _do_setup_state(args) -> int:
    from ..admin import setup
    return _emit(setup.state(), args)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="qfz-data", description="QFinZero data pipeline")
    ap.add_argument("--massive", help="override RAW_MASSIVE_DIR")
    ap.add_argument("--tushare", help="override RAW_TUSHARE_DIR")
    ap.add_argument("--storage", help="override STORAGE_ROOT")
    ap.add_argument("--databento", help="override RAW_DATABENTO_DIR")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="show raw data + conversion state")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=_print_status)

    c = sub.add_parser("convert", help="convert raw data into UPQ storage")
    c.add_argument("--market", choices=["us", "cn", "global"], default=None)
    c.add_argument("--asset", choices=["stock", "option", "future", "crypto", "fx", "rates", "corp"], default=None)
    c.add_argument("--resolution", choices=["daily", "minute", "quotes"], default=None)
    c.add_argument("--quote-interval", type=int, choices=[1, 5, 15, 30, 60], default=None,
                   help="keep one NBBO per N minutes in the quote stores (default 1)")
    c.add_argument("--stock-quote-interval", type=int, choices=[1, 5, 15, 30, 60], default=None)
    c.add_argument("--option-quote-interval", type=int, choices=[1, 5, 15, 30, 60], default=None)
    c.add_argument("--future-quote-interval", type=int, choices=[1, 5, 15, 30, 60], default=None)
    c.add_argument("--fx-quote-interval", type=int, choices=[1, 5, 15, 30, 60], default=None)
    c.add_argument("--start", help="YYYY-MM-DD inclusive")
    c.add_argument("--end", help="YYYY-MM-DD inclusive")
    c.add_argument("--all", action="store_true", help="convert all assets for the market(s)")
    c.add_argument("--corp-actions", action="store_true", help="also build corporate actions")
    c.add_argument("--force", action="store_true", help="reconvert even if unchanged")
    c.add_argument("--threads", type=int, default=None)
    c.add_argument("--vendor", action="append", choices=["massive", "tushare", "databento"],
                   help="limit to one raw vendor (repeatable; default: all present)")
    c.add_argument("--jobs", type=int, default=None,
                   help="worker processes for Databento file extraction (default 1)")
    c.set_defaults(func=_do_convert)

    v = sub.add_parser("validate", help="schema / row-count checks on storage")
    v.set_defaults(func=_do_validate)

    u = sub.add_parser("update", help="detect new raw and convert (convert-only orchestration)")
    u.add_argument("--source", default="all",
                   help="all | prices | news | econ | earnings | <source_id>[,...]")
    u.add_argument("--market", choices=["us", "cn"], default=None)
    u.add_argument("--since", help="YYYY-MM-DD lower bound passed to the converters")
    u.add_argument("--dry-run", action="store_true", help="show the plan, convert nothing")
    u.add_argument("--force", action="store_true", help="convert even if not stale")
    u.add_argument("--status", action="store_true", help="print freshness + last run, convert nothing")
    u.add_argument("--json", action="store_true")
    u.set_defaults(func=_do_update)

    # ── admin: config ──
    cf = sub.add_parser("config", help="show / edit vendor credentials + dirs + schedule (masked)")
    cf.add_argument("--set", action="append", metavar="section.key=value",
                    help="set a config value (repeatable), e.g. tushare.token=abc")
    cf.add_argument("--json", action="store_true", default=True, help=argparse.SUPPRESS)
    cf.set_defaults(func=_do_config)

    # ── admin: scan ──
    sc = sub.add_parser("scan", help="check vendor reachability / permissions")
    sc.add_argument("provider", choices=["massive", "tushare", "databento"])
    sc.add_argument("--json", action="store_true", default=True, help=argparse.SUPPRESS)
    sc.set_defaults(func=_do_scan)

    # ── admin: acquire (trigger download scripts) ──
    sc = sub.add_parser("index", help="catalogue raw files in place (no conversion) under _state/index")
    sc.add_argument("dirs", nargs="*", help="directories (default: the configured raw libraries)")
    sc.add_argument("--no-symbols", action="store_true", help="skip per-file symbol lists (faster)")
    sc.add_argument("--threads", type=int, default=8)
    sc.add_argument("--json", action="store_true", help="emit the report as JSON")
    sc.set_defaults(func=_do_index)

    mp = sub.add_parser("massive-parquet",
                        help="convert massive .csv.gz flat files in the raw library to sorted, page-indexed parquet")
    mp.add_argument("indices", nargs="*", help="e.g. global_forex/quotes_v1 (default: the whole library)")
    mp.add_argument("--workers", type=int, default=4)
    mp.add_argument("--delete-csv", action="store_true",
                    help="remove each .csv.gz once its parquet is verified (default: keep both)")
    mp.add_argument("--json", action="store_true", help="emit the report as JSON")
    mp.set_defaults(func=_do_massive_parquet)

    ac = sub.add_parser("acquire", help="trigger a raw-download script (dry-run by default)")
    ac.add_argument("target", nargs="?", help="news | databento")
    ac.add_argument("--list", action="store_true", help="list acquire targets + readiness")
    ac.add_argument("--run", action="store_true", help="actually run (default is --dry-run)")
    ac.add_argument("--prod", action="store_true", help="use the script's production paths")
    ac.add_argument("--json", action="store_true", help="emit JSON instead of streaming logs")
    dbg = ac.add_argument_group("databento target")
    dbg.add_argument("--dataset", help="e.g. XNAS.ITCH, EQUS.MINI, OPRA.PILLAR")
    dbg.add_argument("--schema", help="e.g. ohlcv-1m, trades, tcbbo, mbo")
    dbg.add_argument("--symbols", help="comma-separated, e.g. SPY,QQQ or SPY.OPT with --stype-in parent")
    dbg.add_argument("--stype-in", default="raw_symbol", help="raw_symbol (default) | parent | ...")
    dbg.add_argument("--start", help="YYYY-MM-DD inclusive")
    dbg.add_argument("--end", help="YYYY-MM-DD inclusive")
    dbg.add_argument("--max-cost", type=float, default=None,
                     help="refuse to download when the quoted cost (USD) exceeds this")
    ac.set_defaults(func=_do_acquire)

    # ── admin: schedule ──
    sh = sub.add_parser("schedule", help="show / apply / clear the cron update schedule")
    sh.add_argument("action", nargs="?", choices=["show", "apply", "clear"], default="show")
    sh.add_argument("--dry-run", action="store_true", help="preview the crontab, install nothing")
    sh.add_argument("--json", action="store_true", default=True, help=argparse.SUPPRESS)
    sh.set_defaults(func=_do_schedule)

    # ── admin: explore ──
    ex = sub.add_parser("explore", help="coverage overview, or per-symbol for one store")
    ex.add_argument("--symbols", metavar="STORE", help="stock_daily | stock_minute | option_day | option_minute")
    ex.add_argument("--limit", type=int, default=200)
    ex.add_argument("--start", help="YYYY-MM-DD")
    ex.add_argument("--end", help="YYYY-MM-DD")
    ex.add_argument("--json", action="store_true", default=True, help=argparse.SUPPRESS)
    ex.set_defaults(func=_do_explore)

    # ── maintenance: archive compression ──
    cp = sub.add_parser("compact", help="rewrite partitions older than N days at zstd level 9 (3-6%% smaller)")
    cp.add_argument("--older-than", type=int, default=30, help="days (default 30)")
    cp.add_argument("--stores", default=None, help="comma-separated stores (default: all price stores)")
    cp.add_argument("--dry-run", action="store_true")
    cp.set_defaults(func=_do_compact)

    # ── admin: setup-state ──
    ss = sub.add_parser("setup-state", help="first-run setup state (wizard vs status)")
    ss.add_argument("--json", action="store_true", default=True, help=argparse.SUPPRESS)
    ss.set_defaults(func=_do_setup_state)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
