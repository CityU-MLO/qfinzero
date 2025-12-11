from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

class ImportanceLevel(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3

@dataclass
class NewsItem:

    id: str
    source: str
    title: str
    content: str
    timestamp: datetime
    company_symbol: Optional[str] = None
    url: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        
        return {
            'id': self.id,
            'source': self.source,
            'title': self.title,
            'content': self.content,
            'timestamp': self.timestamp.isoformat(),
            'company_symbol': self.company_symbol,
            'url': self.url,
            'raw_data': self.raw_data
        }

@dataclass
class EconomicEvent:

    event_id: str
    date: datetime
    event_name: str
    country: str
    importance: int
    source: str
    description: Optional[str] = None
    actual_value: Optional[float] = None
    forecast_value: Optional[float] = None
    previous_value: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:

        return {
            'event_id': self.event_id,
            'date': self.date.isoformat(),
            'event_name': self.event_name,
            'country': self.country,
            'importance': self.importance,
            'source': self.source,
            'description': self.description,
            'actual_value': self.actual_value,
            'forecast_value': self.forecast_value,
            'previous_value': self.previous_value
        }

@dataclass
class TradingDayBundle:
    """Trading Day Data Packet"""
    trading_date: datetime
    news_items: List[NewsItem] = field(default_factory=list)
    economic_events: List[EconomicEvent] = field(default_factory=list)
    has_major_events: bool = False
    
    def add_news_item(self, news_item: NewsItem):

        self.news_items.append(news_item)
    
    def add_economic_event(self, event: EconomicEvent):

        self.economic_events.append(event)
        # If there are high-importance events, mark them as major events.
        if event.importance >= 3:
            self.has_major_events = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'trading_date': self.trading_date.isoformat(),
            'news_count': len(self.news_items),
            'events_count': len(self.economic_events),
            'has_major_events': self.has_major_events,
            'news_items': [item.to_dict() for item in self.news_items],
            'economic_events': [event.to_dict() for event in self.economic_events]
        }