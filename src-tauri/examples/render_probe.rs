//! Drive `render_page` against a real webview and report what came back.
//!
//! The title channel cannot be exercised from a unit test: it needs a live
//! WKWebView, a page that runs its own scripts, and the platform's real title
//! handling -- which is where every defect in this module has actually lived.
//!
//! Run: `cargo run --example render_probe -- <url> [<url>…]`

// The probe uses one entry point; the rest of the module is the shell's.
#[path = "../src/render.rs"]
#[allow(dead_code)]
mod render;

fn count(haystack: &str, needle: &str) -> usize {
    haystack.matches(needle).count()
}

fn main() {
    let urls: Vec<String> = std::env::args().skip(1).collect();
    if urls.is_empty() {
        eprintln!("usage: render_probe <url> [<url>…]");
        std::process::exit(2);
    }

    tauri::Builder::default()
        .setup(move |app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let mut failures = 0;
                for url in urls {
                    let started = std::time::Instant::now();
                    match render::render_page(handle.clone(), url.clone()).await {
                        Ok(html) => {
                            // Written out so the extraction pipeline can be run
                            // over the real rendered DOM, not a byte count.
                            if let Ok(dir) = std::env::var("LUMINARY_PROBE_OUT") {
                                let name = url
                                    .trim_end_matches('/')
                                    .rsplit('/')
                                    .next()
                                    .unwrap_or("page");
                                let _ = std::fs::write(
                                    std::path::Path::new(&dir).join(format!("{name}.html")),
                                    &html,
                                );
                            }
                            println!(
                            "OK   {url}\n     {}ms  {} bytes  figure={} svg={} img={} canvas={}",
                            started.elapsed().as_millis(),
                            html.len(),
                            count(&html, "<figure"),
                            count(&html, "<svg"),
                            count(&html, "<img"),
                            count(&html, "<canvas"),
                            );
                        }
                        Err(e) => {
                            failures += 1;
                            println!("FAIL {url}\n     {}ms  {e}", started.elapsed().as_millis());
                        }
                    }
                }
                std::process::exit(if failures > 0 { 1 } else { 0 });
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("could not start the probe")
        .run(|_handle, event| {
            // Destroying the render window ends the process otherwise, because
            // the probe has no main window of its own. The shell always does,
            // so this keeps the probe honest rather than papering over a bug.
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                api.prevent_exit();
            }
        });
}
