//! Spawns and reaps the backend and the local model server.

use std::io::{BufRead, BufReader};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

pub struct Supervisor {
    children: Mutex<Vec<Child>>,
}

impl Supervisor {
    pub fn new() -> Self {
        Self {
            children: Mutex::new(Vec::new()),
        }
    }

    fn track(&self, child: Child) {
        self.children.lock().unwrap().push(child);
    }

    /// Terminate both children. Called on window close and on app exit.
    ///
    /// Kuzu holds an exclusive OS file lock, so a survivor blocks the next
    /// launch outright rather than degrading anything.
    pub fn shutdown(&self) {
        let mut children = self.children.lock().unwrap();
        for child in children.iter_mut() {
            let _ = child.kill();
            let _ = child.wait();
        }
        children.clear();
    }
}

impl Default for Supervisor {
    fn default() -> Self {
        Self::new()
    }
}

/// Ask the OS for a free port, then release it.
///
/// Fixed ports collide with a user's own Ollama on 11434, or with a Luminary
/// installed the old way on 7820.
pub fn free_port() -> Result<u16, String> {
    let listener =
        TcpListener::bind("127.0.0.1:0").map_err(|e| format!("no free port: {e}"))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("no local addr: {e}"))?
        .port();
    drop(listener);
    Ok(port)
}

/// Drain both pipes.
///
/// Both must be read, not just logged: an undrained pipe fills its 64KB buffer
/// and then blocks the child on its next write. uvicorn logs to stderr, so
/// piping it without a reader wedges the backend a few seconds into startup.
fn stream_output(child: &mut Child, tag: &'static str) {
    if let Some(stdout) = child.stdout.take() {
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                println!("[{tag}] {line}");
            }
        });
    }
    if let Some(stderr) = child.stderr.take() {
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                eprintln!("[{tag}] {line}");
            }
        });
    }
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
        .stderr(Stdio::piped());

    let mut child = cmd.spawn().map_err(|e| format!("could not start ollama: {e}"))?;
    stream_output(&mut child, "ollama");
    sup.track(child);
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
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = cmd.spawn().map_err(|e| format!("could not start backend: {e}"))?;
    stream_output(&mut child, "backend");
    sup.track(child);
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
