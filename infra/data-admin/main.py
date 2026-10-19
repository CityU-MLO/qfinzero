"""QFinZero data-admin service (:19340).

The operator control plane for the shared data protocol — the thin FastAPI wrapper
(design §3.5) over :mod:`qfinzero.admin` (config / scan / acquire / scheduler /
explore / setup) and :mod:`qfinzero.update` (convert-only orchestration). Long jobs
(convert, download) run in a background thread with SSE log streaming.

Run:  ``python infra/data-admin/main.py``   (or set ``DATA_ADMIN_PORT``)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the repo importable when run as a bare script.
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from fastapi import Body, FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402

from qfinzero.admin import acquire, config_store, explore, scan, scheduler, setup  # noqa: E402
from jobs import registry, sse_logs  # noqa: E402

app = FastAPI(title="QFinZero data-admin", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _orchestrator():
    from qfinzero.pipeline.paths import resolve
    from qfinzero.update import Orchestrator
    d = config_store.dirs()
    paths = resolve(d.get("raw_massive"), d.get("raw_tushare"), d.get("storage_root"),
                    d.get("raw_databento"))
    return Orchestrator(paths=paths)


# ── health ──────────────────────────────────────────────────────────────────
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "data-admin", "version": "0.1.0"}


# ── setup / config ──────────────────────────────────────────────────────────
@app.get("/data/setup-state")
def setup_state() -> dict:
    return setup.state()


@app.get("/data/config")
def get_config() -> dict:
    return config_store.masked()


@app.put("/data/config")
def put_config(patch: dict = Body(...)) -> dict:
    config_store.update(patch or {})
    return config_store.masked()


@app.post("/data/scan")
def post_scan(body: dict = Body(...)) -> dict:
    provider = str((body or {}).get("provider", "")).lower()
    if provider not in scan.PROVIDERS:
        raise HTTPException(422, f"provider must be one of {list(scan.PROVIDERS)}")
    return scan.scan(provider)


# ── sources / status (freshness) ────────────────────────────────────────────
@app.get("/data/sources")
def sources(source: str = "all", market: str | None = None) -> dict:
    return _orchestrator().status(source, market)


@app.get("/data/status")
def status(source: str = "all", market: str | None = None) -> dict:
    return _orchestrator().status(source, market)


# ── jobs: update (convert) + acquire (download) ─────────────────────────────
def _refresh_plan(source: str, market=None) -> list[dict]:
    from qfinzero.admin import refresh
    rows = {r["id"]: r for r in _orchestrator().status(source, market)["sources"]}
    ids = [i for i, r in rows.items() if r.get("domain") == "price"]
    return refresh.plan(ids, rows)


@app.post("/data/refresh/plan")
def refresh_plan(body: dict = Body(default={})) -> dict:
    """What an update would do per source: vendor days to fetch (massive),
    local days to convert, or why nothing happens. Lists remote files only."""
    try:
        return {"items": _refresh_plan(str((body or {}).get("source", "prices")), (body or {}).get("market"))}
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.post("/data/update")
def start_update(body: dict = Body(default={})) -> dict:
    source = str((body or {}).get("source", "all"))
    market = (body or {}).get("market")
    dry_run = bool((body or {}).get("dry_run", False))
    force = bool((body or {}).get("force", False))
    fetch = bool((body or {}).get("fetch", False))
    since = (body or {}).get("since")
    label = f"update {source}" + (" + fetch" if fetch and not dry_run else "") + (" (dry-run)" if dry_run else "")

    def _task(job):
        job.log(f"[update] source={source} market={market or 'all'} dry_run={dry_run} force={force} fetch={fetch}")
        fetched = None
        if fetch:
            from qfinzero.admin import refresh
            items = _refresh_plan(source, market)
            for it in items:
                job.log(f"  [plan] {it['id']}: {it['action']}" + (f" - {it['message']}" if it.get("message") else ""))
            if not dry_run and any(it["action"] == "fetch" for it in items):
                fetched = refresh.run(items, on_line=job.log, on_progress=job.update, should_stop=job.cancelled)
            if dry_run:
                job.log("[update] done (plan only)")
                return {"ok": True, "dry_run": True, "refresh": items}
        res = _orchestrator().run(source, market=market, since=since, force=force, dry_run=dry_run)
        if res.get("dry_run"):
            for it in res.get("plan", []):
                job.log(f"  [{'RUN ' if it['will_run'] else 'skip'}] {it['id']}: {it['state']} ({it['reason']})")
        else:
            for r in res.get("results", []):
                job.log(f"  {r['status']:8} {r['id']}: rows={r.get('rows',0)} partitions={r.get('partitions',0)}"
                        + (f" ERROR {r['error']}" if r.get("error") else ""))
            converted = sum(r.get("rows", 0) for r in res.get("results", []))
            if not converted and not (fetched and fetched.get("fetched")):
                job.log("[update] already up to date: nothing new to fetch or convert")
        if fetched is not None:
            res["refresh"] = fetched
            # the download already converted its days, so the run above found
            # nothing left; record the fetch as this source's last run instead
            from qfinzero.update.manifest import UpdateManifest
            orch = _orchestrator()
            manifest = UpdateManifest.load(orch.paths.storage)
            for r in fetched.get("fetched", []):
                manifest.record(r["id"], status="ok" if r["ok"] else "error", reason="fetched",
                                fetched_days=r.get("files", 0), fetched_until=r.get("last"), error=r.get("error"))
            manifest.save()
            if not fetched["ok"]:
                res["ok"] = False
                res["error"] = fetched.get("error")
        job.log("[update] done")
        return res

    return registry.submit("update", label, _task, meta={"source": source, "fetch": fetch}).snapshot()


@app.post("/data/acquire")
def start_acquire(body: dict = Body(default={})) -> dict:
    target = str((body or {}).get("target", ""))
    dry_run = bool((body or {}).get("dry_run", True))
    prod = bool((body or {}).get("prod", False))
    if target not in acquire.TARGETS:
        raise HTTPException(422, f"target must be one of {sorted(acquire.TARGETS)}")
    label = f"acquire {target}" + (" (dry-run)" if dry_run else "")

    params = (body or {}).get("params")

    def _task(job):
        return acquire.acquire(target, dry_run=dry_run, prod=prod, on_line=job.log,
                               params=params if isinstance(params, dict) else None)

    return registry.submit("acquire", label, _task).snapshot()


@app.get("/data/acquire/targets")
def acquire_targets() -> dict:
    return {"targets": acquire.targets()}


@app.get("/data/jobs")
def list_jobs() -> dict:
    return {"jobs": registry.list()}


@app.get("/data/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id!r} not found")
    return job.snapshot(with_lines=True)


@app.get("/data/jobs/{job_id}/logs")
def job_logs(job_id: str):
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id!r} not found")
    return StreamingResponse(sse_logs(job), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── schedule ────────────────────────────────────────────────────────────────
@app.get("/data/schedule")
def get_schedule() -> dict:
    return scheduler.status()


@app.put("/data/schedule")
def put_schedule(patch: dict = Body(...)) -> dict:
    config_store.update({"schedule": (patch or {}).get("schedule", patch or {})})
    return scheduler.status()


@app.post("/data/schedule/apply")
def apply_schedule(body: dict = Body(default={})) -> dict:
    return scheduler.apply(dry_run=bool((body or {}).get("dry_run", False)))


@app.post("/data/schedule/clear")
def clear_schedule() -> dict:
    return scheduler.clear()


# ── explorer ────────────────────────────────────────────────────────────────
@app.get("/data/explore")
def explore_overview() -> dict:
    return explore.overview()


@app.get("/data/explore/symbols")
def explore_symbols(
    store: str = Query(...), limit: int = 200,
    start: str | None = None, end: str | None = None,
) -> dict:
    return explore.store_symbols(store, limit=limit, start=start, end=end)


# ── data setup utility: browse / inspect / import local files, download + convert ──
def _setup_error(e: Exception):
    if isinstance(e, PermissionError):
        raise HTTPException(status_code=403, detail=str(e))
    if isinstance(e, (FileNotFoundError, NotADirectoryError)):
        raise HTTPException(status_code=404, detail=str(e))
    raise HTTPException(status_code=422, detail=str(e))


@app.get("/setup/status")
def setup_status() -> dict:
    from qfinzero.admin import datasetup, massive_dl
    return {**datasetup.status(), "massive_indices": list(massive_dl.INDICES)}


@app.get("/setup/browse")
def setup_browse(path: str | None = None, hidden: bool = False) -> dict:
    from qfinzero.admin import datasetup
    try:
        return datasetup.browse(path, show_hidden=hidden)
    except (PermissionError, FileNotFoundError, NotADirectoryError, ValueError) as e:
        _setup_error(e)


@app.post("/setup/inspect")
def setup_inspect(body: dict = Body(...)) -> dict:
    from qfinzero.admin import datasetup
    try:
        return datasetup.inspect(str(body.get("vendor", "")), list(body.get("paths") or []))
    except (PermissionError, FileNotFoundError, ValueError) as e:
        _setup_error(e)


@app.post("/setup/import")
def setup_import(body: dict = Body(...)) -> dict:
    from qfinzero.admin import datasetup
    vendor = str(body.get("vendor", ""))
    paths = list(body.get("paths") or [])
    if vendor not in datasetup.VENDORS or not paths:
        raise HTTPException(422, "vendor and at least one path are required")
    try:
        for p in paths:
            datasetup._allowed(datasetup.Path(p))
    except PermissionError as e:
        _setup_error(e)
    convert, jobs = bool(body.get("convert", True)), int(body.get("jobs", 4))
    intervals = body.get("quote_intervals") or None

    def _task(job):
        return datasetup.import_local(vendor, paths, on_line=job.log, convert=convert, jobs=jobs,
                                      quote_intervals=intervals)

    return registry.submit("import", f"import {vendor} ({len(paths)} selection(s))", _task).snapshot()


@app.post("/setup/download")
def setup_download(body: dict = Body(...)) -> dict:
    """``dry_run`` (default) answers at once with the quote; otherwise a job."""
    from qfinzero.admin import datasetup
    vendor = str(body.get("vendor", ""))
    params = body.get("params") or {}
    dry_run = bool(body.get("dry_run", True))
    if vendor not in datasetup.VENDORS:
        raise HTTPException(422, f"vendor must be one of {datasetup.VENDORS}")
    if dry_run:
        lines: list[str] = []
        try:
            res = datasetup.download(vendor, params, dry_run=True, on_line=lines.append)
        except Exception as e:  # noqa: BLE001 — bad parameters or credentials
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "lines": lines}
        return {**res, "lines": lines}
    convert, jobs = bool(body.get("convert", True)), int(body.get("jobs", 4))
    intervals = body.get("quote_intervals") or None

    key = datasetup.choose_key(vendor, params)
    product = params.get("dataset") or params.get("index") or ""
    what = " ".join(str(x) for x in (product, params.get("schema") or "", params.get("start") or "",
                                     params.get("end") or "") if x)

    def _task(job):
        return datasetup.download(vendor, params, dry_run=False, convert=convert, on_line=job.log, jobs=jobs,
                                  quote_intervals=intervals, on_progress=job.update,
                                  should_stop=job.cancelled, job_id=job.id)

    meta = {"vendor": vendor, "product": product, "key_id": (key or {}).get("id"),
            "key_label": (key or {}).get("label"), "max_cost": params.get("max_cost")}
    return registry.submit("download", f"download {vendor} {what}".strip(), _task, meta=meta).snapshot()


@app.post("/data/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(404, f"no job {job_id}")
    return {"ok": job.cancel(), "job": job.snapshot()}


# ── layouts, vendor keys, spend ──────────────────────────────────────────

@app.get("/setup/layout")
def setup_layout() -> dict:
    from qfinzero.admin import layout
    return layout.describe()


@app.post("/setup/layout/init")
def setup_layout_init(body: dict = Body(default={})) -> dict:
    from qfinzero.admin import layout
    try:
        return layout.init(body.get("paths") or None)
    except (ValueError, OSError) as e:
        raise HTTPException(422, str(e))


@app.get("/setup/keys")
def setup_keys() -> dict:
    from qfinzero.admin import config_store, vendor_keys
    return {"keys": {v: config_store.masked_keys(v) for v in ("databento", "massive")},
            "catalog": vendor_keys.catalog(), "spend": vendor_keys.spend()}


@app.post("/setup/keys/{vendor}")
def setup_save_key(vendor: str, body: dict = Body(...)) -> dict:
    from qfinzero.admin import config_store
    try:
        return config_store.save_key(vendor, body)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.delete("/setup/keys/{vendor}/{key_id}")
def setup_delete_key(vendor: str, key_id: str) -> dict:
    from qfinzero.admin import config_store
    try:
        return {"ok": config_store.delete_key(vendor, key_id)}
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/setup/keys/{vendor}/{key_id}/test")
def setup_test_key(vendor: str, key_id: str) -> dict:
    from qfinzero.admin import vendor_keys
    try:
        return vendor_keys.test_key(vendor, key_id)
    except KeyError:
        raise HTTPException(404, f"no {vendor} key {key_id}")
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/setup/compact")
def setup_compact(body: dict = Body(default={})) -> dict:
    """Archive compression of the QFZ store; ``dry_run`` answers at once."""
    from pathlib import Path
    from qfinzero.admin import config_store
    from qfinzero.pipeline.compact import compact
    storage = Path(config_store.dirs().get("storage_root", ""))
    days = int(body.get("older_than_days", 30))
    if body.get("dry_run", True):
        return compact(storage, older_than_days=days, dry_run=True)

    def _task(job):
        return compact(storage, older_than_days=days, on_line=job.log,
                       on_progress=job.update, should_stop=job.cancelled)
    return registry.submit("compact", f"compact QFZ store (older than {days} days)", _task).snapshot()


@app.get("/setup/spend")
def setup_spend(month: str | None = None) -> dict:
    from qfinzero.admin import vendor_keys
    return vendor_keys.spend(month)


# ── coverage map (read-only; the hub lets every signed-in user GET it via /api/coverage) ──
@app.get("/coverage/extent")
def coverage_extent() -> dict:
    from qfinzero.admin import coverage
    start, end = coverage.default_range()
    return {"stores": coverage.extent(), "default": {"start": start, "end": end},
            "suggested": coverage.suggest(limit=12), "suggested_futures": coverage.suggest_futures()}


@app.get("/coverage/matrix")
def coverage_matrix(tickers: str = Query(...), start: str = Query(...), end: str = Query(...),
                    events: bool = True) -> dict:
    from qfinzero.admin import coverage
    syms = tickers.split(",")
    try:
        out = coverage.matrix(syms, start, end)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if events:
        out["events"] = coverage.events(syms, start, end)
    return out


@app.get("/coverage/cell")
def coverage_cell(ticker: str = Query(...), date: str = Query(...)) -> dict:
    from qfinzero.admin import coverage
    out = coverage.cell(ticker, date)
    out["events"] = coverage.day_events(ticker, date)
    return out


@app.get("/coverage/asset")
def coverage_asset(ticker: str = Query(...), start: str = Query(...), end: str = Query(...)) -> dict:
    from qfinzero.admin import coverage
    return coverage.asset(ticker, start, end)


@app.get("/coverage/days")
def coverage_days(start: str = Query(...), end: str = Query(...)) -> dict:
    from qfinzero.admin import coverage
    return {"days": coverage.days(start, end)}


@app.get("/coverage/day")
def coverage_day(date: str = Query(...)) -> dict:
    from qfinzero.admin import coverage
    return coverage.day(date)


@app.get("/coverage/suggest")
def coverage_suggest(q: str = "", limit: int = 20) -> dict:
    from qfinzero.admin import coverage
    return {"tickers": coverage.suggest(q, min(limit, 100))}


def main() -> None:
    import uvicorn
    port = int(os.environ.get("DATA_ADMIN_PORT", "19340"))
    host = os.environ.get("QFZ_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
