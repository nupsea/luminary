#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod logging;
mod render;
mod report;
mod stage;
mod supervisor;

use std::os::unix::process::ExitStatusExt;
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use supervisor::Supervisor;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_opener::OpenerExt;

/// The ceiling for a backend that is alive but slow -- a cold first run pays
/// migrations and heavy imports. A backend that *dies* is reported the moment
/// it does, so this timeout is now only reached by a genuine hang.
const READY_TIMEOUT: Duration = Duration::from_secs(180);

/// How much of the log travels with a report.
const REPORT_LOG_LINES: usize = 200;

#[derive(Clone, Default, Serialize)]
struct BootEvent {
    step: &'static str,
    /// Plain English, for the person looking at the screen.
    message: String,
    /// Technical cause, shown behind a disclosure and sent with a report.
    detail: String,
    failed: bool,
}

/// The last thing `boot` reported.
///
/// `boot` starts as soon as the window is built and can fail before the splash
/// has parsed its own script, and `emit` reaches whoever is listening at the
/// time -- nobody, that early. Keeping the state lets the splash ask for it
/// once it is ready, so an instant failure is as visible as a slow one.
#[derive(Default)]
struct BootState {
    last: Mutex<Option<BootEvent>>,
    running: AtomicBool,
    /// Where the bundled Ollama is listening, so a report can ask it for its
    /// version and model list. 0 until it starts.
    ollama_port: AtomicU16,
}

fn publish(app: &AppHandle, event: BootEvent) {
    if event.failed {
        logging::write(
            "shell",
            &format!(
                "FAILED at {}: {} | {}",
                event.step, event.message, event.detail
            ),
        );
    } else {
        logging::write("shell", &format!("{}: {}", event.step, event.message));
    }

    if let Some(state) = app.try_state::<BootState>() {
        if let Ok(mut last) = state.last.lock() {
            *last = Some(event.clone());
        }
    }
    let _ = app.emit("boot", event);
}

fn progress(app: &AppHandle, step: &'static str, message: &str) {
    publish(
        app,
        BootEvent {
            step,
            message: message.into(),
            ..Default::default()
        },
    );
}

fn fail(app: &AppHandle, step: &'static str, message: &str, detail: &str) {
    publish(
        app,
        BootEvent {
            step,
            message: message.into(),
            detail: detail.into(),
            failed: true,
        },
    );
}

/// A note that does not stop startup, shown alongside the progress line.
fn warn(app: &AppHandle, message: &str) {
    logging::write("shell", &format!("warning: {message}"));
    let _ = app.emit("boot-warning", message.to_string());
}

fn describe(status: std::process::ExitStatus) -> String {
    match (status.code(), status.signal()) {
        (Some(code), _) => format!("exit code {code}"),
        (None, Some(signal)) => format!("killed by signal {signal}"),
        _ => "an unknown status".into(),
    }
}

/// Wait for the backend to answer, for it to die, or for the deadline.
///
/// Watching only the port was the single worst diagnostic in the app: uvicorn
/// runs lifespan startup *before* binding a socket, so any exception during
/// startup -- a failed migration, a bad DATA_DIR -- means the port never opens
/// at all. That produced three minutes of silence followed by "did not answer",
/// while the traceback that explained it was discarded.
fn wait_for_backend(sup: &Supervisor, port: u16) -> Result<(), (String, String)> {
    let deadline = Instant::now() + READY_TIMEOUT;
    let addr = format!("127.0.0.1:{port}");

    loop {
        if std::net::TcpStream::connect(&addr).is_ok() {
            return Ok(());
        }
        if let Some(status) = sup.exited("backend") {
            return Err((
                "Luminary's engine stopped unexpectedly while starting up.".into(),
                format!(
                    "backend exited with {} before opening {addr}\n\n{}",
                    describe(status),
                    sup.tail("backend").join("\n")
                ),
            ));
        }
        if Instant::now() >= deadline {
            return Err((
                "Luminary's engine is taking longer than expected and has stopped responding."
                    .into(),
                format!(
                    "no response on {addr} within {}s\n\n{}",
                    READY_TIMEOUT.as_secs(),
                    sup.tail("backend").join("\n")
                ),
            ));
        }
        std::thread::sleep(Duration::from_millis(250));
    }
}

fn boot(app: AppHandle, sup: Arc<Supervisor>) {
    progress(&app, "stage", "Starting up");

    let stage = match stage::stage_dir(&app) {
        Ok(p) => p,
        Err(e) => {
            return fail(
                &app,
                "stage",
                "Luminary could not find its program files. If you just installed it, \
                 try dragging Luminary to your Applications folder again from the disk image.",
                &e,
            )
        }
    };

    let missing = stage::missing_pieces(&stage);
    if !missing.is_empty() {
        return fail(
            &app,
            "stage",
            "This copy of Luminary looks incomplete. Downloading it again and \
             replacing the copy in Applications should fix it.",
            &format!("missing from {}: {}", stage.display(), missing.join(", ")),
        );
    }

    let data_dir = match stage::data_dir(&app) {
        Ok(p) => p,
        Err(e) => {
            return fail(
                &app,
                "library",
                "Luminary could not open the folder where your library is kept.",
                &e,
            )
        }
    };

    // Before anything opens the library: Kuzu takes an exclusive lock, so a
    // process stranded by a previous crash blocks this launch outright.
    sup.set_runtime_file(&data_dir);
    supervisor::reap_leftovers(&data_dir);

    if let Some(warning) = stage::space_warning(&data_dir) {
        warn(&app, &warning);
    }

    progress(&app, "engine", "Warming up the engine");
    let ollama_port = match supervisor::free_port() {
        Ok(p) => p,
        Err(e) => {
            return fail(
                &app,
                "engine",
                "Luminary could not reserve a local port.",
                &e,
            )
        }
    };
    if let Some(state) = app.try_state::<BootState>() {
        state.ollama_port.store(ollama_port, Ordering::Relaxed);
    }
    // Non-fatal: the library, search and cloud routing all work without it.
    if let Err(e) = supervisor::spawn_ollama(&sup, &stage, &data_dir, ollama_port) {
        logging::write("shell", &format!("local model server unavailable: {e}"));
        warn(
            &app,
            "The local AI engine did not start. Your library will open, but chat may be unavailable.",
        );
    }

    progress(&app, "backend", "Opening your library");
    let port = match supervisor::free_port() {
        Ok(p) => p,
        Err(e) => {
            return fail(
                &app,
                "backend",
                "Luminary could not reserve a local port.",
                &e,
            )
        }
    };
    if let Err(e) = supervisor::spawn_backend(&sup, &stage, &data_dir, port, ollama_port) {
        return fail(
            &app,
            "backend",
            "Luminary's engine could not be started.",
            &e,
        );
    }

    if let Err((message, detail)) = wait_for_backend(&sup, port) {
        return fail(&app, "backend", &message, &detail);
    }

    progress(&app, "ready", "Ready");
    if let Some(window) = app.get_webview_window("main") {
        let url = format!("http://127.0.0.1:{port}");
        // Navigating to the backend's own origin keeps the SPA and the API
        // same-origin, so neither CORS nor TrustedHostMiddleware needs relaxing.
        grant_spa_render(&app, port);
        if let Ok(parsed) = url.parse() {
            let _ = window.navigate(parsed);
        }
    }
}

/// Let the SPA -- and only the SPA -- ask for a page to be rendered.
///
/// Navigating the main window to the backend makes it a *remote* origin as far
/// as the ACL is concerned, so an app command it invokes is rejected unless a
/// capability names both the command and the origin. The port is chosen at
/// startup, so the grant cannot be a static capability file; wildcarding the
/// port there would hand `render_page` to anything listening on loopback.
///
/// Failure is logged rather than fatal: every article still imports over the
/// backend's static fetch, which measured full prose and headings on eight of
/// nine test pages. It is logged loudly because a silent rejection here is
/// indistinguishable from a page that simply did not need rendering.
fn grant_spa_render(app: &AppHandle, port: u16) {
    let capability = tauri::ipc::CapabilityBuilder::new(format!("spa-render-{port}"))
        .local(false)
        .remote(render::spa_origin_pattern(port))
        .window("main")
        .permission("allow-render-page");

    match app.add_capability(capability) {
        Ok(()) => logging::write(
            "shell",
            &format!("page rendering enabled for the app origin on port {port}"),
        ),
        Err(e) => logging::write(
            "shell",
            &format!("page rendering unavailable, imports will use the static fetch: {e}"),
        ),
    }
}

/// Run `boot` on its own thread, at most once at a time.
fn start_boot(app: AppHandle, sup: Arc<Supervisor>) {
    if let Some(state) = app.try_state::<BootState>() {
        if state.running.swap(true, Ordering::SeqCst) {
            return;
        }
    }
    std::thread::spawn(move || {
        boot(app.clone(), sup);
        if let Some(state) = app.try_state::<BootState>() {
            state.running.store(false, Ordering::SeqCst);
        }
    });
}

fn build_report(app: &AppHandle) -> report::Report {
    let last = app
        .try_state::<BootState>()
        .and_then(|s| s.last.lock().ok().and_then(|l| l.clone()))
        .unwrap_or_default();

    let ollama_port = app
        .try_state::<BootState>()
        .map(|s| s.ollama_port.load(Ordering::Relaxed))
        .unwrap_or(0);

    report::Report {
        step: last.step.to_string(),
        message: last.message,
        detail: last.detail,
        log: logging::tail(REPORT_LOG_LINES),
        ollama_port,
    }
}

#[tauri::command]
fn boot_state(state: State<'_, BootState>) -> Option<BootEvent> {
    state.last.lock().map_or(None, |last| last.clone())
}

/// The exact text that a report would carry, redacted. Shown to the user before
/// anything leaves the machine, and used by the copy button.
#[tauri::command]
fn diagnostics(app: AppHandle) -> String {
    build_report(&app).to_text()
}

/// Open a prefilled issue form in the browser.
///
/// Opened from Rust rather than handed to the webview, so the splash never gets
/// the ability to open arbitrary URLs. Nothing is submitted by this -- the user
/// still reviews the form and presses Submit on GitHub.
#[tauri::command]
fn report_issue(app: AppHandle) -> Result<(), String> {
    let url = build_report(&app).issue_url();
    logging::write("shell", "opening a prefilled issue form in the browser");
    app.opener()
        .open_url(url, None::<&str>)
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn reveal_log(app: AppHandle) -> Result<(), String> {
    let path = logging::path().ok_or("there is no log file")?;
    app.opener()
        .reveal_item_in_dir(path)
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn retry_boot(app: AppHandle, sup: State<'_, Arc<Supervisor>>) {
    logging::write("shell", "retrying startup at the user's request");
    sup.shutdown();
    start_boot(app.clone(), sup.inner().clone());
}

/// Bring the existing window forward. `set_focus` alone leaves a hidden or
/// minimized window where it is, which reads as nothing having happened.
fn activate(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn main() {
    logging::init();

    let supervisor = Arc::new(Supervisor::new());
    let for_setup = supervisor.clone();
    let for_exit = supervisor.clone();

    tauri::Builder::default()
        // Kuzu takes an exclusive file lock, so a second instance cannot open
        // the library at all.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            activate(app);
        }))
        .plugin(tauri_plugin_opener::init())
        .manage(BootState::default())
        .manage(supervisor.clone())
        .invoke_handler(tauri::generate_handler![
            boot_state,
            diagnostics,
            report_issue,
            reveal_log,
            retry_boot,
            render::render_page
        ])
        .setup(move |app| {
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Luminary")
                .inner_size(1280.0, 860.0)
                .min_inner_size(900.0, 600.0)
                // On by default, and it swallows the OS drop before the webview
                // sees it -- so the app's HTML5 drop handlers never fired and
                // dragging a file in did nothing at all.
                .disable_drag_drop_handler()
                .build()?;

            start_boot(app.handle().clone(), for_setup.clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to start Luminary")
        .run(move |app, event| match event {
            RunEvent::Exit => for_exit.shutdown(),
            // macOS reactivation: Spotlight, the Dock, or `open -a` on an app
            // that is already running. Without this the click does nothing
            // visible and the user launches again, or gives up.
            RunEvent::Reopen { .. } => activate(app),
            _ => {}
        });
}
