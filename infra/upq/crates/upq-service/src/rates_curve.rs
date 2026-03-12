/// Standard tenor points in years
const TENOR_YEARS: [f64; 7] = [
    1.0 / 12.0, // 1M
    3.0 / 12.0, // 3M
    1.0,        // 1Y
    2.0,        // 2Y
    5.0,        // 5Y
    10.0,       // 10Y
    30.0,       // 30Y
];

/// Column names matching the parquet schema
const TENOR_COLUMNS: [&str; 7] = [
    "yield_1_month",
    "yield_3_month",
    "yield_1_year",
    "yield_2_year",
    "yield_5_year",
    "yield_10_year",
    "yield_30_year",
];

/// A yield curve for a specific date
#[derive(Debug, Clone)]
pub struct RatesCurve {
    /// (tenor_years, yield_decimal) pairs, sorted by tenor
    points: Vec<(f64, f64)>,
}

/// Error type for curve operations
#[derive(Debug, Clone, PartialEq)]
pub enum CurveError {
    /// No rate data available
    MissingData,
    /// Not enough points to interpolate
    InsufficientPoints,
}

impl RatesCurve {
    /// Build a curve from a JSON row (as returned by DuckDB query).
    /// Yields in the row are in percentage form (e.g., 4.53 = 4.53%).
    /// Internally we convert to decimal (0.0453) for BSM computation.
    pub fn from_json_row(row: &serde_json::Value) -> Result<Self, CurveError> {
        let mut points = Vec::new();

        for (i, col_name) in TENOR_COLUMNS.iter().enumerate() {
            if let Some(val) = row.get(*col_name) {
                if let Some(rate_pct) = val.as_f64() {
                    if rate_pct.is_finite() {
                        // Convert percentage to decimal
                        points.push((TENOR_YEARS[i], rate_pct / 100.0));
                    }
                }
            }
        }

        if points.is_empty() {
            return Err(CurveError::MissingData);
        }

        // Already sorted by construction since TENOR_YEARS is sorted
        Ok(RatesCurve { points })
    }

    /// Build a curve from explicit (tenor_years, yield_decimal) pairs.
    /// Used primarily for testing.
    pub fn from_points(mut points: Vec<(f64, f64)>) -> Result<Self, CurveError> {
        if points.is_empty() {
            return Err(CurveError::MissingData);
        }
        points.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
        Ok(RatesCurve { points })
    }

    /// Interpolate the yield for a given time-to-expiry T (in years).
    /// Uses linear interpolation between adjacent tenor points.
    /// Clamps at boundaries: if T < min tenor, use min tenor rate; if T > max tenor, use max tenor rate.
    pub fn interpolate(&self, t: f64) -> Result<f64, CurveError> {
        if self.points.is_empty() {
            return Err(CurveError::InsufficientPoints);
        }

        if self.points.len() == 1 {
            return Ok(self.points[0].1);
        }

        let first = self.points[0];
        let last = self.points[self.points.len() - 1];

        // Clamp below minimum
        if t <= first.0 {
            return Ok(first.1);
        }

        // Clamp above maximum
        if t >= last.0 {
            return Ok(last.1);
        }

        // Find bracketing points
        for window in self.points.windows(2) {
            let (t0, r0) = window[0];
            let (t1, r1) = window[1];

            if t >= t0 && t <= t1 {
                // Linear interpolation
                let frac = (t - t0) / (t1 - t0);
                return Ok(r0 + frac * (r1 - r0));
            }
        }

        // Should not reach here if points are properly sorted
        Ok(last.1)
    }
}
