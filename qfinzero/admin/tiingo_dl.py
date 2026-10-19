"""Tiingo BOATS (Blue Ocean ATS overnight session) into the raw library.

Two feeds, both written as the vendor sent them (gzip JSON) under
``$RAW_TIINGO_DIR/boats/`` and read in place by the converter
(:mod:`qfinzero.pipeline.sources.tiingo`):

* ``prices/<YYYY-MM>/<TICKER>.json.gz`` - overnight 1-minute OHLCV bars from
  ``/boats/<ticker>/prices`` (history starts 2026-07-07; earlier months come back
  empty). A month is fetched once it is over and again while it is current.
* ``quotes/<YYYY-MM-DD>/<HHMM>.json.gz`` - the all-ticker top of book from
  ``/boats``, taken once a minute by :func:`record_quotes` while the session
  runs (Tiingo keeps no quote history, so quotes exist from when recording
  starts). Date and time are ET at the moment of the request.

The key comes from the ``tiingo`` vendor keys (Data setup -> Vendor keys,
product ``boats``) or ``TIINGO_API_KEY``; it is sent as a header and never
written to the library.
"""

from __future__ import annotations

import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

BASE = "https://api.tiingo.com"
HISTORY_START = date(2026, 7, 1)          # first month Tiingo serves BOATS bars for
ET = ZoneInfo("America/New_York")
COLUMNS = "open,high,low,close,volume"
OnLine = Callable[[str], None]


def api_key() -> str:
    from . import config_store
    k = config_store.pick_key("tiingo", "boats")
    return (k or {}).get("api_key") or os.environ.get("TIINGO_API_KEY", "")


def root_dir() -> Path:
    from . import config_store
    return Path(config_store.dirs().get("raw_tiingo") or os.environ.get("RAW_TIINGO_DIR") or "/data/tiingo")


class Client:
    """Minimal REST client: token header, JSON out, backoff on 429/5xx."""

    def __init__(self, key: str, per_hour: int | None = None, opener=None):
        if not key:
            raise ValueError("Tiingo API key not configured (Data setup -> Vendor keys -> Tiingo)")
        self.key = key
        self.gap = 3600.0 / per_hour if per_hour else 0.0
        self._last = 0.0
        self._lock = threading.Lock()      # requests are spaced across threads
        self._open = opener or urllib.request.urlopen

    def _pace(self) -> None:
        with self._lock:
            wait = self._last + self.gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def get(self, path: str, params: dict[str, Any] | None = None, tries: int = 5) -> Any:
        url = BASE + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        for i in range(tries):
            self._pace()
            req = urllib.request.Request(url, headers={"Authorization": f"Token {self.key}",
                                                       "Content-Type": "application/json"})
            try:
                with self._open(req, timeout=60) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return []
                if e.code in (429, 500, 502, 503, 504) and i + 1 < tries:
                    time.sleep(min(60, 2 ** i * 5))
                    continue
                raise RuntimeError(f"Tiingo {e.code} for {path}: {e.read()[:200]!r}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if i + 1 < tries:
                    time.sleep(min(60, 2 ** i * 5))
                    continue
                raise RuntimeError(f"Tiingo unreachable: {e}") from None
        return []


def _write_gz(path: Path, obj: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = gzip.compress(json.dumps(obj, separators=(",", ":")).encode(), mtime=0)
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return len(data)


def universe(client: Client) -> list[str]:
    """Every ticker BOATS quotes (the all-ticker snapshot)."""
    snap = client.get("/boats") or []
    return sorted({str(x["ticker"]).upper() for x in snap if x.get("ticker")})


def months(start: date, end: date) -> list[tuple[date, date]]:
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        out.append((max(cur, start), min(nxt - timedelta(days=1), end)))
        cur = nxt
    return out


def download_prices(*, key: str | None = None, root: Path | None = None, start: str | None = None,
                    end: str | None = None, tickers: Iterable[str] | None = None, per_hour: int = 9000,
                    workers: int = 6,
                    on_line: OnLine | None = None, on_progress: Optional[Callable[..., None]] = None,
                    should_stop: Optional[Callable[[], bool]] = None, client: Client | None = None) -> dict[str, Any]:
    """Fetch overnight minute bars per ticker and month. Past months already in
    the library are skipped; the current month is always refreshed. A month of
    one ticker is about 1 MB, so ``workers`` requests run at once (still spaced
    to ``per_hour``)."""
    from concurrent.futures import ThreadPoolExecutor
    say = on_line or (lambda _l: None)
    prog = on_progress or (lambda **_k: None)
    stop = should_stop or (lambda: False)
    client = client or Client(key or api_key(), per_hour=per_hour)
    root = (root or root_dir()) / "boats" / "prices"
    today = datetime.now(ET).date()
    s = max(date.fromisoformat(start) if start else HISTORY_START, HISTORY_START)
    e = min(date.fromisoformat(end) if end else today, today)
    syms = sorted({t.strip().upper() for t in tickers if t.strip()}) if tickers else universe(client)
    plan = []
    for m0, m1 in months(s, e):
        current = m1 >= today - timedelta(days=1)
        for t in syms:
            out = root / m0.strftime("%Y-%m") / f"{t}.json.gz"
            if out.exists() and not current:
                continue
            plan.append((t, m0, m1, out))
    say(f"[tiingo] {len(syms)} tickers, {s} .. {e}: {len(plan)} requests")
    prog(stage="downloading", files_total=len(plan), files_done=0)
    def fetch(job):
        t, m0, m1, out = job
        if stop():
            return None
        # the session of m1 ends the next morning: ask one day further
        rows = client.get(f"/boats/{t.lower()}/prices", {"startDate": m0.isoformat(),
                                                          "endDate": (m1 + timedelta(days=1)).isoformat(),
                                                          "resampleFreq": "1min", "columns": COLUMNS}) or []
        if rows:
            _write_gz(out, rows)
        return sum(1 for r in rows if r.get("volume")) if rows else -1

    written = bars = empty = done = 0
    with ThreadPoolExecutor(max(1, workers)) as ex:
        for n in ex.map(fetch, plan):
            if n is None:
                continue
            done += 1
            if n < 0:
                empty += 1
            else:
                written += 1
                bars += n
            if done % 200 == 0 or done == len(plan):
                say(f"[tiingo] {done}/{len(plan)} requests, {written} files, {bars:,} traded minutes")
                prog(files_done=done)
    if done < len(plan):
        say("[tiingo] stopped by the user")
    return {"ok": True, "requests": len(plan), "done": done, "files": written, "empty": empty,
            "traded_minutes": bars, "root": str(root)}


def in_session(now: datetime) -> bool:
    """20:00-04:00 ET, Sunday evening to Friday morning."""
    et = now.astimezone(ET)
    m = et.hour * 60 + et.minute
    wd = et.weekday()             # Mon 0 .. Sun 6
    if m >= 20 * 60:
        return wd in (6, 0, 1, 2, 3)
    if m < 4 * 60:
        return wd in (0, 1, 2, 3, 4)
    return False


def record_quotes(*, key: str | None = None, root: Path | None = None, minutes: int | None = None,
                  on_line: OnLine | None = None, should_stop: Optional[Callable[[], bool]] = None,
                  client: Client | None = None, now: Callable[[], datetime] | None = None,
                  sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Take the all-ticker top of book once a minute until the session ends
    (or ``minutes`` snapshots). Safe to start often (the scheduler runs it every
    few minutes): outside the session it returns at once, and a second copy
    returns while one is recording (lock file)."""
    import fcntl
    say = on_line or (lambda _l: None)
    stop = should_stop or (lambda: False)
    clock = now or (lambda: datetime.now(ET))
    root = (root or root_dir()) / "boats" / "quotes"
    if minutes is None and not in_session(clock()):
        return {"ok": True, "snapshots": 0, "note": "outside the 20:00-04:00 ET session", "root": str(root)}
    root.mkdir(parents=True, exist_ok=True)
    lock = open(root / ".recording.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        return {"ok": True, "snapshots": 0, "note": "already recording", "root": str(root)}
    client = client or Client(key or api_key())
    taken = 0
    while not stop() and (minutes is None or taken < minutes):
        t = clock()
        if not in_session(t):
            if taken or minutes is None:
                break
        snap = client.get("/boats") or []
        et = t.astimezone(ET)
        out = root / et.strftime("%Y-%m-%d") / f"{et.strftime('%H%M')}.json.gz"
        _write_gz(out, snap)
        taken += 1
        if taken % 30 == 1:
            say(f"[tiingo] {et:%Y-%m-%d %H:%M} ET: {len(snap)} tickers -> {out}")
        # next minute boundary, plus a few seconds for the venue's last updates
        t2 = clock()
        sleep(max(1.0, 60 - t2.second - t2.microsecond / 1e6 + 3))
    lock.close()
    return {"ok": True, "snapshots": taken, "root": str(root)}
