use serde_json::json;
use upq_service::rates_curve::{CurveError, RatesCurve};

fn assert_near(actual: f64, expected: f64, tol: f64, label: &str) {
    let diff = (actual - expected).abs();
    assert!(
        diff < tol,
        "{label}: expected {expected}, got {actual}, diff {diff} > tol {tol}"
    );
}

#[test]
fn curve_from_json_row_parses_all_tenors() {
    let row = json!({
        "date": "2025-01-02",
        "yield_1_month": 4.53,
        "yield_3_month": 4.35,
        "yield_1_year": 4.22,
        "yield_2_year": 4.28,
        "yield_5_year": 4.43,
        "yield_10_year": 4.60,
        "yield_30_year": 4.82
    });

    let curve = RatesCurve::from_json_row(&row).expect("should parse");

    // Check 1M rate: 4.53% -> 0.0453
    let r = curve.interpolate(1.0 / 12.0).expect("should interpolate");
    assert_near(r, 0.0453, 1e-8, "1M rate");

    // Check 30Y rate
    let r = curve.interpolate(30.0).expect("should interpolate");
    assert_near(r, 0.0482, 1e-8, "30Y rate");
}

#[test]
fn curve_interpolation_midpoint() {
    // Create a simple two-point curve
    let curve = RatesCurve::from_points(vec![
        (1.0, 0.04), // 1Y = 4%
        (5.0, 0.05), // 5Y = 5%
    ])
    .expect("should create curve");

    // Interpolate at 3Y (midpoint)
    let r = curve.interpolate(3.0).expect("should interpolate");
    assert_near(r, 0.045, 1e-10, "linear interpolation at midpoint");
}

#[test]
fn curve_interpolation_near_endpoints() {
    let curve = RatesCurve::from_points(vec![
        (0.25, 0.03),  // 3M = 3%
        (1.0, 0.035),  // 1Y = 3.5%
        (5.0, 0.04),   // 5Y = 4%
    ])
    .expect("should create curve");

    // Just past first point
    let r = curve.interpolate(0.30).expect("should interpolate");
    let expected = 0.03 + (0.30 - 0.25) / (1.0 - 0.25) * (0.035 - 0.03);
    assert_near(r, expected, 1e-10, "interpolation near first point");
}

#[test]
fn curve_clamps_below_min_tenor() {
    let curve = RatesCurve::from_points(vec![(0.25, 0.03), (1.0, 0.04)])
        .expect("should create curve");

    // T below minimum tenor should clamp to min rate
    let r = curve.interpolate(0.01).expect("should interpolate");
    assert_near(r, 0.03, 1e-10, "clamp below min tenor");
}

#[test]
fn curve_clamps_above_max_tenor() {
    let curve = RatesCurve::from_points(vec![(1.0, 0.04), (10.0, 0.05)])
        .expect("should create curve");

    // T above maximum tenor should clamp to max rate
    let r = curve.interpolate(50.0).expect("should interpolate");
    assert_near(r, 0.05, 1e-10, "clamp above max tenor");
}

#[test]
fn curve_exact_tenor_point() {
    let curve = RatesCurve::from_points(vec![
        (1.0, 0.04),
        (2.0, 0.045),
        (5.0, 0.05),
    ])
    .expect("should create curve");

    let r = curve.interpolate(2.0).expect("should interpolate");
    assert_near(r, 0.045, 1e-10, "exact tenor point");
}

#[test]
fn curve_single_point() {
    let curve = RatesCurve::from_points(vec![(1.0, 0.04)]).expect("should create curve");

    // Any T should return the single rate
    let r = curve.interpolate(0.5).expect("should interpolate");
    assert_near(r, 0.04, 1e-10, "single point curve below");

    let r = curve.interpolate(5.0).expect("should interpolate");
    assert_near(r, 0.04, 1e-10, "single point curve above");
}

#[test]
fn curve_missing_data_returns_error() {
    let row = json!({
        "date": "2025-01-02"
    });

    let result = RatesCurve::from_json_row(&row);
    assert_eq!(result.err(), Some(CurveError::MissingData));
}

#[test]
fn curve_empty_points_returns_error() {
    let result = RatesCurve::from_points(vec![]);
    assert_eq!(result.err(), Some(CurveError::MissingData));
}

#[test]
fn curve_handles_partial_data() {
    // Only some tenors available
    let row = json!({
        "date": "2025-01-02",
        "yield_1_year": 4.0,
        "yield_10_year": 4.5
    });

    let curve = RatesCurve::from_json_row(&row).expect("should parse with partial data");

    // Should interpolate between the two available points
    let r = curve.interpolate(5.0).expect("should interpolate");
    let expected = 0.04 + (5.0 - 1.0) / (10.0 - 1.0) * (0.045 - 0.04);
    assert_near(r, expected, 1e-10, "partial data interpolation");
}

#[test]
fn curve_ignores_nan_values() {
    let row = json!({
        "date": "2025-01-02",
        "yield_1_month": null,
        "yield_3_month": 4.35,
        "yield_1_year": 4.22
    });

    let curve = RatesCurve::from_json_row(&row).expect("should parse, skipping null");

    // 1M should be null/skipped, so clamp to 3M rate
    let r = curve.interpolate(1.0 / 12.0).expect("should interpolate");
    assert_near(r, 0.0435, 1e-8, "clamps to lowest available tenor");
}

#[test]
fn curve_full_interpolation_across_tenors() {
    let row = json!({
        "date": "2025-01-02",
        "yield_1_month": 4.53,
        "yield_3_month": 4.35,
        "yield_1_year": 4.22,
        "yield_2_year": 4.28,
        "yield_5_year": 4.43,
        "yield_10_year": 4.60,
        "yield_30_year": 4.82
    });

    let curve = RatesCurve::from_json_row(&row).expect("should parse");

    // Test short tenor (2 months — between 1M and 3M)
    let r = curve.interpolate(2.0 / 12.0).expect("should interpolate");
    assert!(
        r > 0.0435 && r < 0.0453,
        "2M rate should be between 1M and 3M, got {r}"
    );

    // Test mid tenor (3Y — between 2Y and 5Y)
    let r = curve.interpolate(3.0).expect("should interpolate");
    assert!(
        r > 0.0428 && r < 0.0443,
        "3Y rate should be between 2Y and 5Y, got {r}"
    );

    // Test long tenor (20Y — between 10Y and 30Y)
    let r = curve.interpolate(20.0).expect("should interpolate");
    assert!(
        r > 0.0460 && r < 0.0482,
        "20Y rate should be between 10Y and 30Y, got {r}"
    );
}
