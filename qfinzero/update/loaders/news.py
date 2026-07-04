"""Load raw Benzinga news (massive) into ESP's MongoDB ``ticker_news``.

ESP reads Polygon-shaped news docs (``published_utc``, ``title``, ``publisher.name``,
``tickers``, ``description``, ``article_url``, ``keywords``). The massive Benzinga
drop stores stringified lists (``"['AAPL','MSFT']"``) which we parse.

    python -m qfinzero.update.loaders.news --since 2025-01 --until 2026-12
    python -m qfinzero.update.loaders.news --months 12          # last N months
    python -m qfinzero.update.loaders.news --status             # counts only
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from qfinzero import config

# massive Benzinga news drop: <RAW_MASSIVE_DIR>/benzinga/news/YYYY/YYYY-MM.jsonl
_MONTH_RE = re.compile(r"(\d{4})-(\d{2})\.jsonl$")


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


def to_doc(rec: dict) -> dict | None:
    """Benzinga record -> ESP/Polygon ticker_news doc, or None if unusable."""
    bid = str(rec.get("benzinga_id") or "").strip()
    if not bid:
        return None
    published = _parse_dt(rec.get("published"))
    if published is None:
        return None
    return {
        "_id": f"bz_{bid}",
        "published_utc": published,
        "title": rec.get("title") or "",
        "description": "",  # the massive Benzinga drop carries no body/summary
        "article_url": rec.get("url"),
        "author": rec.get("author"),
        "publisher": {"name": "Benzinga"},
        "tickers": _parse_list(rec.get("tickers")),
        "keywords": _parse_list(rec.get("channels")) + _parse_list(rec.get("tags")),
    }


def _month_files(since: str | None, until: str | None) -> list[Path]:
    out = []
    for p in _news_dir().rglob("*.jsonl"):
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


def _collection():
    from pymongo import MongoClient
    client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=4000)
    return client, client[config.MONGO_DB][config.MONGO_COLLECTION]


def load(since: str | None = None, until: str | None = None, batch: int = 2000) -> dict:
    from pymongo import UpdateOne

    files = _month_files(since, until)
    if not files:
        return {"files": 0, "upserts": 0, "note": f"no news files in {_news_dir()}"}

    client, coll = _collection()
    # indexes ESP queries on (idempotent)
    coll.create_index([("published_utc", -1)])
    coll.create_index([("tickers", 1)])

    total = upserts = skipped = 0
    ops: list = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
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
    return {"files": len(files), "read": total, "upserts": upserts,
            "skipped": skipped, "collection_count": count,
            "range": [since or "*", until or "*"]}


def status() -> dict:
    try:
        client, coll = _collection()
        n = coll.estimated_document_count()
        latest = coll.find_one(sort=[("published_utc", -1)], projection={"published_utc": 1})
        client.close()
        return {"mongo": config.MONGO_URI, "collection_count": n,
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
    args = ap.parse_args(argv)

    if args.status:
        print(json.dumps(status(), indent=2))
        return 0
    since = _default_since(args.months) if args.months else args.since
    result = load(since, args.until)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
