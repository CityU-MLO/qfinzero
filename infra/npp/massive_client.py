"""Stable Massive (Polygon-like) REST client.

This module provides a single `MassiveClient` with a small, well-tested
surface area used by the rest of the pipeline. It prefers `requests` when
available and falls back to the standard library `urllib` when necessary.

Behavior notes:
- If no API key is configured (env `MASSIVE_API_KEY`) the client will operate
  in "dry-run" mode and immediately return `{"status": "dry-run", "data": []}`
  for GET calls so the rest of the code can be exercised without network.
- The `get` method implements a simple retry with exponential backoff when
  429/temporary failures occur.
"""
from __future__ import annotations

import os
import time
import json
from typing import Optional, Any, Dict

BASE_URL = "https://api.massive.com/v1"
API_KEY = os.environ.get("MASSIVE_API_KEY")


class MassiveClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = BASE_URL, timeout: int = 10):
        self.api_key = api_key or API_KEY
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        hdr = {"Accept": "application/json"}
        if self.api_key:
            hdr["Authorization"] = f"Bearer {self.api_key}"
        return hdr

    @property
    def dry_run(self) -> bool:
        return not bool(self.api_key)

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, retries: int = 3, backoff: float = 1.0) -> Any:
        """Perform GET request with retry/backoff and requests/urllib fallback.

        Returns parsed JSON on success, or raises on permanent failure.
        In dry-run mode returns {"status": "dry-run", "data": []}.
        """
        if params is None:
            params = {}

        # Dry-run: short-circuit so callers can test without network/key
        if self.dry_run:
            return {"status": "dry-run", "data": []}

        url = f"{self.base_url}{path}"

        # First try to use requests if available
        try:
            import requests  # type: ignore
        except Exception:
            requests = None

        for attempt in range(1, retries + 1):
            # If we have requests, use it
            if requests is not None:
                try:
                    r = requests.get(url, params=params, headers=self._headers(), timeout=self.timeout)
                    if r.status_code == 429:
                        # rate limited: backoff and retry
                        time.sleep(backoff * attempt)
                        continue
                    r.raise_for_status()
                    return r.json()
                except requests.HTTPError:
                    if attempt == retries:
                        raise
                    time.sleep(backoff * attempt)
                    continue
                except requests.RequestException:
                    if attempt == retries:
                        raise
                    time.sleep(backoff * attempt)
                    continue

            # Fallback to urllib
            try:
                import urllib.request as _ur
                import urllib.parse as _up

                query = _up.urlencode({k: v for k, v in params.items() if v is not None}) if params else ""
                full_url = f"{url}?{query}" if query else url
                req = _ur.Request(full_url, headers=self._headers())
                with _ur.urlopen(req, timeout=self.timeout) as resp:
                    code = resp.getcode()
                    body = resp.read()
                    if code == 429:
                        time.sleep(backoff * attempt)
                        continue
                    if code >= 400:
                        if attempt == retries:
                            raise Exception(f"HTTP {code}")
                        time.sleep(backoff * attempt)
                        continue
                    return json.loads(body.decode("utf-8"))
            except Exception:
                if attempt == retries:
                    raise
                time.sleep(backoff * attempt)

        raise RuntimeError("Failed to GET after retries")

    def get_news(self, symbol: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None, page: int = 1, page_size: int = 100) -> Any:
        """Convenience wrapper for the Massive `/stocks/news` endpoint.

        Parameters follow Massive API naming: `symbol`, `start`, `end`.
        """
        params: Dict[str, Any] = {"page": page, "page_size": page_size}
        if symbol:
            params["symbol"] = symbol
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        return self.get("/stocks/news", params=params)


__all__ = ["MassiveClient"]
