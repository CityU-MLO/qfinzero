"""Vendor key catalog, key checks and the Databento spend ledger.

Keys themselves are stored by :mod:`config_store` (``keys.<vendor>``). This
module knows what each vendor sells (so the UI can offer products to scope a
key to), checks a key against the vendor, and records what Databento downloads
cost so budgets can be enforced.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from . import config_store

DATABENTO_DATASETS = [
    ("GLBX.MDP3", "CME Globex futures and options"),
    ("OPRA.PILLAR", "US equity options (OPRA)"),
    ("EQUS.MINI", "US equities, consolidated mini"),
    ("EQUS.SUMMARY", "US equities, daily summary"),
    ("DBEQ.BASIC", "Databento US equities basic"),
    ("XNAS.ITCH", "Nasdaq TotalView-ITCH"),
    ("XNYS.PILLAR", "NYSE integrated"),
    ("ARCX.PILLAR", "NYSE Arca integrated"),
    ("OCEA.MEMOIR", "Blue Ocean ATS (overnight)"),
    ("IFUS.IMPACT", "ICE Futures US"),
    ("IFEU.IMPACT", "ICE Futures Europe"),
    ("NDEX.IMPACT", "ICE Endex"),
    ("XEUR.EOBI", "Eurex"),
]


def massive_indices() -> list[tuple[str, str]]:
    from .massive_dl import INDICES
    return [(i, f"{a} {r}") for i, (a, r) in INDICES.items()]


def catalog() -> dict[str, list[dict[str, str]]]:
    return {"databento": [{"product": c, "name": n} for c, n in DATABENTO_DATASETS],
            "massive": [{"product": c, "name": n} for c, n in massive_indices()],
            "tiingo": [{"product": "boats", "name": "BOATS overnight (Blue Ocean ATS)"}]}


def _find(vendor: str, key_id: str) -> dict[str, Any]:
    k = next((k for k in config_store.vendor_keys(vendor) if k.get("id") == key_id), None)
    if k is None:
        raise KeyError(key_id)
    return k


def test_key(vendor: str, key_id: str, *, databento_client=None, s3=None) -> dict[str, Any]:
    """Check a key with the vendor. Databento: the key authenticates and lists
    datasets. massive: which flat-file products the key can download. Every
    key can list every product, so each product's newest file is fetched with
    HEAD; only those the subscription covers answer. The key can then be
    scoped to exactly those."""
    k = _find(vendor, key_id)
    if vendor == "tiingo":
        from . import tiingo_dl
        try:
            snap = tiingo_dl.Client(k["api_key"]).get("/boats/spy")
        except Exception as e:  # noqa: BLE001 - report the vendor's answer
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return {"ok": True, "access": {"boats": bool(snap)}}
    if vendor == "databento":
        try:
            client = databento_client or __import__("databento").Historical(k["api_key"])
            datasets = list(client.metadata.list_datasets())
        except ModuleNotFoundError:
            return {"ok": False, "error": "databento package not installed (pip install 'qfinzero[databento]')"}
        except Exception as e:  # noqa: BLE001 - report the vendor's answer
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return {"ok": True, "datasets": len(datasets),
                "note": "Databento does not say which datasets a key is licensed for; scope it by hand."}
    try:
        if s3 is None:
            from .massive_dl import client
            endpoint = k.get("s3_endpoint") or config_store.massive_s3().get("endpoint")
            s3 = client(k.get("s3_access_key_id", ""), k.get("s3_secret_access_key", ""), endpoint)
    except ModuleNotFoundError:
        return {"ok": False, "error": "boto3 not installed (pip install 'qfinzero[massive]')"}
    from datetime import date

    from .massive_dl import can_download, latest_key
    access: dict[str, bool] = {}
    errors: dict[str, str] = {}
    for index, _ in massive_indices():
        try:
            key = latest_key(s3, index, date.today().year)
            why = can_download(s3, key) if key else "no files listed"
        except Exception as e:  # noqa: BLE001 - listing refused
            why = type(e).__name__
        access[index] = why is None
        if why:
            errors[index] = why
    ok = any(access.values())
    return {"ok": ok, "access": access, **({"error": "the key can download none of the products"} if not ok else {}),
            "errors": errors}


# ── Databento spend ledger ────────────────────────────────────────────────

_LOCK = threading.Lock()


def ledger_path() -> Path:
    return config_store.config_path().parent / "databento_spend.jsonl"


def record_spend(key_id: str, dataset: str, schema: str, cost_usd: float, files: int, job: str = "") -> None:
    if cost_usd <= 0:
        return
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key_id": key_id, "dataset": dataset,
           "schema": schema, "cost_usd": round(float(cost_usd), 4), "files": files, "job": job}
    with _LOCK:
        p = ledger_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(row) + "\n")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass


def spend(month: str | None = None) -> dict[str, Any]:
    """Spend per key in a month (``YYYY-MM``, default this month) and the last rows."""
    month = month or time.strftime("%Y-%m", time.gmtime())
    rows = []
    try:
        rows = [json.loads(line) for line in ledger_path().read_text().splitlines() if line.strip()]
    except OSError:
        pass
    by_key: dict[str, float] = {}
    for r in rows:
        if r["ts"].startswith(month):
            by_key[r["key_id"]] = by_key.get(r["key_id"], 0.0) + float(r["cost_usd"])
    budgets = {k["id"]: k.get("monthly_budget_usd") for k in config_store.vendor_keys("databento")}
    return {"month": month, "by_key": {k: round(v, 4) for k, v in by_key.items()},
            "budgets": {k: v for k, v in budgets.items() if v not in (None, "")},
            "total": round(sum(by_key.values()), 4), "recent": rows[-20:][::-1]}


def budget_left(key_id: str) -> float | None:
    """What a key may still spend this month (None = no budget set)."""
    b = next((k.get("monthly_budget_usd") for k in config_store.vendor_keys("databento") if k.get("id") == key_id), None)
    if b in (None, ""):
        return None
    return float(b) - float(spend()["by_key"].get(key_id, 0.0))
