"""Background job runner for the data-admin service.

Long-running work (convert/update, imports, downloads) runs in a worker thread
while the request returns a ``job_id`` immediately; the UI polls
``/data/jobs/{id}`` or streams ``/data/jobs/{id}/logs`` (SSE).

A job carries a log and a structured ``progress`` (files, bytes, rate, ETA,
stage, cost) that its task updates through :meth:`Job.update`, and can be
cancelled: :meth:`Job.cancelled` turns true and the task stops at its next
check. Finished jobs are written to ``$QFZ_STATE_DIR/jobs/`` so the history
(and what downloads cost) survives a restart; a job that was running when the
service stopped comes back as ``interrupted``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

_MAX_HISTORY = 200
_MAX_LINES = 1000
_KEEP_LINES = 300          # lines kept in the saved copy
TERMINAL = ("done", "error", "cancelled", "interrupted")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _jobs_dir() -> Path:
    root = os.environ.get("QFZ_DATA_ROOT", "/data/qfinzero")
    return Path(os.environ.get("QFZ_STATE_DIR", f"{root}/_state")) / "jobs"


@dataclass
class Job:
    id: str
    kind: str
    label: str
    status: str = "queued"          # queued | running | done | error | cancelled | interrupted
    created_at: str = field(default_factory=_now)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    lines: list[str] = field(default_factory=list)
    progress: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)      # vendor, key, cost, …
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _t0: float = 0.0

    def log(self, line: str) -> None:
        with self._lock:
            self.lines.append(line)
            if len(self.lines) > _MAX_LINES:
                del self.lines[0]

    def update(self, **fields: Any) -> None:
        """Merge progress fields (``files_done``, ``files_total``, ``bytes_done``,
        ``bytes_total``, ``stage``, ``current``, ``cost_usd``…); rate and ETA are
        derived from bytes (else files) over the time since the job started."""
        with self._lock:
            self.progress.update({k: v for k, v in fields.items() if v is not None})
            p = self.progress
            el = max(1e-6, time.time() - self._t0) if self._t0 else None
            if el:
                p["elapsed_s"] = round(el, 1)
                if p.get("bytes_done"):
                    p["rate_bps"] = p["bytes_done"] / el
                if p.get("bytes_total") and p.get("bytes_done"):
                    left = max(0, p["bytes_total"] - p["bytes_done"])
                    p["eta_s"] = round(left / max(1.0, p["rate_bps"]), 1)
                elif p.get("files_total") and p.get("files_done"):
                    per = el / p["files_done"]
                    p["eta_s"] = round(per * max(0, p["files_total"] - p["files_done"]), 1)

    def cancel(self) -> bool:
        if self.status in TERMINAL:
            return False
        self._cancel.set()
        self.log("[cancel] requested; stopping after the current file")
        return True

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def snapshot(self, with_lines: bool = False) -> dict[str, Any]:
        with self._lock:
            d = {
                "id": self.id, "kind": self.kind, "label": self.label,
                "status": self.status, "created_at": self.created_at,
                "started_at": self.started_at, "ended_at": self.ended_at,
                "error": self.error, "n_lines": len(self.lines),
                "progress": dict(self.progress), "meta": dict(self.meta),
                "cancel_requested": self._cancel.is_set(),
            }
            if with_lines:
                d["lines"] = list(self.lines)
                d["result"] = self.result
            return d

    def lines_from(self, idx: int) -> tuple[list[str], str]:
        with self._lock:
            return self.lines[idx:], self.status


class JobRegistry:
    def __init__(self, persist_dir: Optional[Path] = None) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._n = 0
        self._lock = threading.Lock()
        self._dir = persist_dir
        self._load()

    # ── persistence ──────────────────────────────────────────────────

    def _path(self, jid: str) -> Optional[Path]:
        return (self._dir / f"{jid}.json") if self._dir else None

    def _save(self, job: Job) -> None:
        p = self._path(job.id)
        if p is None:
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            d = job.snapshot(with_lines=True)
            d["lines"] = d["lines"][-_KEEP_LINES:]
            try:
                json.dumps(d["result"])
            except (TypeError, ValueError):
                d["result"] = str(d["result"])
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(d))
            tmp.replace(p)
        except OSError:
            pass

    def _load(self) -> None:
        if not self._dir or not self._dir.is_dir():
            return
        rows = []
        for f in self._dir.glob("*.json"):
            try:
                rows.append(json.loads(f.read_text()))
            except (OSError, ValueError):
                continue
        rows.sort(key=lambda r: r.get("created_at") or "")
        for r in rows[-_MAX_HISTORY:]:
            job = Job(id=r["id"], kind=r.get("kind", ""), label=r.get("label", ""),
                      status=r.get("status", "done"), created_at=r.get("created_at") or _now(),
                      started_at=r.get("started_at"), ended_at=r.get("ended_at"), result=r.get("result"),
                      error=r.get("error"), lines=r.get("lines") or [], progress=r.get("progress") or {},
                      meta=r.get("meta") or {})
            if job.status not in TERMINAL:            # the service stopped while it ran
                job.status, job.error = "interrupted", "the data service restarted while this job ran"
                job.ended_at = job.ended_at or _now()
                self._save(job)
            self._jobs[job.id] = job
            self._order.append(job.id)
            try:
                self._n = max(self._n, int(job.id.rsplit("-", 1)[-1]))
            except ValueError:
                pass

    # ── running ──────────────────────────────────────────────────────

    def submit(self, kind: str, label: str, target: Callable[[Job], Any], meta: Optional[dict] = None) -> Job:
        with self._lock:
            self._n += 1
            jid = f"{kind}-{self._n}"
            job = Job(id=jid, kind=kind, label=label, meta=dict(meta or {}))
            self._jobs[jid] = job
            self._order.append(jid)
            while len(self._order) > _MAX_HISTORY:
                old = self._order.pop(0)
                self._jobs.pop(old, None)
                p = self._path(old)
                if p is not None:
                    p.unlink(missing_ok=True)
        self._save(job)

        def _run() -> None:
            job.status = "running"
            job.started_at = _now()
            job._t0 = time.time()
            self._save(job)
            try:
                job.result = target(job)
                if job.cancelled():
                    job.status = "cancelled"
                    job.error = "cancelled by the user"
                # a target may signal failure via a falsy "ok"
                elif isinstance(job.result, dict) and job.result.get("ok") is False:
                    job.status = "error"
                    job.error = str(job.result.get("error") or "job reported ok=false")
                else:
                    job.status = "done"
            except Exception as e:  # noqa: BLE001 — surface, don't crash the server
                job.status = "error"
                job.error = f"{type(e).__name__}: {e}"
                job.log(f"[error] {job.error}")
            finally:
                job.ended_at = _now()
                job.update()
                self._save(job)

        threading.Thread(target=_run, name=f"job:{jid}", daemon=True).start()
        return job

    def get(self, jid: str) -> Optional[Job]:
        return self._jobs.get(jid)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._jobs[j].snapshot() for j in reversed(self._order) if j in self._jobs]


def sse_logs(job: Job, poll: float = 0.4, idle_timeout: float = 900.0) -> Iterator[str]:
    """Yield SSE frames of a job's log lines until it reaches a terminal state."""
    idx = 0
    waited = 0.0
    yield f"event: status\ndata: {job.status}\n\n"
    while True:
        new, status = job.lines_from(idx)
        idx += len(new)
        for line in new:
            waited = 0.0
            yield f"data: {line}\n\n"
        if status in TERMINAL:
            yield f"event: end\ndata: {status}\n\n"
            return
        time.sleep(poll)
        waited += poll
        if waited >= idle_timeout:
            yield "event: end\ndata: timeout\n\n"
            return


registry = JobRegistry(_jobs_dir() if os.environ.get("QFZ_JOBS_PERSIST", "1") != "0" else None)
