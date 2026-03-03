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

#[test]
fn validate_date_rejects_invalid_format() {
    let result = upq_core::validation::validate_date("2025/01/06");
    assert!(result.is_err());
}

#[test]
fn validate_datetime_rejects_invalid_format() {
    let result = upq_core::validation::validate_datetime("2025-01-06 09:30:00");
    assert!(result.is_err());
}

// ── validate_datetime: LLM-generated UTC formats ─────────────────

#[test]
fn validate_datetime_accepts_bare_format() {
    // Baseline: YYYY-MM-DDTHH:MM:SS (already works)
    let result = upq_core::validation::validate_datetime("2026-01-27T15:40:00");
    assert!(result.is_ok());
}

#[test]
fn validate_datetime_accepts_z_suffix() {
    // LLMs (GPT, Claude) almost always append Z for UTC
    let result = upq_core::validation::validate_datetime("2026-01-27T15:40:00Z");
    assert!(result.is_ok(), "should accept Z suffix — LLMs generate this format");
}

#[test]
fn validate_datetime_accepts_plus_zero_offset() {
    // Some LLMs use +00:00 instead of Z
    let result = upq_core::validation::validate_datetime("2026-01-27T15:40:00+00:00");
    assert!(result.is_ok(), "should accept +00:00 offset — LLMs generate this format");
}

#[test]
fn validate_datetime_rejects_non_utc_offset() {
    // Non-UTC offsets should be rejected — UPQ expects UTC only
    let result = upq_core::validation::validate_datetime("2026-01-27T15:40:00+05:30");
    assert!(result.is_err(), "should reject non-UTC offset");
}

#[test]
fn validate_datetime_rejects_garbage() {
    let result = upq_core::validation::validate_datetime("not-a-date");
    assert!(result.is_err());
}

// ── validate_date_or_datetime: same UTC tolerance ────────────────

#[test]
fn validate_date_or_datetime_accepts_z_suffix() {
    let result = upq_core::validation::validate_date_or_datetime("2026-01-27T15:40:00Z");
    assert!(result.is_ok(), "date_or_datetime should also accept Z suffix");
}

#[test]
fn validate_date_or_datetime_accepts_plus_zero_offset() {
    let result = upq_core::validation::validate_date_or_datetime("2026-01-27T15:40:00+00:00");
    assert!(result.is_ok(), "date_or_datetime should also accept +00:00");
}
