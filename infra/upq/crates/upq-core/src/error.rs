use thiserror::Error;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum CoreError {
    #[error("invalid resolution: {0}")]
    InvalidResolution(String),
    #[error("unsupported field: {0}")]
    UnsupportedField(String),
    #[error("invalid OPRA contract: {0}")]
    InvalidOpraContract(String),
    #[error("invalid date: {0}")]
    InvalidDate(String),
    #[error("invalid date range: start must be <= end")]
    InvalidDateRange,
    #[error("unsupported tenor: {0}")]
    UnsupportedTenor(String),
}
