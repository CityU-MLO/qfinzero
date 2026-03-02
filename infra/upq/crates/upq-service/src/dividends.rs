use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct DividendEvent {
    pub ex_date_days: i32,
    pub amount: f64,
}

pub struct DividendCalendar {
    events: HashMap<String, Vec<DividendEvent>>,
}

impl DividendCalendar {
    pub fn empty() -> Self {
        Self {
            events: HashMap::new(),
        }
    }

    /// Build from a flat list of (ticker, event) pairs. Sorts internally.
    pub fn from_events(mut items: Vec<(String, DividendEvent)>) -> Self {
        let mut events: HashMap<String, Vec<DividendEvent>> = HashMap::new();
        for (ticker, event) in items.drain(..) {
            events.entry(ticker).or_default().push(event);
        }
        for v in events.values_mut() {
            v.sort_by_key(|e| e.ex_date_days);
        }
        Self { events }
    }

    /// Sum of present values of dividends where ex_date in (obs_date_days, expiry_days].
    /// Returns (pv_sum, dividend_count).
    pub fn pv_dividends(
        &self,
        ticker: &str,
        obs_date_days: i32,
        expiry_days: i32,
        r: f64,
    ) -> (f64, usize) {
        let events = match self.events.get(ticker) {
            Some(e) => e,
            None => return (0.0, 0),
        };
        let start = events.partition_point(|e| e.ex_date_days <= obs_date_days);
        let end = events.partition_point(|e| e.ex_date_days <= expiry_days);

        let slice = &events[start..end];
        let mut pv_sum = 0.0;
        for e in slice {
            let t_i = (e.ex_date_days - obs_date_days) as f64 / 365.0;
            pv_sum += e.amount * (-r * t_i).exp();
        }
        (pv_sum, slice.len())
    }
}
