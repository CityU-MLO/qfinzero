use upq_service::splits::SplitCalendar;
use std::io::Write;
use tempfile::NamedTempFile;

#[test]
fn test_load_splits_json() -> Result<(), Box<dyn std::error::Error>> {
    let json = r#"{"splits":[
        {"ticker":"NVDA","effective_date":"2024-06-10","ratio":10},
        {"ticker":"TSLA","effective_date":"2022-08-25","ratio":3}
    ]}"#;
    let mut f = NamedTempFile::new()?;
    f.write_all(json.as_bytes())?;

    let cal = SplitCalendar::load(f.path())?;
    assert!(cal.has_splits("NVDA"));
    assert!(cal.has_splits("TSLA"));
    assert!(!cal.has_splits("AAPL"));
    Ok(())
}

#[test]
fn test_cumulative_factor_before_split() -> Result<(), Box<dyn std::error::Error>> {
    let json = r#"{"splits":[
        {"ticker":"NVDA","effective_date":"2024-06-10","ratio":10}
    ]}"#;
    let mut f = NamedTempFile::new()?;
    f.write_all(json.as_bytes())?;

    let cal = SplitCalendar::load(f.path())?;
    let factor = cal.adjustment_factor("NVDA", "2024-06-07");
    assert!((factor - 0.1).abs() < 1e-9, "pre-split factor should be 0.1, got {}", factor);
    Ok(())
}

#[test]
fn test_cumulative_factor_after_split() -> Result<(), Box<dyn std::error::Error>> {
    let json = r#"{"splits":[
        {"ticker":"NVDA","effective_date":"2024-06-10","ratio":10}
    ]}"#;
    let mut f = NamedTempFile::new()?;
    f.write_all(json.as_bytes())?;

    let cal = SplitCalendar::load(f.path())?;
    let factor = cal.adjustment_factor("NVDA", "2024-06-10");
    assert!((factor - 1.0).abs() < 1e-9, "post-split factor should be 1.0, got {}", factor);
    Ok(())
}

#[test]
fn test_no_splits_returns_factor_one() -> Result<(), Box<dyn std::error::Error>> {
    let json = r#"{"splits":[]}"#;
    let mut f = NamedTempFile::new()?;
    f.write_all(json.as_bytes())?;

    let cal = SplitCalendar::load(f.path())?;
    let factor = cal.adjustment_factor("AAPL", "2024-01-01");
    assert!((factor - 1.0).abs() < 1e-9);
    Ok(())
}

#[test]
fn test_adjust_ohlcv() -> Result<(), Box<dyn std::error::Error>> {
    let json = r#"{"splits":[
        {"ticker":"NVDA","effective_date":"2024-06-10","ratio":10}
    ]}"#;
    let mut f = NamedTempFile::new()?;
    f.write_all(json.as_bytes())?;

    let cal = SplitCalendar::load(f.path())?;
    let (o, h, l, c, v) = cal.adjust_ohlcv("NVDA", "2024-06-07", 1200.0, 1220.0, 1180.0, 1210.0, 5_000_000);
    assert!((c - 121.0).abs() < 0.01, "close should be 121.0, got {}", c);
    assert!((o - 120.0).abs() < 0.01);
    assert!((h - 122.0).abs() < 0.01);
    assert!((l - 118.0).abs() < 0.01);
    assert_eq!(v, 50_000_000, "volume should be 10x");
    Ok(())
}

#[test]
fn test_empty_calendar_factor_is_one() {
    let cal = SplitCalendar::empty();
    let factor = cal.adjustment_factor("NVDA", "2024-06-07");
    assert!((factor - 1.0).abs() < 1e-9);
}

#[test]
fn test_empty_calendar_has_no_splits() {
    let cal = SplitCalendar::empty();
    assert!(!cal.has_splits("NVDA"));
}

#[test]
fn test_post_split_ohlcv_unchanged() -> Result<(), Box<dyn std::error::Error>> {
    let json = r#"{"splits":[
        {"ticker":"NVDA","effective_date":"2024-06-10","ratio":10}
    ]}"#;
    let mut f = NamedTempFile::new()?;
    f.write_all(json.as_bytes())?;

    let cal = SplitCalendar::load(f.path())?;
    let (o, _h, _l, c, v) = cal.adjust_ohlcv("NVDA", "2024-06-10", 120.0, 122.0, 118.0, 121.0, 50_000_000);
    assert!((c - 121.0).abs() < 0.01, "post-split close should be unchanged");
    assert!((o - 120.0).abs() < 0.01);
    assert_eq!(v, 50_000_000, "post-split volume should be unchanged");
    Ok(())
}
