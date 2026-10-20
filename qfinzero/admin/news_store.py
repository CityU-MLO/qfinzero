"""Where news lives: the MongoDB connection and one collection per vendor.

News used to share one collection (``ticker_news``) across vendors, told
apart only by the id prefix (``bz_`` Benzinga, ``ts_`` Tushare). That
collection is also read by other services, so it is left as it is: the
vendors are *copied* into their own collections (``news_benzinga``,
``news_tushare``…) by :func:`split`, and the ``mode`` setting switches QFZ
from the shared collection (``legacy``) to the vendor collections (``vendor``)
once the copy is verified. Loaders write to the vendor collection in
``vendor`` mode and to the shared one in ``legacy`` mode.

The settings live in the data configuration (``news`` section); the URI may
carry a password and is masked in the API. Environment variables
(``MONGO_URI``, ``MONGO_DB``, ``MONGO_COLLECTION``) are the defaults.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Optional

from . import config_store

DEFAULT_SOURCES = [
    {"id": "benzinga", "vendor": "Benzinga", "market": "us", "collection": "news_benzinga", "prefix": "bz_"},
    {"id": "tushare", "vendor": "Tushare", "market": "cn", "collection": "news_tushare", "prefix": "ts_"},
]
# the indexes ESP queries on (the shared collection has the same set)
INDEXES = [
    [("published_utc", -1)],
    [("tickers", 1), ("published_utc", -1)],
    [("market", 1), ("published_utc", -1), ("_id", 1)],
    [("news_kind", 1), ("published_utc", -1)],
]
# ESP reads news in (published_utc, _id) order with optional ticker, content-level and
# title filters. These indexes give that order (a page stops after `limit` rows instead
# of sorting the whole window) and carry content_level and title, so those filters are
# applied to index keys and only matching documents are read. Vendor collections only:
# the shared legacy collection is left as it is.
SEARCH_INDEXES = [
    [("published_utc", 1), ("_id", 1), ("content_level", 1), ("title", 1)],
    [("tickers", 1), ("published_utc", 1), ("_id", 1), ("content_level", 1)],
]
# superseded by SEARCH_INDEXES (dropped when the indexes are ensured)
OBSOLETE_INDEXES = ("published_utc_-1_title_1",)

# What an article carries: "full" (the article text, body_text), "summary" (a teaser or
# a flash item's text, description) or "headline" (the title only).
CONTENT_LEVELS = ("headline", "summary", "full")


def content_fields(doc: dict) -> dict[str, Any]:
    """``content_level`` and ``content_chars`` (characters of the longest text) of a news doc."""
    body = str(doc.get("body_text") or "").strip()
    desc = str(doc.get("description") or "").strip()
    level = "full" if body else "summary" if desc else "headline"
    return {"content_level": level, "content_chars": len(body or desc)}


def levels_at_least(min_content: Optional[str]) -> Optional[list[str]]:
    """The content levels a ``min_content`` filter keeps (``None``: every article)."""
    if not min_content or min_content == "headline":
        return None
    if min_content not in CONTENT_LEVELS:
        raise ValueError(f"min_content must be one of {', '.join(CONTENT_LEVELS)}")
    return list(CONTENT_LEVELS[CONTENT_LEVELS.index(min_content):])


def _text(field: str) -> dict:
    return {"$trim": {"input": {"$convert": {"input": f"${field}", "to": "string", "onError": "", "onNull": ""}}}}


# content_fields as an update pipeline (server side)
CONTENT_PIPELINE = [{"$set": {
    "content_level": {"$switch": {"branches": [
        {"case": {"$gt": [{"$strLenCP": _text("body_text")}, 0]}, "then": "full"},
        {"case": {"$gt": [{"$strLenCP": _text("description")}, 0]}, "then": "summary"}], "default": "headline"}},
    "content_chars": {"$max": [{"$strLenCP": _text("body_text")}, {"$strLenCP": _text("description")}]},
}}]


def backfill_content(db, name: str, on_line: Optional[Callable[[str], None]] = None) -> int:
    """Set content_level / content_chars on documents that lack them, one year at a time."""
    from datetime import datetime
    say = on_line or (lambda _l: None)
    coll = db[name]
    lo = coll.find_one({"published_utc": {"$type": "date"}}, sort=[("published_utc", 1)], projection={"published_utc": 1})
    hi = coll.find_one({"published_utc": {"$type": "date"}}, sort=[("published_utc", -1)], projection={"published_utc": 1})
    done = 0
    if lo and hi:
        for year in range(lo["published_utc"].year, hi["published_utc"].year + 1):
            r = coll.update_many({"published_utc": {"$gte": datetime(year, 1, 1), "$lt": datetime(year + 1, 1, 1)},
                                  "content_level": {"$exists": False}}, CONTENT_PIPELINE)
            done += r.modified_count
            if r.modified_count:
                say(f"[news] {name} {year}: content level set on {r.modified_count:,}")
    r = coll.update_many({"content_level": {"$exists": False}}, CONTENT_PIPELINE)   # undated stragglers
    return done + r.modified_count


def settings() -> dict[str, Any]:
    """Effective news settings (unmasked)."""
    cfg = (config_store.load().get("news") or {})
    sources = cfg.get("sources") or DEFAULT_SOURCES
    return {
        "mongo_uri": cfg.get("mongo_uri") or os.environ.get("MONGO_URI", "mongodb://localhost:27018"),
        "mongo_db": cfg.get("mongo_db") or os.environ.get("MONGO_DB", "market_news"),
        # the shared collection keeps its historical config key
        "legacy_collection": cfg.get("mongo_collection") or os.environ.get("MONGO_COLLECTION", "ticker_news"),
        "mode": cfg.get("mode") if cfg.get("mode") in ("legacy", "vendor") else "legacy",
        "sources": [{**s, "enabled": s.get("enabled", True)} for s in sources],
    }


def mask_uri(uri: str) -> str:
    """``mongodb://user:secret@host`` -> ``mongodb://user:••••@host``."""
    if "@" not in uri or "://" not in uri:
        return uri
    scheme, rest = uri.split("://", 1)
    cred, host = rest.rsplit("@", 1)
    user = cred.split(":", 1)[0]
    return f"{scheme}://{user}:••••@{host}" if ":" in cred else uri


def public_settings() -> dict[str, Any]:
    s = settings()
    return {**s, "mongo_uri": mask_uri(s["mongo_uri"])}


def save(patch: dict[str, Any]) -> dict[str, Any]:
    """Update the ``news`` section. A masked or blank URI keeps the stored one."""
    cur = (config_store.load().get("news") or {})
    out = dict(cur)
    uri = str(patch.get("mongo_uri") or "").strip()
    if uri and "••••" not in uri:
        out["mongo_uri"] = uri
    if patch.get("mongo_db"):
        out["mongo_db"] = str(patch["mongo_db"]).strip()
    if patch.get("legacy_collection"):
        out["mongo_collection"] = str(patch["legacy_collection"]).strip()
    if patch.get("mode") in ("legacy", "vendor"):
        out["mode"] = patch["mode"]
    if isinstance(patch.get("sources"), list):
        clean = []
        for s in patch["sources"]:
            if not s.get("id") or not s.get("collection"):
                raise ValueError("a source needs an id and a collection")
            clean.append({k: s.get(k) for k in ("id", "vendor", "market", "collection", "prefix", "enabled") if k in s})
        out["sources"] = clean
    config_store.update({"news": out})
    return public_settings()


def read_targets(s: Optional[dict] = None) -> list[tuple[str, str]]:
    """``[(source id, collection)]`` QFZ reads news from in the current mode."""
    s = s or settings()
    if s["mode"] == "vendor":
        return [(x["id"], x["collection"]) for x in s["sources"] if x.get("enabled", True)]
    return [("shared", s["legacy_collection"])]


def write_target(source_id: str, s: Optional[dict] = None) -> str:
    """Collection a loader for ``source_id`` writes to."""
    s = s or settings()
    if s["mode"] == "vendor":
        for x in s["sources"]:
            if x["id"] == source_id:
                return x["collection"]
    return s["legacy_collection"]


def client(uri: Optional[str] = None, timeout_ms: int = 4000):
    from pymongo import MongoClient
    return MongoClient(uri or settings()["mongo_uri"], serverSelectionTimeoutMS=timeout_ms)


def test(uri: Optional[str] = None, db: Optional[str] = None) -> dict[str, Any]:
    """Connect and report the server and the database's collections."""
    s = settings()
    uri = uri if uri and "••••" not in uri else s["mongo_uri"]
    db = db or s["mongo_db"]
    try:
        c = client(uri)
        info = c.server_info()
        names = sorted(c[db].list_collection_names())
        c.close()
        return {"ok": True, "version": info.get("version"), "database": db, "collections": names}
    except Exception as e:  # noqa: BLE001 - report the driver's answer
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _prefix_range(prefix: str) -> dict:
    """``_id`` range of one id prefix (``bz_`` -> [``bz_``, ``bz` ``))."""
    return {"$gte": prefix, "$lt": prefix[:-1] + chr(ord(prefix[-1]) + 1)}


def _coll_usage(db, name: str, names: Optional[set[str]] = None) -> dict[str, Any]:
    # MongoDB 8 answers collstats on a missing collection with zeros, so look first
    if name not in (names if names is not None else set(db.list_collection_names())):
        return {"collection": name, "exists": False}
    try:
        st = db.command("collstats", name)
    except Exception:  # noqa: BLE001 - dropped meanwhile
        return {"collection": name, "exists": False}
    coll = db[name]
    first = coll.find_one({}, sort=[("published_utc", 1)], projection={"published_utc": 1})
    last = coll.find_one({}, sort=[("published_utc", -1)], projection={"published_utc": 1})
    iso = lambda d: d["published_utc"].isoformat() if d and d.get("published_utc") else None  # noqa: E731
    return {
        "collection": name, "exists": True, "documents": st.get("count", 0),
        "data_bytes": st.get("size", 0), "storage_bytes": st.get("storageSize", 0),
        "index_bytes": st.get("totalIndexSize", 0), "avg_doc_bytes": st.get("avgObjSize", 0),
        "indexes": sorted(st.get("indexSizes", {})), "first": iso(first), "last": iso(last),
    }


def usage() -> dict[str, Any]:
    """Server, database and per-collection usage (cheap: stats and index ends only)."""
    s = settings()
    out: dict[str, Any] = {"settings": public_settings(), "ok": False}
    try:
        c = client()
        info = c.server_info()
        db = c[s["mongo_db"]]
        dbst = db.command("dbstats")
        out.update(ok=True, version=info.get("version"), database={
            "name": s["mongo_db"], "data_bytes": dbst.get("dataSize", 0), "storage_bytes": dbst.get("storageSize", 0),
            "index_bytes": dbst.get("indexSize", 0), "collections": dbst.get("collections", 0),
            "fs_used_bytes": dbst.get("fsUsedSize"), "fs_total_bytes": dbst.get("fsTotalSize")})
        names = set(db.list_collection_names())
        out["shared"] = _coll_usage(db, s["legacy_collection"], names)
        out["sources"] = [{**src, **_coll_usage(db, src["collection"], names)} for src in s["sources"]]
        out["read_from"] = [c_ for _, c_ in read_targets(s)]
        c.close()
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def ensure_indexes(db, name: str) -> list[str]:
    vendor = name != settings()["legacy_collection"]
    out = [db[name].create_index(k) for k in INDEXES + (SEARCH_INDEXES if vendor else [])]
    if vendor:
        have = {ix["name"] for ix in db[name].list_indexes()}
        for old in OBSOLETE_INDEXES:
            if old in have:
                db[name].drop_index(old)
    return out


def split(*, on_line: Optional[Callable[[str], None]] = None, on_progress: Optional[Callable[..., None]] = None,
          should_stop: Optional[Callable[[], bool]] = None, sources: Optional[list[str]] = None) -> dict[str, Any]:
    """Copy each vendor's documents from the shared collection into its own
    collection (server side, ``$merge``; re-running only refreshes), index it
    and check the counts. The shared collection is not modified."""
    say = on_line or (lambda _l: None)
    prog = on_progress or (lambda **_k: None)
    stop = should_stop or (lambda: False)
    s = settings()
    c = client(timeout_ms=10000)
    db = c[s["mongo_db"]]
    shared = db[s["legacy_collection"]]
    todo = [x for x in s["sources"] if x.get("prefix") and (not sources or x["id"] in sources)]
    expected = {x["id"]: shared.count_documents({"_id": _prefix_range(x["prefix"])}) for x in todo}
    total = sum(expected.values())
    say(f"[split] {s['legacy_collection']}: " + ", ".join(f"{x['id']} {expected[x['id']]:,}" for x in todo))
    prog(stage="planned", files_total=total, files_done=0)
    results, done = [], 0
    for x in todo:
        if stop():
            say("[split] stopped by the user")
            break
        say(f"[split] {x['id']}: copying {expected[x['id']]:,} documents into {x['collection']}")
        prog(stage="copying", current=x["collection"])
        t0 = time.time()
        finished = threading.Event()

        def watch(name=x["collection"], base=done):
            while not finished.wait(5):
                try:
                    n = db.command("collstats", name).get("count", 0)
                except Exception:  # noqa: BLE001
                    n = 0
                prog(files_done=base + n)
        w = threading.Thread(target=watch, daemon=True)
        w.start()
        try:
            shared.aggregate([{"$match": {"_id": _prefix_range(x["prefix"])}},
                              {"$merge": {"into": x["collection"], "on": "_id", "whenMatched": "replace",
                                          "whenNotMatched": "insert"}}], allowDiskUse=True)
        finally:
            finished.set()
            w.join(timeout=1)
        say(f"[split] {x['id']}: copied in {time.time() - t0:.0f}s; indexing")
        prog(stage="indexing", current=x["collection"])
        ensure_indexes(db, x["collection"])
        got = db[x["collection"]].count_documents({"_id": _prefix_range(x["prefix"])})
        ok = got >= expected[x["id"]]
        want = expected[x["id"]]
        say(f"[split] {x['id']}: {got:,} documents" + ("" if ok else f", expected {want:,}"))
        done += expected[x["id"]]
        prog(files_done=done)
        results.append({"id": x["id"], "collection": x["collection"], "expected": expected[x["id"]], "copied": got, "ok": ok})
    c.close()
    return {"ok": bool(results) and all(r["ok"] for r in results) and len(results) == len(todo), "sources": results}
