"""massive (formerly Polygon) flat-file downloads into the raw massive root.

Flat files live in an S3-compatible bucket (``flatfiles``) as
``<index>/YYYY/MM/YYYY-MM-DD.csv.gz``, for example
``us_stocks_sip/minute_aggs_v1/2026/08/2026-08-03.csv.gz``. Each download is
converted to parquet in the layout the massive adapter reads::

    $RAW_MASSIVE_DIR/<index>/YYYY/MM/YYYY-MM-DD.parquet

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
}
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})\.csv\.gz$")


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
                path = root / index / d[:4] / d[5:7] / f"{d}.parquet"
                out.append({"key": obj["Key"], "date": d, "size": int(obj["Size"]),
                            "path": str(path), "exists": path.exists()})
    out.sort(key=lambda x: x["date"])
    return out


def csv_to_parquet(csv_gz: Path, parquet: Path) -> None:
    """Stream a gzipped flat-file CSV into zstd parquet (bounded memory)."""
    import pyarrow as pa
    import pyarrow.csv as pacsv
    import pyarrow.parquet as pq
    parquet.parent.mkdir(parents=True, exist_ok=True)
    tmp = parquet.with_suffix(".parquet.part")
    with pa.input_stream(str(csv_gz), compression="gzip") as stream:
        reader = pacsv.open_csv(stream, read_options=pacsv.ReadOptions(block_size=64 << 20))
        writer = pq.ParquetWriter(str(tmp), reader.schema, compression="zstd")
        try:
            for batch in reader:
                writer.write_batch(batch)
        finally:
            writer.close()
    os.replace(tmp, parquet)


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
        tmp = target.with_suffix(".csv.gz.part")
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
