from datetime import datetime, timedelta
import logging
from typing import List, Optional, Dict, Any
import pandas as pd

from ..utils.data_models import EconomicEvent
from ..config.settings import ECON_EVENT_IMPORTANCE_THRESHOLD

class EconomicEventsCollector:
    """
    Economic Event Collector - Using the Ecocal library
    Alternative solution: If Ecocal is unsatisfactory, you can switch to other data sources.
    """
    
    def __init__(self, use_fallback: bool = False):
        self.use_fallback = use_fallback
        self.ecocal = None
        self.logger = logging.getLogger(__name__)
        
        if not use_fallback:
            self._init_ecocal()
    
    def _init_ecocal(self):
        """Initialize Ecocal library"""
        try:
            from ecocal import Calendar
            self.ecocal_cls = Calendar
            self.logger.info("ecocal library initialization successful")
        except ImportError:
            self.logger.warning("The ecocal library is not installed.")
            self.use_fallback = True
        except Exception as e:
            self.logger.error(f"ecocal initialization failed: {e}")
            self.use_fallback = True
    
    def fetch_events(self, 
                    start_date: datetime, 
                    end_date: datetime,
                    min_importance: int = 2,
                    countries: Optional[List[str]] = None) -> List[EconomicEvent]:
        """
       Get economic events within the specified date range.
        """
        if self.use_fallback or not hasattr(self, 'ecocal_cls'):
            return self._fetch_events_fallback(start_date, end_date, min_importance)
        return self._fetch_events_ecocal(start_date, end_date, min_importance, countries)
    
    def _fetch_events_ecocal(self, 
                           start_date: datetime, 
                           end_date: datetime,
                           min_importance: int,
                           countries: Optional[List[str]] = None) -> List[EconomicEvent]:
        """Use ecocal to fetch economic events"""
        try:
            
            cal = self.ecocal_cls(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
            df = cal.calendar
            if df is None or df.empty:
                self.logger.warning("ecocal returned no data")
                return []
            economic_events = []
            for _, row in df.iterrows():
                # ecocal fields: Id, Start, Name, Impact, Currency
                event_id = row.get('Id', '')
                event_name = row.get('Name', 'Unknown Event')
                event_date = row.get('Start')
                country = row.get('Currency', 'Unknown')
                importance = row.get('Impact', 'NONE')
                description = ''  
                # Impact string to fraction conversion
                impact_map = {'HIGH': 3, 'MEDIUM': 2, 'LOW': 1, 'NONE': 0}
                imp = impact_map.get(str(importance).upper(), 0)
                if imp < min_importance:
                    continue
                # Country filtering (approximated by currency field)
                if countries and country not in countries:
                    continue
                # Date parsing
                try:
                    if isinstance(event_date, str):
                       
                        try:
                            event_date = datetime.strptime(event_date[:10], '%m/%d/%Y')
                        except Exception:
                            event_date = datetime.strptime(event_date[:10], '%Y-%m-%d')
                    elif hasattr(event_date, 'to_pydatetime'):
                        event_date = event_date.to_pydatetime()
                except Exception:
                    continue
                event = EconomicEvent(
                    event_id=event_id or f"econ_{country}_{event_date.strftime('%Y%m%d')}_{abs(hash(event_name)) % 10000:04d}",
                    date=event_date,
                    event_name=event_name,
                    country=country,
                    importance=imp,
                    source="ecocal",
                    description=description
                )
                economic_events.append(event)
            self.logger.info(f"Retrieve {len(economic_events)} economic events from the economic database")
            return economic_events
        except Exception as e:
            self.logger.error(f"ecocal failed to retrieve events: {e}")
            return self._fetch_events_fallback(start_date, end_date, min_importance)
    
    def _parse_ecocal_event(self, 
                          event_data: Dict[str, Any],
                          min_importance: int,
                          countries: Optional[List[str]] = None) -> Optional[EconomicEvent]:
        """Pharse a single ecocal event dictionary into EconomicEvent"""
        try:
            # Adjust these fields according to the actual data structure of Ecocal
            # This is a sample mapping; it needs to be adjusted according to the actual situation
            # Extract event information
            event_name = event_data.get('event', 'Unknown Event')
            event_date_str = event_data.get('date', '')
            country = event_data.get('country', 'Unknown')
            importance = event_data.get('importance', 1)
            
            # Importance filtering
            if importance < min_importance:
                return None
            
            # Country filtering
            if countries and country not in countries:
                return None
            
            # Date parsing
            try:
                event_date = datetime.strptime(event_date_str, '%Y-%m-%d')
            except (ValueError, TypeError):
                self.logger.warning(f"Unable to resolve event date: {event_date_str}")
                return None
            
            # Construct EconomicEvent object
            event = EconomicEvent(
                event_id=f"econ_{country}_{event_date.strftime('%Y%m%d')}_{hash(event_name) % 10000:04d}",
                date=event_date,
                event_name=event_name,
                country=country,
                importance=importance,
                source="ecocal",
                description=event_data.get('description', '')
            )
            
            return event
            
        except Exception as e:
            self.logger.debug(f"Failed to resolve ecocal event: {e}")
            return None
    
    def _fetch_events_fallback(self, 
                             start_date: datetime, 
                             end_date: datetime,
                             min_importance: int) -> List[EconomicEvent]:
        """
        Alternative solutions for obtaining economic events
        """
        self.logger.info("Useing fallback method to fetch economic events")
       
        return []

# Test
def test_ecocal_integration():
   
    import logging
    logging.basicConfig(level=logging.INFO)
    
    collector = EconomicEventsCollector()
    
    # Test events over the last 30 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    events = collector.fetch_events(start_date, end_date, min_importance=2)
    
    print(f"Obtain {len(events)} economic events from Ecocal:")
    for event in events[:5]:  
        print(f"  {event.date.strftime('%Y-%m-%d')}: {event.event_name} ({event.country}, Importance:{event.importance})")

if __name__ == "__main__":
    test_ecocal_integration()