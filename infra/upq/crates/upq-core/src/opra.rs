use chrono::NaiveDate;
use regex::Regex;

use crate::error::CoreError;

#[derive(Debug, Clone, PartialEq)]
pub struct ParsedOpraContract {
    pub underlying: String,
    pub expiry: String,
    pub right: String,
    pub strike: f64,
}

pub fn parse_opra_contract(contract: &str) -> Result<ParsedOpraContract, CoreError> {
    let pattern = Regex::new(r"^O:([A-Z]+)[0-9]{0,2}(\d{6})([CP])(\d{8})$")
        .map_err(|_| CoreError::InvalidOpraContract(contract.to_string()))?;

    let captures = pattern
        .captures(contract)
        .ok_or_else(|| CoreError::InvalidOpraContract(contract.to_string()))?;

    let underlying = captures
        .get(1)
        .map(|m| m.as_str().to_string())
        .ok_or_else(|| CoreError::InvalidOpraContract(contract.to_string()))?;
    let expiry_yy_mm_dd = captures
        .get(2)
        .map(|m| m.as_str())
        .ok_or_else(|| CoreError::InvalidOpraContract(contract.to_string()))?;
    let expiry = NaiveDate::parse_from_str(expiry_yy_mm_dd, "%y%m%d")
        .map_err(|_| CoreError::InvalidOpraContract(contract.to_string()))?
        .format("%Y-%m-%d")
        .to_string();
    let right = captures
        .get(3)
        .map(|m| m.as_str().to_string())
        .ok_or_else(|| CoreError::InvalidOpraContract(contract.to_string()))?;
    let strike = captures
        .get(4)
        .map(|m| m.as_str())
        .ok_or_else(|| CoreError::InvalidOpraContract(contract.to_string()))?
        .parse::<f64>()
        .map_err(|_| CoreError::InvalidOpraContract(contract.to_string()))?
        / 1000.0;

    Ok(ParsedOpraContract {
        underlying,
        expiry,
        right,
        strike,
    })
}
