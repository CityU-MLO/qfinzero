//! Where a store's rows come from: converted partitions, or raw files read in place.
//!
//! The raw-data index (`qfz-data index`) writes `_state/index/views/<store>.json`
//! for the stores it can read straight from the vendors' files: the trade date of
//! each raw file, the converter's own projection as a template (`{src}`,
//! `{trade_date}`), and the converted part a raw file stands in for. When
//! `UPQ_IN_PLACE` names the store (`option_minute,option_day,stock_daily`, or
//! `all`), [`source`] reads those raw files through the template and adds the
//! other vendors' parts of the same dates; otherwise it reads the converted
//! partitions exactly as before.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::SystemTime;

use serde::Deserialize;

#[derive(Debug, Deserialize)]
pub struct View {
    pub store: String,
    pub replaces: String,
    pub template: String,
    pub date_expr: String,
    pub files: BTreeMap<String, String>,
}

fn lit(s: &str) -> String {
    format!("'{}'", s.replace('\'', "''"))
}

fn list(paths: &[String]) -> String {
    paths.iter().map(|p| lit(p)).collect::<Vec<_>>().join(", ")
}

/// Stores `UPQ_IN_PLACE` turns on (re-read each call so tests can set it).
pub fn enabled(store: &str) -> bool {
    std::env::var("UPQ_IN_PLACE")
        .map(|v| v.split(',').any(|s| s.trim() == store || s.trim() == "all"))
        .unwrap_or(false)
}

type Cache = Mutex<HashMap<PathBuf, (SystemTime, Arc<View>)>>;

fn cache() -> &'static Cache {
    static C: OnceLock<Cache> = OnceLock::new();
    C.get_or_init(|| Mutex::new(HashMap::new()))
}

/// The view file of `store`, reloaded when the index rewrites it.
pub fn load(root: &Path, store: &str) -> Option<Arc<View>> {
    let path = root.join("_state/index/views").join(format!("{store}.json"));
    let mtime = std::fs::metadata(&path).and_then(|m| m.modified()).ok()?;
    if let Ok(c) = cache().lock() {
        if let Some((t, v)) = c.get(&path) {
            if *t == mtime {
                return Some(Arc::clone(v));
            }
        }
    }
    let view: View = serde_json::from_str(&std::fs::read_to_string(&path).ok()?).ok()?;
    let view = Arc::new(view);
    if let Ok(mut c) = cache().lock() {
        c.insert(path, (mtime, Arc::clone(&view)));
    }
    Some(view)
}

fn parquet_files(dir: &Path) -> Vec<PathBuf> {
    let mut out: Vec<PathBuf> = std::fs::read_dir(dir)
        .map(|it| {
            it.filter_map(Result::ok)
                .map(|e| e.path())
                .filter(|p| p.extension().is_some_and(|x| x == "parquet"))
                .collect()
        })
        .unwrap_or_default();
    out.sort();
    out
}

/// Partition dirs of `store` with ET trade dates in `[start, end]`.
fn partitions(root: &Path, store: &str, start: &str, end: &str) -> Vec<(String, PathBuf)> {
    let mut out: Vec<(String, PathBuf)> = std::fs::read_dir(root.join(store))
        .map(|it| {
            it.filter_map(Result::ok)
                .filter_map(|e| {
                    let name = e.file_name().to_string_lossy().to_string();
                    let d = name.strip_prefix("trade_date=")?.to_string();
                    (d.as_str() >= start && d.as_str() <= end).then(|| (d, e.path()))
                })
                .collect()
        })
        .unwrap_or_default();
    out.sort();
    out
}

/// A `FROM` item for the rows of `store` on ET trade dates `[start, end]`, or
/// `None` when nothing holds them. Callers keep their own `trade_date` filters.
pub fn source(root: &Path, store: &str, start: &str, end: &str) -> Option<String> {
    let view = if enabled(store) { load(root, store) } else { None };
    let Some(view) = view else {
        return legacy(root, store, start, end);
    };
    let raw: Vec<(String, String)> = view
        .files
        .range(start.to_string()..=end.to_string())
        .map(|(d, p)| (d.clone(), p.clone()))
        .collect();
    let raw_dates: BTreeSet<&str> = raw.iter().map(|(d, _)| d.as_str()).collect();
    let mut parts: Vec<String> = Vec::new();
    for (d, dir) in partitions(root, store, start, end) {
        for f in parquet_files(&dir) {
            let replaced = raw_dates.contains(d.as_str())
                && f.file_name().is_some_and(|n| n.to_string_lossy() == view.replaces);
            if !replaced {
                parts.push(f.to_string_lossy().to_string());
            }
        }
    }
    let raw_sql = (!raw.is_empty()).then(|| {
        let files: Vec<String> = raw.iter().map(|(_, p)| p.clone()).collect();
        let src = format!("read_parquet([{}], filename = true)", list(&files));
        view.template.replace("{src}", &src).replace("{trade_date}", &view.date_expr)
    });
    let parts_sql =
        (!parts.is_empty()).then(|| format!("SELECT * FROM read_parquet([{}], union_by_name = true)", list(&parts)));
    match (raw_sql, parts_sql) {
        (Some(r), Some(p)) => Some(format!("(SELECT * FROM ({r}) UNION ALL BY NAME {p})")),
        (Some(r), None) => Some(format!("({r})")),
        (None, Some(p)) => Some(format!("({p})")),
        (None, None) => None,
    }
}

/// The converted partitions, read as the handlers always have.
fn legacy(root: &Path, store: &str, start: &str, end: &str) -> Option<String> {
    let dir = root.join(store);
    if start == end {
        let part = dir.join(format!("trade_date={start}"));
        if parquet_files(&part).is_empty() {
            return None;
        }
        return Some(format!("read_parquet({})", lit(&part.join("*.parquet").to_string_lossy())));
    }
    if partitions(root, store, start, end).iter().all(|(_, p)| parquet_files(p).is_empty()) {
        return None;
    }
    Some(format!("read_parquet({})", lit(&dir.join("trade_date=*").join("*.parquet").to_string_lossy())))
}

/// First and last trade date the raw files of an in-place store cover (freshness).
pub fn raw_range(root: &Path, store: &str) -> Option<(String, String)> {
    if !enabled(store) {
        return None;
    }
    let v = load(root, store)?;
    Some((v.files.keys().next()?.clone(), v.files.keys().next_back()?.clone()))
}
