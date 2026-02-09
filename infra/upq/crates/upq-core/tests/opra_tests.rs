use upq_core::opra::parse_opra_contract;

#[test]
fn parse_opra_contract_parses_contract() -> Result<(), upq_core::error::CoreError> {
    let parsed = parse_opra_contract("O:NVDA250117C00136000")?;
    assert_eq!(parsed.underlying, "NVDA");
    assert_eq!(parsed.expiry, "2025-01-17");
    assert_eq!(parsed.right, "C");
    assert!((parsed.strike - 136.0).abs() < 1e-9);
    Ok(())
}

#[test]
fn parse_opra_contract_rejects_malformed_input() {
    let parsed = parse_opra_contract("BAD:NVDA");
    assert!(parsed.is_err());
}
