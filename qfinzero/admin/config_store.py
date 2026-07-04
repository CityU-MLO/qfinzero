"""Editable runtime configuration — data dirs, vendor credentials, update schedule.

The operator edits these from the Console data manager (or ``qfz-data config``)
instead of hand-writing shell env: the shared RAW roots, the per-store output root,
the MASSIVE flat-files S3 credentials + REST key, the Tushare token, the ESP/Mongo
connection, and the auto-update schedule. Persisted as JSON at
``$QFZ_DATA_ROOT/_state/qfz.config.json`` (gitignored — it holds secrets, ``data/``
is already ignored) and **applied to ``os.environ``** so the pipeline, the download
scripts (``upq_flatfiles.sh`` reads ``POLYGON_S3_*``) and the services keep working
unchanged.

Secrets never leave the box in the clear: :func:`masked` renders them as
``••••last4`` for display, and :func:`update` only overwrites a secret when a fresh
non-masked value is supplied (so saving the form back doesn't wipe a key).

House style: ``from __future__ import annotations``, stdlib-only, best-effort I/O.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

__all__ = [
    "config_path", "load", "save", "update", "masked", "apply_to_env",
    "massive_s3", "massive_rest", "tushare_token", "dirs", "schedule",
    "mongo", "persisted",
]

_LOCK = threading.RLock()

# Secret leaf paths (section, key) — masked on display, preserved on save.
_SECRETS = {
    ("massive", "s3_access_key_id"),
    ("massive", "s3_secret_access_key"),
    ("massive", "rest_api_key"),
    ("tushare", "token"),
    ("news", "benzinga_api_key"),
}


def _qfz_data_root() -> str:
    # Import lazily so this module stays importable without triggering config's
    # env-load side effects in contexts that don't need them.
    return os.environ.get("QFZ_DATA_ROOT", "/data/qfinzero")


def config_path() -> Path:
    """Where the editable config lives (override with ``QFZ_CONFIG_FILE``)."""
    default = Path(_qfz_data_root()) / "_state" / "qfz.config.json"
    return Path(os.environ.get("QFZ_CONFIG_FILE", str(default)))


def _defaults() -> dict[str, Any]:
    """Seed values from the environment / known defaults (so an env-configured
    box shows real values before anything is saved)."""
    root = _qfz_data_root()
    return {
        "dirs": {
            "qfz_data_root": root,
            "raw_massive": os.environ.get("RAW_MASSIVE_DIR", "/data/massive_data"),
            "raw_tushare": os.environ.get("RAW_TUSHARE_DIR", "/data/tushare_data"),
            "storage_root": os.environ.get("STORAGE_ROOT", f"{root}/upq"),
        },
        # MASSIVE / Polygon flat-files (US stocks, options, rates, corp actions).
        # S3 is the download transport (upq_flatfiles.sh); REST is the reference/
        # permissions endpoint. In practice the REST key == the S3 secret.
        "massive": {
            "s3_access_key_id": os.environ.get("POLYGON_S3_ACCESS_KEY_ID", ""),
            "s3_secret_access_key": os.environ.get("POLYGON_S3_SECRET_ACCESS_KEY", ""),
            "s3_endpoint": os.environ.get("MASSIVE_S3_ENDPOINT", "https://files.polygon.io"),
            "s3_bucket": os.environ.get("MASSIVE_S3_BUCKET", "flatfiles"),
            "rest_api_key": os.environ.get("MASSIVE_REST_API_KEY", os.environ.get("POLYGON_API_KEY", "")),
            "rest_base_url": os.environ.get("MASSIVE_REST_BASE_URL", "https://api.polygon.io"),
        },
        "tushare": {"token": os.environ.get("TUSHARE_TOKEN", "")},
        # ESP news/econ/earnings sources.
        "news": {
            "mongo_uri": os.environ.get("MONGO_URI", "mongodb://localhost:27018"),
            "mongo_db": os.environ.get("MONGO_DB", "market_news"),
            "mongo_collection": os.environ.get("MONGO_COLLECTION", "ticker_news"),
            "benzinga_api_key": os.environ.get("BENZINGA_API_KEY", ""),
        },
        # Auto-update schedule — one entry per update "group" the scheduler drives.
        # ``cron`` is a 5-field expression; blank/disabled means no cron line.
        # Defaults mirror the cadences baked into the existing download scripts.
        "schedule": {
            "prices": {"enabled": False, "cron": "30 17 * * 1-5"},   # weekdays 17:30
            "news": {"enabled": False, "cron": "0 6 * * *"},          # daily 06:00
        },
    }


def _merge(base: dict, over: dict) -> dict:
    """Deep-merge ``over`` into a copy of ``base`` (one level of nesting)."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def load() -> dict[str, Any]:
    """Return the full config (file merged over env/defaults). Secrets in the clear."""
    with _LOCK:
        cfg = _defaults()
        p = config_path()
        if p.exists():
            try:
                cfg = _merge(cfg, json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
        return cfg


def persisted() -> dict[str, Any]:
    """Only what the operator actually saved (raw file, no seeded defaults)."""
    p = config_path()
    if not p.exists():
        return {}
    try:
        return dict(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {}


def save(cfg: dict[str, Any]) -> Path:
    """Write the full config to disk (0600) and apply it to the environment."""
    with _LOCK:
        p = config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        try:
            os.chmod(p, 0o600)  # secrets — owner-only
        except OSError:
            pass
        apply_to_env(cfg)
        return p


def update(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge ``patch`` into the stored config and persist.

    A secret field is overwritten only when the patch carries a non-empty value
    that is not the masked placeholder — so posting the (masked) form back keeps
    the key. Returns the new full config (clear).
    """
    with _LOCK:
        new = _merge(load(), {})
        for section, vals in (patch or {}).items():
            if not isinstance(vals, dict):
                new[section] = vals
                continue
            dst = new.setdefault(section, {})
            for k, v in vals.items():
                if (section, k) in _SECRETS:
                    sv = str(v or "")
                    if not sv or "•" in sv:  # blank or masked -> keep existing
                        continue
                dst[k] = v
        save(new)
        return new


def masked(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Display view: secret leaves become ``••••last4`` (or '' when unset)."""
    cfg = cfg or load()
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in cfg.items()}
    for section, key in _SECRETS:
        if section in out and isinstance(out[section], dict):
            val = str(out[section].get(key, "") or "")
            out[section][key] = (("•" * 4 + val[-4:]) if val else "")
    return out


def apply_to_env(cfg: dict[str, Any] | None = None) -> None:
    """Push dirs + credentials into ``os.environ`` so the pipeline, the download
    scripts and the services observe them (only non-empty values overwrite)."""
    cfg = cfg or load()
    d = cfg.get("dirs", {}) or {}
    m = cfg.get("massive", {}) or {}
    n = cfg.get("news", {}) or {}
    tok = (cfg.get("tushare", {}) or {}).get("token", "")
    env = {
        "QFZ_DATA_ROOT": d.get("qfz_data_root", ""),
        "RAW_MASSIVE_DIR": d.get("raw_massive", ""),
        "RAW_TUSHARE_DIR": d.get("raw_tushare", ""),
        "STORAGE_ROOT": d.get("storage_root", ""),
        # MASSIVE flat-files S3 — the names upq_flatfiles.sh reads.
        "POLYGON_S3_ACCESS_KEY_ID": m.get("s3_access_key_id", ""),
        "POLYGON_S3_SECRET_ACCESS_KEY": m.get("s3_secret_access_key", ""),
        "MASSIVE_S3_ENDPOINT": m.get("s3_endpoint", ""),
        "MASSIVE_S3_BUCKET": m.get("s3_bucket", ""),
        "MASSIVE_REST_API_KEY": m.get("rest_api_key", ""),
        "MASSIVE_REST_BASE_URL": m.get("rest_base_url", ""),
        "TUSHARE_TOKEN": tok or "",
        "MONGO_URI": n.get("mongo_uri", ""),
        "MONGO_DB": n.get("mongo_db", ""),
        "MONGO_COLLECTION": n.get("mongo_collection", ""),
        "BENZINGA_API_KEY": n.get("benzinga_api_key", ""),
    }
    for k, v in env.items():
        if v:
            os.environ[k] = str(v)


# ── typed accessors (used by scan / acquire / scheduler / services) ──────────
def massive_s3() -> dict[str, str]:
    m = load().get("massive", {}) or {}
    return {
        "access_key_id": m.get("s3_access_key_id", ""),
        "secret_access_key": m.get("s3_secret_access_key", ""),
        "endpoint": m.get("s3_endpoint", "") or "https://files.polygon.io",
        "bucket": m.get("s3_bucket", "") or "flatfiles",
    }


def massive_rest() -> dict[str, str]:
    m = load().get("massive", {}) or {}
    return {
        "api_key": m.get("rest_api_key", ""),
        "base_url": m.get("rest_base_url", "") or "https://api.polygon.io",
    }


def tushare_token() -> str:
    return str((load().get("tushare", {}) or {}).get("token", "") or "")


def dirs() -> dict[str, str]:
    return dict(load().get("dirs", {}) or {})


def mongo() -> dict[str, str]:
    n = load().get("news", {}) or {}
    return {
        "uri": n.get("mongo_uri", ""),
        "db": n.get("mongo_db", ""),
        "collection": n.get("mongo_collection", ""),
    }


def schedule() -> dict[str, Any]:
    return dict(load().get("schedule", {}) or {})
