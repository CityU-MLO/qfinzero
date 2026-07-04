"""Streaming reverse proxy used by the hub to reach internal children.

Preserves method, query, headers, status and streams the response body (so SSE
job/chat logs flow through unbuffered). Hop-by-hop headers are dropped.
"""

from __future__ import annotations

import httpx
from fastapi import Request
from fastapi.responses import Response, StreamingResponse

# Hop-by-hop headers (RFC 7230 §6.1) + ones httpx/uvicorn must recompute.
# NOTE: content-encoding is preserved — we stream the RAW (still-compressed)
# upstream body via aiter_raw(), so the client must decode it itself.
_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length",
}


class ReverseProxy:
    def __init__(self, timeout: float | None = None):
        # No read timeout — long-lived SSE streams must stay open.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, read=None), follow_redirects=False
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def probe(self, url: str, timeout: float = 1.5) -> bool:
        """Quick liveness check of an internal service (used by /health)."""
        try:
            r = await self._client.get(url, timeout=timeout)
            return r.status_code < 500
        except Exception:  # noqa: BLE001
            return False

    async def forward(self, request: Request, target_base: str, upstream_path: str) -> Response:
        url = target_base.rstrip("/") + "/" + upstream_path.lstrip("/")
        if request.url.query:
            url += "?" + request.url.query

        headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP}
        body = await request.body()

        req = self._client.build_request(
            request.method, url, headers=headers, content=body or None
        )
        try:
            upstream = await self._client.send(req, stream=True)
        except httpx.ConnectError:
            return Response(
                content=f'{{"error":"upstream unavailable","target":"{target_base}"}}',
                status_code=502, media_type="application/json",
            )

        resp_headers = {
            k: v for k, v in upstream.headers.items() if k.lower() not in _HOP
        }

        async def stream():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        return StreamingResponse(
            stream(),
            status_code=upstream.status_code,
            headers=resp_headers,
            media_type=upstream.headers.get("content-type"),
        )
