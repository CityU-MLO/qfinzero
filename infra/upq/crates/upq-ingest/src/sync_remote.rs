use std::fs;
use std::process::Command;

use thiserror::Error;

use crate::sync_plan::{DatasetFileLists, SyncItem};

#[derive(Debug, Error)]
pub enum SyncRemoteError {
    #[error("command failed: {0}")]
    CommandFailed(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

const SSH_CONNECT_TIMEOUT_ARG: &str = "ConnectTimeout=10";
const SSH_SERVER_ALIVE_INTERVAL_ARG: &str = "ServerAliveInterval=15";
const SSH_SERVER_ALIVE_COUNT_MAX_ARG: &str = "ServerAliveCountMax=2";
const RSYNC_IO_TIMEOUT_SECONDS: &str = "120";

pub fn collect_remote_files(
    host: &str,
    remote_root: &str,
) -> Result<DatasetFileLists, SyncRemoteError> {
    let normalized_root = normalize_remote_root(remote_root);
    let quoted_root = shell_quote(&normalized_root);

    let stock_day = ssh_glob(
        host,
        &format!(
            "ls -1 {}/stock/us_stocks_sip_day_aggs_v1_*.csv.gz 2>/dev/null | sort",
            quoted_root
        ),
    )?;
    let stock_minute = ssh_glob(
        host,
        &format!(
            "ls -1 {}/stock/us_stocks_sip_minute_aggs_v1_*.csv.gz 2>/dev/null | sort",
            quoted_root
        ),
    )?;
    let option_day = ssh_glob(host, &build_option_day_find_cmd(&normalized_root))?;
    let option_minute = ssh_glob(host, &build_option_minute_find_cmd(&normalized_root))?;

    let rates_path = join_remote_path(&normalized_root, "assets/treasury_yields.csv");
    let rates_file = if ssh_file_exists(host, &rates_path)? {
        Some(rates_path)
    } else {
        None
    };

    let dividends_path = "/home/qlib/news/massive_dividends.sqlite";
    let dividends_file = if ssh_file_exists(host, dividends_path)? {
        Some(dividends_path.to_string())
    } else {
        None
    };

    Ok(DatasetFileLists {
        stock_day,
        stock_minute,
        option_day,
        option_minute,
        rates_file,
        dividends_file,
    })
}

pub fn run_sync_plan(host: &str, plan: &[SyncItem], execute: bool) -> Result<(), SyncRemoteError> {
    for item in plan {
        println!("SYNC {} -> {}", item.remote_path, item.local_dir);
        if !execute {
            continue;
        }

        fs::create_dir_all(&item.local_dir)?;
        let remote = format!("{}:{}", host, item.remote_path);
        let output = Command::new("rsync")
            .arg("-avz")
            .arg(format!("--timeout={RSYNC_IO_TIMEOUT_SECONDS}"))
            .arg(remote)
            .arg(item.local_dir.as_str())
            .output()?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            return Err(SyncRemoteError::CommandFailed(stderr));
        }
    }

    Ok(())
}

fn ssh_glob(host: &str, remote_cmd: &str) -> Result<Vec<String>, SyncRemoteError> {
    let output = Command::new("ssh")
        .args(ssh_timeout_args())
        .arg(host)
        .arg(remote_cmd)
        .output()?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        return Err(SyncRemoteError::CommandFailed(stderr));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    Ok(stdout
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .map(ToString::to_string)
        .collect())
}

fn ssh_file_exists(host: &str, remote_file: &str) -> Result<bool, SyncRemoteError> {
    let cmd = format!(
        "if [ -f '{}' ]; then echo yes; else echo no; fi",
        remote_file.replace('\'', "'\"'\"'")
    );
    let output = Command::new("ssh")
        .args(ssh_timeout_args())
        .arg(host)
        .arg(cmd)
        .output()?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        return Err(SyncRemoteError::CommandFailed(stderr));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    Ok(stdout.trim() == "yes")
}

fn shell_quote(input: &str) -> String {
    format!("'{}'", input.replace('\'', "'\"'\"'"))
}

fn normalize_remote_root(remote_root: &str) -> String {
    let trimmed = remote_root.trim_end_matches('/');
    if trimmed.is_empty() {
        "/".to_string()
    } else {
        trimmed.to_string()
    }
}

fn join_remote_path(root: &str, suffix: &str) -> String {
    if root == "/" {
        format!("/{suffix}")
    } else {
        format!("{root}/{suffix}")
    }
}

fn ssh_timeout_args() -> [&'static str; 8] {
    [
        "-o",
        "BatchMode=yes",
        "-o",
        SSH_CONNECT_TIMEOUT_ARG,
        "-o",
        SSH_SERVER_ALIVE_INTERVAL_ARG,
        "-o",
        SSH_SERVER_ALIVE_COUNT_MAX_ARG,
    ]
}

fn build_option_day_find_cmd(remote_root: &str) -> String {
    let option_day_root = join_remote_path(remote_root, "us_options_opra/day_aggs_v1");
    format!(
        "find {} -type f -name '*.csv.gz' | sort",
        shell_quote(&option_day_root)
    )
}

fn build_option_minute_find_cmd(remote_root: &str) -> String {
    let option_minute_root = join_remote_path(remote_root, "us_options_opra/minute_aggs_v1");
    format!(
        "find {} -type f -name '*.csv.gz' | sort",
        shell_quote(&option_minute_root)
    )
}

#[cfg(test)]
mod tests {
    use super::{
        build_option_day_find_cmd, build_option_minute_find_cmd, join_remote_path, shell_quote,
    };

    #[test]
    fn shell_quote_quotes_special_characters() {
        let escaped = shell_quote("/tmp/data;rm -rf /");
        assert_eq!(escaped, "'/tmp/data;rm -rf /'");
    }

    #[test]
    fn shell_quote_handles_single_quotes() {
        let escaped = shell_quote("/tmp/o'hare/data");
        assert_eq!(escaped, "'/tmp/o'\"'\"'hare/data'");
    }

    #[test]
    fn join_remote_path_handles_root_directory() {
        assert_eq!(
            join_remote_path("/", "assets/treasury_yields.csv"),
            "/assets/treasury_yields.csv"
        );
        assert_eq!(
            join_remote_path("/home/qlib/data", "assets/treasury_yields.csv"),
            "/home/qlib/data/assets/treasury_yields.csv"
        );
    }

    #[test]
    fn option_day_find_command_targets_exact_day_aggs_path() {
        let cmd = build_option_day_find_cmd("/home/qlib/data");
        assert_eq!(
            cmd,
            "find '/home/qlib/data/us_options_opra/day_aggs_v1' -type f -name '*.csv.gz' | sort"
        );
    }

    #[test]
    fn option_minute_find_command_targets_exact_minute_aggs_path() {
        let cmd = build_option_minute_find_cmd("/home/qlib/data");
        assert_eq!(
            cmd,
            "find '/home/qlib/data/us_options_opra/minute_aggs_v1' -type f -name '*.csv.gz' | sort"
        );
    }
}
