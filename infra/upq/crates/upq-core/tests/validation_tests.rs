use upq_core::validation::{validate_fields, validate_resolution};

#[test]
fn validate_resolution_rejects_invalid_value() {
    let result = validate_resolution("hour");
    assert!(result.is_err());
}

#[test]
fn validate_fields_rejects_unknown_columns() {
    let allowlist = ["ticker", "window_start", "close"];
    let result = validate_fields(&["ticker", "hack"], &allowlist);
    assert!(result.is_err());
}

#[test]
fn validate_fields_accepts_known_columns() {
    let allowlist = ["ticker", "window_start", "close"];
    let result = validate_fields(&["ticker", "close"], &allowlist);
    assert!(result.is_ok());
}
