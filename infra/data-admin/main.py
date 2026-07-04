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
    paths = resolve(d.get("raw_massive"), d.get("raw_tushare"), d.get("storage_root"))
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
    if provider not in ("massive", "tushare"):
        raise HTTPException(422, "provider must be 'massive' or 'tushare'")
    return scan.scan(provider)


# ── sources / status (freshness) ────────────────────────────────────────────
@app.get("/data/sources")
def sources(source: str = "all", market: str | None = None) -> dict:
    return _orchestrator().status(source, market)


@app.get("/data/status")
def status(source: str = "all", market: str | None = None) -> dict:
    return _orchestrator().status(source, market)


# ── jobs: update (convert) + acquire (download) ─────────────────────────────
@app.post("/data/update")
def start_update(body: dict = Body(default={})) -> dict:
    source = str((body or {}).get("source", "all"))
    market = (body or {}).get("market")
    dry_run = bool((body or {}).get("dry_run", False))
    force = bool((body or {}).get("force", False))
    since = (body or {}).get("since")
    label = f"update {source}" + (" (dry-run)" if dry_run else "")

    def _task(job):
        job.log(f"[update] source={source} market={market or 'all'} dry_run={dry_run} force={force}")
        res = _orchestrator().run(source, market=market, since=since, force=force, dry_run=dry_run)
        if res.get("dry_run"):
            for it in res.get("plan", []):
                job.log(f"  [{'RUN ' if it['will_run'] else 'skip'}] {it['id']}: {it['state']} ({it['reason']})")
        else:
            for r in res.get("results", []):
                job.log(f"  {r['status']:8} {r['id']}: rows={r.get('rows',0)} partitions={r.get('partitions',0)}"
                        + (f" ERROR {r['error']}" if r.get("error") else ""))
        job.log("[update] done")
        return res

    return registry.submit("update", label, _task).snapshot()


@app.post("/data/acquire")
def start_acquire(body: dict = Body(default={})) -> dict:
    target = str((body or {}).get("target", ""))
    dry_run = bool((body or {}).get("dry_run", True))
    prod = bool((body or {}).get("prod", False))
    if target not in acquire.TARGETS:
        raise HTTPException(422, f"target must be one of {sorted(acquire.TARGETS)}")
    label = f"acquire {target}" + (" (dry-run)" if dry_run else "")

    def _task(job):
        return acquire.acquire(target, dry_run=dry_run, prod=prod, on_line=job.log)

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


def main() -> None:
    import uvicorn
    port = int(os.environ.get("DATA_ADMIN_PORT", "19340"))
    host = os.environ.get("QFZ_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
