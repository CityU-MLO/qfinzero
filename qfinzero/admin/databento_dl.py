"""Databento historical downloads into the raw Databento root.

``qfz-data acquire databento --dataset … --schema … --symbols … --start … --end …``
(or ``POST /data/acquire`` with ``target="databento"``) lands DBN files at::

    $RAW_DATABENTO_DIR/<dataset>/<schema>/<symbol>/<YYYY-MM-DD>.dbn.zst          # tick schemas
    $RAW_DATABENTO_DIR/<dataset>/<schema>/<symbol>/<start>_<end>.dbn.zst         # ohlcv-*

which ``qfz-data convert --vendor databento`` then reads in place.

Spending money is never implicit:

* **Dry-run by default** — prints the quoted cost (``metadata.get_cost``, free to
  call), the billable size and the files it would write.
* **Paid data needs a ceiling** — a real run refuses when the quote is above
  ``max_cost`` (USD), and ``max_cost`` defaults to 0, so only free requests (for
  example data inside a subscription) run without an explicit ``--max-cost``.
* Existing files are skipped and only the missing ones are quoted, so re-runs
  are idempotent and never pay twice.
* **Budgets** — a key may carry a monthly budget (``monthly_budget_usd``); a
  request whose quote is above what is left this month is refused. What a run
  actually fetched is recorded in the spend ledger (``vendor_keys``).

Progress goes to ``on_progress(**fields)`` (files, bytes written so far, the
file being fetched) and ``should_stop()`` is checked between files.
"""

from __future__ import annotations

import os
import re
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

OnLine = Callable[[str], None]

TICK_SCHEMAS = {
    "mbo", "mbp-1", "mbp-10", "tbbo", "trades", "tcbbo", "cmbp-1",
    "bbo-1s", "bbo-1m", "cbbo-1s", "cbbo-1m", "statistics", "status", "imbalance",
}
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _days(start: date, end: date) -> list[date]:
    out, cur = [], start
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _parse_date(s: str | None, name: str) -> date:
    if not s:
        raise ValueError(f"missing {name} (YYYY-MM-DD)")
    return date.fromisoformat(str(s)[:10])


def plan(params: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    """Expand a request into per-file jobs ``{symbol, start, end, path}``.

    Tick schemas are split per weekday per symbol (one file per trading day);
    OHLCV schemas use one file per symbol for the whole range.
    """
    dataset = str(params.get("dataset") or "").strip()
    schema = str(params.get("schema") or "").strip()
    if not dataset or not schema:
        raise ValueError("dataset and schema are required")
    from qfinzero.pipeline.sources.databento import out_of_scope
    if out_of_scope(schema, dataset):
        raise ValueError(f"{schema} from {dataset} is not used by QFinZero (it stops at consolidated BBO; "
                         "market-by-order data only from Blue Ocean, OCEA.MEMOIR)")
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

    base = root / _SAFE.sub("_", dataset) / _SAFE.sub("_", schema)
    jobs = []
    for sym in syms:
        sdir = base / _SAFE.sub("_", sym)
        if schema in TICK_SCHEMAS:
            for d in _days(start, end):
                jobs.append({"symbol": sym, "start": d.isoformat(),
                             "end": (d + timedelta(days=1)).isoformat(),
                             "path": str(sdir / f"{d.isoformat()}.dbn.zst")})
        else:
            jobs.append({"symbol": sym, "start": start.isoformat(),
                         "end": (end + timedelta(days=1)).isoformat(),
                         "path": str(sdir / f"{start.isoformat()}_{end.isoformat()}.dbn.zst")})
    return jobs


def _client(api_key: str):
    import databento as db
    return db.Historical(api_key)


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
) -> dict[str, Any]:
    """Quote, and unless ``dry_run``, download a Databento request as DBN files."""
    log = on_line or (lambda _ln: None)
    prog = on_progress or (lambda **_k: None)
    stop = should_stop or (lambda: False)
    try:
        jobs = plan(params, root)
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
    todo = [j for j in jobs if not Path(j["path"]).exists()]
    log(f"[databento] {dataset} {schema} {len(jobs)} file(s), {len(jobs) - len(todo)} already present")

    # Quote only what is missing, grouped by identical (start, end) windows.
    cost, size = 0.0, 0
    windows: dict[tuple[str, str], list[str]] = {}
    for j in todo:
        windows.setdefault((j["start"], j["end"]), []).append(j["symbol"])
    try:
        for (s, e), syms in windows.items():
            kw = dict(dataset=dataset, schema=schema, symbols=syms, stype_in=stype_in,
                      start=s, end=e)
            cost += float(client.metadata.get_cost(**kw))
            size += int(client.metadata.get_billable_size(**kw))
    except Exception as e:  # noqa: BLE001 - bad symbols/dates/entitlements
        return {"ok": False, "error": f"quote failed: {type(e).__name__}: {e}"}
    log(f"[databento] quote: ${cost:,.2f} for {size / 1e9:,.3f} GB billable "
        f"({len(todo)} file(s) to fetch)")
    from .vendor_keys import budget_left, record_spend
    left = budget_left(key_id) if key_id else None
    summary = {"dataset": dataset, "schema": schema, "files": len(jobs),
               "to_fetch": len(todo), "cost_usd": round(cost, 4), "billable_bytes": size,
               "root": str(root), "dry_run": dry_run, "key_id": key_id,
               "budget_left_usd": None if left is None else round(left, 4)}
    prog(stage="quoted", files_total=len(todo), files_done=0, bytes_done=0, cost_usd=round(cost, 4),
         billable_bytes=size)
    if dry_run:
        for j in todo[:10]:
            log(f"  would write {j['path']}")
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

    written, failed, done_bytes = 0, [], 0
    prog(stage="downloading")
    for j in todo:
        if stop():
            log("[databento] stopped by the user")
            break
        out = Path(j["path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + ".part")
        prog(current=f"{j['symbol']} {j['start']}")
        watching = threading.Event()

        def watch(tmp=tmp, base=done_bytes):
            while not watching.wait(0.5):
                try:
                    prog(bytes_done=base + tmp.stat().st_size)
                except OSError:
                    pass
        w = threading.Thread(target=watch, daemon=True)
        w.start()
        try:
            client.timeseries.get_range(
                dataset=dataset, schema=schema, symbols=[j["symbol"]], stype_in=stype_in,
                start=j["start"], end=j["end"], path=str(tmp))
            os.replace(tmp, out)
            written += 1
            done_bytes += out.stat().st_size
            log(f"  wrote {out}")
        except Exception as e:  # noqa: BLE001 - keep going, report at the end
            tmp.unlink(missing_ok=True)
            failed.append({"path": str(out), "error": f"{type(e).__name__}: {e}"})
            log(f"  FAILED {out}: {e}")
        finally:
            watching.set()
            w.join(timeout=2)
        prog(files_done=written + len(failed), bytes_done=done_bytes, files_failed=len(failed))
    spent = cost * written / len(todo) if todo else 0.0
    record_spend(key_id or "default", dataset, schema, spent, written, job_id)
    prog(stage="done", cost_usd=round(spent, 4))
    stopped = written + len(failed) < len(todo)
    return {"ok": not failed and not stopped, **summary, "written": written, "failed": failed,
            "spent_usd": round(spent, 4), **({"error": "stopped by the user"} if stopped else {})}
