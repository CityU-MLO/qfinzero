"""The two on-disk layouts and their initialisation.

QFinZero keeps data in two kinds of directory:

* **RAW libraries**, one per vendor, in the vendor's own download layout:
  massive flat files (``<index>/YYYY/MM/YYYY-MM-DD.parquet``), Databento DBN
  files (``<dataset>/<schema>/<symbol>/<date>.dbn.zst``, plus ``imports/``
  links), Tushare dumps. Downloads land here and imports are linked here; the
  pipeline reads them in place and never writes into them.
* **The QFZ store** (``STORAGE_ROOT``): the converted, query-ready layout UPQ
  serves, Hive-partitioned zstd parquet per store and trade date, with the
  pipeline's state (``_state``) and staging (``_staging``).

Each initialised directory carries a ``.qfz-layout.json`` marker naming what it
is, so a mount can be recognised and a wrong path (a RAW library pointed at as
the store, say) is caught before anything is written. The paths themselves are
saved in the data configuration (``dirs``), so they survive restarts and every
service and command sees the same ones.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from . import config_store

MARKER = ".qfz-layout.json"
LAYOUT_VERSION = 1

# vendor -> (config key, sub-directories created at init, what it holds)
RAW = {
    "massive": ("raw_massive", ["us_stocks_sip", "us_options_opra", "global_crypto", "global_forex"],
                "massive flat files: <index>/YYYY/MM/YYYY-MM-DD.parquet (global_*: .csv.gz)"),
    "databento": ("raw_databento", ["imports"],
                  "Databento DBN: <asset>/<dataset>/<schema>/<symbol>/<YYYY-MM-DD>.dbn.zst with asset in "
                  "equity|options|futures; _meta/ logs; imports/ holds links"),
    "tushare": ("raw_tushare", [], "Tushare dumps"),
}

QFZ_STORES = [
    "stock_daily", "stock_minute", "stock_quote_minute",
    "option_day", "option_minute", "option_quote_minute",
    "future_daily", "future_minute", "future_quote_minute",
    "crypto_daily", "crypto_minute", "fx_daily", "fx_minute", "fx_quote_minute",
    "corporate_actions", "dividends", "rates",
]


def _info(path: str) -> dict[str, Any]:
    p = Path(path) if path else None
    out: dict[str, Any] = {"path": path, "exists": bool(p and p.is_dir()), "writable": False,
                           "free_bytes": None, "total_bytes": None, "marker": None}
    if not out["exists"]:
        return out
    out["writable"] = os.access(p, os.W_OK)
    try:
        du = shutil.disk_usage(p)
        out["free_bytes"], out["total_bytes"] = du.free, du.total
    except OSError:
        pass
    try:
        out["marker"] = json.loads((p / MARKER).read_text())
    except (OSError, ValueError):
        pass
    return out


def describe() -> dict[str, Any]:
    """Both layouts with their paths, state and markers."""
    d = config_store.dirs()
    raw = {}
    for vendor, (key, _subs, what) in RAW.items():
        raw[vendor] = {**_info(d.get(key, "")), "config_key": key, "holds": what}
    store = _info(d.get("storage_root", ""))
    if store["exists"]:
        base = Path(store["path"])
        store["stores"] = {s: (base / s).is_dir() for s in QFZ_STORES}
    return {"raw": raw, "qfz": {**store, "config_key": "storage_root",
                                "holds": "QFZ store: <store>/trade_date=YYYY-MM-DD/*.parquet",
                                "format": storage_format()},
            "data_root": d.get("qfz_data_root"), "config_file": str(config_store.config_path())}


def _check_marker(p: Path, kind: str, vendor: str | None) -> None:
    try:
        m = json.loads((p / MARKER).read_text())
    except (OSError, ValueError):
        return
    if m.get("kind") != kind or (vendor and m.get("vendor") != vendor):
        what = m.get("vendor") or m.get("kind")
        raise ValueError(f"{p} is already initialised as {what}; choose another directory")


def _write_marker(p: Path, body: dict[str, Any]) -> None:
    path = p / MARKER
    if path.exists():
        try:
            old = json.loads(path.read_text())
            body = {**old, **body, "created_at": old.get("created_at", body["created_at"])}
        except (OSError, ValueError):
            pass
    path.write_text(json.dumps(body, indent=2))


def _foreign(p: Path) -> bool:
    """An existing directory with content but no marker: someone else's data."""
    if not p.is_dir() or (p / MARKER).exists():
        return False
    try:
        return any(True for _ in p.iterdir())
    except OSError:
        return True


def init(paths: dict[str, str] | None = None) -> dict[str, Any]:
    """Save the given paths (``{config key: path}``) and create both layouts:
    directories, standard sub-directories and markers. Idempotent.

    A directory that already holds files but has no marker is left alone
    (reported under ``skipped``) unless it was named in ``paths``: pointing at
    a shared data directory must be a deliberate choice."""
    if paths:
        allowed = {k for k, *_ in RAW.values()} | {"storage_root", "qfz_data_root"}
        bad = set(paths) - allowed
        if bad:
            raise ValueError(f"unknown directories: {', '.join(sorted(bad))}")
        clean = {k: str(Path(v).expanduser()) for k, v in paths.items() if v}
        # one directory, one role
        cur = {**config_store.dirs(), **clean}
        roles = {k: os.path.realpath(cur[k]) for k in [k for k, *_ in RAW.values()] + ["storage_root"] if cur.get(k)}
        seen: dict[str, str] = {}
        for k, real in roles.items():
            if real in seen:
                raise ValueError(f"{k} and {seen[real]} point to the same directory")
            seen[real] = k
        config_store.update({"dirs": clean})
    d = config_store.dirs()
    chosen = set(paths or {})
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    created: list[str] = []
    skipped: list[dict[str, str]] = []

    def mk(p: Path) -> None:
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(str(p))

    for vendor, (key, subs, what) in RAW.items():
        if not d.get(key):
            continue
        root = Path(d[key])
        if root.exists():
            _check_marker(root, "raw", vendor)
            if key not in chosen and _foreign(root):
                skipped.append({"path": str(root), "config_key": key,
                                "reason": "existing data without a marker; choose it explicitly to initialise it"})
                continue
        mk(root)
        for s in subs:
            mk(root / s)
        body = {"kind": "raw", "vendor": vendor, "layout_version": LAYOUT_VERSION, "holds": what, "created_at": now}
        if vendor == "databento":
            from .databento_dl import LAYOUT
            body["databento_layout"] = LAYOUT
        _write_marker(root, body)
    store = Path(d["storage_root"])
    if store.exists():
        _check_marker(store, "qfz", None)
    is_store = store.is_dir() and any((store / s).is_dir() for s in QFZ_STORES)
    if "storage_root" not in chosen and _foreign(store) and not is_store:
        skipped.append({"path": str(store), "config_key": "storage_root",
                        "reason": "existing data without a marker; choose it explicitly to initialise it"})
    else:
        mk(store)
        for s in [*QFZ_STORES, "_state", "_staging"]:
            mk(store / s)
        _write_marker(store, {"kind": "qfz", "layout_version": LAYOUT_VERSION, "format": storage_format(),
                              "created_at": now})
    return {"ok": True, "created": created, "skipped": skipped, "layout": describe()}


# ── the QFZ parquet format ────────────────────────────────────────────────

DEFAULT_FORMAT = {"compression": "zstd", "level": 3, "row_group_rows": 122_880}


def storage_format() -> dict[str, Any]:
    """Compression and row-group size the converter writes the QFZ store with."""
    f = dict(DEFAULT_FORMAT)
    f.update({k: v for k, v in (config_store.load().get("format") or {}).items() if k in DEFAULT_FORMAT})
    return f
