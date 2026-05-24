"""
QFinZero — Lightweight API metrics middleware.

Usage (2 lines in any FastAPI service):

    from qfinzero.metrics import attach_metrics
    attach_metrics(app, service_name="pmb")

This auto-registers:
  - A Starlette middleware that tracks per-endpoint latency, throughput, errors
  - A GET /_stats endpoint returning all metrics as JSON
"""

import time
import threading
from collections import defaultdict, deque
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class _EndpointStats:
    """Thread-safe per-endpoint metrics accumulator."""

    __slots__ = ("count", "errors", "active", "_latencies", "_recent", "_lock")

    def __init__(self, window: int = 1000):
        self.count = 0
        self.errors = 0
        self.active = 0
        self._latencies: deque = deque(maxlen=window)
        self._recent: deque = deque(maxlen=window)  # (timestamp, latency_ms)
        self._lock = threading.Lock()

    def record(self, latency_ms: float, is_error: bool) -> None:
        now = time.time()
        with self._lock:
            self.count += 1
            self._latencies.append(latency_ms)
            self._recent.append((now, latency_ms))
            if is_error:
                self.errors += 1

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            lats = sorted(self._latencies)
            n = len(lats)

            # Recent window: last 60 seconds
            cutoff = now - 60
            recent = [(t, l) for t, l in self._recent if t >= cutoff]
            recent_count = len(recent)
            recent_avg = sum(l for _, l in recent) / recent_count if recent_count else 0

            return {
                "count": self.count,
                "errors": self.errors,
                "active": self.active,
                "latency_ms": {
                    "p50": lats[int(n * 0.5)] if n else 0,
                    "p95": lats[int(n * 0.95)] if n else 0,
                    "p99": lats[int(n * 0.99)] if n else 0,
                    "avg": sum(lats) / n if n else 0,
                    "max": lats[-1] if n else 0,
                },
                "last_60s": {
                    "count": recent_count,
                    "avg_ms": round(recent_avg, 2),
                    "rpm": round(recent_count * 60 / 60, 1),  # requests per minute
                },
            }


class _MetricsStore:
    """Global metrics store keyed by endpoint string."""

    def __init__(self, service_name: str):
        self.service_name = service_name
        self.start_time = time.time()
        self._endpoints: dict[str, _EndpointStats] = defaultdict(_EndpointStats)
        self._total_requests = 0
        self._total_errors = 0
        self._active_requests = 0
        self._lock = threading.Lock()

    def get_endpoint(self, key: str) -> _EndpointStats:
        return self._endpoints[key]

    def inc_active(self) -> None:
        with self._lock:
            self._active_requests += 1

    def dec_active(self, is_error: bool) -> None:
        with self._lock:
            self._active_requests -= 1
            self._total_requests += 1
            if is_error:
                self._total_errors += 1

    def snapshot(self) -> dict:
        with self._lock:
            active = self._active_requests
            total = self._total_requests
            errors = self._total_errors

        endpoints = {}
        for key, stats in self._endpoints.items():
            endpoints[key] = stats.snapshot()

        return {
            "service": self.service_name,
            "uptime_seconds": round(time.time() - self.start_time, 1),
            "total_requests": total,
            "total_errors": errors,
            "active_requests": active,
            "endpoints": endpoints,
        }


class _MetricsMiddleware(BaseHTTPMiddleware):

    def __init__(self, app, store: _MetricsStore):
        super().__init__(app)
        self._store = store

    async def dispatch(self, request: Request, call_next: Callable):
        # Skip the /_stats endpoint itself
        if request.url.path == "/_stats":
            return await call_next(request)

        method = request.method
        path = request.url.path
        key = f"{method} {path}"

        ep = self._store.get_endpoint(key)

        self._store.inc_active()
        ep.active += 1
        start = time.perf_counter()
        is_error = False

        try:
            response = await call_next(request)
            is_error = response.status_code >= 400
            return response
        except Exception:
            is_error = True
            raise
        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            ep.active -= 1
            ep.record(latency_ms, is_error)
            self._store.dec_active(is_error)


def attach_metrics(app, service_name: str) -> _MetricsStore:
    """Attach metrics middleware and /_stats endpoint to a FastAPI app.

    Args:
        app: FastAPI application instance
        service_name: e.g. "pmb", "esp"

    Returns:
        The MetricsStore (useful for testing, usually ignored)
    """
    store = _MetricsStore(service_name)
    app.add_middleware(_MetricsMiddleware, store=store)

    @app.get("/_stats", include_in_schema=False)
    async def stats_endpoint():
        return JSONResponse(store.snapshot())

    return store
