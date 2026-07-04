"""In-process background job runner for the data-admin service.

Long-running work (convert/update, raw download) runs in a worker thread while the
request returns a ``job_id`` immediately; the UI polls ``/data/jobs/{id}`` or streams
``/data/jobs/{id}/logs`` (SSE). Bounded history, thread-safe line buffer, no external
queue — the design doc's "thin FastAPI service" with jobs + SSE.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Optional

_MAX_HISTORY = 200
_MAX_LINES = 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    kind: str
    label: str
    status: str = "queued"          # queued | running | done | error
    created_at: str = field(default_factory=_now)
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    lines: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def log(self, line: str) -> None:
        with self._lock:
            self.lines.append(line)
            if len(self.lines) > _MAX_LINES:
                del self.lines[0]

    def snapshot(self, with_lines: bool = False) -> dict[str, Any]:
        with self._lock:
            d = {
                "id": self.id, "kind": self.kind, "label": self.label,
                "status": self.status, "created_at": self.created_at,
                "started_at": self.started_at, "ended_at": self.ended_at,
                "error": self.error, "n_lines": len(self.lines),
            }
            if with_lines:
                d["lines"] = list(self.lines)
                d["result"] = self.result
            return d

    def lines_from(self, idx: int) -> tuple[list[str], str]:
        with self._lock:
            return self.lines[idx:], self.status


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._counter = itertools.count(1)
        self._lock = threading.Lock()

    def submit(self, kind: str, label: str, target: Callable[[Job], Any]) -> Job:
        with self._lock:
            jid = f"{kind}-{next(self._counter)}"
            job = Job(id=jid, kind=kind, label=label)
            self._jobs[jid] = job
            self._order.append(jid)
            while len(self._order) > _MAX_HISTORY:
                self._jobs.pop(self._order.pop(0), None)

        def _run() -> None:
            job.status = "running"
            job.started_at = _now()
            try:
                job.result = target(job)
                # a target may signal failure via a falsy "ok"
                if isinstance(job.result, dict) and job.result.get("ok") is False:
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
        if status in ("done", "error"):
            yield f"event: end\ndata: {status}\n\n"
            return
        time.sleep(poll)
        waited += poll
        if waited >= idle_timeout:
            yield "event: end\ndata: timeout\n\n"
            return


registry = JobRegistry()
