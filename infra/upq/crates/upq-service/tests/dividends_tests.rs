use upq_service::dividends::{DividendCalendar, DividendEvent};

#[test]
fn empty_calendar_returns_zero_pv() {
    let cal = DividendCalendar::empty();
    let (pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    assert_eq!(pv, 0.0);
    assert_eq!(count, 0);
}

#[test]
fn unknown_ticker_returns_zero_pv() {
    let cal = DividendCalendar::from_events(vec![(
        "AAPL".to_string(),
        DividendEvent {
            ex_date_days: 19050,
            amount: 0.25,
        },
    )]);
    let (pv, count) = cal.pv_dividends("TSLA", 19000, 19100, 0.05);
    assert_eq!(pv, 0.0);
    assert_eq!(count, 0);
}

#[test]
fn single_dividend_in_range() {
    let cal = DividendCalendar::from_events(vec![(
        "AAPL".to_string(),
        DividendEvent {
            ex_date_days: 19050,
            amount: 0.25,
        },
    )]);
    let (pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    assert_eq!(count, 1);
    let t_i = 50.0 / 365.0;
    let expected = 0.25 * (-0.05_f64 * t_i).exp();
    assert!(
        (pv - expected).abs() < 1e-10,
        "pv={pv}, expected={expected}"
    );
}

#[test]
fn multiple_dividends_sum_correctly() {
    let cal = DividendCalendar::from_events(vec![
        (
            "AAPL".to_string(),
            DividendEvent {
                ex_date_days: 19030,
                amount: 0.25,
            },
        ),
        (
            "AAPL".to_string(),
            DividendEvent {
                ex_date_days: 19060,
                amount: 0.26,
            },
        ),
    ]);
    let (pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    assert_eq!(count, 2);
    let pv1 = 0.25 * (-0.05_f64 * 30.0 / 365.0).exp();
    let pv2 = 0.26 * (-0.05_f64 * 60.0 / 365.0).exp();
    assert!((pv - (pv1 + pv2)).abs() < 1e-10);
}

#[test]
fn excludes_dividend_on_obs_date() {
    let cal = DividendCalendar::from_events(vec![(
        "AAPL".to_string(),
        DividendEvent {
            ex_date_days: 19000,
            amount: 0.25,
        },
    )]);
    let (_pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    assert_eq!(count, 0);
    assert_eq!(_pv, 0.0);
}

#[test]
fn includes_dividend_on_expiry_date() {
    let cal = DividendCalendar::from_events(vec![(
        "AAPL".to_string(),
        DividendEvent {
            ex_date_days: 19100,
            amount: 0.25,
        },
    )]);
    let (_pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    assert_eq!(count, 1);
}

#[test]
fn excludes_dividends_outside_range() {
    let cal = DividendCalendar::from_events(vec![
        (
            "AAPL".to_string(),
            DividendEvent {
                ex_date_days: 18990,
                amount: 0.10,
            },
        ),
        (
            "AAPL".to_string(),
            DividendEvent {
                ex_date_days: 19050,
                amount: 0.25,
            },
        ),
        (
            "AAPL".to_string(),
            DividendEvent {
                ex_date_days: 19200,
                amount: 0.30,
            },
        ),
    ]);
    let (pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    assert_eq!(count, 1);
    let expected = 0.25 * (-0.05_f64 * 50.0 / 365.0).exp();
    assert!((pv - expected).abs() < 1e-10);
}

#[test]
fn zero_rate_means_no_discounting() {
    let cal = DividendCalendar::from_events(vec![(
        "AAPL".to_string(),
        DividendEvent {
            ex_date_days: 19050,
            amount: 1.00,
        },
    )]);
    let (pv, count) = cal.pv_dividends("AAPL", 19000, 19100, 0.0);
    assert_eq!(count, 1);
    assert!(
        (pv - 1.0).abs() < 1e-10,
        "at r=0, PV should equal face value"
    );
}

#[test]
fn multiple_tickers_are_independent() {
    let cal = DividendCalendar::from_events(vec![
        (
            "AAPL".to_string(),
            DividendEvent {
                ex_date_days: 19050,
                amount: 0.25,
            },
        ),
        (
            "MSFT".to_string(),
            DividendEvent {
                ex_date_days: 19050,
                amount: 0.75,
            },
        ),
    ]);
    let (pv_aapl, _) = cal.pv_dividends("AAPL", 19000, 19100, 0.05);
    let (pv_msft, _) = cal.pv_dividends("MSFT", 19000, 19100, 0.05);
    assert!(pv_msft > pv_aapl, "MSFT dividend is larger");
}
