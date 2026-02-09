use upq_ingest::cli::{parse_args, IngestCommand};

#[test]
fn parse_args_reads_sync_sample_options() -> Result<(), Box<dyn std::error::Error>> {
    let args = vec![
        "upq-ingest".to_string(),
        "sync-sample".to_string(),
        "--host".to_string(),
        "qlib".to_string(),
        "--days".to_string(),
        "14".to_string(),
        "--local-root".to_string(),
        "./raw_sample".to_string(),
        "--execute".to_string(),
    ];

    let command = parse_args(&args)?;
    match command {
        IngestCommand::SyncSample(opts) => {
            assert_eq!(opts.host, "qlib");
            assert_eq!(opts.days, 14);
            assert_eq!(opts.local_root, "./raw_sample");
            assert!(opts.execute);
        }
        IngestCommand::Ingest(_) => {
            return Err(std::io::Error::other("expected sync-sample command").into());
        }
    }

    Ok(())
}

#[test]
fn parse_args_rejects_unknown_subcommand() {
    let args = vec!["upq-ingest".to_string(), "oops".to_string()];
    let parsed = parse_args(&args);
    assert!(parsed.is_err());
}

#[test]
fn parse_args_rejects_zero_days() {
    let args = vec![
        "upq-ingest".to_string(),
        "sync-sample".to_string(),
        "--days".to_string(),
        "0".to_string(),
    ];

    let parsed = parse_args(&args);
    assert!(parsed.is_err());
}

#[test]
fn parse_args_reads_ingest_options() -> Result<(), Box<dyn std::error::Error>> {
    let args = vec![
        "upq-ingest".to_string(),
        "ingest".to_string(),
        "--raw-root".to_string(),
        "./raw_sample".to_string(),
        "--storage-root".to_string(),
        "./storage".to_string(),
        "--manifest".to_string(),
        "./state/manifest.sqlite".to_string(),
    ];

    let command = parse_args(&args)?;
    match command {
        IngestCommand::Ingest(opts) => {
            assert_eq!(opts.raw_root, "./raw_sample");
            assert_eq!(opts.storage_root, "./storage");
            assert_eq!(opts.manifest_path, "./state/manifest.sqlite");
        }
        IngestCommand::SyncSample(_) => {
            return Err(std::io::Error::other("expected ingest command").into());
        }
    }

    Ok(())
}
