"""Editable runtime configuration — data dirs, vendor credentials, update schedule.

The operator edits these from the Console data manager (or ``qfz-data config``)
instead of hand-writing shell env: the shared RAW roots, the per-store output root,
the MASSIVE flat-files S3 credentials + REST key, the Tushare token, the Databento
API key, the ESP/Mongo
connection, and the auto-update schedule. Persisted as JSON at
``$QFZ_DATA_ROOT/_state/qfz.config.json`` (gitignored — it holds secrets, ``data/``
is already ignored) and **applied to ``os.environ``** so the pipeline, the download
scripts (``POLYGON_S3_*``) and the services keep working
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
    "massive_s3", "massive_rest", "tushare_token", "databento_key", "dirs", "schedule",
    "mongo", "persisted",
]

_LOCK = threading.RLock()

# Secret leaf paths (section, key) — masked on display, preserved on save.
_SECRETS = {
    ("massive", "s3_access_key_id"),
    ("massive", "s3_secret_access_key"),
    ("massive", "rest_api_key"),
    ("tushare", "token"),
    ("databento", "api_key"),
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
            "raw_databento": os.environ.get("RAW_DATABENTO_DIR", "/data/databento"),
            "raw_tiingo": os.environ.get("RAW_TIINGO_DIR", "/data/tiingo"),
            "storage_root": os.environ.get("STORAGE_ROOT", f"{root}/upq"),
        },
        # MASSIVE / Polygon flat-files (US stocks, options, rates, corp actions).
        # S3 is the download transport (massive_dl); REST is the reference/
        # permissions endpoint. In practice the REST key == the S3 secret.
        "massive": {
            "s3_access_key_id": os.environ.get("POLYGON_S3_ACCESS_KEY_ID", ""),
            "s3_secret_access_key": os.environ.get("POLYGON_S3_SECRET_ACCESS_KEY", ""),
            "s3_endpoint": os.environ.get("MASSIVE_S3_ENDPOINT", "https://files.polygon.io"),
            "s3_bucket": os.environ.get("MASSIVE_S3_BUCKET", "flatfiles"),
            "rest_api_key": os.environ.get("MASSIVE_REST_API_KEY", os.environ.get("POLYGON_API_KEY", "")),
            "rest_base_url": os.environ.get("MASSIVE_REST_BASE_URL", "https://api.polygon.io"),
        },
        # Quote stores: keep one NBBO per N minutes (1, 5, 15, 30, 60).
        "quotes": {"stock_interval_min": 1, "option_interval_min": 1, "future_interval_min": 1},
        "tushare": {"token": os.environ.get("TUSHARE_TOKEN", "")},
        # Databento historical API (DBN downloads; US equities + OPRA options).
        "databento": {"api_key": os.environ.get("DATABENTO_API_KEY", "")},
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
            # Tiingo BOATS overnight. Cron runs on server time, so the recorder is
            # started every 10 minutes and does nothing outside 20:00-04:00 ET.
            "tiingo_quotes": {"enabled": False, "cron": "*/10 * * * *"},
            "tiingo_prices": {"enabled": False, "cron": "0 18 * * 1-5"},   # after 04:00 ET on a UTC+8 box
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
            if section == "keys":          # managed by save_key / delete_key (secrets inside)
                continue
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
    if "keys" in out:
        out["keys"] = {v: masked_keys(v) for v in KEY_SECRETS}
    return out


def apply_to_env(cfg: dict[str, Any] | None = None) -> None:
    """Push dirs + credentials into ``os.environ`` so the pipeline, the download
    scripts and the services observe them (only non-empty values overwrite)."""
    cfg = cfg or load()
    d = cfg.get("dirs", {}) or {}
    m = cfg.get("massive", {}) or {}
    n = cfg.get("news", {}) or {}
    tok = (cfg.get("tushare", {}) or {}).get("token", "")
    dbk = (cfg.get("databento", {}) or {}).get("api_key", "")
    env = {
        "QFZ_DATA_ROOT": d.get("qfz_data_root", ""),
        "RAW_MASSIVE_DIR": d.get("raw_massive", ""),
        "RAW_TUSHARE_DIR": d.get("raw_tushare", ""),
        "RAW_DATABENTO_DIR": d.get("raw_databento", ""),
        "RAW_TIINGO_DIR": d.get("raw_tiingo", ""),
        "STORAGE_ROOT": d.get("storage_root", ""),
        # MASSIVE flat-files S3 (the names the massive downloads read).
        "POLYGON_S3_ACCESS_KEY_ID": m.get("s3_access_key_id", ""),
        "POLYGON_S3_SECRET_ACCESS_KEY": m.get("s3_secret_access_key", ""),
        "MASSIVE_S3_ENDPOINT": m.get("s3_endpoint", ""),
        "MASSIVE_S3_BUCKET": m.get("s3_bucket", ""),
        "MASSIVE_REST_API_KEY": m.get("rest_api_key", ""),
        "MASSIVE_REST_BASE_URL": m.get("rest_base_url", ""),
        "TUSHARE_TOKEN": tok or "",
        "DATABENTO_API_KEY": dbk or "",
        "MONGO_URI": n.get("mongo_uri", ""),
        "MONGO_DB": n.get("mongo_db", ""),
        "MONGO_COLLECTION": n.get("mongo_collection", ""),
        "BENZINGA_API_KEY": n.get("benzinga_api_key", ""),
    }
    for k, v in env.items():
        if v:
            os.environ[k] = str(v)


# ── typed accessors (used by scan / acquire / scheduler / services) ──────────
def massive_s3(index: str | None = None) -> dict[str, str]:
    """S3 credentials for a massive flat-file index (the first key whose products
    cover it; without ``index``, the first key)."""
    k = pick_key("massive", index) or {}
    m = load().get("massive", {}) or {}
    return {
        "access_key_id": k.get("s3_access_key_id", ""),
        "secret_access_key": k.get("s3_secret_access_key", ""),
        "endpoint": k.get("s3_endpoint") or m.get("s3_endpoint", "") or "https://files.polygon.io",
        "bucket": m.get("s3_bucket", "") or "flatfiles",
        "key_id": k.get("id", ""),
    }


def massive_rest() -> dict[str, str]:
    m = load().get("massive", {}) or {}
    return {
        "api_key": m.get("rest_api_key", ""),
        "base_url": m.get("rest_base_url", "") or "https://api.polygon.io",
    }


def tushare_token() -> str:
    return str((load().get("tushare", {}) or {}).get("token", "") or "")


def databento_key(dataset: str | None = None) -> str:
    """The API key for a Databento dataset (the first key whose products cover
    it; without ``dataset``, the first key)."""
    return str((pick_key("databento", dataset) or {}).get("api_key", "") or "")


# ── vendor keys: several per vendor, each for some products ──────────────────
#
# Databento and massive sell products separately, so a team may hold one key per
# subscription or a single key for everything. ``keys.<vendor>`` is a list of
# ``{id, label, products, <secrets>…}``; ``products`` are dataset codes
# (``GLBX.MDP3``) or flat-file indices (``us_options_opra/*``), shell-style
# patterns allowed, ``["*"]`` for all. A download uses the first key whose
# products match. The single key of older configs shows up as ``default``.

KEY_SECRETS = {
    "databento": ("api_key",),
    "massive": ("s3_access_key_id", "s3_secret_access_key", "rest_api_key"),
    "tiingo": ("api_key",),
}
KEY_FIELDS = {
    "databento": ("label", "products", "monthly_budget_usd", "note"),
    "massive": ("label", "products", "s3_endpoint", "note"),
    "tiingo": ("label", "products", "note"),
}


def _legacy_key(vendor: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    if vendor == "tiingo":           # keys only (no single-key section)
        return None
    if vendor == "databento":
        v = (cfg.get("databento", {}) or {}).get("api_key", "")
        return {"id": "default", "label": "default", "products": ["*"], "api_key": v} if v else None
    m = cfg.get("massive", {}) or {}
    if m.get("s3_access_key_id") or m.get("s3_secret_access_key") or m.get("rest_api_key"):
        return {"id": "default", "label": "default", "products": ["*"],
                "s3_access_key_id": m.get("s3_access_key_id", ""),
                "s3_secret_access_key": m.get("s3_secret_access_key", ""),
                "rest_api_key": m.get("rest_api_key", "")}
    return None


def vendor_keys(vendor: str) -> list[dict[str, Any]]:
    """All keys of a vendor, secrets in the clear."""
    if vendor not in KEY_SECRETS:
        raise ValueError(f"unknown vendor {vendor!r}")
    cfg = load()
    keys = [dict(k) for k in ((cfg.get("keys") or {}).get(vendor) or [])]
    legacy = _legacy_key(vendor, cfg)
    if legacy and not any(k.get("id") == "default" for k in keys):
        keys.insert(0, legacy)
    return keys


def _matches(patterns, product: str | None) -> bool:
    import fnmatch
    pats = patterns or ["*"]
    if product is None:
        return True
    return any(p == "*" or fnmatch.fnmatchcase(product, p) or product.startswith(p.rstrip("*").rstrip("/") + "/")
               for p in pats)


def pick_key(vendor: str, product: str | None = None) -> dict[str, Any] | None:
    """The first key of ``vendor`` whose products cover ``product``."""
    for k in vendor_keys(vendor):
        if any(k.get(s) for s in KEY_SECRETS[vendor]) and _matches(k.get("products"), product):
            return k
    return None


def masked_keys(vendor: str) -> list[dict[str, Any]]:
    out = []
    for k in vendor_keys(vendor):
        v = {f: k.get(f) for f in ("id", *KEY_FIELDS[vendor]) if f in k}
        v.setdefault("products", ["*"])
        for sname in KEY_SECRETS[vendor]:
            val = str(k.get(sname) or "")
            v[sname] = ("•" * 4 + val[-4:]) if val else ""
        out.append(v)
    return out


def save_key(vendor: str, key: dict[str, Any]) -> dict[str, Any]:
    """Add (no ``id``) or update a key. Blank or masked secrets keep the stored
    value. Returns the masked key."""
    import secrets as _secrets
    with _LOCK:
        keys = vendor_keys(vendor)
        kid = str(key.get("id") or "") or "k_" + _secrets.token_hex(4)
        cur = next((k for k in keys if k.get("id") == kid), None)
        new = dict(cur or {"id": kid})
        for f in KEY_FIELDS[vendor]:
            if f in key:
                new[f] = key[f]
        if isinstance(new.get("products"), str):
            new["products"] = [p.strip() for p in new["products"].split(",") if p.strip()]
        new["products"] = new.get("products") or ["*"]
        for sname in KEY_SECRETS[vendor]:
            sv = str(key.get(sname) or "")
            if sv and "•" not in sv:
                new[sname] = sv.strip()
        if not any(new.get(s) for s in KEY_SECRETS[vendor]):
            raise ValueError("a key needs its secret")
        keys = [new if k.get("id") == kid else k for k in keys] if cur else [*keys, new]
        cfg = load()
        cfg.setdefault("keys", {})[vendor] = keys
        save(cfg)
        return next(k for k in masked_keys(vendor) if k["id"] == kid)


def delete_key(vendor: str, key_id: str) -> bool:
    with _LOCK:
        keys = vendor_keys(vendor)
        if not any(k.get("id") == key_id for k in keys):
            return False
        cfg = load()
        cfg.setdefault("keys", {})[vendor] = [k for k in keys if k.get("id") != key_id]
        if key_id == "default":           # the single key of older configs
            if vendor == "databento":
                cfg.setdefault("databento", {})["api_key"] = ""
            else:
                cfg.setdefault("massive", {}).update(s3_access_key_id="", s3_secret_access_key="", rest_api_key="")
        save(cfg)
        return True


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
