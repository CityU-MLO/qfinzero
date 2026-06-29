//! Unified corporate-actions calendar + on-read price/volume adjustment.
//!
//! Loads `corporate_actions/corporate_actions.parquet` (produced by the
//! `qfz-data` pipeline) with columns:
//!   symbol, ex_date, split_ratio, dividend_cash, div_price_ratio, currency, source
//!
//! Adjustment is **forward** (most recent bar unchanged, history rescaled) and
//! purely multiplicative on read — the dividend price ratio is precomputed by the
//! pipeline as `1 - cash/close_prev`, so no query-time close lookup is needed.
//!
//! For a bar at `trade_date`, accumulate over every event with `ex_date > trade_date`:
//!   * split : price *= 1/split_ratio ;  volume *= split_ratio
//!   * total : additionally price *= div_price_ratio   (volume unchanged by dividends)
//!
//! A legacy integer-ratio `splits.json` is still honoured as a fallback when no
//! corporate-actions parquet is present.

use std::collections::HashMap;
use std::path::Path;

use duckdb::Connection;
use thiserror::Error;

use crate::splits::SplitCalendar;

#[derive(Debug, Error)]
pub enum CorporateActionError {
    #[error("duckdb error: {0}")]
    Duckdb(#[from] duckdb::Error),
}

/// Price-adjustment mode requested by a client.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AdjustMode {
    /// Raw / as-traded prints (default).
    None,
    /// Split-adjusted only.
    Split,
    /// Split- and dividend-adjusted (total return).
    Total,
}

impl AdjustMode {
    pub fn parse(value: Option<&str>) -> Result<Self, String> {
        match value.map(|s| s.trim().to_ascii_lowercase()).as_deref() {
            None | Some("") | Some("none") | Some("raw") => Ok(AdjustMode::None),
            Some("split") | Some("splits") => Ok(AdjustMode::Split),
            Some("total") | Some("all") | Some("forward") => Ok(AdjustMode::Total),
            Some(other) => Err(format!(
                "adjust must be one of none|split|total (got '{other}')"
            )),
        }
    }
}

#[derive(Debug, Clone)]
struct CaEvent {
    ex_date: String, // YYYY-MM-DD (lexicographically comparable)
    split_ratio: f64,
    div_price_ratio: f64,
}

/// Per-symbol corporate-action events, sorted by ex_date ascending.
#[derive(Debug)]
pub struct CorporateActions {
    events: HashMap<String, Vec<CaEvent>>,
}

impl CorporateActions {
    pub fn empty() -> Self {
        Self {
            events: HashMap::new(),
        }
    }

    /// Resolve from a storage root: prefer the corporate-actions parquet, else a
    /// legacy `splits.json`, else empty.
    pub fn load_from_storage(storage_root: &Path) -> Self {
        let parquet = storage_root.join("corporate_actions/corporate_actions.parquet");
        if parquet.is_file() {
            match Self::load_parquet(&parquet) {
                Ok(ca) => {
                    tracing::info!(path = %parquet.display(), symbols = ca.events.len(),
                        "loaded corporate actions");
                    return ca;
                }
                Err(e) => tracing::warn!(error = %e, "failed to load corporate actions parquet"),
            }
        }
        let splits_json = storage_root.join("splits.json");
        if splits_json.is_file() {
            if let Ok(sc) = SplitCalendar::load(&splits_json) {
                tracing::info!("loaded legacy splits.json as corporate actions fallback");
                return Self::from_split_calendar(&sc);
            }
        }
        tracing::info!("no corporate actions found, adjustments disabled");
        Self::empty()
    }

    fn load_parquet(path: &Path) -> Result<Self, CorporateActionError> {
        let conn = Connection::open_in_memory()?;
        let path_literal = path.to_string_lossy().replace('\'', "''");
        let sql = format!(
            "SELECT symbol, \
                    strftime(ex_date, '%Y-%m-%d') AS ex_date, \
                    split_ratio::DOUBLE AS split_ratio, \
                    div_price_ratio::DOUBLE AS div_price_ratio \
             FROM read_parquet('{path_literal}') \
             ORDER BY symbol, ex_date"
        );
        let mut stmt = conn.prepare(&sql)?;
        let mut events: HashMap<String, Vec<CaEvent>> = HashMap::new();
        let rows = stmt.query_map([], |row| {
            let symbol: String = row.get(0)?;
            let ex_date: String = row.get(1)?;
            let split_ratio: f64 = row.get(2)?;
            let div_price_ratio: f64 = row.get(3)?;
            Ok((symbol, ex_date, split_ratio, div_price_ratio))
        })?;
        for row in rows {
            let (symbol, ex_date, split_ratio, div_price_ratio) = row?;
            events.entry(symbol).or_default().push(CaEvent {
                ex_date,
                split_ratio,
                div_price_ratio,
            });
        }
        Ok(Self { events })
    }

    fn from_split_calendar(sc: &SplitCalendar) -> Self {
        // Re-derive float split events from the legacy integer calendar by probing
        // its public adjustment_factor across event boundaries is awkward; instead
        // rely on the parquet path in practice. The fallback only needs to keep
        // split semantics working, so we reconstruct from the calendar's behaviour.
        let mut events: HashMap<String, Vec<CaEvent>> = HashMap::new();
        for (ticker, evs) in sc.iter_events() {
            for (ex_date, ratio) in evs {
                events.entry(ticker.clone()).or_default().push(CaEvent {
                    ex_date,
                    split_ratio: ratio,
                    div_price_ratio: 1.0,
                });
            }
        }
        Self { events }
    }

    pub fn has_events(&self, symbol: &str) -> bool {
        self.events.get(symbol).is_some_and(|v| !v.is_empty())
    }

    /// Forward (price_factor, volume_factor) for a bar at `trade_date`.
    pub fn factors(&self, symbol: &str, trade_date: &str, mode: AdjustMode) -> (f64, f64) {
        if mode == AdjustMode::None {
            return (1.0, 1.0);
        }
        let events = match self.events.get(symbol) {
            Some(e) => e,
            None => return (1.0, 1.0),
        };
        let mut price_factor = 1.0_f64;
        let mut vol_factor = 1.0_f64;
        for e in events {
            if trade_date < e.ex_date.as_str() {
                if e.split_ratio > 0.0 && (e.split_ratio - 1.0).abs() > 1e-12 {
                    price_factor /= e.split_ratio;
                    vol_factor *= e.split_ratio;
                }
                if mode == AdjustMode::Total
                    && e.div_price_ratio > 0.0
                    && (e.div_price_ratio - 1.0).abs() > 1e-12
                {
                    price_factor *= e.div_price_ratio;
                }
            }
        }
        (price_factor, vol_factor)
    }
}
