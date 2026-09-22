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

/// The macOS archive is flat; elsewhere Ollama searches `lib/ollama` beside itself.
#[cfg(target_os = "macos")]
pub const OLLAMA_LIBRARY_DIR: &str = "ollama";
#[cfg(not(target_os = "macos"))]
pub const OLLAMA_LIBRARY_DIR: &str = "ollama/lib/ollama";

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

/// Where the library lives: writable, outside the read-only install. Local, not
/// roaming: a Windows domain profile syncs `%APPDATA%` to a server at every sign-in.
pub fn data_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_local_data_dir()
        .map_err(|e| format!("no app data dir: {e}"))?;
    std::fs::create_dir_all(&dir).map_err(|e| format!("could not create {dir:?}: {e}"))?;
    Ok(dir)
}

/// Written by `stage_ollama.sh`; decides whether the relocated copy is current.
pub const ENGINE_STAMP: &str = "ollama/ENGINE_VERSION";

/// macOS runs from the bundle: its archive carries Metal and has no pack to fetch.
const RELOCATE_ENGINE: bool = !cfg!(target_os = "macos");

/// Where the engine runs from: the stage, or a writable copy of it.
///
/// `ollama serve` finds its runners only relative to its own executable (no env
/// override), so a later-downloaded accelerator pack must land beside the shipped
/// runners, and the Linux install dir is read-only. `before_copy` runs only when
/// a copy is needed.
pub fn engine_dir(
    stage: &Path,
    data_dir: &Path,
    before_copy: impl FnOnce(),
) -> Result<PathBuf, String> {
    if !RELOCATE_ENGINE {
        return Ok(stage.to_path_buf());
    }
    relocate_engine(stage, data_dir, before_copy)
}

/// Compiled everywhere so the tests exercise it on every platform.
fn relocate_engine(
    stage: &Path,
    data_dir: &Path,
    before_copy: impl FnOnce(),
) -> Result<PathBuf, String> {
    let stamp_file = stage.join(ENGINE_STAMP);
    let want = std::fs::read_to_string(&stamp_file)
        .map_err(|e| format!("no engine stamp at {stamp_file:?}: {e}"))?;
    let want = want.trim();
    if want.is_empty() {
        return Err(format!("engine stamp at {stamp_file:?} is empty"));
    }

    let engine = data_dir.join("engine");
    if std::fs::read_to_string(engine.join(ENGINE_STAMP)).is_ok_and(|have| have.trim() == want) {
        return Ok(engine);
    }

    before_copy();
    // Copy aside and rename: an interrupted copy never replaces a working engine.
    let staging = data_dir.join("engine.new");
    let _ = std::fs::remove_dir_all(&staging);
    copy_tree(&stage.join("ollama"), &staging.join("ollama"))?;
    let _ = std::fs::remove_dir_all(&engine);
    std::fs::rename(&staging, &engine)
        .map_err(|e| format!("could not move the engine into {engine:?}: {e}"))?;
    Ok(engine)
}

fn copy_tree(from: &Path, to: &Path) -> Result<(), String> {
    std::fs::create_dir_all(to).map_err(|e| format!("could not create {to:?}: {e}"))?;
    let entries = std::fs::read_dir(from).map_err(|e| format!("could not read {from:?}: {e}"))?;
    for entry in entries {
        let entry = entry.map_err(|e| format!("could not read {from:?}: {e}"))?;
        let src = entry.path();
        let dst = to.join(entry.file_name());
        let kind = entry
            .file_type()
            .map_err(|e| format!("could not stat {src:?}: {e}"))?;
        if kind.is_dir() {
            copy_tree(&src, &dst)?;
        } else if kind.is_symlink() {
            copy_link(&src, &dst)?;
        } else {
            // fs::copy carries the unix mode, keeping the runners executable.
            std::fs::copy(&src, &dst)
                .map_err(|e| format!("could not copy {src:?} to {dst:?}: {e}"))?;
        }
    }
    Ok(())
}

/// Recreated, not followed: versioned CUDA sonames all link to one file.
#[cfg(unix)]
fn copy_link(src: &Path, dst: &Path) -> Result<(), String> {
    let target =
        std::fs::read_link(src).map_err(|e| format!("could not read the link {src:?}: {e}"))?;
    std::os::unix::fs::symlink(&target, dst)
        .map_err(|e| format!("could not link {dst:?} -> {target:?}: {e}"))
}

#[cfg(not(unix))]
fn copy_link(src: &Path, dst: &Path) -> Result<(), String> {
    std::fs::copy(src, dst)
        .map(|_| ())
        .map_err(|e| format!("could not copy {src:?} to {dst:?}: {e}"))
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

    /// A fresh (root, stage, data) with an engine staged at v0.32.5.
    fn engine_fixture(tag: &str) -> (PathBuf, PathBuf, PathBuf) {
        let root = std::env::temp_dir().join(format!("luminary-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let (stage, data) = (root.join("stage"), root.join("data"));
        let lib = stage.join("ollama/lib/ollama/cuda_v13");
        std::fs::create_dir_all(&lib).unwrap();
        std::fs::create_dir_all(&data).unwrap();
        std::fs::write(lib.join("libggml-cuda.so"), b"runner").unwrap();
        std::fs::write(stage.join(OLLAMA_BINARY), b"engine").unwrap();
        std::fs::write(stage.join(ENGINE_STAMP), "v0.32.5").unwrap();
        (root, stage, data)
    }

    #[test]
    fn an_engine_is_copied_once_and_then_reused() {
        let (root, stage, data) = engine_fixture("engine");

        let mut copied = false;
        let engine = relocate_engine(&stage, &data, || copied = true).unwrap();
        assert!(copied, "the first call has to copy");
        assert_eq!(engine, data.join("engine"));
        assert!(engine.join(OLLAMA_BINARY).is_file());
        assert!(engine
            .join("ollama/lib/ollama/cuda_v13/libggml-cuda.so")
            .is_file());
        assert!(!data.join("engine.new").exists(), "staging dir left behind");

        // A downloaded accelerator pack: a file not in the stage.
        let pack = engine.join("ollama/lib/ollama/cuda_v13/pack-marker");
        std::fs::write(&pack, b"downloaded").unwrap();

        let mut copied_again = false;
        let again = relocate_engine(&stage, &data, || copied_again = true).unwrap();
        assert!(!copied_again, "an unchanged release must not be recopied");
        assert_eq!(again, engine);
        assert!(
            pack.is_file(),
            "the second launch destroyed a downloaded pack"
        );

        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn a_new_release_replaces_the_copy() {
        let (root, stage, data) = engine_fixture("engine-up");

        let engine = relocate_engine(&stage, &data, || {}).unwrap();
        let stale = engine.join("ollama/lib/ollama/cuda_v13/pack-marker");
        std::fs::write(&stale, b"built against the old release").unwrap();

        std::fs::write(stage.join(ENGINE_STAMP), "v0.33.0").unwrap();
        let mut copied = false;
        relocate_engine(&stage, &data, || copied = true).unwrap();
        assert!(copied, "a new release has to be copied");
        assert!(
            !stale.exists(),
            "a runner built against the old release survived the upgrade"
        );
        assert_eq!(
            std::fs::read_to_string(engine.join(ENGINE_STAMP)).unwrap(),
            "v0.33.0"
        );

        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn a_stage_with_no_stamp_is_reported_not_silently_copied() {
        let (root, stage, data) = engine_fixture("engine-no");
        std::fs::remove_file(stage.join(ENGINE_STAMP)).unwrap();

        let err = relocate_engine(&stage, &data, || {}).unwrap_err();
        assert!(err.contains("ENGINE_VERSION"), "unhelpful error: {err}");
        assert!(!data.join("engine").exists());

        std::fs::write(stage.join(ENGINE_STAMP), "   \n").unwrap();
        assert!(
            relocate_engine(&stage, &data, || {}).is_err(),
            "an empty stamp is not a version"
        );

        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn free_space_is_readable_for_a_real_directory() {
        assert!(luminary_host::free_space(&std::env::temp_dir()).is_some_and(|b| b > 0));
    }
}
