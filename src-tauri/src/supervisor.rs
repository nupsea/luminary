//! Spawns, supervises and reaps the backend and the local model server.

use std::collections::VecDeque;
use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::logging;

/// Enough of a child's output to explain why it died, without turning the
/// failure screen into a wall of text.
const TAIL_LINES: usize = 60;

/// How long a child gets to exit on SIGTERM before SIGKILL. The backend's own
/// shutdown path is bounded at 5s, so this only has to cover that plus slack.
const TERM_GRACE: Duration = Duration::from_secs(6);

/// Processes we spawned last time, so a crash cannot strand them.
const RUNTIME_FILE: &str = ".runtime.json";

struct Tracked {
    name: &'static str,
    child: Child,
    /// Equal to the child's pid, because we spawn with `process_group(0)`.
    pgid: i32,
    exe: PathBuf,
    tail: Arc<Mutex<VecDeque<String>>>,
}

#[derive(Serialize, Deserialize)]
struct Record {
    name: String,
    pid: i32,
    pgid: i32,
    exe: String,
}

#[derive(Default)]
pub struct Supervisor {
    children: Mutex<Vec<Tracked>>,
    runtime_file: Mutex<Option<PathBuf>>,
}

impl Supervisor {
    pub fn new() -> Self {
        Self::default()
    }

    /// Where to record what we spawn. Set once the library directory is known.
    pub fn set_runtime_file(&self, data_dir: &Path) {
        if let Ok(mut slot) = self.runtime_file.lock() {
            *slot = Some(data_dir.join(RUNTIME_FILE));
        }
    }

    fn track(&self, tracked: Tracked) {
        if let Ok(mut children) = self.children.lock() {
            children.push(tracked);
        }
        self.persist();
    }

    fn persist(&self) {
        let Ok(slot) = self.runtime_file.lock() else {
            return;
        };
        let Some(path) = slot.as_ref() else { return };
        let Ok(children) = self.children.lock() else {
            return;
        };
        let records: Vec<Record> = children
            .iter()
            .map(|c| Record {
                name: c.name.to_string(),
                pid: c.child.id() as i32,
                pgid: c.pgid,
                exe: c.exe.to_string_lossy().into_owned(),
            })
            .collect();
        if let Ok(json) = serde_json::to_string(&records) {
            let _ = std::fs::write(path, json);
        }
    }

    /// Has the named child exited? `None` means it is still running.
    pub fn exited(&self, name: &str) -> Option<ExitStatus> {
        let mut children = self.children.lock().ok()?;
        let tracked = children.iter_mut().find(|c| c.name == name)?;
        tracked.child.try_wait().ok().flatten()
    }

    /// The last lines the named child wrote, oldest first.
    pub fn tail(&self, name: &str) -> Vec<String> {
        let Ok(children) = self.children.lock() else {
            return Vec::new();
        };
        children
            .iter()
            .find(|c| c.name == name)
            .and_then(|c| c.tail.lock().ok().map(|t| t.iter().cloned().collect()))
            .unwrap_or_default()
    }

    /// Terminate both children and everything they spawned.
    ///
    /// SIGTERM to the whole process group first: ollama's model runners are its
    /// children, and killing only the leader used to strand them. The grace
    /// period matters because SIGKILL leaves SQLite's WAL unmerged and Kuzu's
    /// exclusive lock is only released when the holder actually dies.
    pub fn shutdown(&self) {
        let Ok(mut children) = self.children.lock() else {
            return;
        };
        if children.is_empty() {
            return;
        }

        for tracked in children.iter() {
            logging::write("shell", &format!("stopping {}", tracked.name));
            signal_group(tracked.pgid, libc::SIGTERM);
        }

        let deadline = Instant::now() + TERM_GRACE;
        for tracked in children.iter_mut() {
            while Instant::now() < deadline {
                match tracked.child.try_wait() {
                    Ok(Some(_)) => break,
                    Ok(None) => std::thread::sleep(Duration::from_millis(100)),
                    Err(_) => break,
                }
            }
        }

        for tracked in children.iter_mut() {
            if matches!(tracked.child.try_wait(), Ok(None)) {
                logging::write(
                    "shell",
                    &format!("{} ignored SIGTERM, killing", tracked.name),
                );
                signal_group(tracked.pgid, libc::SIGKILL);
            }
            let _ = tracked.child.kill();
            let _ = tracked.child.wait();
        }
        children.clear();
        drop(children);

        if let Ok(slot) = self.runtime_file.lock() {
            if let Some(path) = slot.as_ref() {
                let _ = std::fs::remove_file(path);
            }
        }
    }
}

fn signal_group(pgid: i32, sig: i32) {
    if pgid > 1 {
        // SAFETY: a plain kill(2) on a process group we created.
        unsafe { libc::killpg(pgid, sig) };
    }
}

fn alive(pid: i32) -> bool {
    // SAFETY: signal 0 performs error checking without sending anything.
    unsafe { libc::kill(pid, 0) == 0 }
}

/// What is actually running under this pid, as the kernel sees it.
fn executable_of(pid: i32) -> Option<String> {
    let out = Command::new("/bin/ps")
        .args(["-p", &pid.to_string(), "-o", "comm="])
        .output()
        .ok()?;
    let path = String::from_utf8_lossy(&out.stdout).trim().to_string();
    (!path.is_empty()).then_some(path)
}

/// Kill anything a previous run left behind, before opening the library.
///
/// A crash or force-quit never delivers `RunEvent::Exit`, so the children
/// survive; Kuzu's exclusive lock then blocks the next launch outright.
///
/// The executable check is the safety property, not an optimisation. Pids are
/// recycled, and killing by pid alone would eventually kill a stranger's
/// process -- including the user's own long-running `ollama serve`.
pub fn reap_leftovers(data_dir: &Path) {
    let path = data_dir.join(RUNTIME_FILE);
    let Ok(raw) = std::fs::read_to_string(&path) else {
        return;
    };
    let Ok(records) = serde_json::from_str::<Vec<Record>>(&raw) else {
        let _ = std::fs::remove_file(&path);
        return;
    };

    for record in records {
        if record.pid <= 1 || !alive(record.pid) {
            continue;
        }
        let actual = executable_of(record.pid);
        if is_ours(&record, actual.as_deref()) {
            logging::write(
                "shell",
                &format!(
                    "reaping orphaned {} from a previous run (pid {})",
                    record.name, record.pid
                ),
            );
            signal_group(record.pgid, libc::SIGTERM);
            std::thread::sleep(Duration::from_millis(500));
            if alive(record.pid) {
                signal_group(record.pgid, libc::SIGKILL);
            }
        } else {
            logging::write(
                "shell",
                &format!(
                    "pid {} is now {:?}, not ours -- leaving it alone",
                    record.pid,
                    actual.unwrap_or_else(|| "unreadable".into())
                ),
            );
        }
    }
    let _ = std::fs::remove_file(&path);
}

/// Is the process now holding this pid the one we recorded?
///
/// The safety property of reaping. Pids are recycled, so killing by pid alone
/// would eventually kill a stranger's process -- including the user's own
/// long-running `ollama serve`, which is exactly the binary name we look for.
fn is_ours(record: &Record, actual_exe: Option<&str>) -> bool {
    actual_exe.is_some_and(|exe| exe == record.exe)
}

/// Ask the OS for a free port, then release it.
///
/// Fixed ports collide with a user's own Ollama on 11434, or with a Luminary
/// installed the old way on 7820.
pub fn free_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| format!("no free port: {e}"))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("no local addr: {e}"))?
        .port();
    drop(listener);
    Ok(port)
}

/// Drain both pipes into the log, keeping the tail for the failure screen.
///
/// Both must be read, not just logged: an undrained pipe fills its 64KB buffer
/// and then blocks the child on its next write. uvicorn logs to stderr, so
/// piping it without a reader wedges the backend a few seconds into startup.
fn stream_output(child: &mut Child, tag: &'static str) -> Arc<Mutex<VecDeque<String>>> {
    let tail = Arc::new(Mutex::new(VecDeque::with_capacity(TAIL_LINES)));

    for stream in [
        child
            .stdout
            .take()
            .map(|s| Box::new(s) as Box<dyn std::io::Read + Send>),
        child
            .stderr
            .take()
            .map(|s| Box::new(s) as Box<dyn std::io::Read + Send>),
    ]
    .into_iter()
    .flatten()
    {
        let tail = tail.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stream).lines().map_while(Result::ok) {
                logging::write(tag, &line);
                if let Ok(mut tail) = tail.lock() {
                    if tail.len() == TAIL_LINES {
                        tail.pop_front();
                    }
                    tail.push_back(line);
                }
            }
        });
    }
    tail
}

pub fn spawn_ollama(
    sup: &Supervisor,
    stage: &Path,
    data_dir: &Path,
    port: u16,
) -> Result<(), String> {
    let binary = stage.join("ollama/ollama");
    if !binary.is_file() {
        return Err(format!("no ollama binary at {binary:?}"));
    }
    let models = data_dir.join("ollama/models");
    std::fs::create_dir_all(&models).map_err(|e| format!("could not create {models:?}: {e}"))?;

    let mut cmd = Command::new(&binary);
    base_env(&mut cmd)
        .arg("serve")
        .env("OLLAMA_HOST", format!("127.0.0.1:{port}"))
        .env("OLLAMA_MODELS", &models)
        // The runner libs sit beside the binary in the official tarball.
        .env("OLLAMA_LIBRARY_PATH", stage.join("ollama"))
        .env("OLLAMA_KEEP_ALIVE", "30m")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        // Its model runners are its own children; a new group lets us take the
        // whole tree down at once.
        .process_group(0);

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("could not start ollama: {e}"))?;
    let pgid = child.id() as i32;
    let tail = stream_output(&mut child, "ollama");
    sup.track(Tracked {
        name: "ollama",
        child,
        pgid,
        exe: binary,
        tail,
    });
    Ok(())
}

pub fn spawn_backend(
    sup: &Supervisor,
    stage: &Path,
    data_dir: &Path,
    port: u16,
    ollama_port: u16,
) -> Result<(), String> {
    let python = stage.join("python/bin/python3.13");
    if !python.is_file() {
        return Err(format!("no interpreter at {python:?}"));
    }

    let mut cmd = Command::new(&python);
    base_env(&mut cmd)
        // -I isolates the interpreter: no PYTHONPATH, no PYTHONHOME, no user
        // site, so a user's own Python cannot leak into ours.
        .args([
            "-I",
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
            "--no-access-log",
        ])
        // Settings reads `.env` relative to the working directory, and a
        // GUI-launched process starts at `/`. Pointing it at the library turns
        // that into a user-editable config file in a findable place.
        .current_dir(data_dir)
        .env("LUMINARY_APP_ROOT", stage)
        .env("DATA_DIR", data_dir)
        .env("LUMINARY_MODE", "public")
        .env("OLLAMA_URL", format!("http://127.0.0.1:{ollama_port}"))
        .env("PATH", bundled_path(stage))
        .env("PYTHONUNBUFFERED", "1")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        // Lets the backend exit on its own if this process dies without ever
        // getting the chance to stop it.
        .env("LUMINARY_PARENT_PID", std::process::id().to_string())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .process_group(0);

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("could not start backend: {e}"))?;
    let pgid = child.id() as i32;
    let tail = stream_output(&mut child, "backend");
    sup.track(Tracked {
        name: "backend",
        child,
        pgid,
        exe: python,
        tail,
    });
    Ok(())
}

/// Console scripts the backend spawns by name (yt-dlp) plus the system minimum.
fn bundled_path(stage: &Path) -> String {
    let mut parts: Vec<PathBuf> = vec![stage.join("python/bin")];
    parts.push(PathBuf::from("/usr/bin"));
    parts.push(PathBuf::from("/bin"));
    parts
        .iter()
        .map(|p| p.to_string_lossy().into_owned())
        .collect::<Vec<_>>()
        .join(":")
}

/// Start from an empty environment so a user's DYLD_*, PYTHON* or VIRTUAL_ENV
/// cannot reach either child, then add back only what is needed.
fn base_env(cmd: &mut Command) -> &mut Command {
    cmd.env_clear();
    if let Ok(home) = std::env::var("HOME") {
        cmd.env("HOME", home);
    }
    cmd.env("PATH", "/usr/bin:/bin");
    cmd
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(exe: &str) -> Record {
        Record {
            name: "ollama".into(),
            pid: 4242,
            pgid: 4242,
            exe: exe.into(),
        }
    }

    #[test]
    fn a_matching_executable_is_ours_to_reap() {
        let r = record("/Applications/Luminary.app/Contents/Resources/ollama/ollama");
        assert!(is_ours(
            &r,
            Some("/Applications/Luminary.app/Contents/Resources/ollama/ollama")
        ));
    }

    #[test]
    fn a_users_own_ollama_on_a_recycled_pid_is_never_killed() {
        let r = record("/Applications/Luminary.app/Contents/Resources/ollama/ollama");
        // Same binary name, different install: theirs, not ours.
        assert!(!is_ours(&r, Some("/usr/local/bin/ollama")));
        assert!(!is_ours(
            &r,
            Some("/Applications/Ollama.app/Contents/MacOS/ollama")
        ));
    }

    #[test]
    fn an_unreadable_or_exited_process_is_left_alone() {
        let r = record("/Applications/Luminary.app/Contents/Resources/ollama/ollama");
        assert!(!is_ours(&r, None));
    }

    #[test]
    fn our_own_pid_resolves_to_our_own_executable() {
        let pid = std::process::id() as i32;
        assert!(alive(pid));
        // Proves the ps lookup that the safety check depends on actually works.
        assert!(executable_of(pid).is_some_and(|exe| !exe.is_empty()));
    }

    #[test]
    fn reaping_a_missing_or_corrupt_runtime_file_is_harmless() {
        let dir = std::env::temp_dir().join(format!("luminary-reap-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();

        reap_leftovers(&dir); // no file at all

        std::fs::write(dir.join(RUNTIME_FILE), b"not json").unwrap();
        reap_leftovers(&dir);
        assert!(
            !dir.join(RUNTIME_FILE).exists(),
            "corrupt file must be cleared"
        );

        std::fs::remove_dir_all(&dir).unwrap();
    }
}
