use std::path::PathBuf;
use std::process::Command;

fn main() {
    println!("cargo:rerun-if-env-changed=QFINZERO_GIT_HASH");
    println!("cargo:rerun-if-changed=../../../../.git/HEAD");

    if let Ok(explicit) = std::env::var("QFINZERO_GIT_HASH") {
        println!("cargo:rustc-env=QFINZERO_GIT_HASH={explicit}");
        return;
    }

    let manifest_dir = match std::env::var("CARGO_MANIFEST_DIR") {
        Ok(value) => PathBuf::from(value),
        Err(_) => return,
        };
    let repo_root = manifest_dir.join("../../../../");
    let hash = Command::new("git")
        .arg("-C")
        .arg(&repo_root)
        .args(["rev-parse", "--short=7", "HEAD"])
        .output()
        .ok()
        .filter(|output| output.status.success())
        .and_then(|output| String::from_utf8(output.stdout).ok())
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "unknown".to_string());

    println!("cargo:rustc-env=QFINZERO_GIT_HASH={hash}");
}
