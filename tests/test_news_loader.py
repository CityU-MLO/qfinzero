"""Benzinga news -> ESP docs: the massive drop and the monthly archive deliveries."""

from __future__ import annotations

import gzip
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from qfinzero.update.loaders import news  # noqa: E402

ARCHIVE = {
    "benzinga_id": 60859291, "author": "mohd haider", "published": "2026-08-01T02:21:21Z",
    "last_updated": "2026-08-01T03:00:00Z", "title": "Brin &#39;Leading&#39; Campaign",
    "teaser": "Short &amp; sweet.", "body": "<p>First &#8220;para&#8221;.</p><p>Second <a href='x'>link</a>.</p>",
    "url": "https://www.benzinga.com/x", "images": ["https://cdn/x?width=250", "https://cdn/x?width=2048"],
    "channels": ["news", "politics"], "tickers": ["SPY"], "tags": ["donald trump"],
}
DROP = {"benzinga_id": "39798184", "published": "2024-06-01T12:00:00Z", "title": "Old",
        "tickers": "['AAPL', 'MSFT']", "channels": "['markets']", "tags": "[]", "url": "u"}


def test_archive_delivery_fields():
    d = news.to_doc(ARCHIVE)
    assert d["_id"] == "bz_60859291" and d["tickers"] == ["SPY"] and d["title"] == "Brin 'Leading' Campaign"
    assert d["description"] == "Short & sweet."
    assert d["body_text"] == "First “para”.\nSecond link."
    assert d["image_url"].endswith("width=2048") and d["keywords"] == ["news", "politics", "donald trump"]
    assert d["updated_utc"].isoformat() == "2026-08-01T03:00:00+00:00"


def test_massive_drop_unchanged():
    d = news.to_doc(DROP)
    assert d["tickers"] == ["AAPL", "MSFT"] and d["description"] == "" and "body_text" not in d and "image_url" not in d


def test_month_files_include_gzip(tmp_path, monkeypatch):
    monkeypatch.setattr(news, "_news_dir", lambda: tmp_path)
    (tmp_path / "2026").mkdir()
    with gzip.open(tmp_path / "2026" / "2026-08.jsonl.gz", "wt") as f:
        f.write(json.dumps(ARCHIVE) + "\n")
    (tmp_path / "2026" / "2026-07.jsonl").write_text(json.dumps(DROP) + "\n")
    assert [p.name for p in news._month_files("2026-08", "2026-08")] == ["2026-08.jsonl.gz"]
    assert len(news._month_files(None, None)) == 2


def test_every_doc_says_how_much_content_it_has():
    full = news.to_doc(ARCHIVE)
    assert (full["content_level"], full["content_chars"]) == ("full", len(full["body_text"]))
    teaser = news.to_doc({**ARCHIVE, "body": ""})
    assert (teaser["content_level"], teaser["content_chars"]) == ("summary", len("Short & sweet."))
    assert news.to_doc(DROP)["content_level"] == "headline" and news.to_doc(DROP)["content_chars"] == 0
