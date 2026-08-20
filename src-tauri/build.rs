fn main() {
    // Boot-screen assets are embedded into the binary at compile time by
    // `tauri::generate_context!`, but cargo does not know they are inputs.
    // Without this, editing the boot page changes nothing until something in
    // src/ happens to force a rebuild -- and the app ships the previous copy.
    println!("cargo:rerun-if-changed=boot");
    for entry in std::fs::read_dir("boot").into_iter().flatten().flatten() {
        println!("cargo:rerun-if-changed={}", entry.path().display());
    }

    // Naming the commands here generates an `allow-<command>` permission for
    // each. It also flips the app into having an ACL manifest, which changes
    // enforcement: without one, `resolve_access` is consulted only for remote
    // origins, where it can never match, so every command is silently
    // unreachable from a remote origin and unguarded from a local one
    // (tauri-2.11.5/src/webview/mod.rs:1820). The SPA is served by the backend
    // over loopback and is therefore a *remote* origin, which is why its
    // `render_page` invokes were rejected before reaching Rust.
    //
    // Every command listed here now needs an explicit grant in some capability.
    // Omitting one breaks it from the boot page too, silently.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "boot_state",
            "diagnostics",
            "render_page",
            "report_issue",
            "retry_boot",
            "reveal_log",
        ]),
    ))
    .expect("failed to run tauri-build");
}
