"""Split a DBN file into one file per day, losslessly.

Records are copied byte for byte. Each output keeps the source's DBN version,
dataset, schema and symbology types, has its start/end set to its day and only
the symbology mappings of its own instruments on that day. :func:`verify`
checks that every output decodes with the databento package and that the
outputs' records, in order, are exactly the source's.

The day of a record is the UTC date of ``ts_recv`` (``ts_event`` for schemas
without it, such as OHLCV), as Databento cuts its own daily files; Blue Ocean
(``OCEA.*``) files are one 20:00-04:00 ET session each, named by the ET date
the session opens (:func:`session_day`).
"""

from __future__ import annotations

import datetime as dt
import os
import struct
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Callable, Optional
from zoneinfo import ZoneInfo

DAY_NS = 86_400_000_000_000
ET = ZoneInfo("America/New_York")
SESSION_DATASETS = ("OCEA.",)


ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def _is_zstd(path: Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(4) == ZSTD_MAGIC


def read(src: Path) -> tuple[bytes, bytes]:
    """(metadata bytes, record bytes) of a DBN file, zstd-compressed or not (by its content)."""
    import zstandard as zs
    with open(src, "rb") as fh:
        raw = zs.ZstdDecompressor().stream_reader(fh).read() if _is_zstd(src) else fh.read()
    if raw[:3] != b"DBN":
        raise ValueError(f"{src}: not a DBN file")
    mlen = struct.unpack_from("<I", raw, 4)[0]
    return raw[:8 + mlen], raw[8 + mlen:]


def header_symbols(path: Path) -> list[str]:
    """The ``symbols`` a DBN file was requested with (header only)."""
    import databento_dbn as dbn
    import zstandard as zs
    with open(path, "rb") as fh:
        stream = zs.ZstdDecompressor().stream_reader(fh) if _is_zstd(path) else fh
        head = stream.read(8)
        if head[:3] != b"DBN":
            raise ValueError(f"{path}: not a DBN file")
        mlen = struct.unpack_from("<I", head, 4)[0]
        head += stream.read(mlen)
    return [str(s) for s in dbn.Metadata.decode(head).symbols]


def utc_day(ns) -> "object":
    import numpy as np
    return (np.asarray(ns, dtype=np.int64) // DAY_NS).astype(np.int64)


def session_day(ns) -> "object":
    """ET date a 20:00-04:00 ET session opens on (days since the epoch)."""
    import numpy as np
    import pandas as pd
    local = pd.to_datetime(np.asarray(ns, dtype=np.int64), utc=True).tz_convert(ET).tz_localize(None)
    opened = (local - pd.Timedelta(hours=20)).normalize()
    return ((opened - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1)).to_numpy(dtype=np.int64)


def is_session_dataset(dataset: str) -> bool:
    return str(dataset).upper().startswith(SESSION_DATASETS)


def day_window(dataset: str, day: dt.date) -> tuple[int, int]:
    """[start, end) in UTC ns of the file for ``day``."""
    if is_session_dataset(dataset):
        start = dt.datetime(day.year, day.month, day.day, 20, tzinfo=ET)
        nxt = day + dt.timedelta(days=1)
        end = dt.datetime(nxt.year, nxt.month, nxt.day, 4, tzinfo=ET)
        return int(start.timestamp()) * 10**9, int(end.timestamp()) * 10**9
    start = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc).timestamp()) * 10**9
    return start, start + DAY_NS


def split(src: Path, out_dir: Path, *, overwrite: Optional[set[dt.date]] = None, level: int = 3,
          day_of: Optional[Callable] = None) -> tuple[list[tuple[Path, object]], object]:
    """Write ``out_dir/<YYYY-MM-DD>.dbn.zst`` per day; returns ([(path, record index)], records).

    An existing output is never replaced unless its day is in ``overwrite``.
    Each file is written as ``.part`` and renamed once complete.
    """
    import databento as db
    import databento_dbn as dbn
    import numpy as np
    import zstandard as zs

    store = db.DBNStore.from_file(src)
    meta = store.metadata
    first = next(iter(store.to_ndarray(count=1)), None)
    head, body = read(src)
    if first is None or not body:
        return [], np.zeros(0)
    dtype = first.dtype
    if len(body) % dtype.itemsize:
        raise ValueError(f"{src}: variable-length records cannot be split")
    recs = np.frombuffer(body, dtype=dtype)
    src_md = dbn.Metadata.decode(head)
    ts = recs["ts_recv"] if "ts_recv" in dtype.names else recs["ts_event"]
    days = (day_of or (session_day if is_session_dataset(meta.dataset) else utc_day))(ts)
    out_dir.mkdir(parents=True, exist_ok=True)
    cctx = zs.ZstdCompressor(level=level)
    outs = []
    for d in np.unique(days):
        day = dt.date(1970, 1, 1) + dt.timedelta(days=int(d))
        idx = np.nonzero(days == d)[0]
        sub = recs[idx]
        iids = {int(i) for i in np.unique(sub["instrument_id"])}
        maps = []
        for raw_sym, ivs in meta.mappings.items():
            for iv in ivs:
                if int(iv["symbol"]) in iids and iv["start_date"] <= day < iv["end_date"]:
                    maps.append(NS(raw_symbol=raw_sym, intervals=[NS(
                        start_date=day, end_date=day + dt.timedelta(days=1), symbol=iv["symbol"])]))
        lo, hi = day_window(meta.dataset, day)
        md = dbn.Metadata(dataset=meta.dataset, schema=src_md.schema, start=max(lo, meta.start),
                          stype_in=src_md.stype_in, stype_out=src_md.stype_out,
                          end=min(hi, meta.end) if meta.end else hi, symbols=list(meta.symbols), partial=[],
                          not_found=[], mappings=maps, limit=None, ts_out=meta.ts_out, version=meta.version)
        out = out_dir / f"{day.isoformat()}.dbn.zst"
        if out.exists() and day not in (overwrite or set()):
            raise FileExistsError(f"refusing to overwrite {out}")
        part = out.with_name(out.name + ".part")
        part.write_bytes(cctx.compress(bytes(md.encode()) + sub.tobytes()))
        os.replace(part, out)
        outs.append((out, idx))
    return outs, recs


def verify(outs, recs) -> bool:
    """Outputs decode with databento, hold exactly their records, and use every record once."""
    import databento as db
    import numpy as np
    seen = np.zeros(len(recs), dtype=bool)
    for out, idx in outs:
        got = np.frombuffer(read(out)[1], dtype=recs.dtype)
        if len(db.DBNStore.from_file(out).to_ndarray()) != len(idx) or got.tobytes() != recs[idx].tobytes():
            raise ValueError(f"{out}: records differ from the source")
        seen[idx] = True
    if not seen.all():
        raise ValueError("records left over after the split")
    return True
