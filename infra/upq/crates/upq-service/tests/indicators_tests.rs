use upq_service::indicators::{parse_indicators, Indicator, max_lookback, compute_indicators};
use serde_json::json;

#[test]
fn test_parse_valid_indicators() {
    let result = parse_indicators("ma_5, EMA_12, macd").unwrap();
    assert_eq!(result, vec![
        Indicator::Ma(5),
        Indicator::Ema(12),
        Indicator::Macd,
    ]);
}

#[test]
fn test_parse_deduplicates() {
    let result = parse_indicators("ma_5,ma_5,MA_5").unwrap();
    assert_eq!(result, vec![Indicator::Ma(5)]);
}

#[test]
fn test_parse_invalid_indicator() {
    assert!(parse_indicators("rsi_14").is_err());
    assert!(parse_indicators("ma_0").is_err());
    assert!(parse_indicators("ma_abc").is_err());
}

#[test]
fn test_max_lookback() {
    let inds = vec![Indicator::Ma(20), Indicator::Ema(12), Indicator::Macd];
    assert_eq!(max_lookback(&inds), 70);
}

#[test]
fn test_max_lookback_ma_only() {
    let inds = vec![Indicator::Ma(60)];
    assert_eq!(max_lookback(&inds), 59);
}

#[test]
fn test_compute_sma_basic() {
    let mut rows: Vec<serde_json::Value> = (1..=5)
        .map(|i| json!({"ticker": "TEST", "close": i as f64 * 10.0}))
        .collect();

    compute_indicators(&mut rows, &[Indicator::Ma(3)]);

    assert!(rows[0]["ma_3"].is_null());
    assert!(rows[1]["ma_3"].is_null());
    assert_eq!(rows[2]["ma_3"].as_f64().unwrap(), 20.0);
    assert_eq!(rows[3]["ma_3"].as_f64().unwrap(), 30.0);
    assert_eq!(rows[4]["ma_3"].as_f64().unwrap(), 40.0);
}

#[test]
fn test_compute_ema_basic() {
    let mut rows: Vec<serde_json::Value> = (1..=5)
        .map(|i| json!({"ticker": "TEST", "close": i as f64 * 10.0}))
        .collect();

    compute_indicators(&mut rows, &[Indicator::Ema(3)]);

    assert!(rows[0]["ema_3"].is_null());
    assert!(rows[1]["ema_3"].is_null());
    assert_eq!(rows[2]["ema_3"].as_f64().unwrap(), 20.0);
    assert_eq!(rows[3]["ema_3"].as_f64().unwrap(), 30.0);
    assert_eq!(rows[4]["ema_3"].as_f64().unwrap(), 40.0);
}

#[test]
fn test_compute_macd_returns_three_columns() {
    let mut rows: Vec<serde_json::Value> = (1..=50)
        .map(|i| json!({"ticker": "TEST", "close": 100.0 + i as f64}))
        .collect();

    compute_indicators(&mut rows, &[Indicator::Macd]);

    assert!(rows[0]["macd"].is_null());
    assert!(rows[20]["macd"].is_null());
    assert!(rows[25]["macd"].as_f64().is_some());
    assert!(rows[35]["macd_signal"].as_f64().is_some());
    assert!(rows[35]["macd_histogram"].as_f64().is_some());

    for row in &rows {
        assert!(row.get("macd").is_some());
        assert!(row.get("macd_signal").is_some());
        assert!(row.get("macd_histogram").is_some());
    }
}

#[test]
fn test_compute_multi_ticker() {
    let mut rows = vec![
        json!({"ticker": "A", "close": 10.0}),
        json!({"ticker": "A", "close": 20.0}),
        json!({"ticker": "A", "close": 30.0}),
        json!({"ticker": "B", "close": 100.0}),
        json!({"ticker": "B", "close": 200.0}),
        json!({"ticker": "B", "close": 300.0}),
    ];

    compute_indicators(&mut rows, &[Indicator::Ma(3)]);

    assert_eq!(rows[2]["ma_3"].as_f64().unwrap(), 20.0);
    assert_eq!(rows[5]["ma_3"].as_f64().unwrap(), 200.0);
}

#[test]
fn test_empty_rows_no_panic() {
    let mut rows: Vec<serde_json::Value> = vec![];
    compute_indicators(&mut rows, &[Indicator::Ma(5), Indicator::Macd]);
    assert!(rows.is_empty());
}
