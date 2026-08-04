//! Locating the staged payload (`Contents/Resources` in a bundle).

use std::path::{Path, PathBuf};

use tauri::{AppHandle, Manager};

/// Every piece the shell needs before it is worth spawning anything.
const REQUIRED: [&str; 4] = [
    "surface-manifest.json",
    "python/bin/python3.13",
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

/// Free bytes on the volume holding `path`, if it can be determined.
pub fn free_space(path: &Path) -> Option<u64> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;

    let c_path = CString::new(path.as_os_str().as_bytes()).ok()?;
    let mut stat: libc::statvfs = unsafe { std::mem::zeroed() };
    // SAFETY: a valid NUL-terminated path and an owned, correctly sized struct.
    if unsafe { libc::statvfs(c_path.as_ptr(), &mut stat) } != 0 {
        return None;
    }
    Some(stat.f_bavail as u64 * stat.f_frsize as u64)
}

/// A human-readable warning when the disk is too full to finish first run.
pub fn space_warning(data_dir: &Path) -> Option<String> {
    let free = free_space(data_dir)?;
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

        std::fs::remove_file(dir.join("python/bin/python3.13")).unwrap();
        assert_eq!(missing_pieces(&dir), vec!["python/bin/python3.13"]);

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
        assert!(free_space(&std::env::temp_dir()).is_some_and(|b| b > 0));
    }
}
