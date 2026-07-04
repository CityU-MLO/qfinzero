"""Provider reachability / permission scans — "check user permission".

Answers the operator's "does my key actually work, and what can it reach?" for
each vendor, from stored :mod:`~qfinzero.admin.config_store` credentials:

* :func:`scan_massive_s3` — list the MASSIVE / Polygon flat-files bucket's
  top-level datasets with the S3 key; the definitive entitlement signal (the
  key can list exactly the datasets it is entitled to). Uses ``boto3`` when
  present, else the ``aws`` CLI (which the download scripts already require).
* :func:`scan_massive_rest` — validate the REST key against the reference API.
* :func:`scan_tushare` — validate the Tushare token with a tiny ``trade_cal`` call.

Every scan is best-effort and never raises: a failure is reported as
``{"ok": False, "error": "..."}`` so the wizard can render a red state instead of
500ing. Network/CLI/parse errors are all folded into that envelope.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Callable, Optional

from . import config_store

# Datasets the QFinZero pipeline actually converts (used to flag "required"
# coverage in the scan result — the rest are informational).
REQUIRED_MASSIVE_DATASETS = {
    "us_stocks_sip": "US stocks (SIP)",
    "us_options_opra": "US options (OPRA)",
}


# ── MASSIVE / Polygon flat-files S3 ─────────────────────────────────────────
def _s3_list_prefixes_boto3(s3: dict[str, str]) -> Optional[list[str]]:
    """Top-level bucket prefixes via boto3, or ``None`` if boto3 is unavailable."""
    try:
        import boto3
        from botocore.config import Config
    except ModuleNotFoundError:
        return None
    cfg = Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"})
    client = boto3.client(
        "s3",
        endpoint_url=s3.get("endpoint") or "https://files.polygon.io",
        aws_access_key_id=s3.get("access_key_id") or "",
        aws_secret_access_key=s3.get("secret_access_key") or "",
        config=cfg,
    )
    resp = client.list_objects_v2(Bucket=s3.get("bucket") or "flatfiles", Delimiter="/")
    return [p["Prefix"].rstrip("/") for p in resp.get("CommonPrefixes", [])]


def _s3_list_prefixes_awscli(s3: dict[str, str]) -> list[str]:
    """Top-level bucket prefixes via the ``aws`` CLI (``PRE <name>/`` lines)."""
    env = {
        "AWS_ACCESS_KEY_ID": s3.get("access_key_id") or "",
        "AWS_SECRET_ACCESS_KEY": s3.get("secret_access_key") or "",
        "PATH": _system_path(),
    }
    out = subprocess.run(
        ["aws", "s3", "ls", f"s3://{s3.get('bucket') or 'flatfiles'}/",
         "--endpoint-url", s3.get("endpoint") or "https://files.polygon.io"],
        capture_output=True, text=True, timeout=30, env=env, check=True,
    ).stdout
    prefixes: list[str] = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == "PRE":
            prefixes.append(parts[1].rstrip("/"))
    return prefixes


def _system_path() -> str:
    import os
    return os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")


def scan_massive_s3(
    s3: dict[str, str] | None = None,
    lister: Callable[[dict[str, str]], Optional[list[str]]] | None = None,
) -> dict[str, Any]:
    """List the flat-files bucket's datasets with the configured S3 key.

    ``lister`` is injectable for tests. Returns ``{ok, endpoint, bucket,
    datasets:[{name, required, label}], error?}``.
    """
    s3 = s3 or config_store.massive_s3()
    if not (s3.get("access_key_id") and s3.get("secret_access_key")):
        return {"ok": False, "error": "S3 credentials not configured",
                "endpoint": s3.get("endpoint"), "bucket": s3.get("bucket"), "datasets": []}
    try:
        if lister is not None:
            prefixes = lister(s3)
        else:
            prefixes = _s3_list_prefixes_boto3(s3)
            if prefixes is None:  # boto3 absent → aws CLI
                prefixes = _s3_list_prefixes_awscli(s3)
    except FileNotFoundError:
        return {"ok": False, "error": "no S3 client available (install boto3 or the aws CLI)",
                "endpoint": s3.get("endpoint"), "bucket": s3.get("bucket"), "datasets": []}
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or "").strip().splitlines()[-1] if e.stderr else f"aws exited {e.returncode}"
        return {"ok": False, "error": msg, "endpoint": s3.get("endpoint"),
                "bucket": s3.get("bucket"), "datasets": []}
    except Exception as e:  # noqa: BLE001 — boto/network errors → red state, not a 500
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "endpoint": s3.get("endpoint"), "bucket": s3.get("bucket"), "datasets": []}

    names = sorted(set(prefixes or []))
    datasets = [{"name": n, "required": n in REQUIRED_MASSIVE_DATASETS,
                 "label": REQUIRED_MASSIVE_DATASETS.get(n, "")} for n in names]
    missing = [d for d in REQUIRED_MASSIVE_DATASETS if d not in names]
    return {
        "ok": True, "endpoint": s3.get("endpoint"), "bucket": s3.get("bucket"),
        "datasets": datasets, "count": len(datasets), "missing_required": missing,
    }


# ── MASSIVE / Polygon REST reference API ────────────────────────────────────
def scan_massive_rest(rest: dict[str, str] | None = None) -> dict[str, Any]:
    """Validate the REST key against the reference API (best-effort)."""
    rest = rest or config_store.massive_rest()
    key = rest.get("api_key") or ""
    base = (rest.get("base_url") or "https://api.polygon.io").rstrip("/")
    if not key:
        return {"ok": False, "error": "REST API key not configured", "base_url": base}
    url = f"{base}/v3/reference/tickers"
    try:
        import requests
        r = requests.get(url, params={"limit": 1, "apiKey": key}, timeout=15)
        if r.status_code == 200:
            body = r.json()
            return {"ok": True, "base_url": base, "status": body.get("status"),
                    "sample_count": len(body.get("results") or [])}
        if r.status_code in (401, 403):
            return {"ok": False, "base_url": base, "error": f"unauthorized ({r.status_code})"}
        return {"ok": False, "base_url": base, "error": f"HTTP {r.status_code}"}
    except Exception as e:  # noqa: BLE001 — REST URL may not be exact; degrade gracefully
        return {"ok": False, "base_url": base, "error": f"unreachable: {type(e).__name__}: {e}"}


# ── Tushare ─────────────────────────────────────────────────────────────────
def scan_tushare(token: str | None = None) -> dict[str, Any]:
    """Validate the Tushare token with a minimal ``trade_cal`` request."""
    token = token if token is not None else config_store.tushare_token()
    if not token:
        return {"ok": False, "error": "Tushare token not configured"}
    payload = {"api_name": "trade_cal", "token": token,
               "params": {"exchange": "SSE", "start_date": "20250101", "end_date": "20250110"},
               "fields": "cal_date,is_open"}
    try:
        import requests
        r = requests.post("https://api.tushare.pro", data=json.dumps(payload), timeout=15)
        body = r.json()
        if body.get("code") == 0:
            rows = ((body.get("data") or {}).get("items")) or []
            return {"ok": True, "rows": len(rows)}
        return {"ok": False, "error": body.get("msg") or f"tushare code {body.get('code')}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ── dispatcher ──────────────────────────────────────────────────────────────
def scan(provider: str) -> dict[str, Any]:
    """Scan one provider. ``provider`` ∈ ``massive`` | ``tushare``."""
    p = (provider or "").lower()
    if p == "massive":
        s3 = scan_massive_s3()
        rest = scan_massive_rest()
        return {"provider": "massive", "ok": bool(s3.get("ok")), "s3": s3, "rest": rest}
    if p == "tushare":
        ts = scan_tushare()
        return {"provider": "tushare", "ok": bool(ts.get("ok")), "tushare": ts}
    return {"provider": provider, "ok": False, "error": f"unknown provider {provider!r}"}
