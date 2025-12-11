# src/data_sources/stockbench_news.py
"""
StockBenchNewsLoader
- Compatible with storage layout: data/raw/news_by_day/<SYMBOL>/<YYYY-MM-DD>.json
- Each file expected to contain a top-level object with "items": [ ... ] (or a list)
- Each item may contain published_utc / published / timestamp fields. We parse them leniently.
- Returns a list of normalized dicts:
  { title, content, timestamp_utc, source, url, company_symbol, raw_data }
"""
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from dateutil import parser

from ..config.settings import STOCKBENCH_DATA_PATH

class StockBenchNewsLoader:
    def __init__(self, data_path: Optional[str] = None):
        # default to configured path
        self.data_path = data_path or STOCKBENCH_DATA_PATH

    def _parse_timestamp(self, ts: Any) -> Optional[datetime]:
        if not ts:
            return None
        if isinstance(ts, datetime):
            dt = ts
        else:
            try:
                dt = parser.isoparse(ts) if isinstance(ts, str) and ts.endswith("Z") else parser.parse(str(ts))
            except Exception:
                return None
        # Ensure we return a timezone-aware datetime in UTC
        if dt.tzinfo is None:
            # treat naive timestamps as UTC
            return dt.replace(tzinfo=timezone.utc)
        else:
            # convert to UTC
            return dt.astimezone(timezone.utc)
        
    def _ensure_aware_utc(self, dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _read_items_from_file(self, filepath: Path) -> List[Dict[str, Any]]:
        try:
            txt = filepath.read_text(encoding="utf-8")
            obj = json.loads(txt)
        except Exception:
            return []

        # object may be { "items": [...] } or a list itself
        raw_items = []
        if isinstance(obj, dict) and "items" in obj and isinstance(obj["items"], list):
            raw_items = obj["items"]
        elif isinstance(obj, list):
            raw_items = obj
        elif isinstance(obj, dict):
            # try to find any list values that look like items
            for v in obj.values():
                if isinstance(v, list):
                    raw_items = v
                    break
        else:
            return []

        normalized = []
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            # normalize common field names
            title = it.get("title") or it.get("headline") or it.get("event_name") or ""
            content = it.get("description") or it.get("content") or it.get("summary") or ""
            ts = it.get("published_utc") or it.get("published") or it.get("timestamp") or it.get("date") or it.get("published_at")
            source = it.get("source") or it.get("publisher") or it.get("api_source") or None
            url = it.get("url") or it.get("article_url") or it.get("link") or it.get("article_link")
            normalized.append({
                "title": title,
                "content": content,
                "timestamp_raw": ts,
                "timestamp_utc": None,  # filled after parsing
                "source": source,
                "url": url,
                "raw_data": it
            })
        return normalized

    def fetch_news(self, start_date: datetime, end_date: datetime, force_reload: bool = False) -> List[Dict[str, Any]]:
        """
        Scan data_path/<SYMBOL>/*.json and return normalized items whose timestamp falls within [start_date, end_date].
        start_date and end_date are naive or tz-aware datetimes - parser returns tz-aware if input had tz.
        """

        start_dt = self._ensure_aware_utc(start_date)
        end_dt = self._ensure_aware_utc(end_date)
        if start_dt is None or end_dt is None:
            return []
        
        base = Path(self.data_path)
        results: List[Dict[str, Any]] = []
        if not base.exists():
            return results

        # iterate company directories
        for company_dir in sorted(base.iterdir()):
            if not company_dir.is_dir():
                continue
            company = company_dir.name
            # read each json file under the company's dir
            for f in sorted(company_dir.glob("*.json")):
                items = self._read_items_from_file(f)
                if not items:
                    continue
                for it in items:
                    ts_raw = it.get("timestamp_raw")
                    dt = self._parse_timestamp(ts_raw)
                    if dt is None:
                        continue
                    # Make dt UTC-aware
                    dt = self._ensure_aware_utc(dt)
                    if dt is None:
                        continue
                    # now both dt and start_dt/end_dt are UTC-aware -> safe to compare
                    if start_dt <= dt <= end_dt:
                        it["timestamp_utc"] = dt.isoformat().replace("+00:00", "Z")
                        it["company_symbol"] = company
                        results.append({
                            "id": it["raw_data"].get("id") or None,
                            "source": it.get("source") or "stockbench",
                            "title": it.get("title") or "",
                            "content": it.get("content") or "",
                            "timestamp_utc": it.get("timestamp_utc"),
                            "company_symbol": it.get("company_symbol"),
                            "url": it.get("url"),
                            "raw_data": it.get("raw_data")
                        })
        return results