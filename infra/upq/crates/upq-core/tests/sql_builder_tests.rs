use upq_core::sql_builder::{build_option_chain_sql, build_stock_sql, build_tenor_projection};

#[test]
fn stock_sql_contains_partition_and_ticker_predicates() {
    let sql = build_stock_sql("stock_minute", &["ticker", "window_start", "close"], 5000);
    assert!(sql.contains("trade_date >= ?"));
    assert!(sql.contains("trade_date <= ?"));
    assert!(sql.contains("ticker IN"));
    assert!(sql.contains("LIMIT 5000"));
}

#[test]
fn chain_sql_targets_single_day_partition() {
    let sql = build_option_chain_sql(&["ticker", "expiry", "strike"]);
    assert!(sql.contains("trade_date = ?"));
    assert!(sql.contains("underlying = ?"));
    assert!(sql.contains("ORDER BY expiry, strike"));
}

#[test]
fn tenor_projection_only_selects_requested_tenors() {
    let projection = build_tenor_projection(&["yield_1_month", "yield_10_year"]);
    assert_eq!(projection, "date, yield_1_month, yield_10_year");
}

#[test]
fn tenor_projection_defaults_to_all_columns_when_filter_is_empty() {
    let projection = build_tenor_projection(&[]);
    assert_eq!(
        projection,
        "date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year"
    );
}
