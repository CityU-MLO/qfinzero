use std::fs;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

use chrono::Utc;
use rusqlite::{params, Connection, OptionalExtension};
use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileStatus {
    Pending,
    Done,
    Error,
}

impl FileStatus {
    fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Done => "done",
            Self::Error => "error",
        }
    }

    fn from_str(value: &str) -> Option<Self> {
        match value {
            "pending" => Some(Self::Pending),
            "done" => Some(Self::Done),
            "error" => Some(Self::Error),
            _ => None,
        }
    }
}

#[derive(Debug, Error)]
pub enum ManifestError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("database error: {0}")]
    Db(#[from] rusqlite::Error),
}

#[derive(Debug, Clone, Copy)]
struct Signature {
    size: i64,
    mtime: i64,
}

pub struct ManifestStore {
    conn: Connection,
}

impl ManifestStore {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, ManifestError> {
        let path = path.as_ref();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }

        let conn = Connection::open(path)?;
        conn.execute_batch(
            "
            CREATE TABLE IF NOT EXISTS manifest (
                file_path TEXT PRIMARY KEY,
                file_size INTEGER NOT NULL,
                file_mtime INTEGER NOT NULL,
                status TEXT NOT NULL,
                rows_ingested INTEGER,
                error_msg TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_manifest_status ON manifest(status);
            ",
        )?;

        Ok(Self { conn })
    }

    pub fn should_process(&self, source: &Path) -> Result<bool, ManifestError> {
        let signature = file_signature(source)?;
        let key = normalized_path(source);

        let existing: Option<(i64, i64, String)> = self
            .conn
            .query_row(
                "SELECT file_size, file_mtime, status FROM manifest WHERE file_path = ?1",
                params![key],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .optional()?;

        match existing {
            Some((size, mtime, status))
                if size == signature.size
                    && mtime == signature.mtime
                    && status == FileStatus::Done.as_str() =>
            {
                Ok(false)
            }
            _ => {
                self.upsert(source, signature, FileStatus::Pending, None, None)?;
                Ok(true)
            }
        }
    }

    pub fn mark_done(&self, source: &Path, rows_ingested: i64) -> Result<(), ManifestError> {
        let signature = file_signature(source)?;
        self.upsert(
            source,
            signature,
            FileStatus::Done,
            Some(rows_ingested),
            None,
        )
    }

    pub fn mark_error(&self, source: &Path, message: &str) -> Result<(), ManifestError> {
        let signature = file_signature(source)?;
        self.upsert(source, signature, FileStatus::Error, None, Some(message))
    }

    pub fn status_of(&self, source: &Path) -> Result<Option<FileStatus>, ManifestError> {
        let key = normalized_path(source);
        let status: Option<String> = self
            .conn
            .query_row(
                "SELECT status FROM manifest WHERE file_path = ?1",
                params![key],
                |row| row.get(0),
            )
            .optional()?;

        Ok(status.and_then(|value| FileStatus::from_str(&value)))
    }

    fn upsert(
        &self,
        source: &Path,
        signature: Signature,
        status: FileStatus,
        rows_ingested: Option<i64>,
        error_msg: Option<&str>,
    ) -> Result<(), ManifestError> {
        let key = normalized_path(source);
        let updated_at = Utc::now().to_rfc3339();

        self.conn.execute(
            "
            INSERT INTO manifest (file_path, file_size, file_mtime, status, rows_ingested, error_msg, updated_at)
            VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
            ON CONFLICT(file_path) DO UPDATE SET
                file_size = excluded.file_size,
                file_mtime = excluded.file_mtime,
                status = excluded.status,
                rows_ingested = excluded.rows_ingested,
                error_msg = excluded.error_msg,
                updated_at = excluded.updated_at
            ",
            params![
                key,
                signature.size,
                signature.mtime,
                status.as_str(),
                rows_ingested,
                error_msg,
                updated_at
            ],
        )?;

        Ok(())
    }
}

fn normalized_path(path: &Path) -> String {
    let resolved: PathBuf = path.to_path_buf();
    resolved.to_string_lossy().to_string()
}

fn file_signature(path: &Path) -> Result<Signature, ManifestError> {
    let metadata = fs::metadata(path)?;
    let size =
        i64::try_from(metadata.len()).map_err(|_| std::io::Error::other("file too large"))?;
    let modified = metadata.modified()?;
    let seconds = modified
        .duration_since(UNIX_EPOCH)
        .map_err(|_| std::io::Error::other("mtime before epoch"))?
        .as_secs();
    let mtime = i64::try_from(seconds).map_err(|_| std::io::Error::other("mtime overflow"))?;

    Ok(Signature { size, mtime })
}
