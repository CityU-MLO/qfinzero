"""Load raw Benzinga news (massive) into ESP's MongoDB ``ticker_news``.

ESP reads Polygon-shaped news docs (``published_utc``, ``title``, ``publisher.name``,
``tickers``, ``description``, ``article_url``, ``keywords``). The massive Benzinga
drop stores stringified lists (``"['AAPL','MSFT']"``) which we parse. Benzinga's
monthly archive deliveries (``YYYY-MM.jsonl.gz``) carry real lists plus the
teaser, images and the HTML body: the teaser becomes ``description``, the
largest image ``image_url`` and the body plain text ``body_text``.

    python -m qfinzero.update.loaders.news --since 2025-01 --until 2026-12
    python -m qfinzero.update.loaders.news --months 12          # last N months
    python -m qfinzero.update.loaders.news --status             # counts only
"""

from __future__ import annotations

import argparse
import ast
import gzip
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from qfinzero import config

# massive Benzinga news drop: <RAW_MASSIVE_DIR>/benzinga/news/YYYY/YYYY-MM.jsonl
_MONTH_RE = re.compile(r"(\d{4})-(\d{2})\.jsonl(?:\.gz)?$")
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"</?(?:p|div|br|li|ul|ol|h[1-6]|tr|table|blockquote)[^>]*>", re.I)


def _news_dir() -> Path:
    return Path(config.RAW_MASSIVE_DIR) / "benzinga" / "news"


def _parse_list(value) -> list[str]:
    """Parse a stringified python list (``"['A','B']"``) into a list of str."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    s = str(value).strip()
    if not s or s in ("[]", "''", '""'):
        return []
    try:
        v = ast.literal_eval(s)
        return [str(x) for x in v] if isinstance(v, (list, tuple)) else []
    except (ValueError, SyntaxError):
        return []


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def html_text(body: str | None) -> str:
    """Article HTML -> plain text with paragraph breaks."""
    if not body:
        return ""
    t = _BLOCK_RE.sub("\n", str(body))
    t = html.unescape(_TAG_RE.sub("", t))
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in t.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def to_doc(rec: dict) -> dict | None:
    """Benzinga record -> ESP/Polygon ticker_news doc, or None if unusable."""
    bid = str(rec.get("benzinga_id") or "").strip()
    if not bid:
        return None
    published = _parse_dt(rec.get("published"))
    if published is None:
        return None
    doc = {
        "_id": f"bz_{bid}",
        "published_utc": published,
        "title": html.unescape(rec.get("title") or ""),
        # the massive drop has no summary; archive deliveries have a teaser
        "description": html_text(rec.get("teaser")),
        "article_url": rec.get("url"),
        "author": rec.get("author"),
        "publisher": {"name": "Benzinga"},
        "tickers": _parse_list(rec.get("tickers")),
        "keywords": _parse_list(rec.get("channels")) + _parse_list(rec.get("tags")),
    }
    images = _parse_list(rec.get("images"))
    if images:
        doc["image_url"] = images[-1]           # deliveries list sizes small -> large
    body = html_text(rec.get("body"))
    if body:
        doc["body_text"] = body
    updated = _parse_dt(rec.get("last_updated"))
    if updated:
        doc["updated_utc"] = updated
    from qfinzero.admin.news_store import content_fields
    doc.update(content_fields(doc))
    return doc


def _month_files(since: str | None, until: str | None) -> list[Path]:
    out = []
    for p in _news_dir().rglob("*.jsonl*"):
        m = _MONTH_RE.search(p.name)
        if not m:
            continue
        ym = f"{m.group(1)}-{m.group(2)}"
        if since and ym < since:
            continue
        if until and ym > until:
            continue
        out.append(p)
    return sorted(out)


def _collection(name: str | None = None):
    """Client and the collection Benzinga news goes to: ``news_benzinga`` once
    news is split by vendor, the shared collection before (Data setup -> News)."""
    from qfinzero.admin import news_store
    s = news_store.settings()
    client = news_store.client(s["mongo_uri"])
    return client, client[s["mongo_db"]][name or news_store.write_target("benzinga", s)]


def load(since: str | None = None, until: str | None = None, batch: int = 2000,
         collection: str | None = None, files: list[Path] | None = None, on_line=None) -> dict:
    from pymongo import UpdateOne

    from qfinzero.admin import news_store
    files = files if files is not None else _month_files(since, until)
    if not files:
        return {"files": 0, "upserts": 0, "note": f"no news files in {_news_dir()}"}

    client, coll = _collection(collection)
    say = on_line or (lambda _l: None)
    say(f"[news] {len(files)} file(s) -> {coll.database.name}.{coll.name}")
    news_store.ensure_indexes(coll.database, coll.name)   # the indexes ESP queries on (idempotent)

    total = upserts = skipped = 0
    ops: list = []
    for f in files:
        opener = gzip.open if f.name.endswith(".gz") else open
        with opener(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                doc = to_doc(rec)
                if doc is None:
                    skipped += 1
                    continue
                total += 1
                ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": doc}, upsert=True))
                if len(ops) >= batch:
                    r = coll.bulk_write(ops, ordered=False)
                    upserts += (r.upserted_count + r.modified_count)
                    ops = []
    if ops:
        r = coll.bulk_write(ops, ordered=False)
        upserts += (r.upserted_count + r.modified_count)

    count = coll.estimated_document_count()
    client.close()
    say(f"[news] read {total:,}, written {upserts:,}, skipped {skipped:,}; {coll.name} holds {count:,}")
    return {"files": len(files), "read": total, "upserts": upserts,
            "skipped": skipped, "collection": coll.name, "collection_count": count,
            "range": [since or "*", until or "*"]}


def unpack(paths: list[str], on_line=None) -> list[Path]:
    """Month files from ``paths`` (``.jsonl``, ``.jsonl.gz`` or a Benzinga
    archive ``.zip`` with ``data/YYYY-MM.jsonl.gz`` and ``manifest.json``).
    Archives are checked against their manifest's SHA-256 and their month
    files copied into the raw news library."""
    import hashlib
    import zipfile
    say = on_line or (lambda _l: None)
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out += sorted(x for x in p.rglob("*.jsonl*") if _MONTH_RE.search(x.name))
            continue
        if p.suffix != ".zip":
            if not _MONTH_RE.search(p.name):
                raise ValueError(f"{p.name}: expected YYYY-MM.jsonl[.gz]")
            out.append(p)
            continue
        with zipfile.ZipFile(p) as z:
            manifest = json.loads(z.read("manifest.json")) if "manifest.json" in z.namelist() else {}
            sums = {f["file"]: f.get("file_sha256") for f in manifest.get("files", [])}
            for name in z.namelist():
                m = _MONTH_RE.search(Path(name).name)
                if not m or name.endswith("/"):
                    continue
                data = z.read(name)
                want = sums.get(name)
                if want and hashlib.sha256(data).hexdigest() != want:
                    raise ValueError(f"{p.name}:{name}: SHA-256 does not match the manifest")
                dst = _news_dir() / m.group(1) / Path(name).name
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists() or dst.read_bytes() != data:
                    dst.write_bytes(data)
                say(f"[news] {p.name}:{name} -> {dst}" + (" (checksum ok)" if want else ""))
                out.append(dst)
            if manifest:
                (_news_dir() / str(manifest.get("month", "x"))[:4] / f"{manifest.get('month')}.manifest.json").write_text(
                    json.dumps(manifest, indent=2))
    return out


def status() -> dict:
    try:
        client, coll = _collection()
        n = coll.estimated_document_count()
        latest = coll.find_one(sort=[("published_utc", -1)], projection={"published_utc": 1})
        client.close()
        return {"mongo": config.MONGO_URI, "collection": coll.name, "collection_count": n,
                "latest": latest.get("published_utc").isoformat() if latest and latest.get("published_utc") else None}
    except Exception as e:  # noqa: BLE001
        return {"mongo": config.MONGO_URI, "error": str(e)}


def _default_since(months: int) -> str:
    now = datetime.now(timezone.utc)
    y, m = now.year, now.month - months
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qfz-news", description="Load Benzinga news -> ESP MongoDB")
    ap.add_argument("--since", help="first month YYYY-MM (inclusive)")
    ap.add_argument("--until", help="last month YYYY-MM (inclusive)")
    ap.add_argument("--months", type=int, help="load the last N months (overrides --since)")
    ap.add_argument("--status", action="store_true", help="show Mongo collection status only")
    ap.add_argument("--files", nargs="+", help="month files or Benzinga archive .zip files to load "
                                               "(archives are checked against their manifest and unpacked into the library)")
    ap.add_argument("--backfill-content", nargs="*", metavar="COLLECTION",
                    help="set content_level/content_chars on documents lacking them and ensure the ESP "
                         "indexes (default: every vendor collection)")
    args = ap.parse_args(argv)

    if args.backfill_content is not None:
        from qfinzero.admin import news_store
        s = news_store.settings()
        client = news_store.client(s["mongo_uri"])
        db = client[s["mongo_db"]]
        names = args.backfill_content or [src["collection"] for src in s["sources"]]
        out = {}
        for name in names:
            out[name] = news_store.backfill_content(db, name, on_line=print)
            news_store.ensure_indexes(db, name)
        client.close()
        print(json.dumps({"updated": out}, indent=2))
        return 0
    if args.files:
        result = load(files=unpack(args.files, on_line=print), on_line=print)
        print(json.dumps(result, indent=2, default=str))
        return 0
    if args.status:
        print(json.dumps(status(), indent=2))
        return 0
    since = _default_since(args.months) if args.months else args.since
    result = load(since, args.until)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
