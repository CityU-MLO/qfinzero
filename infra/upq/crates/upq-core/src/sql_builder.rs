pub fn build_stock_sql(dataset: &str, fields: &[&str], limit: usize) -> String {
    let projection = if fields.is_empty() {
        "ticker, window_start, close".to_string()
    } else {
        fields.join(", ")
    };

    format!(
        "SELECT {projection} FROM read_parquet(?) WHERE trade_date >= ? AND trade_date <= ? AND ticker IN (SELECT UNNEST(?)) AND window_start >= ? AND window_start <= ? ORDER BY ticker, window_start LIMIT {limit}",
    )
    .replace("read_parquet(?)", &format!("read_parquet('{dataset}')"))
}

pub fn build_option_chain_sql(fields: &[&str]) -> String {
    let projection = if fields.is_empty() {
        "ticker, expiry, strike, right, close".to_string()
    } else {
        fields.join(", ")
    };

    format!(
        "SELECT {projection} FROM read_parquet(?) WHERE trade_date = ? AND underlying = ? ORDER BY expiry, strike"
    )
}

pub fn build_tenor_projection(tenors: &[&str]) -> String {
    if tenors.is_empty() {
        return "date, yield_1_month, yield_3_month, yield_1_year, yield_2_year, yield_5_year, yield_10_year, yield_30_year".to_string();
    }

    format!("date, {}", tenors.join(", "))
}
