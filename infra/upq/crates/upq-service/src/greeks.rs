use std::f64::consts::PI;

/// Standard normal CDF.
///
/// Uses the identity Φ(x) = 0.5·(1 + erf(x/√2)) with an accurate erf
/// approximation. `norm_cdf(0.0)` returns exactly `0.5`.
pub fn norm_cdf(x: f64) -> f64 {
    0.5 * (1.0 + erf_approx(x / std::f64::consts::SQRT_2))
}

/// Approximation of erf(x) using a rational Chebyshev expansion.
///
/// This is the Abramowitz & Stegun formula 7.1.28:
///   erf(x) ≈ 1 - (a1·t + a2·t² + a3·t³ + a4·t⁴ + a5·t⁵)·exp(-x²)
///   where t = 1 / (1 + 0.3275911·x),  valid for x ≥ 0.
/// Max absolute error: ~1.5e-7.
/// For x < 0 the odd symmetry erf(-x) = -erf(x) is used.
/// erf(0) = 0 exactly.
fn erf_approx(x: f64) -> f64 {
    if x == 0.0 {
        return 0.0;
    }
    let ax = x.abs();
    // A&S 7.1.26: t = 1/(1 + p*x) where p = 0.47047 (3-term) — using the
    // 5-term formula 7.1.28 instead, with p = 0.3275911.
    let t = 1.0 / (1.0 + 0.327_591_1 * ax);
    // Horner evaluation of the polynomial in t:
    //   p = a5 + t*(a4 + t*(a3 + t*(a2 + t*a1)))  — built innermost-first
    const A1: f64 = 0.254_829_592;
    const A2: f64 = -0.284_496_736;
    const A3: f64 = 1.421_413_741;
    const A4: f64 = -1.453_152_027;
    const A5: f64 = 1.061_405_429;
    let poly = t * (A1 + t * (A2 + t * (A3 + t * (A4 + t * A5))));
    let erfc_abs = poly * (-ax * ax).exp();
    let erf_abs = 1.0 - erfc_abs.clamp(0.0, 1.0);
    if x > 0.0 {
        erf_abs
    } else {
        -erf_abs
    }
}

/// Standard normal PDF
pub fn norm_pdf(x: f64) -> f64 {
    (1.0 / (2.0 * PI).sqrt()) * (-0.5 * x * x).exp()
}

/// BSM d1 and d2
pub fn bsm_d1_d2(s: f64, k: f64, t: f64, r: f64, q: f64, sigma: f64) -> (f64, f64) {
    let d1 = ((s / k).ln() + (r - q + 0.5 * sigma * sigma) * t) / (sigma * t.sqrt());
    let d2 = d1 - sigma * t.sqrt();
    (d1, d2)
}

/// BSM price for call or put.
/// `is_call`: `true` for call, `false` for put.
pub fn bsm_price(s: f64, k: f64, t: f64, r: f64, q: f64, sigma: f64, is_call: bool) -> f64 {
    let (d1, d2) = bsm_d1_d2(s, k, t, r, q, sigma);
    if is_call {
        s * (-q * t).exp() * norm_cdf(d1) - k * (-r * t).exp() * norm_cdf(d2)
    } else {
        k * (-r * t).exp() * norm_cdf(-d2) - s * (-q * t).exp() * norm_cdf(-d1)
    }
}

/// Greeks computed from the BSM model.
pub struct BsmGreeks {
    pub delta: f64,
    pub gamma: f64,
    /// Theta per calendar day (negative for typical long positions).
    pub theta: f64,
    /// Vega per 1 percentage point of vol (i.e. per 0.01 change in sigma).
    pub vega: f64,
    /// Rho per 1 percentage point of rate (i.e. per 0.01 change in r).
    pub rho: f64,
}

/// Compute all BSM Greeks.
pub fn bsm_greeks(s: f64, k: f64, t: f64, r: f64, q: f64, sigma: f64, is_call: bool) -> BsmGreeks {
    let (d1, d2) = bsm_d1_d2(s, k, t, r, q, sigma);
    let sqrt_t = t.sqrt();
    let pdf_d1 = norm_pdf(d1);
    let exp_qt = (-q * t).exp();
    let exp_rt = (-r * t).exp();

    let delta = if is_call {
        exp_qt * norm_cdf(d1)
    } else {
        -exp_qt * norm_cdf(-d1)
    };

    let gamma = exp_qt * pdf_d1 / (s * sigma * sqrt_t);

    // Theta in per-year, then convert to per-day by dividing by 365.
    let theta_annual = if is_call {
        -s * exp_qt * pdf_d1 * sigma / (2.0 * sqrt_t) - r * k * exp_rt * norm_cdf(d2)
            + q * s * exp_qt * norm_cdf(d1)
    } else {
        -s * exp_qt * pdf_d1 * sigma / (2.0 * sqrt_t) + r * k * exp_rt * norm_cdf(-d2)
            - q * s * exp_qt * norm_cdf(-d1)
    };
    let theta = theta_annual / 365.0;

    // Vega: per 1 percentage point (0.01) of vol.
    let vega = s * exp_qt * pdf_d1 * sqrt_t * 0.01;

    // Rho: per 1 percentage point (0.01) of rate.
    let rho = if is_call {
        k * t * exp_rt * norm_cdf(d2) * 0.01
    } else {
        -k * t * exp_rt * norm_cdf(-d2) * 0.01
    };

    BsmGreeks {
        delta,
        gamma,
        theta,
        vega,
        rho,
    }
}

/// Status of an IV inversion attempt.
#[derive(Debug, Clone, PartialEq)]
pub enum IvStatus {
    Ok,
    BelowIntrinsic,
    NoBracket,
    NoConvergence,
    NonFiniteInput,
    NearExpiryApprox,
}

/// Result from an implied-volatility inversion.
pub struct IvResult {
    pub iv: Option<f64>,
    pub status: IvStatus,
}

/// Implied volatility via Brent's method with a Brenner-Subrahmanyam initial guess.
/// `q = 0` for the no-dividend case.
pub fn implied_volatility(
    market_price: f64,
    s: f64,
    k: f64,
    t: f64,
    r: f64,
    q: f64,
    is_call: bool,
) -> IvResult {
    // Input validation — reject non-finite or non-positive inputs.
    if !market_price.is_finite()
        || !s.is_finite()
        || !k.is_finite()
        || !t.is_finite()
        || !r.is_finite()
        || !q.is_finite()
        || s <= 0.0
        || k <= 0.0
        || market_price <= 0.0
    {
        return IvResult {
            iv: None,
            status: IvStatus::NonFiniteInput,
        };
    }

    // Near-expiry guard: about 1 minute expressed in years.
    let t_min = 1.0 / (365.0 * 24.0 * 60.0);
    if t < t_min {
        let intrinsic = if is_call {
            (s * (-q * t).exp() - k * (-r * t).exp()).max(0.0)
        } else {
            (k * (-r * t).exp() - s * (-q * t).exp()).max(0.0)
        };
        if market_price < intrinsic - 1e-10 {
            return IvResult {
                iv: None,
                status: IvStatus::BelowIntrinsic,
            };
        }
        let time_value = (market_price - intrinsic).max(0.0);
        if time_value < 1e-10 {
            return IvResult {
                iv: Some(0.001),
                status: IvStatus::NearExpiryApprox,
            };
        }
        // Brenner-Subrahmanyam approximation for the near-expiry case.
        let approx_iv = (time_value * (2.0 * PI).sqrt() / (s * t.sqrt())).max(0.001);
        return IvResult {
            iv: Some(approx_iv.min(10.0)),
            status: IvStatus::NearExpiryApprox,
        };
    }

    // Check below intrinsic for normal time horizons.
    let intrinsic = if is_call {
        (s * (-q * t).exp() - k * (-r * t).exp()).max(0.0)
    } else {
        (k * (-r * t).exp() - s * (-q * t).exp()).max(0.0)
    };
    if market_price < intrinsic - 1e-10 {
        return IvResult {
            iv: None,
            status: IvStatus::BelowIntrinsic,
        };
    }

    let sigma_lo = 0.001_f64;
    let sigma_hi = 10.0_f64;
    let max_iter = 100_usize;
    let tol = 1e-10_f64;

    let f = |sigma: f64| -> f64 { bsm_price(s, k, t, r, q, sigma, is_call) - market_price };

    let f_lo = f(sigma_lo);
    let f_hi = f(sigma_hi);

    // Verify that [sigma_lo, sigma_hi] brackets the root.
    if f_lo * f_hi > 0.0 {
        return IvResult {
            iv: None,
            status: IvStatus::NoBracket,
        };
    }

    // Brent's method.
    let mut a = sigma_lo;
    let mut b = sigma_hi;
    let mut fa = f_lo;
    let mut fb = f_hi;
    let mut c = a;
    let mut fc = fa;
    let mut d = b - a;
    let mut e = d;

    for _ in 0..max_iter {
        if fb * fc > 0.0 {
            c = a;
            fc = fa;
            d = b - a;
            e = d;
        }
        if fc.abs() < fb.abs() {
            a = b;
            b = c;
            c = a;
            fa = fb;
            fb = fc;
            fc = fa;
        }

        let tol1 = 2.0 * f64::EPSILON * b.abs() + 0.5 * tol;
        let xm = 0.5 * (c - b);

        if xm.abs() <= tol1 || fb.abs() < tol {
            return IvResult {
                iv: Some(b),
                status: IvStatus::Ok,
            };
        }

        if e.abs() >= tol1 && fa.abs() > fb.abs() {
            // Attempt inverse quadratic interpolation or secant.
            let s_val = fb / fa;
            let (p, q_val) = if (a - c).abs() < tol1 {
                // Secant step.
                let p = 2.0 * xm * s_val;
                let q_local = 1.0 - s_val;
                (p, q_local)
            } else {
                // Inverse quadratic interpolation.
                let q_fa_fc = fa / fc;
                let r_val = fb / fc;
                let p = s_val * (2.0 * xm * q_fa_fc * (q_fa_fc - r_val) - (b - a) * (r_val - 1.0));
                let q_local = (q_fa_fc - 1.0) * (r_val - 1.0) * (s_val - 1.0);
                (p, q_local)
            };

            let (p, q_val) = if p > 0.0 { (p, -q_val) } else { (-p, q_val) };

            let bound = (3.0 * xm * q_val - (tol1 * q_val).abs()).min(e * q_val);
            if 2.0 * p < bound {
                e = d;
                d = p / q_val;
            } else {
                d = xm;
                e = d;
            }
        } else {
            d = xm;
            e = d;
        }

        a = b;
        fa = fb;

        if d.abs() > tol1 {
            b += d;
        } else if xm > 0.0 {
            b += tol1;
        } else {
            b -= tol1;
        }

        fb = f(b);
    }

    // Failed to converge within max_iter iterations.
    IvResult {
        iv: None,
        status: IvStatus::NoConvergence,
    }
}

/// Compute implied volatility and all BSM Greeks from a market price in a single call.
pub fn compute_greeks(
    market_price: f64,
    s: f64,
    k: f64,
    t: f64,
    r: f64,
    q: f64,
    is_call: bool,
) -> (IvResult, Option<BsmGreeks>) {
    let iv_result = implied_volatility(market_price, s, k, t, r, q, is_call);

    match iv_result.iv {
        Some(sigma) => {
            let greeks = bsm_greeks(s, k, t, r, q, sigma, is_call);
            (iv_result, Some(greeks))
        }
        None => (iv_result, None),
    }
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    // Shared test parameters.
    // ATM: S=100, K=100, T=0.25, r=0.05, q=0.02, sigma=0.20
    const ATM_S: f64 = 100.0;
    const ATM_K: f64 = 100.0;
    const ATM_T: f64 = 0.25;
    const ATM_R: f64 = 0.05;
    const ATM_Q: f64 = 0.02;
    const ATM_SIGMA: f64 = 0.20;

    // Deep ITM call: S=100, K=80, T=1.0, r=0.05, q=0.0, sigma=0.30
    const DITM_S: f64 = 100.0;
    const DITM_K: f64 = 80.0;
    const DITM_T: f64 = 1.0;
    const DITM_R: f64 = 0.05;
    const DITM_Q: f64 = 0.0;
    const DITM_SIGMA: f64 = 0.30;

    fn assert_close(actual: f64, expected: f64, tol: f64, msg: &str) {
        let diff = (actual - expected).abs();
        assert!(
            diff <= tol,
            "{}: expected {:.12}, got {:.12}, diff {:.2e} exceeds tol {:.2e}",
            msg,
            expected,
            actual,
            diff,
            tol,
        );
    }

    // -----------------------------------------------------------------------
    // 1. norm_cdf tests
    // -----------------------------------------------------------------------

    #[test]
    fn norm_cdf_at_zero() {
        assert_eq!(norm_cdf(0.0), 0.5, "norm_cdf(0) must be exactly 0.5");
    }

    #[test]
    fn norm_cdf_monotone() {
        let xs = [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0];
        for pair in xs.windows(2) {
            assert!(
                norm_cdf(pair[1]) > norm_cdf(pair[0]),
                "norm_cdf must be monotonically increasing: norm_cdf({}) = {} should be > norm_cdf({}) = {}",
                pair[1], norm_cdf(pair[1]), pair[0], norm_cdf(pair[0]),
            );
        }
    }

    #[test]
    fn norm_cdf_symmetry() {
        // Phi(-x) = 1 - Phi(x) for every x.
        for &x in &[0.5, 1.0, 1.5, 2.0, 2.5, 3.0] {
            assert_close(
                norm_cdf(-x),
                1.0 - norm_cdf(x),
                1e-12,
                &format!("symmetry at x={}", x),
            );
        }
    }

    #[test]
    fn norm_cdf_known_values() {
        // Reference values from the standard normal table.
        let cases = [
            (-2.0, 0.022_750_131_948_179_2),
            (-1.0, 0.158_655_253_931_457_1),
            (1.0, 0.841_344_746_068_543_0),
            (2.0, 0.977_249_868_051_820_8),
        ];
        for &(x, expected) in &cases {
            assert_close(
                norm_cdf(x),
                expected,
                1e-6,
                &format!("norm_cdf({})", x),
            );
        }
    }

    #[test]
    fn norm_cdf_extreme_tails() {
        // Very large positive -> 1, very large negative -> 0.
        assert!(norm_cdf(10.0) > 1.0 - 1e-15, "norm_cdf(10) ~ 1");
        assert!(norm_cdf(-10.0) < 1e-15, "norm_cdf(-10) ~ 0");
    }

    // -----------------------------------------------------------------------
    // 2. bsm_price tests
    // -----------------------------------------------------------------------

    #[test]
    fn bsm_price_atm_call_positive() {
        let price = bsm_price(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, true);
        assert!(
            price > 0.0,
            "ATM call price must be positive, got {}",
            price,
        );
    }

    #[test]
    fn bsm_price_atm_put_positive() {
        let price = bsm_price(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, false);
        assert!(
            price > 0.0,
            "ATM put price must be positive, got {}",
            price,
        );
    }

    #[test]
    fn bsm_price_put_call_parity() {
        // C - P = S*exp(-qT) - K*exp(-rT)
        let call = bsm_price(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, true);
        let put = bsm_price(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, false);
        let forward_diff =
            ATM_S * (-ATM_Q * ATM_T).exp() - ATM_K * (-ATM_R * ATM_T).exp();
        assert_close(
            call - put,
            forward_diff,
            1e-10,
            "put-call parity (ATM)",
        );
    }

    #[test]
    fn bsm_price_put_call_parity_ditm() {
        // Also verify parity with the deep ITM parameters.
        let call = bsm_price(DITM_S, DITM_K, DITM_T, DITM_R, DITM_Q, DITM_SIGMA, true);
        let put = bsm_price(DITM_S, DITM_K, DITM_T, DITM_R, DITM_Q, DITM_SIGMA, false);
        let forward_diff =
            DITM_S * (-DITM_Q * DITM_T).exp() - DITM_K * (-DITM_R * DITM_T).exp();
        assert_close(
            call - put,
            forward_diff,
            1e-10,
            "put-call parity (deep ITM)",
        );
    }

    #[test]
    fn bsm_price_deep_itm_call_near_intrinsic() {
        // Deep ITM call price ≈ S - K*exp(-rT).
        // The time value is O(S * sigma * sqrt(T)) for deep ITM, so use a
        // generous tolerance proportional to that.
        let call = bsm_price(DITM_S, DITM_K, DITM_T, DITM_R, DITM_Q, DITM_SIGMA, true);
        let intrinsic = DITM_S - DITM_K * (-DITM_R * DITM_T).exp();
        // The time-value overshoot should be small relative to spot.
        let time_value = call - intrinsic;
        assert!(
            time_value >= 0.0,
            "deep ITM call must be >= intrinsic, time_value = {}",
            time_value,
        );
        // Generous bound: time value < 10% of spot for deep ITM.
        assert!(
            time_value < 0.10 * DITM_S,
            "time value {} should be small relative to spot",
            time_value,
        );
    }

    #[test]
    fn bsm_price_increases_with_vol() {
        // Vega > 0: price should increase with volatility.
        let price_lo = bsm_price(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, 0.15, true);
        let price_mid = bsm_price(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, 0.20, true);
        let price_hi = bsm_price(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, 0.30, true);
        assert!(
            price_lo < price_mid && price_mid < price_hi,
            "call price must increase with vol: {:.6} < {:.6} < {:.6}",
            price_lo,
            price_mid,
            price_hi,
        );

        // Also for puts.
        let put_lo = bsm_price(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, 0.15, false);
        let put_hi = bsm_price(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, 0.30, false);
        assert!(
            put_lo < put_hi,
            "put price must increase with vol: {:.6} < {:.6}",
            put_lo,
            put_hi,
        );
    }

    // -----------------------------------------------------------------------
    // 3. implied_volatility tests
    // -----------------------------------------------------------------------

    #[test]
    fn iv_round_trip_atm_call() {
        let price = bsm_price(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, true);
        let result = implied_volatility(price, ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, true);
        assert_eq!(result.status, IvStatus::Ok, "ATM call round-trip status");
        assert_close(
            result.iv.unwrap(),
            ATM_SIGMA,
            1e-8,
            "ATM call round-trip IV",
        );
    }

    #[test]
    fn iv_round_trip_atm_put() {
        let price = bsm_price(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, false);
        let result = implied_volatility(price, ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, false);
        assert_eq!(result.status, IvStatus::Ok, "ATM put round-trip status");
        assert_close(
            result.iv.unwrap(),
            ATM_SIGMA,
            1e-8,
            "ATM put round-trip IV",
        );
    }

    #[test]
    fn iv_round_trip_ditm_call() {
        let price = bsm_price(DITM_S, DITM_K, DITM_T, DITM_R, DITM_Q, DITM_SIGMA, true);
        let result = implied_volatility(price, DITM_S, DITM_K, DITM_T, DITM_R, DITM_Q, true);
        assert_eq!(result.status, IvStatus::Ok, "deep ITM call round-trip status");
        assert_close(
            result.iv.unwrap(),
            DITM_SIGMA,
            1e-8,
            "deep ITM call round-trip IV",
        );
    }

    #[test]
    fn iv_round_trip_various_sigmas() {
        // Round-trip at several volatility levels.
        for &sigma in &[0.05, 0.10, 0.50, 1.0, 2.0] {
            let price = bsm_price(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, sigma, true);
            let result = implied_volatility(price, ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, true);
            assert_eq!(
                result.status,
                IvStatus::Ok,
                "round-trip status for sigma={}",
                sigma,
            );
            assert_close(
                result.iv.unwrap(),
                sigma,
                1e-8,
                &format!("round-trip IV for sigma={}", sigma),
            );
        }
    }

    #[test]
    fn iv_below_intrinsic() {
        // A call price below intrinsic should return BelowIntrinsic.
        // Intrinsic = S*exp(-qT) - K*exp(-rT) for ATM with q < r is slightly negative,
        // so use the deep ITM case where intrinsic is large and positive.
        let intrinsic = DITM_S * (-DITM_Q * DITM_T).exp() - DITM_K * (-DITM_R * DITM_T).exp();
        // Price well below intrinsic.
        let price = intrinsic - 1.0;
        assert!(price > 0.0, "test price must be positive");
        let result = implied_volatility(price, DITM_S, DITM_K, DITM_T, DITM_R, DITM_Q, true);
        assert_eq!(
            result.status,
            IvStatus::BelowIntrinsic,
            "below-intrinsic status",
        );
        assert!(result.iv.is_none(), "below-intrinsic should have no IV");
    }

    #[test]
    fn iv_zero_price_non_finite() {
        // Zero price => NonFiniteInput (market_price <= 0.0 guard).
        let result = implied_volatility(0.0, ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, true);
        assert_eq!(result.status, IvStatus::NonFiniteInput, "zero price status");
        assert!(result.iv.is_none());
    }

    #[test]
    fn iv_negative_price_non_finite() {
        let result = implied_volatility(-1.0, ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, true);
        assert_eq!(
            result.status,
            IvStatus::NonFiniteInput,
            "negative price status",
        );
    }

    #[test]
    fn iv_nan_input_non_finite() {
        let result = implied_volatility(f64::NAN, ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, true);
        assert_eq!(result.status, IvStatus::NonFiniteInput, "NaN price status");
    }

    #[test]
    fn iv_very_high_price_no_bracket() {
        // A call price far above any BSM price (even at sigma=10) should fail to bracket.
        // Max BSM call at sigma=10 is bounded by S*exp(-qT), so use a price above that.
        let absurd_price = ATM_S * 10.0;
        let result =
            implied_volatility(absurd_price, ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, true);
        assert_eq!(
            result.status,
            IvStatus::NoBracket,
            "very high price should yield NoBracket",
        );
        assert!(result.iv.is_none());
    }

    #[test]
    fn iv_convergence_small_t() {
        // Small T = 1 day expressed in years.
        let t_small = 1.0 / 365.0;
        let sigma = 0.25;
        let price = bsm_price(ATM_S, ATM_K, t_small, ATM_R, ATM_Q, sigma, true);
        let result = implied_volatility(price, ATM_S, ATM_K, t_small, ATM_R, ATM_Q, true);
        assert!(
            result.status == IvStatus::Ok || result.status == IvStatus::NearExpiryApprox,
            "small T status: {:?}",
            result.status,
        );
        if result.status == IvStatus::Ok {
            assert_close(
                result.iv.unwrap(),
                sigma,
                1e-6,
                "small T round-trip IV",
            );
        }
    }

    #[test]
    fn iv_convergence_large_t() {
        // Large T = 5 years.
        let t_large = 5.0;
        let sigma = 0.20;
        let price = bsm_price(ATM_S, ATM_K, t_large, ATM_R, ATM_Q, sigma, true);
        let result = implied_volatility(price, ATM_S, ATM_K, t_large, ATM_R, ATM_Q, true);
        assert_eq!(result.status, IvStatus::Ok, "large T status");
        assert_close(
            result.iv.unwrap(),
            sigma,
            1e-8,
            "large T round-trip IV",
        );
    }

    // -----------------------------------------------------------------------
    // 4. bsm_greeks tests
    // -----------------------------------------------------------------------

    #[test]
    fn greeks_call_delta_in_range() {
        let g = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, true);
        assert!(
            g.delta > 0.0 && g.delta < 1.0,
            "call delta must be in (0,1), got {}",
            g.delta,
        );
    }

    #[test]
    fn greeks_put_delta_in_range() {
        let g = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, false);
        assert!(
            g.delta > -1.0 && g.delta < 0.0,
            "put delta must be in (-1,0), got {}",
            g.delta,
        );
    }

    #[test]
    fn greeks_gamma_positive() {
        let gc = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, true);
        let gp = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, false);
        assert!(gc.gamma > 0.0, "call gamma must be positive, got {}", gc.gamma);
        assert!(gp.gamma > 0.0, "put gamma must be positive, got {}", gp.gamma);
    }

    #[test]
    fn greeks_gamma_equal_for_call_and_put() {
        // Gamma is the same for call and put with the same parameters.
        let gc = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, true);
        let gp = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, false);
        assert_close(gc.gamma, gp.gamma, 1e-14, "call gamma == put gamma");
    }

    #[test]
    fn greeks_call_theta_negative() {
        // For a typical ATM call, theta should be negative (time decay).
        let g = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, true);
        assert!(
            g.theta < 0.0,
            "call theta should be negative, got {}",
            g.theta,
        );
    }

    #[test]
    fn greeks_vega_positive() {
        let gc = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, true);
        let gp = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, false);
        assert!(gc.vega > 0.0, "call vega must be positive, got {}", gc.vega);
        assert!(gp.vega > 0.0, "put vega must be positive, got {}", gp.vega);
    }

    #[test]
    fn greeks_vega_equal_for_call_and_put() {
        // Vega is the same for call and put with the same parameters.
        let gc = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, true);
        let gp = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, false);
        assert_close(gc.vega, gp.vega, 1e-14, "call vega == put vega");
    }

    #[test]
    fn greeks_put_call_delta_parity() {
        // delta_call - delta_put = exp(-qT)
        let gc = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, true);
        let gp = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, false);
        let expected = (-ATM_Q * ATM_T).exp();
        assert_close(
            gc.delta - gp.delta,
            expected,
            1e-10,
            "put-call delta parity",
        );
    }

    #[test]
    fn greeks_deep_itm_call_delta_near_one() {
        let g = bsm_greeks(DITM_S, DITM_K, DITM_T, DITM_R, DITM_Q, DITM_SIGMA, true);
        assert!(
            g.delta > 0.85,
            "deep ITM call delta should be near 1, got {}",
            g.delta,
        );
    }

    #[test]
    fn greeks_deep_itm_call_gamma_small() {
        // For deep ITM, gamma should be smaller than ATM gamma.
        let g_atm = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, true);
        let g_ditm = bsm_greeks(DITM_S, DITM_K, DITM_T, DITM_R, DITM_Q, DITM_SIGMA, true);
        assert!(
            g_ditm.gamma < g_atm.gamma,
            "deep ITM gamma ({}) should be < ATM gamma ({})",
            g_ditm.gamma,
            g_atm.gamma,
        );
    }

    #[test]
    fn greeks_call_rho_positive() {
        // Call rho should be positive (call value increases with rates).
        let g = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, true);
        assert!(g.rho > 0.0, "call rho must be positive, got {}", g.rho);
    }

    #[test]
    fn greeks_put_rho_negative() {
        // Put rho should be negative.
        let g = bsm_greeks(ATM_S, ATM_K, ATM_T, ATM_R, ATM_Q, ATM_SIGMA, false);
        assert!(g.rho < 0.0, "put rho must be negative, got {}", g.rho);
    }
}
