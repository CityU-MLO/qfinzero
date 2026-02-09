use chrono::{Datelike, NaiveDate};

use crate::error::CoreError;

pub fn split_by_month(start: &str, end: &str) -> Result<Vec<(String, String)>, CoreError> {
    let start_date = NaiveDate::parse_from_str(start, "%Y-%m-%d")
        .map_err(|_| CoreError::InvalidDate(start.to_string()))?;
    let end_date = NaiveDate::parse_from_str(end, "%Y-%m-%d")
        .map_err(|_| CoreError::InvalidDate(end.to_string()))?;

    if start_date > end_date {
        return Err(CoreError::InvalidDateRange);
    }

    let mut chunks = Vec::new();
    let mut cursor = start_date;

    while cursor <= end_date {
        let month_end = end_of_month(cursor)?;
        let chunk_end = if month_end < end_date {
            month_end
        } else {
            end_date
        };
        chunks.push((
            cursor.format("%Y-%m-%d").to_string(),
            chunk_end.format("%Y-%m-%d").to_string(),
        ));

        if chunk_end == end_date {
            break;
        }

        cursor = chunk_end.succ_opt().ok_or(CoreError::InvalidDateRange)?;
    }

    Ok(chunks)
}

pub fn map_tenor_aliases(tenors: &[&str]) -> Result<Vec<&'static str>, CoreError> {
    tenors
        .iter()
        .map(|tenor| match tenor.trim().to_ascii_uppercase().as_str() {
            "1M" | "YIELD_1_MONTH" => Ok("yield_1_month"),
            "3M" | "YIELD_3_MONTH" => Ok("yield_3_month"),
            "1Y" | "YIELD_1_YEAR" => Ok("yield_1_year"),
            "2Y" | "YIELD_2_YEAR" => Ok("yield_2_year"),
            "5Y" | "YIELD_5_YEAR" => Ok("yield_5_year"),
            "10Y" | "YIELD_10_YEAR" => Ok("yield_10_year"),
            "30Y" | "YIELD_30_YEAR" => Ok("yield_30_year"),
            other => Err(CoreError::UnsupportedTenor(other.to_string())),
        })
        .collect()
}

fn end_of_month(date: NaiveDate) -> Result<NaiveDate, CoreError> {
    let year = date.year();
    let month = date.month();

    let next_month_start = if month == 12 {
        NaiveDate::from_ymd_opt(year + 1, 1, 1)
    } else {
        NaiveDate::from_ymd_opt(year, month + 1, 1)
    }
    .ok_or(CoreError::InvalidDateRange)?;

    next_month_start
        .pred_opt()
        .ok_or(CoreError::InvalidDateRange)
}
