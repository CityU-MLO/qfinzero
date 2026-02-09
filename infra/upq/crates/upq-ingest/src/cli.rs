use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SyncSampleOptions {
    pub host: String,
    pub days: usize,
    pub remote_root: String,
    pub local_root: String,
    pub execute: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IngestRunOptions {
    pub raw_root: String,
    pub storage_root: String,
    pub manifest_path: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompactRunOptions {
    pub storage_root: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IngestCommand {
    SyncSample(SyncSampleOptions),
    Ingest(IngestRunOptions),
    Compact(CompactRunOptions),
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum ParseArgsError {
    #[error("missing subcommand; supported: sync-sample")]
    MissingSubcommand,
    #[error("unsupported subcommand: {0}")]
    UnsupportedSubcommand(String),
    #[error("missing value for flag: {0}")]
    MissingFlagValue(String),
    #[error("invalid --days value: {0}")]
    InvalidDays(String),
    #[error("unknown flag for sync-sample: {0}")]
    UnknownFlag(String),
    #[error("unknown flag for ingest: {0}")]
    UnknownIngestFlag(String),
    #[error("unknown flag for compact: {0}")]
    UnknownCompactFlag(String),
}

pub fn parse_args(args: &[String]) -> Result<IngestCommand, ParseArgsError> {
    let subcommand = args.get(1).ok_or(ParseArgsError::MissingSubcommand)?;
    match subcommand.as_str() {
        "sync-sample" => parse_sync_sample(args),
        "ingest" => parse_ingest(args),
        "compact" => parse_compact(args),
        other => Err(ParseArgsError::UnsupportedSubcommand(other.to_string())),
    }
}

fn parse_sync_sample(args: &[String]) -> Result<IngestCommand, ParseArgsError> {
    let mut options = SyncSampleOptions {
        host: "qlib".to_string(),
        days: 14,
        remote_root: "/home/qlib/data".to_string(),
        local_root: "./raw_sample".to_string(),
        execute: false,
    };

    let mut index = 2;
    while index < args.len() {
        let flag = &args[index];
        match flag.as_str() {
            "--host" => {
                let value = next_value(args, index, flag)?;
                options.host = value.to_string();
                index += 2;
            }
            "--days" => {
                let value = next_value(args, index, flag)?;
                let parsed = value
                    .parse::<usize>()
                    .map_err(|_| ParseArgsError::InvalidDays(value.to_string()))?;
                if parsed == 0 {
                    return Err(ParseArgsError::InvalidDays(value.to_string()));
                }
                options.days = parsed;
                index += 2;
            }
            "--remote-root" => {
                let value = next_value(args, index, flag)?;
                options.remote_root = value.to_string();
                index += 2;
            }
            "--local-root" => {
                let value = next_value(args, index, flag)?;
                options.local_root = value.to_string();
                index += 2;
            }
            "--execute" => {
                options.execute = true;
                index += 1;
            }
            other => return Err(ParseArgsError::UnknownFlag(other.to_string())),
        }
    }

    Ok(IngestCommand::SyncSample(options))
}

fn parse_ingest(args: &[String]) -> Result<IngestCommand, ParseArgsError> {
    let mut options = IngestRunOptions {
        raw_root: "./raw_sample".to_string(),
        storage_root: "./storage".to_string(),
        manifest_path: "./state/manifest.sqlite".to_string(),
    };

    let mut index = 2;
    while index < args.len() {
        let flag = &args[index];
        match flag.as_str() {
            "--raw-root" => {
                let value = next_value(args, index, flag)?;
                options.raw_root = value.to_string();
                index += 2;
            }
            "--storage-root" => {
                let value = next_value(args, index, flag)?;
                options.storage_root = value.to_string();
                index += 2;
            }
            "--manifest" => {
                let value = next_value(args, index, flag)?;
                options.manifest_path = value.to_string();
                index += 2;
            }
            other => return Err(ParseArgsError::UnknownIngestFlag(other.to_string())),
        }
    }

    Ok(IngestCommand::Ingest(options))
}

fn parse_compact(args: &[String]) -> Result<IngestCommand, ParseArgsError> {
    let mut options = CompactRunOptions {
        storage_root: "./storage".to_string(),
    };

    let mut index = 2;
    while index < args.len() {
        let flag = &args[index];
        match flag.as_str() {
            "--storage-root" => {
                let value = next_value(args, index, flag)?;
                options.storage_root = value.to_string();
                index += 2;
            }
            other => return Err(ParseArgsError::UnknownCompactFlag(other.to_string())),
        }
    }

    Ok(IngestCommand::Compact(options))
}

fn next_value<'a>(args: &'a [String], index: usize, flag: &str) -> Result<&'a str, ParseArgsError> {
    args.get(index + 1)
        .map(|s| s.as_str())
        .ok_or_else(|| ParseArgsError::MissingFlagValue(flag.to_string()))
}
