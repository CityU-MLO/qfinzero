//! Point-in-time caps ("as of").
//!
//! Every data endpoint accepts an optional `as_of` (ISO datetime, UTC unless it
//! carries an offset, or integer nanoseconds). The service may also be started
//! with `UPQ_AS_OF` as a hard ceiling; the effective cap is the earlier of the
//! two. Nothing that was not yet final at the cap is returned:
//!
//! * a minute bar `[t, t+60s)` is visible once `t + 60s <= as_of`;
//! * a stock daily bar for date D once `as_of >= D 16:00 ET`;
//! * an option daily bar (and the end-of-day chain) once `as_of >= D 16:15 ET`;
//! * rates and dividends up to the trading date of `as_of`.

use chrono::{DateTime, Duration, NaiveDate, NaiveDateTime, NaiveTime, TimeZone, Utc};
use chrono_tz::America::New_York;

pub const NS_PER_MIN: i64 = 60_000_000_000;

/// 16:00 ET: a stock daily bar is final.
pub const STOCK_CLOSE: (u32, u32) = (16, 0);
/// 16:15 ET: an option daily bar is final (index/ETF options trade to 16:15).
pub const OPTION_CLOSE: (u32, u32) = (16, 15);

/// Parse an `as_of` value: integer nanoseconds or an ISO datetime.
pub fn parse_as_of(input: &str) -> Result<i64, &'static str> {
    let s = input.trim();
    if s.is_empty() {
        return Err("as_of must not be empty");
    }
    if let Ok(ns) = s.parse::<i64>() {
        return Ok(ns);
    }
    if let Ok(dt) = DateTime::parse_from_rfc3339(s) {
        return dt
            .with_timezone(&Utc)
            .timestamp_nanos_opt()
            .ok_or("as_of out of range");
    }
    let bare = s.strip_suffix('Z').unwrap_or(s);
    for fmt in ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"] {
        if let Ok(ndt) = NaiveDateTime::parse_from_str(bare, fmt) {
            return ndt.and_utc().timestamp_nanos_opt().ok_or("as_of out of range");
        }
    }
    Err("as_of must be an ISO datetime or integer nanoseconds")
}

/// The effective cap: the earlier of the service ceiling and the request value.
pub fn resolve(ceiling: Option<i64>, requested: Option<&str>) -> Result<Option<i64>, &'static str> {
    let req = match requested {
        Some(v) if !v.trim().is_empty() => Some(parse_as_of(v)?),
        _ => None,
    };
    Ok(match (ceiling, req) {
        (Some(a), Some(b)) => Some(a.min(b)),
        (a, b) => a.or(b),
    })
}

/// Read `UPQ_AS_OF`. An unparsable value fails closed (nothing is visible).
pub fn ceiling_from_env() -> Option<i64> {
    let raw = std::env::var("UPQ_AS_OF").ok()?;
    match parse_as_of(&raw) {
        Ok(ns) => Some(ns),
        Err(e) => {
            tracing::error!(value = %raw, error = e, "invalid UPQ_AS_OF; serving no data");
            Some(i64::MIN)
        }
    }
}

/// Latest `window_start` a minute bar may have to be visible at `as_of`.
pub fn minute_cap(as_of: i64) -> i64 {
    as_of.saturating_sub(NS_PER_MIN)
}

/// ET calendar date of a timestamp.
pub fn et_date(ns: i64) -> Option<NaiveDate> {
    let secs = ns.div_euclid(1_000_000_000);
    let utc = DateTime::from_timestamp(secs, 0)?;
    Some(utc.with_timezone(&New_York).date_naive())
}

/// Last date whose daily bar is final at `as_of`, given the ET close time.
pub fn daily_cap_date(as_of: i64, close: (u32, u32)) -> Option<NaiveDate> {
    let secs = as_of.div_euclid(1_000_000_000);
    let et = DateTime::from_timestamp(secs, 0)?.with_timezone(&New_York);
    let close_t = NaiveTime::from_hms_opt(close.0, close.1, 0)?;
    if et.time() >= close_t {
        Some(et.date_naive())
    } else {
        et.date_naive().checked_sub_signed(Duration::days(1))
    }
}

/// UTC nanoseconds of 00:00 ET on `date` (the `window_start` of option day bars).
pub fn et_midnight_ns(date: NaiveDate) -> Option<i64> {
    let ndt = date.and_hms_opt(0, 0, 0)?;
    New_York
        .from_local_datetime(&ndt)
        .earliest()?
        .with_timezone(&Utc)
        .timestamp_nanos_opt()
}

/// ET date strings bounding a `[start_ns, end_ns]` window, for partition pruning.
/// Partitions are ET trade dates, so pruning on the UTC date (as before) could
/// skip the bars of 19:00-20:00 ET in winter.
pub fn et_date_bounds(start_ns: i64, end_ns: i64) -> Option<(String, String)> {
    let a = et_date(start_ns)?;
    let b = et_date(end_ns)?;
    Some((a.format("%Y-%m-%d").to_string(), b.format("%Y-%m-%d").to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ns(s: &str) -> i64 {
        parse_as_of(s).unwrap_or(0)
    }

    #[test]
    fn parses_iso_offsets_and_nanos() {
        assert_eq!(ns("2025-01-02T14:30:00Z"), 1_735_828_200_000_000_000);
        assert_eq!(ns("2025-01-02T09:30:00-05:00"), 1_735_828_200_000_000_000);
        assert_eq!(ns("2025-01-02T14:30:00"), 1_735_828_200_000_000_000);
        assert_eq!(ns("1735828200000000000"), 1_735_828_200_000_000_000);
        assert!(parse_as_of("yesterday").is_err());
    }

    #[test]
    fn resolve_takes_the_earlier_cap() {
        assert_eq!(resolve(Some(5), Some("9")), Ok(Some(5)));
        assert_eq!(resolve(Some(9), Some("5")), Ok(Some(5)));
        assert_eq!(resolve(None, Some("5")), Ok(Some(5)));
        assert_eq!(resolve(Some(5), None), Ok(Some(5)));
        assert_eq!(resolve(None, None), Ok(None));
    }

    #[test]
    fn daily_bars_become_visible_after_the_close() {
        let d = |s: &str| NaiveDate::parse_from_str(s, "%Y-%m-%d").ok();
        // 15:59 ET -> yesterday's bar is the latest final one
        assert_eq!(daily_cap_date(ns("2025-01-02T20:59:00Z"), STOCK_CLOSE), d("2025-01-01"));
        assert_eq!(daily_cap_date(ns("2025-01-02T21:00:00Z"), STOCK_CLOSE), d("2025-01-02"));
        assert_eq!(daily_cap_date(ns("2025-01-02T21:00:00Z"), OPTION_CLOSE), d("2025-01-01"));
        assert_eq!(daily_cap_date(ns("2025-06-02T20:15:00Z"), OPTION_CLOSE), d("2025-06-02"));
    }

    #[test]
    fn minute_bar_needs_its_full_minute() {
        let t = ns("2025-01-02T14:30:00Z");
        assert_eq!(minute_cap(t + NS_PER_MIN), t);
    }

    #[test]
    fn et_bounds_cover_winter_post_market() {
        // 19:30 ET on 2025-01-02 is 00:30 UTC on 2025-01-03
        let t = ns("2025-01-03T00:30:00Z");
        assert_eq!(
            et_date_bounds(t, t),
            Some(("2025-01-02".to_string(), "2025-01-02".to_string()))
        );
        let midnight = NaiveDate::from_ymd_opt(2026, 8, 21).and_then(et_midnight_ns);
        assert_eq!(midnight, Some(1_787_284_800_000_000_000));
    }
}
