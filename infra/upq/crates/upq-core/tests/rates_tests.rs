use upq_core::rates::{map_tenor_aliases, split_by_month};

#[test]
fn split_by_month_handles_single_month_range() -> Result<(), upq_core::error::CoreError> {
    let chunks = split_by_month("2025-01-05", "2025-01-20")?;
    assert_eq!(
        chunks,
        vec![("2025-01-05".to_string(), "2025-01-20".to_string())]
    );
    Ok(())
}

#[test]
fn split_by_month_splits_cross_month_range() -> Result<(), upq_core::error::CoreError> {
    let chunks = split_by_month("2025-01-20", "2025-03-10")?;
    assert_eq!(
        chunks,
        vec![
            ("2025-01-20".to_string(), "2025-01-31".to_string()),
            ("2025-02-01".to_string(), "2025-02-28".to_string()),
            ("2025-03-01".to_string(), "2025-03-10".to_string()),
        ]
    );
    Ok(())
}

#[test]
fn map_tenor_aliases_maps_short_codes_to_column_names() -> Result<(), upq_core::error::CoreError> {
    let mapped = map_tenor_aliases(&["1M", "3M", "10Y"])?;
    assert_eq!(
        mapped,
        vec!["yield_1_month", "yield_3_month", "yield_10_year"]
    );
    Ok(())
}

#[test]
fn map_tenor_aliases_rejects_unknown_tenor() {
    let err = map_tenor_aliases(&["7Y"]);
    assert!(err.is_err());
}
