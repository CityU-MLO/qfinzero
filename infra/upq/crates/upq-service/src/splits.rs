use std::collections::HashMap;
use std::path::Path;

use serde::Deserialize;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SplitError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Deserialize)]
struct SplitEntry {
    ticker: String,
    effective_date: String, // YYYY-MM-DD
    ratio: u32,             // e.g. 10 for 10:1
}

#[derive(Debug, Deserialize)]
struct SplitsFile {
    splits: Vec<SplitEntry>,
}

#[derive(Debug, Clone)]
struct SplitEvent {
    effective_date: String,
    ratio: u32,
}

/// Holds stock-split metadata and applies on-read price adjustments.
/// Splits are stored per-ticker sorted by effective_date ascending.
#[derive(Debug)]
pub struct SplitCalendar {
    events: HashMap<String, Vec<SplitEvent>>,
}

impl SplitCalendar {
    pub fn empty() -> Self {
        Self {
            events: HashMap::new(),
        }
    }

    pub fn load(path: &Path) -> Result<Self, SplitError> {
        let content = std::fs::read_to_string(path)?;
        let file: SplitsFile = serde_json::from_str(&content)?;

        let mut events: HashMap<String, Vec<SplitEvent>> = HashMap::new();
        for entry in file.splits {
            events.entry(entry.ticker).or_default().push(SplitEvent {
                effective_date: entry.effective_date,
                ratio: entry.ratio,
            });
        }
        // Sort each ticker's splits by date ascending
        for v in events.values_mut() {
            v.sort_by(|a, b| a.effective_date.cmp(&b.effective_date));
        }

        Ok(Self { events })
    }

    pub fn has_splits(&self, ticker: &str) -> bool {
        self.events.get(ticker).is_some_and(|v| !v.is_empty())
    }

    /// Expose events as (ticker, [(effective_date, ratio_as_f64)]) for conversion
    /// into the unified corporate-actions calendar (legacy fallback).
    pub fn iter_events(&self) -> Vec<(String, Vec<(String, f64)>)> {
        self.events
            .iter()
            .map(|(ticker, evs)| {
                (
                    ticker.clone(),
                    evs.iter()
                        .map(|e| (e.effective_date.clone(), e.ratio as f64))
                        .collect(),
                )
            })
            .collect()
    }

    /// Returns the price adjustment factor for a given trade_date.
    /// Factor < 1.0 means the price needs to be divided (pre-split data).
    /// Factor = 1.0 means no adjustment needed.
    ///
    /// For a 10:1 split on 2024-06-10:
    ///   trade_date < 2024-06-10 → factor = 1/10 = 0.1
    ///   trade_date >= 2024-06-10 → factor = 1.0
    pub fn adjustment_factor(&self, ticker: &str, trade_date: &str) -> f64 {
        let splits = match self.events.get(ticker) {
            Some(v) => v,
            None => return 1.0,
        };

        let mut factor = 1.0;
        for split in splits {
            if trade_date < split.effective_date.as_str() {
                factor /= split.ratio as f64;
            }
        }
        factor
    }

    /// Adjust OHLCV values for a given trade_date.
    /// Returns (open, high, low, close, volume) adjusted.
    pub fn adjust_ohlcv(
        &self,
        ticker: &str,
        trade_date: &str,
        open: f64,
        high: f64,
        low: f64,
        close: f64,
        volume: i64,
    ) -> (f64, f64, f64, f64, i64) {
        let factor = self.adjustment_factor(ticker, trade_date);
        if (factor - 1.0).abs() < 1e-12 {
            return (open, high, low, close, volume);
        }
        let vol_factor = (1.0 / factor).round() as i64;
        (
            open * factor,
            high * factor,
            low * factor,
            close * factor,
            volume * vol_factor,
        )
    }
}
