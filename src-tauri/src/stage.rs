//! Locating the staged payload (`Contents/Resources` in a bundle).

use std::path::{Path, PathBuf};

use tauri::{AppHandle, Manager};

/// The staged interpreter. Windows lays python-build-standalone out flat --
/// no `bin/`, no version in the name -- so this is not one path with a suffix.
#[cfg(windows)]
pub const PYTHON_BINARY: &str = "python/python.exe";
#[cfg(not(windows))]
pub const PYTHON_BINARY: &str = "python/bin/python3.13";

/// The staged model server.
#[cfg(windows)]
pub const OLLAMA_BINARY: &str = "ollama/ollama.exe";
#[cfg(not(windows))]
pub const OLLAMA_BINARY: &str = "ollama/ollama";

/// Every piece the shell needs before it is worth spawning anything.
const REQUIRED: [&str; 4] = [
    "surface-manifest.json",
    PYTHON_BINARY,
    "backend/app",
    "frontend",
];

/// First run downloads ~1.4GB of models on top of the installed bundle. Warn
/// below this rather than failing partway through a download.
const MIN_FREE_BYTES: u64 = 4 * 1024 * 1024 * 1024;

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

/// Which required pieces are missing from a stage, if any.
///
/// A partial payload otherwise fails much later, deep inside a spawn, as a
/// path-shaped error that reads like a bug rather than a damaged install.
pub fn missing_pieces(stage: &Path) -> Vec<&'static str> {
    REQUIRED
        .iter()
        .copied()
        .filter(|piece| !stage.join(piece).exists())
        .collect()
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

/// A human-readable warning when the disk is too full to finish first run.
pub fn space_warning(data_dir: &Path) -> Option<String> {
    let free = luminary_host::free_space(data_dir)?;
    if free >= MIN_FREE_BYTES {
        return None;
    }
    Some(format!(
        "Only {:.1} GB of disk space is free. Luminary downloads about 1.5 GB \
         of models the first time it runs, and may not be able to finish.",
        free as f64 / 1_073_741_824.0
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_complete_stage_reports_nothing_missing() {
        let dir = std::env::temp_dir().join(format!("luminary-stage-{}", std::process::id()));
        for piece in REQUIRED {
            let path = dir.join(piece);
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(&path, b"x").unwrap();
        }
        assert!(missing_pieces(&dir).is_empty());

        std::fs::remove_file(dir.join(PYTHON_BINARY)).unwrap();
        assert_eq!(missing_pieces(&dir), vec![PYTHON_BINARY]);

        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn an_empty_resources_directory_reports_every_piece() {
        let dir = std::env::temp_dir().join(format!("luminary-empty-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        assert_eq!(missing_pieces(&dir).len(), REQUIRED.len());
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn free_space_is_readable_for_a_real_directory() {
        assert!(luminary_host::free_space(&std::env::temp_dir()).is_some_and(|b| b > 0));
    }
}
