#![allow(clippy::expect_used)]

use upq_service::greeks::*;

/// Helper: assert float equality within tolerance.
fn assert_near(actual: f64, expected: f64, tol: f64, label: &str) {
    let diff = (actual - expected).abs();
    assert!(
        diff < tol,
        "{label}: expected {expected}, got {actual}, diff {diff} > tol {tol}"
    );
}

// ============== BSM Price Forward Tests ==============

#[test]
fn bsm_price_atm_call() {
    // ATM call: S=100, K=100, T=1, r=0.05, q=0, sigma=0.20
    let price = bsm_price(100.0, 100.0, 1.0, 0.05, 0.0, 0.20, true);
    // Expected ~10.45 (standard BSM reference)
    assert_near(price, 10.4506, 0.01, "ATM call price");
}

#[test]
fn bsm_price_atm_put() {
    // ATM put: S=100, K=100, T=1, r=0.05, q=0, sigma=0.20
    let price = bsm_price(100.0, 100.0, 1.0, 0.05, 0.0, 0.20, false);
    // Put = Call - S + K*exp(-rT) via put-call parity
    let call = bsm_price(100.0, 100.0, 1.0, 0.05, 0.0, 0.20, true);
    let expected = call - 100.0 + 100.0 * (-0.05_f64).exp();
    assert_near(price, expected, 1e-8, "ATM put via put-call parity");
}

#[test]
fn bsm_price_deep_itm_call() {
    // Deep ITM call: S=150, K=100, T=0.5, r=0.03, q=0, sigma=0.25
    let price = bsm_price(150.0, 100.0, 0.5, 0.03, 0.0, 0.25, true);
    // Should be close to intrinsic (about 50) + time value
    assert!(price > 50.0, "deep ITM call should be above intrinsic");
    assert!(price < 55.0, "deep ITM call should not be too high");
}

#[test]
fn bsm_price_deep_otm_call() {
    // Deep OTM call: S=50, K=100, T=0.5, r=0.03, q=0, sigma=0.25
    let price = bsm_price(50.0, 100.0, 0.5, 0.03, 0.0, 0.25, true);
    assert!(price < 0.01, "deep OTM call should be near zero");
}

#[test]
fn bsm_price_deep_itm_put() {
    // Deep ITM put: S=50, K=100, T=0.5, r=0.03, q=0, sigma=0.25
    let price = bsm_price(50.0, 100.0, 0.5, 0.03, 0.0, 0.25, false);
    assert!(
        price > 48.0,
        "deep ITM put should be above intrinsic minus discount"
    );
}

#[test]
fn bsm_price_deep_otm_put() {
    // Deep OTM put: S=150, K=100, T=0.5, r=0.03, q=0, sigma=0.25
    // The BSM price is approximately 0.035 — small but not < 0.01 for these parameters.
    let price = bsm_price(150.0, 100.0, 0.5, 0.03, 0.0, 0.25, false);
    assert!(price >= 0.0, "deep OTM put should be non-negative");
    assert!(price < 0.5, "deep OTM put should be small");
}

// ============== Put-Call Parity ==============

#[test]
fn put_call_parity_holds() {
    // C - P = S*exp(-qT) - K*exp(-rT)
    let s = 100.0;
    let k = 105.0;
    let t = 0.75;
    let r = 0.04;
    let q = 0.0;
    let sigma = 0.30;

    let call = bsm_price(s, k, t, r, q, sigma, true);
    let put = bsm_price(s, k, t, r, q, sigma, false);
    let expected_diff = s * (-q * t).exp() - k * (-r * t).exp();

    assert_near(call - put, expected_diff, 1e-8, "put-call parity");
}

// ============== Greeks Tests ==============

#[test]
fn greeks_delta_call_between_0_and_1() {
    let g = bsm_greeks(100.0, 100.0, 1.0, 0.05, 0.0, 0.20, true);
    assert!(
        g.delta > 0.0 && g.delta < 1.0,
        "call delta should be in (0,1), got {}",
        g.delta
    );
    // ATM call delta should be near 0.5 (slightly above due to drift)
    assert_near(g.delta, 0.6368, 0.01, "ATM call delta");
}

#[test]
fn greeks_delta_put_between_neg1_and_0() {
    let g = bsm_greeks(100.0, 100.0, 1.0, 0.05, 0.0, 0.20, false);
    assert!(
        g.delta > -1.0 && g.delta < 0.0,
        "put delta should be in (-1,0), got {}",
        g.delta
    );
}

#[test]
fn greeks_gamma_positive() {
    let g = bsm_greeks(100.0, 100.0, 1.0, 0.05, 0.0, 0.20, true);
    assert!(g.gamma > 0.0, "gamma should be positive");
    // Call and put gamma should be equal
    let gp = bsm_greeks(100.0, 100.0, 1.0, 0.05, 0.0, 0.20, false);
    assert_near(g.gamma, gp.gamma, 1e-10, "call/put gamma equal");
}

#[test]
fn greeks_theta_call_negative() {
    let g = bsm_greeks(100.0, 100.0, 1.0, 0.05, 0.0, 0.20, true);
    assert!(
        g.theta < 0.0,
        "theta per day should be negative for ATM call, got {}",
        g.theta
    );
}

#[test]
fn greeks_vega_positive() {
    let g = bsm_greeks(100.0, 100.0, 1.0, 0.05, 0.0, 0.20, true);
    assert!(g.vega > 0.0, "vega should be positive");
    // Call and put vega should be equal
    let gp = bsm_greeks(100.0, 100.0, 1.0, 0.05, 0.0, 0.20, false);
    assert_near(g.vega, gp.vega, 1e-10, "call/put vega equal");
}

#[test]
fn greeks_rho_call_positive() {
    let g = bsm_greeks(100.0, 100.0, 1.0, 0.05, 0.0, 0.20, true);
    assert!(g.rho > 0.0, "call rho should be positive");
}

#[test]
fn greeks_rho_put_negative() {
    let g = bsm_greeks(100.0, 100.0, 1.0, 0.05, 0.0, 0.20, false);
    assert!(g.rho < 0.0, "put rho should be negative");
}

// ============== IV Inversion Tests ==============

#[test]
fn iv_recovers_sigma_from_synthetic_price() {
    // Generate a BSM price with known sigma, then recover it.
    let sigma = 0.25;
    let s = 100.0;
    let k = 100.0;
    let t = 1.0;
    let r = 0.05;
    let q = 0.0;

    let price = bsm_price(s, k, t, r, q, sigma, true);
    let result = implied_volatility(price, s, k, t, r, q, true);

    assert_eq!(result.status, IvStatus::Ok);
    let recovered = result.iv.expect("should have IV");
    assert_near(recovered, sigma, 1e-8, "IV recovery from synthetic call");
}

#[test]
fn iv_recovers_sigma_from_synthetic_put() {
    let sigma = 0.35;
    let s = 110.0;
    let k = 100.0;
    let t = 0.5;
    let r = 0.03;
    let q = 0.0;

    let price = bsm_price(s, k, t, r, q, sigma, false);
    let result = implied_volatility(price, s, k, t, r, q, false);

    assert_eq!(result.status, IvStatus::Ok);
    let recovered = result.iv.expect("should have IV");
    assert_near(recovered, sigma, 1e-8, "IV recovery from synthetic put");
}

#[test]
fn iv_below_intrinsic_returns_status() {
    // Price below intrinsic for ITM call.
    let s = 110.0_f64;
    let k = 100.0_f64;
    let t = 1.0_f64;
    let r = 0.05_f64;
    let q = 0.0_f64;
    let intrinsic = s - k * (-r * t).exp();
    let price = intrinsic - 1.0; // below intrinsic

    let result = implied_volatility(price, s, k, t, r, q, true);
    assert_eq!(result.status, IvStatus::BelowIntrinsic);
    assert!(result.iv.is_none());
}

#[test]
fn iv_non_finite_input_returns_status() {
    let result = implied_volatility(f64::NAN, 100.0, 100.0, 1.0, 0.05, 0.0, true);
    assert_eq!(result.status, IvStatus::NonFiniteInput);
    assert!(result.iv.is_none());
}

#[test]
fn iv_negative_price_returns_non_finite() {
    let result = implied_volatility(-5.0, 100.0, 100.0, 1.0, 0.05, 0.0, true);
    assert_eq!(result.status, IvStatus::NonFiniteInput);
}

#[test]
fn iv_near_expiry_returns_approx() {
    // T very small (30 seconds).
    let t = 0.5 / (365.0 * 24.0 * 60.0);
    let result = implied_volatility(0.5, 100.0, 100.0, t, 0.05, 0.0, true);
    assert_eq!(result.status, IvStatus::NearExpiryApprox);
    assert!(result.iv.is_some());
}

#[test]
fn iv_convergence_within_100_iterations() {
    // Verify that normal inputs converge well within the iteration limit.
    let test_cases = vec![
        (100.0_f64, 100.0_f64, 1.0_f64, 0.05_f64, 0.20_f64, true),
        (100.0, 90.0, 0.5, 0.03, 0.30, true),
        (100.0, 110.0, 2.0, 0.02, 0.15, false),
        (50.0, 55.0, 0.25, 0.04, 0.40, false),
    ];

    for (s, k, t, r, sigma, is_call) in test_cases {
        let price = bsm_price(s, k, t, r, 0.0, sigma, is_call);
        let result = implied_volatility(price, s, k, t, r, 0.0, is_call);
        assert_eq!(
            result.status,
            IvStatus::Ok,
            "should converge for s={s}, k={k}, t={t}, r={r}, sigma={sigma}"
        );
        let recovered = result.iv.expect("should have IV");
        assert_near(
            recovered,
            sigma,
            1e-6,
            &format!("IV accuracy for s={s}, k={k}"),
        );
    }
}

#[test]
fn iv_impossible_market_price_returns_no_bracket() {
    // Call price cannot exceed spot (q=0). Use impossible market price.
    let result = implied_volatility(150.0, 100.0, 100.0, 0.5, 0.03, 0.0, true);
    assert_eq!(result.status, IvStatus::NoBracket);
    assert!(result.iv.is_none());
}

#[test]
fn iv_near_expiry_zero_time_value_returns_floor_iv() {
    // When T is below near-expiry threshold and price equals intrinsic,
    // implementation should return approximate floor IV.
    let t = 0.5 / (365.0 * 24.0 * 60.0); // 30s
    let s = 120.0_f64;
    let k = 100.0_f64;
    let r = 0.01_f64;
    let q = 0.0_f64;
    let intrinsic = (s * (-q * t).exp() - k * (-r * t).exp()).max(0.0);

    let result = implied_volatility(intrinsic, s, k, t, r, q, true);
    assert_eq!(result.status, IvStatus::NearExpiryApprox);
    let iv = result.iv.expect("near-expiry branch should return approximate IV");
    assert_near(iv, 0.001, 1e-12, "near-expiry floor IV");
}

#[test]
fn greeks_match_finite_difference_sensitivities() {
    let s = 100.0;
    let k = 95.0;
    let t = 0.75;
    let r = 0.03;
    let q = 0.0;
    let sigma = 0.22;

    let analytic = bsm_greeks(s, k, t, r, q, sigma, true);

    let ds = 0.05;
    let dvol = 1e-4;

    let price_up = bsm_price(s + ds, k, t, r, q, sigma, true);
    let price_mid = bsm_price(s, k, t, r, q, sigma, true);
    let price_dn = bsm_price(s - ds, k, t, r, q, sigma, true);

    let delta_fd = (price_up - price_dn) / (2.0 * ds);
    let gamma_fd = (price_up - 2.0 * price_mid + price_dn) / (ds * ds);

    let vega_up = bsm_price(s, k, t, r, q, sigma + dvol, true);
    let vega_dn = bsm_price(s, k, t, r, q, sigma - dvol, true);
    let vega_fd_per_1pct = ((vega_up - vega_dn) / (2.0 * dvol)) * 0.01;

    assert_near(analytic.delta, delta_fd, 4e-6, "delta finite-difference");
    assert_near(analytic.gamma, gamma_fd, 2e-6, "gamma finite-difference");
    assert_near(
        analytic.vega,
        vega_fd_per_1pct,
        2e-6,
        "vega finite-difference (per 1pct)",
    );
}

// ============== Compute Greeks Integration Tests ==============

#[test]
fn compute_greeks_returns_full_result() {
    let sigma = 0.25;
    let s = 100.0;
    let k = 100.0;
    let t = 1.0;
    let r = 0.05;
    let q = 0.0;

    let price = bsm_price(s, k, t, r, q, sigma, true);
    let (iv_result, greeks) = compute_greeks(price, s, k, t, r, q, true);

    assert_eq!(iv_result.status, IvStatus::Ok);
    assert!(iv_result.iv.is_some());
    let greeks = greeks.expect("should have greeks");
    assert!(greeks.delta > 0.0 && greeks.delta < 1.0);
    assert!(greeks.gamma > 0.0);
    assert!(greeks.theta < 0.0);
    assert!(greeks.vega > 0.0);
    assert!(greeks.rho > 0.0);
}

#[test]
fn compute_greeks_below_intrinsic_returns_none() {
    let s = 120.0_f64;
    let k = 100.0_f64;
    let t = 1.0_f64;
    let r = 0.05_f64;
    let q = 0.0_f64;
    let intrinsic = s - k * (-r * t).exp();
    let price = intrinsic - 2.0;

    let (iv_result, greeks) = compute_greeks(price, s, k, t, r, q, true);
    assert_eq!(iv_result.status, IvStatus::BelowIntrinsic);
    assert!(greeks.is_none());
}

// ============== Norm CDF Tests ==============

#[test]
fn norm_cdf_symmetry() {
    // Φ(-x) = 1 - Φ(x)
    let x = 1.5;
    assert_near(norm_cdf(-x), 1.0 - norm_cdf(x), 1e-12, "norm_cdf symmetry");
}

#[test]
fn norm_cdf_at_zero() {
    assert_near(norm_cdf(0.0), 0.5, 1e-12, "norm_cdf(0) = 0.5");
}

#[test]
fn norm_cdf_at_extremes() {
    assert_near(norm_cdf(10.0), 1.0, 1e-12, "norm_cdf(10) ≈ 1");
    assert_near(norm_cdf(-10.0), 0.0, 1e-12, "norm_cdf(-10) ≈ 0");
}
