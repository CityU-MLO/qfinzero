use std::collections::HashMap;
use std::path::Path;

use duckdb::Connection;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum DividendError {
    #[error("duckdb error: {0}")]
    Duckdb(#[from] duckdb::Error),
}

#[derive(Debug, Clone)]
pub struct DividendEvent {
    pub ex_date_days: i32,
    pub amount: f64,
}

#[derive(Debug)]
pub struct DividendCalendar {
    events: HashMap<String, Vec<DividendEvent>>,
}

impl DividendCalendar {
    pub fn empty() -> Self {
        Self {
            events: HashMap::new(),
        }
    }

    /// Load from a Parquet file with columns: ticker (Utf8), ex_dividend_date (Date32), amount (Float64).
    pub fn load(path: &Path) -> Result<Self, DividendError> {
        let conn = Connection::open_in_memory()?;
        let path_literal = path.to_string_lossy().replace('\'', "''");
        let sql = format!(
            "SELECT ticker, \
                    epoch(ex_dividend_date::TIMESTAMP) / 86400 AS ex_date_days, \
                    amount::DOUBLE AS amount \
             FROM read_parquet('{}') \
             ORDER BY ticker, ex_dividend_date",
            path_literal
        );

        let mut stmt = conn.prepare(&sql)?;
        let mut events: HashMap<String, Vec<DividendEvent>> = HashMap::new();

        let rows = stmt.query_map([], |row| {
            let ticker: String = row.get(0)?;
            let ex_date_days: i64 = row.get(1)?;
            let amount: f64 = row.get(2)?;
            Ok((ticker, ex_date_days as i32, amount))
        })?;

        for row in rows {
            let (ticker, ex_date_days, amount) = row?;
            events.entry(ticker).or_default().push(DividendEvent {
                ex_date_days,
                amount,
            });
        }

        Ok(Self { events })
    }

    /// Build from a flat list of (ticker, event) pairs. Sorts internally.
    pub fn from_events(items: Vec<(String, DividendEvent)>) -> Self {
        let mut events: HashMap<String, Vec<DividendEvent>> = HashMap::new();
        for (ticker, event) in items {
            events.entry(ticker).or_default().push(event);
        }
        for v in events.values_mut() {
            v.sort_by_key(|e| e.ex_date_days);
        }
        Self { events }
    }

    /// Check whether the calendar has any dividend data for the given ticker.
    pub fn has_dividends(&self, ticker: &str) -> bool {
        self.events
            .get(ticker)
            .is_some_and(|v| !v.is_empty())
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

        if start >= end {
            return (0.0, 0);
        }

        let slice = &events[start..end];
        let mut pv_sum = 0.0;
        for e in slice {
            let t_i = (e.ex_date_days - obs_date_days) as f64 / 365.0;
            pv_sum += e.amount * (-r * t_i).exp();
        }
        (pv_sum, slice.len())
    }
}
