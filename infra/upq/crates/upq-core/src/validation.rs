use std::collections::HashSet;

use chrono::{NaiveDate, NaiveDateTime};

use crate::error::CoreError;

pub fn validate_resolution(resolution: &str) -> Result<(), CoreError> {
    match resolution {
        "day" | "minute" => Ok(()),
        other => Err(CoreError::InvalidResolution(other.to_string())),
    }
}

pub fn validate_fields(fields: &[&str], allowlist: &[&str]) -> Result<(), CoreError> {
    let allow: HashSet<&str> = allowlist.iter().copied().collect();
    for field in fields {
        let field = field.trim();
        if field.is_empty() {
            continue;
        }
        if !allow.contains(field) {
            return Err(CoreError::UnsupportedField(field.to_string()));
        }
    }
    Ok(())
}

pub fn validate_date(value: &str) -> Result<(), CoreError> {
    NaiveDate::parse_from_str(value, "%Y-%m-%d")
        .map(|_| ())
        .map_err(|_| CoreError::InvalidDate(value.to_string()))
}

pub fn validate_datetime(value: &str) -> Result<(), CoreError> {
    NaiveDateTime::parse_from_str(value, "%Y-%m-%dT%H:%M:%S")
        .map(|_| ())
        .map_err(|_| CoreError::InvalidDate(value.to_string()))
}

pub fn validate_date_or_datetime(value: &str) -> Result<(), CoreError> {
    validate_date(value).or_else(|_| validate_datetime(value))
}

pub fn parse_csv_list(csv: &str) -> Vec<String> {
    csv.split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(ToString::to_string)
        .collect()
}
