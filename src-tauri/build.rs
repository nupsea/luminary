fn main() {
    // Boot-screen assets are embedded into the binary at compile time by
    // `tauri::generate_context!`, but cargo does not know they are inputs.
    // Without this, editing the boot page changes nothing until something in
    // src/ happens to force a rebuild -- and the app ships the previous copy.
    println!("cargo:rerun-if-changed=boot");
    for entry in std::fs::read_dir("boot").into_iter().flatten().flatten() {
        println!("cargo:rerun-if-changed={}", entry.path().display());
    }

    tauri_build::build()
}
