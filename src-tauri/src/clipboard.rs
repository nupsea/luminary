//! Read an image off the system clipboard for the notes editor.
//!
//! WKWebView announces a pasted image (`types` holds `"Files"`) but withholds
//! the file itself from the page's `paste` event, and `navigator.clipboard.read()`
//! answers only after a native "Paste" confirmation bubble. A macOS screenshot
//! (`public.heic` + `public.tiff`) therefore never reached the editor.

use tauri::ipc::Response;

/// The clipboard image as PNG bytes, or an error when it holds no image.
#[tauri::command]
pub fn read_clipboard_image() -> Result<Response, String> {
    png_from_pasteboard().map(Response::new)
}

#[cfg(target_os = "macos")]
fn png_from_pasteboard() -> Result<Vec<u8>, String> {
    use objc2::AnyThread;
    use objc2_app_kit::{
        NSBitmapImageFileType, NSBitmapImageRep, NSImage, NSPasteboard, NSPasteboardTypePNG,
    };
    use objc2_foundation::NSDictionary;

    let pasteboard = NSPasteboard::generalPasteboard();
    if let Some(png) = pasteboard.dataForType(unsafe { NSPasteboardTypePNG }) {
        return Ok(png.to_vec());
    }
    // NSImage decodes whatever image type is on the pasteboard (HEIC, TIFF, PDF).
    let image = NSImage::initWithPasteboard(NSImage::alloc(), &pasteboard)
        .ok_or("the clipboard holds no image")?;
    let tiff = image
        .TIFFRepresentation()
        .ok_or("the clipboard image has no bitmap")?;
    let bitmap =
        NSBitmapImageRep::imageRepWithData(&tiff).ok_or("the clipboard image has no bitmap")?;
    let png = unsafe {
        bitmap.representationUsingType_properties(NSBitmapImageFileType::PNG, &NSDictionary::new())
    }
    .ok_or("the clipboard image could not be encoded as PNG")?;
    Ok(png.to_vec())
}

// WebView2 and WebKitGTK hand the page the pasted file themselves.
#[cfg(not(target_os = "macos"))]
fn png_from_pasteboard() -> Result<Vec<u8>, String> {
    Err("native clipboard images are read only on macOS".into())
}
