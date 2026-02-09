use std::process::ExitCode;

use upq_ingest::cli::{parse_args, IngestCommand};
use upq_ingest::ingest::{run_ingest, IngestOptions};
use upq_ingest::sync_plan::build_sample_sync_plan;
use upq_ingest::sync_remote::{collect_remote_files, run_sync_plan};

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();

    let command = match parse_args(&args) {
        Ok(command) => command,
        Err(error) => {
            eprintln!("argument error: {error}");
            print_usage();
            return ExitCode::from(2);
        }
    };

    match command {
        IngestCommand::SyncSample(options) => {
            let lists = match collect_remote_files(&options.host, &options.remote_root) {
                Ok(lists) => lists,
                Err(error) => {
                    eprintln!("failed to list remote files: {error}");
                    return ExitCode::from(1);
                }
            };

            let plan = match build_sample_sync_plan(&lists, options.days, &options.local_root) {
                Ok(plan) => plan,
                Err(error) => {
                    eprintln!("failed to build sync plan: {error}");
                    return ExitCode::from(1);
                }
            };

            if let Err(error) = run_sync_plan(&options.host, &plan, options.execute) {
                eprintln!("failed to execute sync plan: {error}");
                return ExitCode::from(1);
            }
        }
        IngestCommand::Ingest(options) => {
            let report = match run_ingest(&IngestOptions {
                raw_root: options.raw_root.into(),
                storage_root: options.storage_root.into(),
                manifest_path: options.manifest_path.into(),
            }) {
                Ok(value) => value,
                Err(error) => {
                    eprintln!("ingest failed: {error}");
                    return ExitCode::from(1);
                }
            };

            println!(
                "ingest complete: processed_files={} skipped_files={}",
                report.processed_files, report.skipped_files
            );
        }
    }

    ExitCode::SUCCESS
}

fn print_usage() {
    eprintln!(
        "usage:\n  upq-ingest sync-sample [--host qlib] [--days 14] [--remote-root /home/qlib/data] [--local-root ./raw_sample] [--execute]\n  upq-ingest ingest [--raw-root ./raw_sample] [--storage-root ./storage] [--manifest ./state/manifest.sqlite]"
    );
}
