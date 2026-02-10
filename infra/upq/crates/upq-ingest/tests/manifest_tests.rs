use std::fs;

use tempfile::TempDir;
use upq_ingest::manifest::{FileStatus, ManifestStore};

#[test]
fn unchanged_file_is_skipped() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let source = tmp.path().join("sample.csv.gz");
    fs::write(&source, b"abc")?;

    let store = ManifestStore::open(tmp.path().join("manifest.sqlite"))?;
    let first = store.should_process(&source)?;
    assert!(first);

    store.mark_done(&source, 100)?;

    let second = store.should_process(&source)?;
    assert!(!second);
    Ok(())
}

#[test]
fn changed_file_is_reprocessed() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let source = tmp.path().join("sample.csv.gz");
    fs::write(&source, b"abc")?;

    let store = ManifestStore::open(tmp.path().join("manifest.sqlite"))?;
    let _ = store.should_process(&source)?;
    store.mark_done(&source, 10)?;

    fs::write(&source, b"abcd")?;

    let changed = store.should_process(&source)?;
    assert!(changed);
    Ok(())
}

#[test]
fn mark_error_transitions_status() -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let source = tmp.path().join("sample.csv.gz");
    fs::write(&source, b"abc")?;

    let store = ManifestStore::open(tmp.path().join("manifest.sqlite"))?;
    let _ = store.should_process(&source)?;
    store.mark_error(&source, "parse failed")?;

    let status = store.status_of(&source)?;
    assert_eq!(status, Some(FileStatus::Error));
    Ok(())
}

#[test]
fn should_process_treats_canonical_and_dotted_paths_as_same_file(
) -> Result<(), Box<dyn std::error::Error>> {
    let tmp = TempDir::new()?;
    let source = tmp.path().join("sample.csv.gz");
    fs::write(&source, b"abc")?;

    let dotted = tmp.path().join(".").join("sample.csv.gz");
    let canonical = fs::canonicalize(&source)?;

    let store = ManifestStore::open(tmp.path().join("manifest.sqlite"))?;
    let first = store.should_process(&dotted)?;
    assert!(first);
    store.mark_done(&dotted, 100)?;

    let second = store.should_process(&canonical)?;
    assert!(!second);
    Ok(())
}
