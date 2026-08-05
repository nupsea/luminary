//! A log file the user can find, and support can read.
//!
//! `~/Library/Logs/Luminary/` rather than somewhere under the library: an
//! unwritable or misconfigured `DATA_DIR` is itself a failure worth recording,
//! so logging must not depend on the thing most likely to be broken. It is also
//! where macOS users and Console.app already look.

use std::collections::VecDeque;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};

/// Rotated at this size, this many files kept. Bounded because the app runs for
/// years on someone's laptop and nothing else prunes it.
const MAX_BYTES: u64 = 2 * 1024 * 1024;
const KEEP: usize = 3;

/// Kept in memory as well as on disk so the failure screen can show recent
/// lines even when the disk write is the thing that failed.
const TAIL_LINES: usize = 400;

struct Sink {
    path: PathBuf,
    file: Mutex<Option<File>>,
    tail: Mutex<VecDeque<String>>,
}

static SINK: OnceLock<Sink> = OnceLock::new();

fn log_dir() -> Option<PathBuf> {
    let home = std::env::var_os("HOME")?;
    Some(PathBuf::from(home).join("Library/Logs/Luminary"))
}

/// Best-effort: a failure to open the log must never stop the app starting.
pub fn init() {
    let sink = match log_dir() {
        Some(dir) => {
            let path = dir.join("luminary.log");
            let file = fs::create_dir_all(&dir).ok().and_then(|_| {
                OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(&path)
                    .ok()
            });
            Sink {
                path,
                file: Mutex::new(file),
                tail: Mutex::new(VecDeque::new()),
            }
        }
        None => Sink {
            path: PathBuf::new(),
            file: Mutex::new(None),
            tail: Mutex::new(VecDeque::new()),
        },
    };
    let _ = SINK.set(sink);
    rotate_if_large();
    write(
        "shell",
        &format!("--- Luminary {} ---", env!("CARGO_PKG_VERSION")),
    );
}

pub fn path() -> Option<PathBuf> {
    let sink = SINK.get()?;
    if sink.path.as_os_str().is_empty() {
        return None;
    }
    Some(sink.path.clone())
}

/// One line, timestamped and tagged with its source (`shell`, `backend`, `ollama`).
pub fn write(tag: &str, line: &str) {
    let Some(sink) = SINK.get() else { return };
    let stamped = format!(
        "{} [{tag}] {line}",
        chrono::Local::now().format("%Y-%m-%d %H:%M:%S%.3f")
    );

    if let Ok(mut tail) = sink.tail.lock() {
        if tail.len() == TAIL_LINES {
            tail.pop_front();
        }
        tail.push_back(stamped.clone());
    }

    if let Ok(mut slot) = sink.file.lock() {
        if let Some(file) = slot.as_mut() {
            let _ = writeln!(file, "{stamped}");
        }
    }
}

/// The most recent lines, oldest first.
pub fn tail(count: usize) -> Vec<String> {
    let Some(sink) = SINK.get() else {
        return Vec::new();
    };
    let Ok(tail) = sink.tail.lock() else {
        return Vec::new();
    };
    tail.iter()
        .skip(tail.len().saturating_sub(count))
        .cloned()
        .collect()
}

/// Roll `luminary.log` to `.1`, `.2`, ... once it grows past `MAX_BYTES`.
fn rotate_if_large() {
    let Some(sink) = SINK.get() else { return };
    let Ok(meta) = fs::metadata(&sink.path) else {
        return;
    };
    if meta.len() < MAX_BYTES {
        return;
    }

    let Ok(mut slot) = sink.file.lock() else {
        return;
    };
    // Dropped before renaming: an open handle would keep writing to the file
    // that just moved out from under it.
    *slot = None;

    let _ = fs::remove_file(sink.path.with_extension(format!("log.{KEEP}")));
    for n in (1..KEEP).rev() {
        let _ = fs::rename(
            sink.path.with_extension(format!("log.{n}")),
            sink.path.with_extension(format!("log.{}", n + 1)),
        );
    }
    let _ = fs::rename(&sink.path, sink.path.with_extension("log.1"));

    *slot = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&sink.path)
        .ok();
}
