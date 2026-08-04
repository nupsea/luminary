#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod stage;
mod supervisor;

use std::sync::Arc;
use std::time::{Duration, Instant};

use serde::Serialize;
use supervisor::Supervisor;
use tauri::{AppHandle, Emitter, Manager, WebviewUrl, WebviewWindowBuilder};

/// How long the backend may take to answer before we show the user an error.
/// A cold first run pays migrations and heavy imports; the model downloads that
/// follow are reported by the app itself, not waited on here.
const READY_TIMEOUT: Duration = Duration::from_secs(180);

#[derive(Clone, Serialize)]
struct BootEvent {
    step: &'static str,
    message: String,
    failed: bool,
}

fn emit(app: &AppHandle, step: &'static str, message: impl Into<String>, failed: bool) {
    let _ = app.emit(
        "boot",
        BootEvent {
            step,
            message: message.into(),
            failed,
        },
    );
}

fn wait_for_backend(port: u16) -> Result<(), String> {
    let deadline = Instant::now() + READY_TIMEOUT;
    let addr = format!("127.0.0.1:{port}");
    while Instant::now() < deadline {
        if std::net::TcpStream::connect(&addr).is_ok() {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    Err(format!("backend did not answer on {addr} within {READY_TIMEOUT:?}"))
}

fn boot(app: AppHandle, sup: Arc<Supervisor>) {
    let stage = match stage::stage_dir(&app) {
        Ok(p) => p,
        Err(e) => return emit(&app, "stage", e, true),
    };
    let data_dir = match stage::data_dir(&app) {
        Ok(p) => p,
        Err(e) => return emit(&app, "stage", e, true),
    };

    emit(&app, "engine", "Warming up the engine", false);
    let ollama_port = match supervisor::free_port() {
        Ok(p) => p,
        Err(e) => return emit(&app, "engine", e, true),
    };
    // Non-fatal: the library, search and cloud routing all work without it.
    if let Err(e) = supervisor::spawn_ollama(&sup, &stage, &data_dir, ollama_port) {
        eprintln!("[shell] local model server unavailable: {e}");
    }

    emit(&app, "backend", "Opening your library", false);
    let port = match supervisor::free_port() {
        Ok(p) => p,
        Err(e) => return emit(&app, "backend", e, true),
    };
    if let Err(e) = supervisor::spawn_backend(&sup, &stage, &data_dir, port, ollama_port) {
        return emit(&app, "backend", e, true);
    }

    if let Err(e) = wait_for_backend(port) {
        return emit(&app, "backend", e, true);
    }

    emit(&app, "ready", "Ready", false);
    if let Some(window) = app.get_webview_window("main") {
        let url = format!("http://127.0.0.1:{port}");
        // Navigating to the backend's own origin keeps the SPA and the API
        // same-origin, so neither CORS nor TrustedHostMiddleware needs relaxing.
        if let Ok(parsed) = url.parse() {
            let _ = window.navigate(parsed);
        }
    }
}

fn main() {
    let supervisor = Arc::new(Supervisor::new());
    let for_setup = supervisor.clone();
    let for_exit = supervisor.clone();

    tauri::Builder::default()
        // Kuzu takes an exclusive file lock, so a second instance cannot open
        // the library at all.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .setup(move |app| {
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Luminary")
                .inner_size(1280.0, 860.0)
                .min_inner_size(900.0, 600.0)
                .build()?;

            let handle = app.handle().clone();
            let sup = for_setup.clone();
            std::thread::spawn(move || boot(handle, sup));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to start Luminary")
        .run(move |_app, event| {
            if let tauri::RunEvent::Exit = event {
                for_exit.shutdown();
            }
        });
}
