"""Massive news fetcher and normalizer.

Provides functions to fetch news via `massive_client.MassiveClient` and
normalize the results to the project's news schema. Dry-run safe.
"""
from __future__ import annotations

from typing import List, Dict, Optional

try:
    # normal package import when running as module
    from src.data_sources.massive_client import MassiveClient
except Exception:
    try:
        # fallback to relative import when executed as package
        from .massive_client import MassiveClient
    except Exception:
        # last-resort: load the client module by path (dry-run friendly)
        import importlib.util, os

        client_path = os.path.join(os.path.dirname(__file__), "massive_client.py")
        spec = importlib.util.spec_from_file_location("massive_client", client_path)
        mc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mc)
        MassiveClient = mc.MassiveClient


def normalize_article(raw: dict) -> Dict:
    # best-effort normalization; adapt to actual Massive fields later
    return {
        "id": raw.get("id") or raw.get("guid"),
        "symbol": raw.get("symbol"),
        "title": raw.get("title"),
        "summary": raw.get("summary") or raw.get("description"),
        "url": raw.get("url") or raw.get("link"),
        "published_at": raw.get("published_at") or raw.get("published"),
        "raw": raw,
    }


def fetch_news_for_symbol(symbol: str, start: Optional[str] = None, end: Optional[str] = None, client: Optional[MassiveClient] = None) -> List[Dict]:
    client = client or MassiveClient()
    out: List[Dict] = []
    page = 1
    while True:
        resp = client.get_news(symbol=symbol, start=start, end=end, page=page)
        if resp is None:
            break
        if isinstance(resp, dict) and resp.get("status") == "dry-run":
            # dry-run returns empty data
            break

        items = resp.get("data") or resp.get("results") or []
        if not items:
            break

        for it in items:
            out.append(normalize_article(it))

        page += 1
    return out
