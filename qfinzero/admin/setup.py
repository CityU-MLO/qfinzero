"""First-run setup-state — drives the Console wizard vs. status view.

"When the user first uses it, show a setup guide; if set, show existing data
status." This computes which setup steps are done from the config store + a live
registry scan, and a ``show_wizard`` hint the Data page branches on.
"""

from __future__ import annotations

from typing import Any

from qfinzero.pipeline.paths import resolve
from . import config_store


def _scan() -> dict:
    d = config_store.dirs()
    paths = resolve(d.get("raw_massive"), d.get("raw_tushare"), d.get("storage_root"))
    from qfinzero.pipeline import registry
    return registry.scan(paths)


def _any_raw(scan: dict) -> bool:
    raw = scan.get("raw", {})
    m = raw.get("massive", {})
    if any((m.get(k, {}) or {}).get("present") for k in
           ("stock_daily", "stock_minute", "option_day", "option_minute")):
        return True
    return bool((raw.get("tushare", {}).get("cn_daily", {}) or {}).get("present"))


def _any_storage(scan: dict) -> bool:
    store = scan.get("storage", {})
    return any((store.get(k, {}) or {}).get("partitions", 0) > 0 for k in
               ("stock_daily", "stock_minute", "option_day", "option_minute"))


def state() -> dict[str, Any]:
    """``{configured, initialized, show_wizard, steps:[...]}`` for the wizard."""
    cfg = config_store.load()
    s3 = cfg.get("massive", {}) or {}
    massive_done = bool(s3.get("s3_access_key_id") and s3.get("s3_secret_access_key"))
    tushare_done = bool((cfg.get("tushare", {}) or {}).get("token"))

    try:
        scan = _scan()
        raw_done, store_done = _any_raw(scan), _any_storage(scan)
    except Exception as e:  # noqa: BLE001 — a bad dir must not 500 the wizard
        raw_done = store_done = False
        scan = {"error": f"{type(e).__name__}: {e}"}

    steps = [
        {"id": "massive", "label": "MASSIVE credentials (US)",
         "done": massive_done, "required": False,
         "detail": "S3 access key + secret for flat-files download"},
        {"id": "tushare", "label": "Tushare token (CN)",
         "done": tushare_done, "required": False,
         "detail": "API token for A-share download"},
        {"id": "raw", "label": "Raw data present",
         "done": raw_done, "required": True,
         "detail": "vendor data in the shared RAW roots"},
        {"id": "storage", "label": "UPQ storage initialized",
         "done": store_done, "required": True,
         "detail": "converted parquet the UPQ service serves"},
    ]
    configured = (massive_done or tushare_done) and (raw_done or store_done)
    return {
        "configured": configured,
        "initialized": store_done,
        "show_wizard": not store_done,
        "has_credentials": massive_done or tushare_done,
        "steps": steps,
    }
