from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
import re
from datetime import datetime, timedelta
import logging
import json
from pathlib import Path

from ..utils.data_models import EconomicEvent
from ..config.settings import FOMC_URL, OUTPUTS_DIR


class FOMCScraper:
    """A robust FOMC calendar scraper with intelligent parsing and caching."""

    CACHE_FILE = Path(OUTPUTS_DIR) / "fomc_cache.json"
    CACHE_EXPIRY_DAYS = 1  # Cache expires after 1 day

    def __init__(self):
        self.base_url = FOMC_URL
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
        self.logger = logging.getLogger(__name__)

    def _read_cache(self) -> Dict:
        try:
            if not self.CACHE_FILE.exists():
                return {}
            with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Validate expiry
            ts = data.get('_fetched_at')
            if not ts:
                return {}
            fetched = date_parser.parse(ts)
            if datetime.now() - fetched > timedelta(days=self.CACHE_EXPIRY_DAYS):
                return {}
            return data.get('events', {})
        except Exception as e:
            self.logger.debug(f"Failed to read FOMC cache: {e}")
            return {}

    def _write_cache(self, events: List[Dict]):
        try:
            payload = {
                '_fetched_at': datetime.now().isoformat(),
                'events': events
            }
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.debug(f"Failed to write FOMC cache: {e}")

    def fetch_fomc_schedule(self) -> List[EconomicEvent]:
        """Fetches and parses the FOMC schedule page, returns list of EconomicEvent"""
        # Try cache first
        cached = self._read_cache()
        if cached:
            self.logger.info("Loaded FOMC schedule from cache")
            return [self._dict_to_event(e) for e in cached]

        try:
            resp = self.session.get(self.base_url, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            self.logger.error(f"Failed to fetch FOMC page: {e}")
            # If cache available but expired, try to return it as a fallback
            if cached:
                return [self._dict_to_event(e) for e in cached]
            return []

        try:
            soup = BeautifulSoup(resp.text, 'html.parser')

            # The FOMC page contains meeting schedule tables. We'll search for dates and meeting names.
            events: List[Dict] = []

            # Find list items or table rows that mention 'FOMC' or 'Federal Open Market Committee'
            tables = soup.find_all('table')
            for table in tables:
                txt = table.get_text(separator=' ').lower()
                if 'fomc' in txt or 'federal open market committee' in txt or 'monetary policy' in txt:
                    for row in table.find_all('tr'):
                        cols = [c.get_text(separator=' ').strip() for c in row.find_all(['td', 'th'])]
                        if not cols:
                            continue
                        joined = ' '.join(cols)
                        parsed = self._extract_event_from_text(joined)
                        if parsed:
                            events.append(parsed)

            # Fallback: scan for links that look like meeting announcements
            if not events:
                for a in soup.find_all('a', href=True):
                    text = a.get_text(separator=' ').strip()
                    href = a['href']
                    if re.search(r'(fomc|federal open market committee|monetary policy)', text, flags=re.I) or re.search(r'fomc', href, flags=re.I):
                        parsed = self._extract_event_from_text(text)
                        if parsed:
                            events.append(parsed)

            # Deduplicate and normalize
            normalized = self._normalize_events(events)
            # Write cache
            self._write_cache([self._event_to_dict(e) for e in normalized])

            return normalized
        except Exception as e:
            self.logger.error(f"Failed to parse FOMC page: {e}")
            return []

    def _extract_event_from_text(self, text: str) -> Optional[Dict]:
        """Try to extract a date and title from free text."""
        try:
            t = re.sub(r'\s+', ' ', text)

            # Try to find year first
            year_match = re.search(r'\b(20\d{2})\b', t)
            year = year_match.group(1) if year_match else None

            # Try to parse dates with month names
            month_names = r'(Jan(uary)?|Feb(ruary)?|Mar(ch)?|Apr(il)?|May|Jun(e)?|Jul(y)?|Aug(ust)?|Sep(tember)?|Oct(ober)?|Nov(ember)?|Dec(ember)?)'
            date_pattern = re.compile(rf'({month_names} [0-3]?\d(?:-[0-3]?\d)?(?:,? \d{{4}})?)', flags=re.I)
            m = date_pattern.search(t)
            if m:
                date_text = m.group(1)
                if year and str(year) not in date_text:
                    date_text = f"{date_text}, {year}"
                date_text = re.sub(r'-\d+', '', date_text)
                try:
                    dt = date_parser.parse(date_text, fuzzy=True)
                except Exception:
                    return None

                title = t.replace(m.group(0), '').strip(' -,:;')
                title = title if title else 'FOMC Meeting'

                return {
                    'event_id': f"fomc_{dt.strftime('%Y%m%d')}",
                    'date': dt,
                    'event_name': title,
                    'country': 'US',
                    'importance': 3,
                    'source': 'federalreserve.gov',
                    'description': title
                }

            # If no month-name match, try ISO date like YYYY-MM-DD
            iso_match = re.search(r'(20\d{2}-\d{2}-\d{2})', t)
            if iso_match:
                dt = date_parser.parse(iso_match.group(1))
                title = t.replace(iso_match.group(1), '').strip(' -,:;') or 'FOMC Meeting'
                return {
                    'event_id': f"fomc_{dt.strftime('%Y%m%d')}",
                    'date': dt,
                    'event_name': title,
                    'country': 'US',
                    'importance': 3,
                    'source': 'federalreserve.gov',
                    'description': title
                }

            return None
        except Exception as e:
            self.logger.debug(f"Error extracting event from text: {e} -- text was: {text}")
            return None

    def _normalize_events(self, events: List[Dict]) -> List[EconomicEvent]:
        seen = set()
        out: List[EconomicEvent] = []
        for e in events:
            try:
                dt = e.get('date')
                if isinstance(dt, str):
                    dt = date_parser.parse(dt)
                if not isinstance(dt, datetime):
                    continue
                key = (e.get('event_name', ''), dt.strftime('%Y%m%d'))
                if key in seen:
                    continue
                seen.add(key)
                ev = EconomicEvent(
                    event_id=e.get('event_id') or f"fomc_{dt.strftime('%Y%m%d')}",
                    date=dt,
                    event_name=e.get('event_name', 'FOMC Meeting'),
                    country=e.get('country', 'US'),
                    importance=int(e.get('importance', 3)),
                    source=e.get('source', 'federalreserve.gov'),
                    description=e.get('description', '')
                )
                out.append(ev)
            except Exception as ex:
                self.logger.debug(f"Failed normalizing event {e}: {ex}")
                continue
        out.sort(key=lambda x: x.date)
        return out

    def _event_to_dict(self, ev: EconomicEvent) -> Dict:
        return {
            'event_id': ev.event_id,
            'date': ev.date.isoformat(),
            'event_name': ev.event_name,
            'country': ev.country,
            'importance': ev.importance,
            'source': ev.source,
            'description': ev.description
        }

    def _dict_to_event(self, d: Dict) -> EconomicEvent:
        dt = d.get('date')
        if isinstance(dt, str):
            dt = date_parser.parse(dt)
        return EconomicEvent(
            event_id=d.get('event_id', f"fomc_{dt.strftime('%Y%m%d')}"),
            date=dt,
            event_name=d.get('event_name', 'FOMC Meeting'),
            country=d.get('country', 'US'),
            importance=int(d.get('importance', 3)),
            source=d.get('source', 'federalreserve.gov'),
            description=d.get('description', '')
        )
