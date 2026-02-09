use upq_ingest::sync_plan::{build_sample_sync_plan, DatasetFileLists};

#[test]
fn build_sample_sync_plan_selects_latest_n_dates_per_dataset(
) -> Result<(), Box<dyn std::error::Error>> {
    let lists = DatasetFileLists {
        stock_day: vec![
            "/home/qlib/data/stock/us_stocks_sip_day_aggs_v1_2025_01_2025-01-06.csv.gz".to_string(),
            "/home/qlib/data/stock/us_stocks_sip_day_aggs_v1_2025_01_2025-01-07.csv.gz".to_string(),
            "/home/qlib/data/stock/us_stocks_sip_day_aggs_v1_2025_01_2025-01-08.csv.gz".to_string(),
        ],
        stock_minute: vec![
            "/home/qlib/data/stock/us_stocks_sip_minute_aggs_v1_2025_01_2025-01-07.csv.gz"
                .to_string(),
            "/home/qlib/data/stock/us_stocks_sip_minute_aggs_v1_2025_01_2025-01-08.csv.gz"
                .to_string(),
            "/home/qlib/data/stock/us_stocks_sip_minute_aggs_v1_2025_01_2025-01-09.csv.gz"
                .to_string(),
        ],
        option_day: vec![
            "/home/qlib/data/us_options_opra/day_aggs_v1/2025/01/2025-01-08.csv.gz".to_string(),
            "/home/qlib/data/us_options_opra/day_aggs_v1/2025/01/2025-01-09.csv.gz".to_string(),
        ],
        option_minute: vec![
            "/home/qlib/data/us_options_opra/minute_aggs_v1/2025/01/2025-01-08.csv.gz".to_string(),
            "/home/qlib/data/us_options_opra/minute_aggs_v1/2025/01/2025-01-09.csv.gz".to_string(),
        ],
        rates_file: Some("/home/qlib/data/assets/treasury_yields.csv".to_string()),
    };

    let plan = build_sample_sync_plan(&lists, 2, "./raw_sample")?;

    assert!(plan
        .iter()
        .any(|i| i.remote_path.ends_with("2025-01-08.csv.gz")));
    assert!(plan
        .iter()
        .any(|i| i.remote_path.ends_with("2025-01-09.csv.gz")));
    assert!(!plan
        .iter()
        .any(|i| i.remote_path.ends_with("2025-01-06.csv.gz")));
    Ok(())
}

#[test]
fn build_sample_sync_plan_includes_rates_file_when_present(
) -> Result<(), Box<dyn std::error::Error>> {
    let lists = DatasetFileLists {
        stock_day: vec![
            "/home/qlib/data/stock/us_stocks_sip_day_aggs_v1_2025_01_2025-01-08.csv.gz".to_string(),
        ],
        stock_minute: vec![
            "/home/qlib/data/stock/us_stocks_sip_minute_aggs_v1_2025_01_2025-01-08.csv.gz"
                .to_string(),
        ],
        option_day: vec![
            "/home/qlib/data/us_options_opra/day_aggs_v1/2025/01/2025-01-08.csv.gz".to_string(),
        ],
        option_minute: vec![
            "/home/qlib/data/us_options_opra/minute_aggs_v1/2025/01/2025-01-08.csv.gz".to_string(),
        ],
        rates_file: Some("/home/qlib/data/assets/treasury_yields.csv".to_string()),
    };

    let plan = build_sample_sync_plan(&lists, 1, "./raw_sample")?;
    assert!(plan
        .iter()
        .any(|i| i.remote_path.ends_with("treasury_yields.csv")));
    Ok(())
}
