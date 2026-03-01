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
