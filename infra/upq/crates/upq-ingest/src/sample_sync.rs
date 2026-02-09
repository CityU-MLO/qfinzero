use std::collections::BTreeSet;

use chrono::NaiveDate;
use regex::Regex;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum SampleSyncError {
    #[error("no trade dates found in source file list")]
    NoTradeDates,
}

pub fn latest_n_trade_dates(files: &[String], n: usize) -> Result<Vec<String>, SampleSyncError> {
    let mut unique_dates = BTreeSet::new();

    for file in files {
        if let Some(date) = extract_iso_date(file) {
            unique_dates.insert(date);
        }
    }

    if unique_dates.is_empty() {
        return Err(SampleSyncError::NoTradeDates);
    }

    let mut ordered: Vec<String> = unique_dates.into_iter().collect();
    if ordered.len() > n {
        ordered = ordered.split_off(ordered.len() - n);
    }

    Ok(ordered)
}

pub fn select_files_for_dates(files: &[String], dates: &[String]) -> Vec<String> {
    files
        .iter()
        .filter(|path| dates.iter().any(|date| path.contains(date)))
        .cloned()
        .collect()
}

fn extract_iso_date(path: &str) -> Option<String> {
    let pattern = Regex::new(r"(\d{4}-\d{2}-\d{2})").ok()?;
    let capture = pattern.captures(path)?;
    let value = capture.get(1)?.as_str();

    if NaiveDate::parse_from_str(value, "%Y-%m-%d").is_ok() {
        Some(value.to_string())
    } else {
        None
    }
}
