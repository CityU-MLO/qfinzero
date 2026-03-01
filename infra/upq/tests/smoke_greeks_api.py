#!/usr/bin/env python3
"""Smoke test for UPQ realtime Greeks endpoints.

Usage:
  python3 infra/upq/tests/smoke_greeks_api.py --host 127.0.0.1 --port 19705
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Any


def build_url(host: str, port: int, path: str, params: dict[str, Any] | None = None) -> str:
    query = urllib.parse.urlencode(params or {})
    if query:
        return f"http://{host}:{port}{path}?{query}"
    return f"http://{host}:{port}{path}"


def get_json(host: str, port: int, path: str, params: dict[str, Any] | None = None) -> Any:
    url = build_url(host, port, path, params)
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read())


def check_health(host: str, port: int) -> None:
    payload = get_json(host, port, "/health")
    if payload.get("status") != "ok":
        raise RuntimeError(f"/health status not ok: {payload}")
    print(f"health: ok (version={payload.get('version')})")


def check_chain(host: str, port: int, underlying: str, date: str, expiry: str) -> tuple[int, Counter[str]]:
    rows = get_json(
        host,
        port,
        "/option/chain_query",
        {
            "underlying": underlying,
            "date": date,
            "expiry_min": expiry,
            "expiry_max": expiry,
            "include_greeks": "true",
        },
    )
    if not isinstance(rows, list):
        raise RuntimeError("chain_query did not return array")
    if not rows:
        raise RuntimeError("chain_query returned empty array")

    statuses: Counter[str] = Counter()
    ok_iv_rows = 0
    for idx, row in enumerate(rows):
        status = row.get("greek_status")
        if not isinstance(status, str):
            raise RuntimeError(f"chain row {idx} missing greek_status")
        statuses[status] += 1

        meta = row.get("greek_meta")
        if not isinstance(meta, dict):
            raise RuntimeError(f"chain row {idx} missing greek_meta")

        if status == "ok":
            iv = row.get("iv")
            delta = row.get("delta")
            if not isinstance(iv, (int, float)) or not isinstance(delta, (int, float)):
                raise RuntimeError(f"chain row {idx} status=ok but iv/delta not numeric")
            ok_iv_rows += 1

    print(f"chain: rows={len(rows)} statuses={dict(statuses)} ok_rows_with_numeric_iv_delta={ok_iv_rows}")
    return len(rows), statuses


def check_ticker_minute(
    host: str,
    port: int,
    contract: str,
    start: str,
    end: str,
) -> tuple[int, Counter[str]]:
    rows = get_json(
        host,
        port,
        "/option/ticker_query",
        {
            "contract": contract,
            "start": start,
            "end": end,
            "resolution": "minute",
            "include_greeks": "true",
        },
    )

    if not isinstance(rows, list):
        raise RuntimeError("ticker_query did not return array")
    if not rows:
        raise RuntimeError("ticker_query returned empty array")

    statuses: Counter[str] = Counter()
    ok_rows = 0
    for idx, row in enumerate(rows):
        status = row.get("greek_status")
        if not isinstance(status, str):
            raise RuntimeError(f"minute row {idx} missing greek_status")
        statuses[status] += 1

        meta = row.get("greek_meta")
        if not isinstance(meta, dict):
            raise RuntimeError(f"minute row {idx} missing greek_meta")
        if meta.get("t_convention") != "minute_precise":
            raise RuntimeError(
                f"minute row {idx} unexpected t_convention={meta.get('t_convention')}"
            )

        if status == "ok":
            iv = row.get("iv")
            delta = row.get("delta")
            if not isinstance(iv, (int, float)) or not isinstance(delta, (int, float)):
                raise RuntimeError(f"minute row {idx} status=ok but iv/delta not numeric")
            ok_rows += 1

    print(f"minute: rows={len(rows)} statuses={dict(statuses)} ok_rows_with_numeric_iv_delta={ok_rows}")
    return len(rows), statuses


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UPQ realtime Greeks smoke test")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=19705)
    parser.add_argument("--underlying", default="AAPL")
    parser.add_argument("--date", default="2025-12-30")
    parser.add_argument("--expiry", default="2026-01-16")
    parser.add_argument("--contract", default="O:AAPL260116C00275000")
    parser.add_argument("--minute-start", default="2025-12-30T14:30:00")
    parser.add_argument("--minute-end", default="2025-12-30T15:00:00")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        check_health(args.host, args.port)
        check_chain(args.host, args.port, args.underlying, args.date, args.expiry)
        check_ticker_minute(args.host, args.port, args.contract, args.minute_start, args.minute_end)
    except urllib.error.HTTPError as exc:
        print(f"HTTP error: {exc.code} {exc.reason}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"Smoke check failed: {exc}", file=sys.stderr)
        return 1

    print("smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
