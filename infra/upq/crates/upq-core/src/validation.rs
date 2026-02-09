use std::collections::HashSet;

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

pub fn parse_csv_list(csv: &str) -> Vec<String> {
    csv.split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(ToString::to_string)
        .collect()
}
