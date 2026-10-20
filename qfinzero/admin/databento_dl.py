"""Databento historical downloads into the raw Databento library.

``qfz-data acquire databento --dataset … --schema … --symbols … --start … --end …``
(or ``POST /data/acquire`` with ``target="databento"``) lands DBN files at::

    $RAW_DATABENTO_DIR/<asset>/<dataset>/<schema>/<SYMBOL>/<YYYY-MM-DD>.dbn.zst

the library layout v2 (2026-10-20), which ``qfz-data convert --vendor databento``
reads in place:

* ``asset`` is ``options`` (``OPRA.*``), ``futures`` (CME Globex, ICE, Nodal,
  Cboe Futures, Eurex) or ``equity`` (US venues and consolidated feeds), taken
  from the dataset (:func:`asset_dir`);
* ``SYMBOL`` is the stock code with spaces as dots (``BRK.B``), the option
  root (``SPY`` for ``SPY.OPT`` or any SPY contract) or the futures product
  root (``ZN`` for ``ZN.v.0`` or ``ZNZ6``) (:func:`symbol_dir`);
* one file holds one symbol directory's day, every schema including OHLCV: the
  UTC date of ``ts_recv`` (``ts_event`` without it), as Databento cuts its own
  files. Blue Ocean (``OCEA.*``) files are one 20:00-04:00 ET session each,
  named by the ET date the session opens.

A request costs about 30 s of latency whatever its size, so the missing days of
a symbol directory are asked for in runs of up to ``chunk_days`` and the result
is split losslessly into day files (:mod:`qfinzero.admin.dbn_split`, verified
record for record); a one-day run is kept exactly as Databento sent it. Days
that come back empty are noted in ``_meta/qfz_downloads.jsonl`` so a re-run
neither quotes nor fetches them again. A day file that lacks a requested symbol
is replaced by one with the union (the larger coverage wins).

Spending money is never implicit:

* **Dry-run by default** — prints the quoted cost (``metadata.get_cost``, free to
  call), the billable size and the files it would write.
* **Paid data needs a ceiling** — a real run refuses when the quote is above
  ``max_cost`` (USD), and ``max_cost`` defaults to 0, so only free requests (for
  example data inside a subscription) run without an explicit ``--max-cost``.
* Days already present are not quoted again, so re-runs never pay twice.
* **Budgets** — a key may carry a monthly budget (``monthly_budget_usd``); a
  request whose quote is above what is left this month is refused. What a run
  actually fetched is recorded in the spend ledger (``vendor_keys``).

Requests never go through a proxy: ``HTTP(S)_PROXY`` / ``ALL_PROXY`` are taken
out of the environment while Databento is called. Progress goes to
``on_progress(**fields)``; ``should_stop()`` is checked between requests.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from . import dbn_split

OnLine = Callable[[str], None]
LAYOUT = "v2 (2026-10-20): <asset>/<dataset>/<schema>/<symbol>/<date>"
LEDGER = Path("_meta") / "qfz_downloads.jsonl"

ASSET_PREFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("options", ("OPRA.",)),
    ("futures", ("GLBX.", "IFUS.", "IFEU.", "IFLL.", "NDEX.", "XCBF.", "XEUR.", "XEEE.")),
    ("equity", ("XNAS.", "EQUS.", "DBEQ.", "XNYS.", "ARCX.", "OCEA.", "BATS.", "BATY.", "EDGA.", "EDGX.",
                "IEXG.", "MEMX.", "XASE.", "XCHI.", "XBOS.", "XPSX.", "XCIS.", "EPRL.")),
)
# runs of days per request: small-record schemas take a month, tick schemas a week
LONG_RUN_SCHEMAS = ("ohlcv-", "definition", "statistics", "status", "imbalance", "bbo-1m", "cbbo-1m")
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_OSI = re.compile(r"^([A-Z]+)\s*\d{6}[CP]\d{8}$")
_FUT_ROOT = re.compile(r"^([A-Z0-9]+?)([FGHJKMNQUVXZ][0-9]{1,2})?$")
_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
_ENV_LOCK = threading.Lock()


def asset_dir(dataset: str) -> str:
    ds = str(dataset).upper()
    for asset, prefixes in ASSET_PREFIXES:
        if ds.startswith(prefixes):
            return asset
    raise ValueError(f"{dataset}: not in the library's asset table (options / equity / futures)")


def symbol_dir(asset: str, symbol: str) -> str:
    """Directory name a requested symbol's files go to."""
    s = str(symbol).strip()
    if asset == "options":
        m = _OSI.match(s)
        root = m.group(1) if m else s.split(".")[0].split(" ")[0]
    elif asset == "futures":
        first = s.split("-")[0].split(".")[0]          # ZN.v.0 / ZN.FUT -> ZN; ZNZ6-ZNH7 -> ZNZ6
        m = _FUT_ROOT.match(first)
        root = m.group(1) if m else first
    else:
        root = re.sub(r"\s+", ".", s)                    # BRK B -> BRK.B
    out = _SAFE.sub("_", root)
    if not out:
        raise ValueError(f"empty symbol directory for {symbol!r}")
    return out


def _parse_date(s: str | None, name: str) -> date:
    if not s:
        raise ValueError(f"missing {name} (YYYY-MM-DD)")
    return date.fromisoformat(str(s)[:10])


@contextmanager
def no_proxy() -> Iterator[None]:
    """Databento is called directly: the box's local proxy would only slow it down."""
    with _ENV_LOCK:
        saved = {k: os.environ.pop(k) for k in _PROXY_VARS if k in os.environ}
    try:
        yield
    finally:
        with _ENV_LOCK:
            os.environ.update(saved)


# ── the ledger of days that came back empty ─────────────────────────────────

def _ledger(root: Path) -> dict[tuple[str, str, str, str], set[str]]:
    """(dataset, schema, dir, day) -> symbols known to have no data that day."""
    out: dict[tuple[str, str, str, str], set[str]] = {}
    p = root / LEDGER
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("status") == "empty":
            out.setdefault((r["dataset"], r["schema"], r["dir"], r["day"]), set()).update(r.get("symbols") or [])
    return out


def _note(root: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    p = root / LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


# ── planning ─────────────────────────────────────────────────────────────────

def _request(params: dict[str, Any]) -> tuple[str, str, str, dict[str, list[str]], date, date]:
    """(dataset, schema, asset, symbol directory -> requested symbols, start, end)."""
    dataset = str(params.get("dataset") or "").strip()
    schema = str(params.get("schema") or "").strip()
    if not dataset or not schema:
        raise ValueError("dataset and schema are required")
    from qfinzero.pipeline.sources.databento import out_of_scope
    if out_of_scope(schema, dataset):
        raise ValueError(f"{schema} is not used by QFinZero (it stops at minute bars and BBO; "
                         "for Blue Ocean's overnight session download ohlcv-1m and bbo-1m)")
    asset = asset_dir(dataset)
    syms = params.get("symbols") or []
    if isinstance(syms, str):
        syms = [s.strip() for s in syms.split(",")]
    syms = [s for s in syms if s]
    if not syms:
        raise ValueError("symbols are required")
    start = _parse_date(params.get("start"), "start")
    end = _parse_date(params.get("end") or params.get("start"), "end")
    if end < start:
        raise ValueError("end is before start")
    groups: dict[str, list[str]] = {}
    for s in syms:
        groups.setdefault(symbol_dir(asset, s), [])
        if s not in groups[symbol_dir(asset, s)]:
            groups[symbol_dir(asset, s)].append(s)
    return dataset, schema, asset, groups, start, end


def slots(params: dict[str, Any]) -> int:
    """Day files the request covers (symbol directories x days)."""
    _, _, _, groups, start, end = _request(params)
    return len(groups) * ((end - start).days + 1)


def plan(params: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    """One job per (symbol directory, day) that is not already in the library:
    ``{dir, day, symbols, path, replace}``. ``replace`` marks a day file that
    exists but lacks a requested symbol (it is fetched again with the union)."""
    dataset, schema, asset, groups, start, end = _request(params)
    base = root / asset / _SAFE.sub("_", dataset) / _SAFE.sub("_", schema)
    empty = _ledger(root)
    jobs = []
    for d, wanted in groups.items():
        cur = start
        while cur <= end:
            day = cur.isoformat()
            path = base / d / f"{day}.dbn.zst"
            need, replace = list(wanted), False
            if path.exists():
                try:
                    have = dbn_split.header_symbols(path)
                except Exception:  # noqa: BLE001 - an unreadable file is fetched again
                    have = []
                missing = [s for s in wanted if s not in have]
                if not missing:
                    cur += timedelta(days=1)
                    continue
                need, replace = sorted(set(have) | set(wanted)), True
            elif set(wanted) <= empty.get((dataset, schema, d, day), set()):
                cur += timedelta(days=1)
                continue
            jobs.append({"dir": d, "day": day, "symbols": need, "path": str(path), "replace": replace})
            cur += timedelta(days=1)
    return jobs


def runs(jobs: list[dict[str, Any]], dataset: str, schema: str, chunk_days: Optional[int] = None) -> list[dict[str, Any]]:
    """Consecutive days of one directory with the same symbols, as single requests."""
    chunk = chunk_days or (31 if schema.startswith(LONG_RUN_SCHEMAS) else 7)
    out: list[dict[str, Any]] = []
    for j in sorted(jobs, key=lambda j: (j["dir"], j["day"])):
        last = out[-1] if out else None
        if (last and last["dir"] == j["dir"] and last["symbols"] == j["symbols"] and len(last["jobs"]) < chunk
                and date.fromisoformat(j["day"]) == date.fromisoformat(last["jobs"][-1]["day"]) + timedelta(days=1)):
            last["jobs"].append(j)
        else:
            out.append({"dir": j["dir"], "symbols": j["symbols"], "jobs": [j]})
    for r in out:
        first, lastd = date.fromisoformat(r["jobs"][0]["day"]), date.fromisoformat(r["jobs"][-1]["day"])
        lo, _ = dbn_split.day_window(dataset, first)
        _, hi = dbn_split.day_window(dataset, lastd)
        r["start"] = datetime.fromtimestamp(lo / 1e9, tz=timezone.utc).isoformat()
        r["end"] = datetime.fromtimestamp(hi / 1e9, tz=timezone.utc).isoformat()
        r["out_dir"] = str(Path(r["jobs"][0]["path"]).parent)
    return out


def _client(api_key: str):
    import databento as db
    return db.Historical(api_key)


def _store_run(tmp: Path, run: dict[str, Any], dataset: str) -> tuple[list[str], list[str]]:
    """Put a downloaded run into day files; returns (written days, empty days)."""
    days = [j["day"] for j in run["jobs"]]
    out_dir = Path(run["out_dir"])
    replace = {date.fromisoformat(j["day"]) for j in run["jobs"] if j["replace"]}
    _, body = dbn_split.read(tmp)
    if not body:
        return [], days
    if len(days) == 1:
        # one day asked for, one day received: keep Databento's file as sent
        out = out_dir / f"{days[0]}.dbn.zst"
        out_dir.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, out)
        return days, []
    outs, recs = dbn_split.split(tmp, out_dir, overwrite=replace)
    dbn_split.verify(outs, recs)
    written = sorted({Path(p).name[:10] for p, _ in outs})
    stray = [d for d in written if d not in days]
    if stray:
        raise ValueError(f"records outside the requested days: {stray[:3]}")
    return written, [d for d in days if d not in written]


def download(
    params: dict[str, Any],
    *,
    api_key: str,
    root: Path,
    dry_run: bool = True,
    on_line: OnLine | None = None,
    client_factory: Optional[Callable[[str], Any]] = None,
    on_progress: Optional[Callable[..., None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    key_id: str = "",
    job_id: str = "",
    chunk_days: Optional[int] = None,
) -> dict[str, Any]:
    """Quote, and unless ``dry_run``, download a Databento request into day files."""
    log = on_line or (lambda _ln: None)
    prog = on_progress or (lambda **_k: None)
    stop = should_stop or (lambda: False)
    root = Path(root)
    try:
        todo = plan(params, root)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if not api_key:
        return {"ok": False, "error": "Databento API key not configured (databento.api_key)"}
    try:
        client = (client_factory or _client)(api_key)
    except ModuleNotFoundError:
        return {"ok": False,
                "error": "databento package not installed (pip install 'qfinzero[databento]')"}

    dataset, schema = params["dataset"], params["schema"]
    stype_in = params.get("stype_in") or "raw_symbol"
    max_cost = float(params.get("max_cost") or 0.0)
    batches = runs(todo, dataset, schema, chunk_days)
    log(f"[databento] {dataset} {schema}: {len(todo)} day file(s) to fetch in {len(batches)} request(s) "
        f"-> {root / asset_dir(dataset)}")

    cost, size = 0.0, 0
    try:
        with no_proxy():
            for r in batches:
                kw = dict(dataset=dataset, schema=schema, symbols=r["symbols"], stype_in=stype_in,
                          start=r["start"], end=r["end"])
                r["cost"] = float(client.metadata.get_cost(**kw))
                cost += r["cost"]
                size += int(client.metadata.get_billable_size(**kw))
    except Exception as e:  # noqa: BLE001 - bad symbols/dates/entitlements
        return {"ok": False, "error": f"quote failed: {type(e).__name__}: {e}"}
    log(f"[databento] quote: ${cost:,.2f} for {size / 1e9:,.3f} GB billable")
    from .vendor_keys import budget_left, record_spend
    left = budget_left(key_id) if key_id else None
    summary = {"dataset": dataset, "schema": schema, "files": slots(params), "to_fetch": len(todo),
               "requests": len(batches),
               "cost_usd": round(cost, 4), "billable_bytes": size, "root": str(root), "layout": LAYOUT,
               "dry_run": dry_run, "key_id": key_id, "budget_left_usd": None if left is None else round(left, 4)}
    prog(stage="quoted", files_total=len(todo), files_done=0, bytes_done=0, cost_usd=round(cost, 4),
         billable_bytes=size)
    if dry_run:
        for j in todo[:10]:
            log(f"  would write {j['path']}" + (" (replacing: adds symbols)" if j["replace"] else ""))
        if len(todo) > 10:
            log(f"  … and {len(todo) - 10} more")
        return {"ok": True, **summary}
    if cost > max_cost + 1e-9:
        return {"ok": False, **summary,
                "error": f"quoted ${cost:,.2f} exceeds max_cost ${max_cost:,.2f}; "
                         "re-run with a higher --max-cost to accept the charge"}
    if left is not None and cost > left + 1e-9:
        return {"ok": False, **summary,
                "error": f"quoted ${cost:,.2f} exceeds what key {key_id} may still spend this month "
                         f"(${left:,.2f}); raise its monthly budget or wait"}

    written, empty, failed, done_bytes, spent, stopped = 0, 0, [], 0, 0.0, False
    tmp_dir = root / "_meta" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    prog(stage="downloading")
    for r in batches:
        if stop():
            log("[databento] stopped by the user")
            stopped = True
            break
        tmp = tmp_dir / f"{uuid.uuid4().hex}.dbn.zst.part"
        label = f"{r['dir']} {r['jobs'][0]['day']}" + (f"..{r['jobs'][-1]['day']}" if len(r["jobs"]) > 1 else "")
        prog(current=label)
        watching = threading.Event()

        def watch(tmp=tmp, base=done_bytes):
            while not watching.wait(0.5):
                try:
                    prog(bytes_done=base + tmp.stat().st_size)
                except OSError:
                    pass
        w = threading.Thread(target=watch, daemon=True)
        w.start()
        t0 = time.time()
        try:
            with no_proxy():
                client.timeseries.get_range(dataset=dataset, schema=schema, symbols=r["symbols"],
                                            stype_in=stype_in, start=r["start"], end=r["end"], path=str(tmp))
            nbytes = tmp.stat().st_size
            days_w, days_e = _store_run(tmp, r, dataset)
            written += len(days_w)
            empty += len(days_e)
            done_bytes += nbytes
            spent += r.get("cost", 0.0)
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _note(root, [{"dataset": dataset, "schema": schema, "dir": r["dir"], "day": d, "symbols": r["symbols"],
                          "status": "written" if d in days_w else "empty", "ts": now, "job": job_id}
                         for d in [j["day"] for j in r["jobs"]]])
            log(f"  {label}: {len(days_w)} day file(s), {len(days_e)} empty ({time.time() - t0:.0f} s)")
        except Exception as e:  # noqa: BLE001 - keep going, report at the end
            failed.append({"run": label, "days": len(r["jobs"]), "error": f"{type(e).__name__}: {e}"})
            log(f"  FAILED {label}: {e}")
        finally:
            watching.set()
            w.join(timeout=2)
            tmp.unlink(missing_ok=True)
        prog(files_done=written + empty + sum(x["days"] for x in failed), bytes_done=done_bytes,
             files_failed=len(failed))
    record_spend(key_id or "default", dataset, schema, spent, written, job_id)
    prog(stage="done", cost_usd=round(spent, 4))
    return {"ok": not failed and not stopped, **summary, "written": written, "empty": empty, "failed": failed,
            "spent_usd": round(spent, 4), **({"error": "stopped by the user"} if stopped else {})}
