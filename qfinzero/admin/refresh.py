"""Bring a source up to date: fetch the days the vendor has and we lack, then convert.

The scheduled update (:mod:`qfinzero.update`) only converts raw files already
on disk. For sources fed by massive flat files, *refresh* first asks massive
which days it has over the last ``LOOKBACK_DAYS`` up to today that the raw
library lacks (new days and gaps alike), downloads them with the matching
vendor key into the library, and converts that date range. Databento is never fetched here:
it bills per request, so it goes through the quote-and-accept download.

    plan(["us_stock_daily"])   -> what would be fetched (no download)
    run(["us_stock_daily"])    -> fetch and convert
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

# update source -> massive flat-file index that feeds it
FEEDS: dict[str, str] = {
    "us_stock_daily": "us_stocks_sip/day_aggs_v1",
    "us_stock_minute": "us_stocks_sip/minute_aggs_v1",
    "us_option_day": "us_options_opra/day_aggs_v1",
    "us_option_minute": "us_options_opra/minute_aggs_v1",
}
# sources that have a vendor but are not fetched automatically, and why
MANUAL = {
    "us_databento": "Databento bills per request: quote and accept it under Download",
    "cn_stock_daily": "Tushare has no downloader here: import the dump under Local files",
}


LOOKBACK_DAYS = 120   # how far back a refresh looks for days missing from the raw library


def _today_et() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def _after(d: Optional[str]) -> Optional[date]:
    if not d:
        return None
    try:
        return date.fromisoformat(d[:10]) + timedelta(days=1)
    except ValueError:
        return None


def plan(source_ids: list[str], status: dict[str, dict], *, today: Optional[date] = None,
         download: Optional[Callable[..., dict]] = None) -> list[dict[str, Any]]:
    """For each source: the vendor days to fetch (``fetch``), the local raw days
    still to convert (``convert_days``) and the resulting ``action``
    (``fetch`` | ``convert`` | ``none`` | ``manual``) with a ``message``.

    ``status`` maps source id -> its row from the update orchestrator
    (``raw_max``, ``store_max``, ``state``, ``behind_days``)."""
    if download is None:
        from .datasetup import download
    today = today or _today_et()
    out = []
    for sid in source_ids:
        st = status.get(sid, {})
        item: dict[str, Any] = {"id": sid, "raw_max": st.get("raw_max"), "store_max": st.get("store_max"),
                                "convert_days": st.get("behind_days") or 0, "fetch": None}
        index = FEEDS.get(sid)
        if index is None:
            item["action"] = "convert" if item["convert_days"] else ("manual" if sid in MANUAL else "none")
            item["message"] = MANUAL.get(sid, "") if item["action"] == "manual" else ""
            out.append(item)
            continue
        newest = max(x for x in (st.get("raw_max"), st.get("store_max"), "") if x is not None) or None
        start = (_after(newest) - timedelta(days=LOOKBACK_DAYS + 1)) if newest else None
        if start is None:
            item["action"] = "convert" if item["convert_days"] else "manual"
            item["message"] = "no local data yet: choose the first range under Download"
            out.append(item)
            continue
        fetch: dict[str, Any] = {"vendor": "massive", "index": index, "start": start.isoformat(),
                                 "end": today.isoformat()}
        if start <= today:
            try:
                res = download("massive", {"index": index, "start": fetch["start"], "end": fetch["end"]},
                               dry_run=True)
            except Exception as e:  # noqa: BLE001 - network, credentials: report, don't fail the page
                res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            if res.get("ok") is False:
                fetch["error"] = str(res.get("error") or "massive is unreachable")
            else:
                missing = res.get("missing_dates") or []
                fetch.update({"files": res.get("missing", 0), "bytes": res.get("bytes", 0),
                              "first": missing[0] if missing else None, "last": missing[-1] if missing else None,
                              "gaps": sum(1 for d in missing if newest and d <= newest[:10]),
                              "key": res.get("key")})
        else:
            fetch.update({"files": 0, "bytes": 0})
        item["fetch"] = fetch
        if fetch.get("files"):
            item["action"] = "fetch"
            item["message"] = (f"{fetch['files']} day(s) on massive missing locally ({fetch['first']} .. {fetch['last']}"
                               + (f", {fetch['gaps']} inside a gap" if fetch["gaps"] else "") + f"), {fetch['bytes'] / 1e9:.2f} GB")
        elif item["convert_days"]:
            item["action"] = "convert"
            item["message"] = "local raw files not converted yet"
        else:
            item["action"] = "none"
            item["message"] = (fetch.get("error") and f"massive: {fetch['error']}") or (
                f"up to date: massive has nothing after {st.get('raw_max') or st.get('store_max')}")
        out.append(item)
    return out


def run(items: list[dict[str, Any]], *, on_line: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[..., None]] = None, should_stop: Optional[Callable[[], bool]] = None,
        download: Optional[Callable[..., dict]] = None) -> dict[str, Any]:
    """Fetch and convert the ``fetch`` items of a :func:`plan`."""
    if download is None:
        from .datasetup import download
    say = on_line or (lambda _l: None)
    results = []
    for it in items:
        f = it.get("fetch") or {}
        if it.get("action") != "fetch":
            continue
        if should_stop and should_stop():
            break
        say(f"[refresh] {it['id']}: fetching {f['files']} day(s) of {f['index']} from massive")
        # only the span of the missing days, so conversion covers just that range
        res = download("massive", {"index": f["index"], "start": f.get("first") or f["start"],
                                   "end": f.get("last") or f["end"]}, dry_run=False,
                       on_line=say, on_progress=on_progress, should_stop=should_stop)
        results.append({"id": it["id"], "ok": res.get("ok", True), "error": res.get("error"),
                        "files": res.get("missing", 0), "last": res.get("last")})
        if res.get("ok") is False:
            say(f"[refresh] {it['id']}: {res.get('error')}")
    return {"ok": all(r["ok"] for r in results), "fetched": results,
            **({"error": "; ".join(f"{r['id']}: {r['error']}" for r in results if not r["ok"])}
               if not all(r["ok"] for r in results) else {})}
