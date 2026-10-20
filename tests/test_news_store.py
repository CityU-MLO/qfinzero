"""News storage settings (Data setup -> News) and the Benzinga archive unpacker."""

import gzip
import hashlib
import io
import json
import zipfile

import pytest


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("QFZ_CONFIG_FILE", str(tmp_path / "qfz.config.json"))
    for k in ("MONGO_URI", "MONGO_DB", "MONGO_COLLECTION"):
        monkeypatch.delenv(k, raising=False)
    from qfinzero.admin import news_store
    return news_store


def test_defaults_read_the_shared_collection(store):
    s = store.settings()
    assert s["mode"] == "legacy"
    assert s["legacy_collection"] == "ticker_news"
    assert store.read_targets(s) == [("shared", "ticker_news")]
    assert store.write_target("benzinga", s) == "ticker_news"
    assert {x["id"]: x["collection"] for x in s["sources"]} == {"benzinga": "news_benzinga", "tushare": "news_tushare"}


def test_vendor_mode_reads_and_writes_vendor_collections(store):
    store.save({"mode": "vendor"})
    s = store.settings()
    assert store.read_targets(s) == [("benzinga", "news_benzinga"), ("tushare", "news_tushare")]
    assert store.write_target("benzinga", s) == "news_benzinga"
    # a disabled vendor is not read
    store.save({"sources": [{**x, "enabled": x["id"] != "tushare"} for x in s["sources"]]})
    assert store.read_targets() == [("benzinga", "news_benzinga")]


def test_uri_is_masked_and_a_masked_uri_keeps_the_stored_one(store):
    store.save({"mongo_uri": "mongodb://qfz:hunter2@db:27017", "mongo_db": "news"})
    pub = store.public_settings()
    assert "hunter2" not in pub["mongo_uri"] and pub["mongo_uri"].startswith("mongodb://qfz:")
    store.save({"mongo_uri": pub["mongo_uri"]})
    store.save({"mongo_uri": ""})
    assert store.settings()["mongo_uri"] == "mongodb://qfz:hunter2@db:27017"
    assert store.settings()["mongo_db"] == "news"
    assert store.mask_uri("mongodb://localhost:27018") == "mongodb://localhost:27018"


def test_shared_collection_keeps_its_config_key(store):
    from qfinzero.admin import config_store
    store.save({"legacy_collection": "old_news"})
    assert config_store.mongo()["collection"] == "old_news"
    assert store.settings()["legacy_collection"] == "old_news"


def test_bad_mode_and_bad_source_are_rejected(store):
    store.save({"mode": "nonsense"})
    assert store.settings()["mode"] == "legacy"
    with pytest.raises(ValueError):
        store.save({"sources": [{"id": "x"}]})


def test_prefix_range_covers_exactly_the_prefix(store):
    r = store._prefix_range("bz_")
    inside = [i for i in ("bz_1", "bz_zzz", "bz`", "bz^9", "ts_1", "bza") if r["$gte"] <= i < r["$lt"]]
    assert inside == ["bz_1", "bz_zzz"]


def _archive(tmp_path, *, corrupt=False):
    month = gzip.compress(b'{"benzinga_id": 1}\n')
    manifest = {"month": "2026-08", "files": [{"file": "data/2026-08.jsonl.gz",
                                              "file_sha256": hashlib.sha256(month).hexdigest()}]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("data/2026-08.jsonl.gz", month + (b"x" if corrupt else b""))
        z.writestr("../evil/2026-09.jsonl.gz", b"")   # only the base name is used
    p = tmp_path / "Benzinga_News_2026-08.zip"
    p.write_bytes(buf.getvalue())
    return p


def test_unpack_checks_the_manifest_and_files_into_the_library(tmp_path, monkeypatch):
    from qfinzero import config
    from qfinzero.update.loaders import news
    monkeypatch.setattr(config, "RAW_MASSIVE_DIR", str(tmp_path / "massive"))
    files = news.unpack([str(_archive(tmp_path))])
    lib = tmp_path / "massive" / "benzinga" / "news" / "2026"
    assert sorted(f.name for f in files) == ["2026-08.jsonl.gz", "2026-09.jsonl.gz"]
    assert all(f.parent == lib for f in files)
    assert (lib / "2026-08.manifest.json").exists()
    assert not (tmp_path / "evil").exists()


def test_unpack_rejects_a_checksum_mismatch(tmp_path, monkeypatch):
    from qfinzero import config
    from qfinzero.update.loaders import news
    monkeypatch.setattr(config, "RAW_MASSIVE_DIR", str(tmp_path / "massive"))
    with pytest.raises(ValueError, match="SHA-256"):
        news.unpack([str(_archive(tmp_path, corrupt=True))])


def test_unpack_rejects_files_without_a_month(tmp_path):
    from qfinzero.update.loaders import news
    p = tmp_path / "news.jsonl"
    p.write_text("")
    with pytest.raises(ValueError):
        news.unpack([str(p)])


def test_content_levels_and_filters():
    from qfinzero.admin import news_store as ns
    assert ns.content_fields({"body_text": " x ", "description": "teaser"}) == {"content_level": "full", "content_chars": 1}
    assert ns.content_fields({"description": "flash text"})["content_level"] == "summary"
    assert ns.content_fields({"title": "only"}) == {"content_level": "headline", "content_chars": 0}
    assert ns.levels_at_least(None) is None and ns.levels_at_least("headline") is None
    assert ns.levels_at_least("summary") == ["summary", "full"] and ns.levels_at_least("full") == ["full"]
    with pytest.raises(ValueError):
        ns.levels_at_least("most")


def test_search_indexes_give_esp_order_and_carry_the_filters():
    from qfinzero.admin import news_store as ns
    window, by_ticker, by_level = ns.SEARCH_INDEXES
    assert by_level[0] == ("content_level", 1)
    assert window[:2] == [("published_utc", 1), ("_id", 1)] and ("title", 1) in window and ("content_level", 1) in window
    assert by_ticker[:3] == [("tickers", 1), ("published_utc", 1), ("_id", 1)]
