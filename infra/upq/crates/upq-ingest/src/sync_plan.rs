use std::collections::BTreeSet;

use thiserror::Error;

use crate::sample_sync::{latest_n_trade_dates, select_files_for_dates, SampleSyncError};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DatasetFileLists {
    pub stock_day: Vec<String>,
    pub stock_minute: Vec<String>,
    pub option_day: Vec<String>,
    pub option_minute: Vec<String>,
    pub rates_file: Option<String>,
    pub dividends_file: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SyncItem {
    pub remote_path: String,
    pub local_dir: String,
}

#[derive(Debug, Error)]
pub enum SyncPlanError {
    #[error("source dataset has no files: {0}")]
    EmptyDataset(&'static str),
    #[error(transparent)]
    Sample(#[from] SampleSyncError),
}

pub fn build_sample_sync_plan(
    lists: &DatasetFileLists,
    days: usize,
    local_root: &str,
) -> Result<Vec<SyncItem>, SyncPlanError> {
    if lists.stock_day.is_empty() {
        return Err(SyncPlanError::EmptyDataset("stock_day"));
    }
    if lists.stock_minute.is_empty() {
        return Err(SyncPlanError::EmptyDataset("stock_minute"));
    }
    if lists.option_day.is_empty() {
        return Err(SyncPlanError::EmptyDataset("option_day"));
    }
    if lists.option_minute.is_empty() {
        return Err(SyncPlanError::EmptyDataset("option_minute"));
    }

    let stock_day_dates = latest_n_trade_dates(&lists.stock_day, days)?;
    let stock_minute_dates = latest_n_trade_dates(&lists.stock_minute, days)?;
    let option_day_dates = latest_n_trade_dates(&lists.option_day, days)?;
    let option_minute_dates = latest_n_trade_dates(&lists.option_minute, days)?;

    let mut items = Vec::new();
    items.extend(to_sync_items(
        &select_files_for_dates(&lists.stock_day, &stock_day_dates),
        format!("{local_root}/stock/day"),
    ));
    items.extend(to_sync_items(
        &select_files_for_dates(&lists.stock_minute, &stock_minute_dates),
        format!("{local_root}/stock/minute"),
    ));
    items.extend(to_sync_items(
        &select_files_for_dates(&lists.option_day, &option_day_dates),
        format!("{local_root}/options/day"),
    ));
    items.extend(to_sync_items(
        &select_files_for_dates(&lists.option_minute, &option_minute_dates),
        format!("{local_root}/options/minute"),
    ));

    if let Some(rates) = lists.rates_file.as_deref() {
        items.push(SyncItem {
            remote_path: rates.to_string(),
            local_dir: format!("{local_root}/assets"),
        });
    }

    if let Some(div) = lists.dividends_file.as_deref() {
        items.push(SyncItem {
            remote_path: div.to_string(),
            local_dir: format!("{local_root}/dividends"),
        });
    }

    Ok(dedup_items(items))
}

fn to_sync_items(paths: &[String], local_dir: String) -> Vec<SyncItem> {
    paths
        .iter()
        .map(|remote_path| SyncItem {
            remote_path: remote_path.to_string(),
            local_dir: local_dir.clone(),
        })
        .collect()
}

fn dedup_items(items: Vec<SyncItem>) -> Vec<SyncItem> {
    let mut seen = BTreeSet::new();
    let mut out = Vec::new();

    for item in items {
        let key = format!("{}|{}", item.remote_path, item.local_dir);
        if seen.insert(key) {
            out.push(item);
        }
    }

    out
}
