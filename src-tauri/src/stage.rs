//! Locating the staged payload (`Contents/Resources` in a bundle).

use std::path::PathBuf;

use tauri::{AppHandle, Manager};

/// The staged tree: interpreter, backend source, SPA, manifest, ollama.
///
/// A packaged app finds it in `Contents/Resources`. `cargo tauri dev` has no
/// such tree, so `LUMINARY_STAGE` and then `build/stage` are tried, which is
/// what makes the shell runnable before there is anything to sign.
pub fn stage_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(explicit) = std::env::var("LUMINARY_STAGE") {
        if !explicit.trim().is_empty() {
            candidates.push(PathBuf::from(explicit));
        }
    }
    if let Ok(resources) = app.path().resource_dir() {
        candidates.push(resources);
    }
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("build/stage"));
        for ancestor in cwd.ancestors() {
            candidates.push(ancestor.join("build/stage"));
        }
    }

    for candidate in candidates {
        if candidate.join("surface-manifest.json").is_file() {
            return Ok(candidate);
        }
    }
    Err("could not locate the staged payload (run `make stage`)".into())
}

/// Where the library lives: writable, outside the read-only signed bundle.
pub fn data_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("no app data dir: {e}"))?;
    std::fs::create_dir_all(&dir).map_err(|e| format!("could not create {dir:?}: {e}"))?;
    Ok(dir)
}
