"""Retry model calls that fail for a moment: the provider is overloaded, rate
limits us, answers 5xx or drops the connection. The provider's retry-after is
honoured; each retry is announced to the stream so the chat can show it.

A turn used to fail on the first "Our servers are currently overloaded", which
some gateways send as an error event inside a 200 stream, where the SDK's own
retries never see it.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
from typing import Any, Optional

from langchain.agents.middleware import AgentMiddleware
from langchain_core.callbacks import adispatch_custom_event

MAX_RETRIES = int(os.environ.get("PLAYGROUND_MODEL_RETRIES", "4"))
MAX_DELAY_S = float(os.environ.get("PLAYGROUND_MODEL_RETRY_MAX_S", "30"))
RETRY_EVENT = "qfz_model_retry"

_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529}
_NAMES = {"APIConnectionError", "APITimeoutError", "ConnectError", "ConnectTimeout", "ReadError",
          "ReadTimeout", "RemoteProtocolError", "TimeoutException", "OverloadedError"}
_TEXT = re.compile(r"overloaded|server_error|service_unavailable|rate[ _]limit|temporarily unavailable"
                   r"|try again later|connection (?:reset|error|closed)", re.I)
_AFTER_MS = re.compile(r"retry-after-ms['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)", re.I)
_AFTER_S = re.compile(r"retry-after['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)", re.I)


def _status(exc: BaseException) -> Optional[int]:
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else None


def transient(exc: BaseException) -> bool:
    """Worth retrying: an HTTP status that means "later", a dropped connection,
    or an error event whose text says the provider is busy."""
    status = _status(exc)
    if status is not None:
        return status in _STATUS
    if type(exc).__name__ in _NAMES:
        return True
    return bool(_TEXT.search(str(exc)))


def retry_after(exc: BaseException) -> Optional[float]:
    """Seconds the provider asked us to wait, from the response headers or,
    for errors that arrive inside the stream, from the error text."""
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    for key, scale in (("retry-after-ms", 1000.0), ("retry-after", 1.0)):
        try:
            if headers.get(key) is not None:
                return float(headers[key]) / scale
        except (TypeError, ValueError):
            pass
    text = str(exc)
    if m := _AFTER_MS.search(text):
        return float(m.group(1)) / 1000
    if m := _AFTER_S.search(text):
        return float(m.group(1))
    return None


def delay_s(attempt: int, exc: BaseException) -> float:
    """Wait before retry ``attempt`` (1-based): retry-after, else 2, 4, 8, ... s."""
    asked = retry_after(exc)
    base = asked if asked is not None else 2.0 * 2 ** (attempt - 1)
    return min(base, MAX_DELAY_S) + random.uniform(0, 0.5)


class ModelRetry(AgentMiddleware):
    """Agent middleware: retry a model call on transient errors."""

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        attempt = 0
        while True:
            try:
                return await handler(request)
            except Exception as exc:  # noqa: BLE001 — re-raised unless transient
                if attempt >= MAX_RETRIES or not transient(exc):
                    raise
                attempt += 1
                wait = delay_s(attempt, exc)
                await adispatch_custom_event(RETRY_EVENT, {"attempt": attempt, "of": MAX_RETRIES,
                                                           "delay_s": round(wait, 1), "error": str(exc)[:300]})
                await asyncio.sleep(wait)
