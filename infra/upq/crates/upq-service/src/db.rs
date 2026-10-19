//! One DuckDB database for the whole service, shared through a fixed pool of
//! connections.
//!
//! Every connection is a clone of the same in-memory database, so queries share
//! one worker thread pool and one parquet metadata cache. A request waits for a
//! free connection instead of creating a database of its own: with a database
//! per thread, concurrent requests each started a full set of DuckDB threads,
//! oversubscribed the CPUs and, past a few dozen at once, ran out of file
//! descriptors.
//!
//! `UPQ_POOL_SIZE` (connections, default half the CPUs, 4..=16) bounds how many
//! queries run at once; `UPQ_DUCKDB_THREADS` (default all CPUs) is the worker
//! pool they share. Async callers are admitted through a semaphore and get
//! [`Busy`] after `UPQ_QUEUE_TIMEOUT_S` (default 30) seconds in the queue.

use std::sync::{Condvar, Mutex, OnceLock};
use std::time::{Duration, Instant};

use duckdb::Connection;
use tokio::sync::Semaphore;

/// The queue wait ran out: the caller should answer 503.
#[derive(Debug)]
pub struct Busy;

struct Pool {
    idle: Mutex<Vec<Connection>>,
    ready: Condvar,
    size: usize,
    /// Keeps the database open while every pooled connection is checked out.
    _base: Mutex<Connection>,
}

static POOL: OnceLock<Result<Pool, String>> = OnceLock::new();
static ADMIT: OnceLock<Semaphore> = OnceLock::new();

fn env_usize(name: &str) -> Option<usize> {
    std::env::var(name).ok().and_then(|v| v.trim().parse().ok()).filter(|n| *n > 0)
}

fn cpus() -> usize {
    std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4)
}

/// Pool size: `UPQ_POOL_SIZE`, else half the CPUs within 4..=16.
pub fn pool_size() -> usize {
    env_usize("UPQ_POOL_SIZE").unwrap_or_else(|| (cpus() / 2).clamp(4, 16))
}

pub fn queue_timeout() -> Duration {
    Duration::from_secs(env_usize("UPQ_QUEUE_TIMEOUT_S").unwrap_or(30) as u64)
}

fn build() -> Result<Pool, String> {
    let base = Connection::open_in_memory().map_err(|e| e.to_string())?;
    let threads = env_usize("UPQ_DUCKDB_THREADS").unwrap_or_else(cpus);
    base.execute_batch(&format!("SET threads TO {threads};")).map_err(|e| e.to_string())?;
    // cache parquet footers across queries (setting name differs by version)
    for setting in ["SET parquet_metadata_cache = true;", "SET enable_object_cache = true;"] {
        let _ = base.execute_batch(setting);
    }
    let size = pool_size();
    let mut idle = Vec::with_capacity(size);
    for _ in 0..size {
        idle.push(base.try_clone().map_err(|e| e.to_string())?);
    }
    Ok(Pool { idle: Mutex::new(idle), ready: Condvar::new(), size, _base: Mutex::new(base) })
}

fn pool() -> Result<&'static Pool, String> {
    POOL.get_or_init(build).as_ref().map_err(Clone::clone)
}

/// Returns its connection to the pool, also when the query panicked.
struct Lease<'a> {
    pool: &'a Pool,
    conn: Option<Connection>,
}

impl Drop for Lease<'_> {
    fn drop(&mut self) {
        if let Some(conn) = self.conn.take() {
            if let Ok(mut idle) = self.pool.idle.lock() {
                idle.push(conn);
            }
            self.pool.ready.notify_one();
        }
    }
}

/// Run `f` on a pooled connection, waiting up to the queue timeout for one.
/// Blocking: call it from `spawn_blocking` (or a thread that may block).
pub fn with_connection<T, E>(f: impl FnOnce(&Connection) -> Result<T, E>) -> Result<Result<T, E>, String> {
    let pool = pool()?;
    let deadline = Instant::now() + queue_timeout();
    let mut idle = pool.idle.lock().map_err(|e| e.to_string())?;
    loop {
        if let Some(conn) = idle.pop() {
            drop(idle);
            let lease = Lease { pool, conn: Some(conn) };
            let Some(leased) = lease.conn.as_ref() else {
                return Err("lost a pooled connection".to_string());
            };
            let out = f(leased);
            drop(lease);
            return Ok(out);
        }
        let left = deadline.saturating_duration_since(Instant::now());
        if left.is_zero() {
            return Err("all database connections are busy".to_string());
        }
        idle = pool.ready.wait_timeout(idle, left).map_err(|e| e.to_string())?.0;
    }
}

/// Admission for async handlers: at most four queued queries per connection;
/// the permit is held while the query runs.
pub async fn admit() -> Result<tokio::sync::SemaphorePermit<'static>, Busy> {
    let sem = ADMIT.get_or_init(|| Semaphore::new(pool_size() * 4));
    match tokio::time::timeout(queue_timeout(), sem.acquire()).await {
        Ok(Ok(permit)) => Ok(permit),
        _ => Err(Busy),
    }
}

/// Connections in the pool (for /health).
pub fn size() -> usize {
    pool().map(|p| p.size).unwrap_or(0)
}
