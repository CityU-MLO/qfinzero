use upq_ingest::sample_sync::{latest_n_trade_dates, select_files_for_dates};

#[test]
fn latest_n_trade_dates_extracts_and_sorts_unique_dates() -> Result<(), Box<dyn std::error::Error>>
{
    let files = vec![
        "/x/us_stocks_sip_day_aggs_v1_2025_01_2025-01-08.csv.gz".to_string(),
        "/x/us_stocks_sip_day_aggs_v1_2025_01_2025-01-06.csv.gz".to_string(),
        "/x/us_stocks_sip_day_aggs_v1_2025_01_2025-01-07.csv.gz".to_string(),
        "/x/us_stocks_sip_day_aggs_v1_2025_01_2025-01-08.csv.gz".to_string(),
    ];

    let dates = latest_n_trade_dates(&files, 2)?;
    assert_eq!(
        dates,
        vec!["2025-01-07".to_string(), "2025-01-08".to_string()]
    );
    Ok(())
}

#[test]
fn select_files_for_dates_filters_only_target_dates() {
    let files = vec![
        "/x/2025-01-06.csv.gz".to_string(),
        "/x/2025-01-07.csv.gz".to_string(),
        "/x/2025-01-08.csv.gz".to_string(),
    ];
    let dates = vec!["2025-01-06".to_string(), "2025-01-08".to_string()];

    let selected = select_files_for_dates(&files, &dates);
    assert_eq!(
        selected,
        vec![
            "/x/2025-01-06.csv.gz".to_string(),
            "/x/2025-01-08.csv.gz".to_string()
        ]
    );
}
