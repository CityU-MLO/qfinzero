"""massive (formerly Polygon) flat-file downloads into the raw massive root.

Flat files live in an S3-compatible bucket (``flatfiles``) as
``<index>/YYYY/MM/YYYY-MM-DD.csv.gz``, for example
``us_stocks_sip/minute_aggs_v1/2026/08/2026-08-03.csv.gz``. Each download is
converted to parquet in the layout the massive adapter reads::

    $RAW_MASSIVE_DIR/<index>/YYYY/MM/YYYY-MM-DD.parquet

:func:`csv_to_parquet` writes the file fast to look up (index level L2): typed
columns, rows by ticker then time, row groups of 122,880 rows, zstd and a page
index (see :func:`_write_opts` for the encodings). :func:`verify_parquet` checks a conversion against its CSV and
:func:`convert_library` converts the ``.csv.gz`` files already in a library.

Like the Databento downloader it plans first (file list and bytes, from the
bucket listing, free) and skips files already on disk, so re-runs fetch only
what is missing. Needs ``boto3`` (``pip install -e ".[massive]"``) and the S3
key pair from the massive dashboard.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

OnLine = Callable[[str], None]

BUCKET = "flatfiles"
# Indices the massive adapter converts (trades / quotes are not converted).
INDICES = {
    "us_stocks_sip/day_aggs_v1": ("stock", "daily"),
    "us_stocks_sip/minute_aggs_v1": ("stock", "minute"),
    "us_options_opra/day_aggs_v1": ("option", "daily"),
    "us_options_opra/minute_aggs_v1": ("option", "minute"),
    # NBBO, tick by tick: very large (OPRA is hundreds of GB a day); converted
    # to the quote stores at the chosen sampling interval.
    "us_options_opra/quotes_v1": ("option", "quotes"),
    "us_stocks_sip/quotes_v1": ("stock", "quotes"),
    # 24-hour markets
    "global_crypto/day_aggs_v1": ("crypto", "daily"),
    "global_crypto/minute_aggs_v1": ("crypto", "minute"),
    "global_forex/day_aggs_v1": ("fx", "daily"),
    "global_forex/minute_aggs_v1": ("fx", "minute"),
    "global_forex/quotes_v1": ("fx", "quotes"),
}
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})\.csv\.gz$")
ROW_GROUP = 122_880
# Column types by name (massive uses the same names across its flat files);
# columns not listed are inferred. Crypto volumes and sizes are fractional.
TYPES = {"ticker": "string", "id": "string", "conditions": "string",
         **{c: "float64" for c in ("open", "high", "low", "close", "price", "bid_price", "ask_price")},
         **{c: "int64" for c in ("volume", "transactions", "window_start", "sip_timestamp", "participant_timestamp",
                                 "trf_timestamp", "size", "bid_size", "ask_size", "exchange", "bid_exchange",
                                 "ask_exchange", "correction", "sequence_number", "tape", "trf_id")}}
FRACTIONAL = {"global_crypto/": ("volume", "size")}


def client(access_key: str, secret_key: str, endpoint: str):
    import boto3
    from botocore.config import Config
    cfg = Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "standard"})
    return boto3.Session(aws_access_key_id=access_key, aws_secret_access_key=secret_key).client(
        "s3", endpoint_url=endpoint, config=cfg)


def _check(index: str) -> None:
    if index not in INDICES:
        raise ValueError(f"index must be one of {', '.join(INDICES)}")


def can_download(s3, key: str) -> Optional[str]:
    """``None`` if ``key`` can be fetched, else why not. massive lets a key list
    every product but only download the subscribed ones (403 on the object)."""
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return None
    except Exception as e:  # noqa: BLE001 - botocore ClientError, network
        code = str(getattr(e, "response", {}).get("Error", {}).get("Code", "")) or type(e).__name__
        if code in ("403", "AccessDenied", "Forbidden"):
            return f"this key can list {key.split('/')[0]}/{key.split('/')[1]} but not download it (403 Forbidden): not in the subscription"
        return f"{type(e).__name__}: {e}"


def latest_key(s3, index: str, year: int) -> Optional[str]:
    """The newest file of ``index`` in ``year`` (or the year before)."""
    for y in (year, year - 1):
        keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{index}/{y}/").get("Contents", [])]
        if keys:
            return sorted(keys)[-1]
    return None


def plan(s3, index: str, start: date, end: date, root: Path) -> list[dict[str, Any]]:
    """Remote files of ``index`` in ``[start, end]``: ``{key, date, size, path, exists}``."""
    _check(index)
    if end < start:
        raise ValueError("end before start")
    out: list[dict[str, Any]] = []
    pages = s3.get_paginator("list_objects_v2")
    for year in range(start.year, end.year + 1):
        for page in pages.paginate(Bucket=BUCKET, Prefix=f"{index}/{year}/"):
            for obj in page.get("Contents", []):
                m = _DATE.search(obj["Key"])
                if not m or not (start.isoformat() <= m.group(1) <= end.isoformat()):
                    continue
                d = m.group(1)
                base = root / index / d[:4] / d[5:7]
                path = base / f"{d}.parquet"
                have = path.exists() or (base / f"{d}.parquet").exists() or (base / f"{d}.csv.gz").exists()
                out.append({"key": obj["Key"], "date": d, "size": int(obj["Size"]),
                            "path": str(path), "exists": have})
    out.sort(key=lambda x: x["date"])
    return out


def _types(path: Path, header: list[str]) -> dict[str, str]:
    frac = next((cols for prefix, cols in FRACTIONAL.items() if prefix.rstrip("/") in path.parts), ())
    return {c: ("float64" if c in frac else TYPES[c]) for c in header if c in TYPES}


def _header(csv_gz: Path) -> list[str]:
    import gzip
    with gzip.open(csv_gz, "rt") as fh:
        return fh.readline().strip().split(",")


def _no_rows(csv_gz: Path) -> bool:
    """massive ships quiet days as a header without even a line break."""
    import gzip
    with gzip.open(csv_gz, "rt") as fh:
        fh.readline()
        return not fh.readline().strip()


def time_column(names) -> Optional[str]:
    return next((c for c in ("window_start", "sip_timestamp", "participant_timestamp") if c in names), None)


def _in_order(batch, last) -> tuple[bool, Any]:
    """Whether ``batch`` continues (ticker, time) order after ``last`` (the previous batch's final key)."""
    import pyarrow.compute as pc
    tick = batch.column(0)
    tcol = time_column(batch.schema.names)
    ts = batch.column(batch.schema.get_field_index(tcol)) if tcol else None
    n = batch.num_rows
    if n == 0:
        return True, last
    key = (tick[0].as_py(), ts[0].as_py() if ts is not None else None)
    if last is not None and (key[0] < last[0] or (key[0] == last[0] and ts is not None and key[1] < last[1])):
        return False, last
    if n > 1:
        a, b = tick.slice(0, n - 1), tick.slice(1)
        ok = pc.less(a, b)
        if ts is not None:
            ok = pc.or_(ok, pc.and_(pc.equal(a, b), pc.less_equal(ts.slice(0, n - 1), ts.slice(1))))
        else:
            ok = pc.or_(ok, pc.equal(a, b))
        if not pc.all(ok).as_py():
            return False, last
    return True, (tick[n - 1].as_py(), ts[n - 1].as_py() if ts is not None else None)


def _write_opts(schema) -> dict[str, Any]:
    """zstd, a page index, dictionaries for text and prices (they repeat), delta
    encoding for integers (sorted timestamps shrink to a few bits). For the
    global flat files this comes out smaller than massive's gzip CSV."""
    ints = [f.name for f in schema if str(f.type) == "int64"]
    return {"compression": "zstd", "compression_level": 3, "write_page_index": True,
            "use_dictionary": [f.name for f in schema if f.name not in ints],
            "column_encoding": {c: "DELTA_BINARY_PACKED" for c in ints}}


def csv_to_parquet(csv_gz: Path, parquet: Path, *, sort_limit: int = 8 << 30) -> dict[str, Any]:
    """Convert one gzipped flat-file CSV to parquet, fast to look up (L2).

    massive ships its files in (ticker, time) order, so the CSV is streamed in
    bounded memory while that order is checked. A file found out of order is
    read again whole and sorted (stable, so ties keep their order) when it is
    under ``sort_limit`` bytes compressed; a larger one is written as it comes
    (and the index reports it as L1). Returns ``{rows, sorted}``.
    """
    import pyarrow as pa
    import pyarrow.csv as pacsv
    import pyarrow.parquet as pq
    header = _header(csv_gz)
    if not header or header[0] != "ticker":
        raise ValueError(f"{csv_gz}: expected a massive flat file starting with a ticker column")
    # empty fields are nulls, as DuckDB reads them (verify_parquet compares the two)
    convert = pacsv.ConvertOptions(column_types=_types(csv_gz, header), strings_can_be_null=True,
                                   quoted_strings_can_be_null=False)
    parquet.parent.mkdir(parents=True, exist_ok=True)
    tmp = parquet.with_name(parquet.name + ".part")

    def stream() -> tuple[int, bool]:
        rows, ordered, last, pending = 0, True, None, []
        with pa.input_stream(str(csv_gz), compression="gzip") as fh:
            reader = pacsv.open_csv(fh, read_options=pacsv.ReadOptions(block_size=64 << 20),
                                    convert_options=convert)
            writer = pq.ParquetWriter(str(tmp), reader.schema, **_write_opts(reader.schema))
            try:
                buffered = 0
                for batch in reader:
                    if ordered:
                        ordered, last = _in_order(batch, last)
                        if not ordered and csv_gz.stat().st_size <= sort_limit:
                            return rows, False
                    pending.append(batch)
                    buffered += batch.num_rows
                    while buffered >= ROW_GROUP:
                        t = pa.Table.from_batches(pending)
                        writer.write_table(t.slice(0, ROW_GROUP), row_group_size=ROW_GROUP)
                        rest = t.slice(ROW_GROUP)
                        pending, buffered = rest.to_batches(), rest.num_rows
                        rows += ROW_GROUP
                if buffered:
                    writer.write_table(pa.Table.from_batches(pending), row_group_size=ROW_GROUP)
                    rows += buffered
            finally:
                writer.close()
        return rows, ordered

    try:
        if _no_rows(csv_gz):
            types = _types(csv_gz, header)
            schema = pa.schema([(c, types.get(c, "string")) for c in header])
            pq.write_table(schema.empty_table(), str(tmp), **_write_opts(schema))
            os.replace(tmp, parquet)
            return {"rows": 0, "sorted": True}
        rows, ordered = stream()
        if not ordered and csv_gz.stat().st_size <= sort_limit:
            with pa.input_stream(str(csv_gz), compression="gzip") as fh:
                t = pacsv.read_csv(fh, convert_options=convert)
            keys = [("ticker", "ascending")] + ([(time_column(t.schema.names), "ascending")]
                                                 if time_column(t.schema.names) else [])
            t = t.sort_by(keys)
            pq.write_table(t, str(tmp), row_group_size=ROW_GROUP, **_write_opts(t.schema))
            rows, ordered = t.num_rows, True
        os.replace(tmp, parquet)
    finally:
        tmp.unlink(missing_ok=True)
    return {"rows": rows, "sorted": ordered}


def verify_parquet(csv_gz: Path, parquet: Path) -> dict[str, Any]:
    """Read both files with DuckDB (an independent CSV parser) and compare row
    counts and an order-independent hash of every row. Raises on a difference."""
    import duckdb
    header = _header(csv_gz)
    types = {"string": "VARCHAR", "float64": "DOUBLE", "int64": "BIGINT"}
    known = _types(csv_gz, header)
    if set(header) - set(known):
        cols = ""
    else:
        cols = ", columns={" + ", ".join(f"'{c}': '{types[known[c]]}'" for c in header) + "}"
    lit = lambda p: str(p).replace("'", "''")  # noqa: E731
    sel = ", ".join(f'"{c}"' for c in header)
    q = "SELECT count(*), sum(hash({cols}))::VARCHAR FROM {src}"
    con = duckdb.connect()
    try:
        con.execute("SET threads = 4")
        a = con.execute(q.format(cols=sel, src=f"read_csv('{lit(csv_gz)}', header=true{cols})")).fetchone()
        b = con.execute(q.format(cols=sel, src=f"read_parquet('{lit(parquet)}')")).fetchone()
    finally:
        con.close()
    if a != b:
        raise ValueError(f"{parquet}: differs from {csv_gz.name} (rows {a[0]} vs {b[0]})")
    return {"rows": int(a[0]), "hash": a[1]}


def convert_library(root: Path, *, indices: Optional[list[str]] = None, workers: int = 4,
                    delete_csv: bool = False, on_line: Optional[OnLine] = None,
                    should_stop: Optional[Callable[[], bool]] = None) -> dict[str, Any]:
    """Convert every ``YYYY-MM-DD.csv.gz`` under ``root`` (or ``root/<index>``)
    that has no parquet beside it, verifying each one. The CSV is kept unless
    ``delete_csv``; with it, a CSV is removed only once its parquet verified
    (including a parquet converted by an earlier run)."""
    import concurrent.futures as cf
    say = on_line or (lambda _l: None)
    stop = should_stop or (lambda: False)
    tops = [root / i for i in indices] if indices else [root]
    todo = sorted(p for top in tops for p in top.rglob("*.csv.gz")
                  if _DATE.search(p.name) and not any(x.startswith((".", "_")) for x in p.relative_to(root).parts))
    say(f"[massive] {len(todo)} csv.gz file(s) under {root}")
    out = {"files": len(todo), "converted": 0, "verified": 0, "deleted": 0, "failed": 0, "unsorted": [],
           "errors": []}

    def one(src: Path) -> tuple[Path, str, dict[str, Any]]:
        if stop():
            return src, "stopped", {}
        dst = src.with_name(src.name[:-len(".csv.gz")] + ".parquet")
        info: dict[str, Any] = {}
        done = "verified"
        if not dst.exists():
            info = csv_to_parquet(src, dst)
            done = "converted"
        info.update(verify_parquet(src, dst))
        if delete_csv:
            src.unlink()
            info["deleted"] = True
        return src, done, info

    with cf.ThreadPoolExecutor(max(1, workers)) as ex:
        futs = {ex.submit(one, p): p for p in todo}
        for i, f in enumerate(cf.as_completed(futs), 1):
            src = futs[f]
            try:
                _, done, info = f.result()
            except Exception as e:  # noqa: BLE001 - report and continue
                out["failed"] += 1
                out["errors"].append(f"{src}: {type(e).__name__}: {e}")
                say(f"  [error] {src}: {type(e).__name__}: {e}")
                continue
            if done == "stopped":
                continue
            out[done] += 1
            out["deleted"] += bool(info.get("deleted"))
            if info.get("sorted") is False:
                out["unsorted"].append(str(src))
            say(f"  [{i}/{len(todo)}] {done} {src.relative_to(root)}  {info.get('rows', 0):,} rows")
    out["ok"] = out["failed"] == 0
    return out


def download(params: dict[str, Any], *, access_key: str, secret_key: str, endpoint: str, root: Path,
             dry_run: bool = True, on_line: Optional[OnLine] = None, s3=None,
             on_progress: Optional[Callable[..., None]] = None,
             should_stop: Optional[Callable[[], bool]] = None) -> dict[str, Any]:
    """Plan (``dry_run``) or fetch one index over a date range. Progress (files
    and bytes, as boto3 transfers them) goes to ``on_progress``; ``should_stop``
    is checked between files."""
    say = on_line or (lambda _l: None)
    prog = on_progress or (lambda **_k: None)
    stop = should_stop or (lambda: False)
    index = str(params.get("index") or "")
    start = date.fromisoformat(str(params.get("start"))[:10])
    end = date.fromisoformat(str(params.get("end"))[:10])
    if s3 is None:
        if not (access_key and secret_key):
            return {"ok": False, "error": "massive S3 access key and secret are required"}
        s3 = client(access_key, secret_key, endpoint)
    files = plan(s3, index, start, end, root)
    todo = [f for f in files if not f["exists"]]
    nbytes = sum(f["size"] for f in todo)
    say(f"[massive] {index} {start}..{end}: {len(files)} files, {len(todo)} missing, "
        f"{nbytes / 1e9:.2f} GB to download")
    result: dict[str, Any] = {"ok": True, "index": index, "files": len(files), "missing": len(todo),
                              "bytes": nbytes, "dry_run": dry_run,
                              "first": files[0]["date"] if files else None,
                              "last": files[-1]["date"] if files else None,
                              "missing_dates": [f["date"] for f in todo]}
    if todo:
        denied = can_download(s3, todo[0]["key"])
        if denied:
            say(f"[massive] {denied}")
            return {**result, "ok": False, "error": denied}
    prog(stage="planned", files_total=len(todo), files_done=0, bytes_total=nbytes, bytes_done=0)
    if dry_run or not todo:
        return result
    done = failed = 0
    first_error = ""
    got = [0]
    for f in todo:
        if stop():
            say("[massive] stopped by the user")
            break
        target = Path(f["path"])
        tmp = target.with_name(f"{f['date']}.csv.gz.part")
        target.parent.mkdir(parents=True, exist_ok=True)
        prog(stage="downloading", current=f["date"])

        def tick(n: int) -> None:
            got[0] += n
            prog(bytes_done=got[0])
        try:
            try:
                s3.download_file(BUCKET, f["key"], str(tmp), Callback=tick)
            except TypeError:          # a client without transfer callbacks
                s3.download_file(BUCKET, f["key"], str(tmp))
                got[0] += f["size"]
            prog(stage="converting", current=f["date"])
            csv_to_parquet(tmp, target)
            done += 1
            say(f"  [{done}/{len(todo)}] {f['date']}  {f['size'] / 1e6:.1f} MB")
        except Exception as e:  # noqa: BLE001 — report and continue with the next day
            failed += 1
            first_error = first_error or f"{type(e).__name__}: {e}"
            say(f"  [error] {f['key']}: {type(e).__name__}: {e}")
        finally:
            tmp.unlink(missing_ok=True)
        prog(files_done=done + failed, files_failed=failed, bytes_done=got[0])
    stopped = done + failed < len(todo)
    result.update(downloaded=done, ok=done == len(todo))
    if stopped:
        result["error"] = "stopped by the user"
    elif failed:
        result["error"] = f"{failed} of {len(todo)} file(s) failed, first: {first_error}"
    return result
