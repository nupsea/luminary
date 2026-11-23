//! The phone's shell: a webview over `frontend/src/mobile`, built by `npm run build:mobile`.
//! It talks to the user's Luminary server through the frontend's transport; nothing here
//! reaches the network itself.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("Luminary could not start");
}
