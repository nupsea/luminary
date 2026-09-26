//! Lines written to stderr, by the shell or a child that inherits it, reach the
//! log callback.
//!
//! Its own test binary: it replaces fd 2 and the panic hook for the whole process.
#![cfg(unix)]

use std::process::Command;
use std::sync::mpsc;
use std::time::Duration;

#[test]
fn own_and_child_stderr_lines_are_passed_on() {
    let (tx, rx) = mpsc::channel::<String>();
    let tx = std::sync::Mutex::new(tx);
    luminary_host::tee_stderr(move |line| {
        let _ = tx.lock().unwrap().send(line.to_string());
    })
    .unwrap();

    let own = b"from the shell\n";
    // SAFETY: write(2) to fd 2 directly; eprintln! is captured by the test harness.
    unsafe { libc::write(libc::STDERR_FILENO, own.as_ptr().cast(), own.len()) };
    // Inherited stderr is how WebKitGTK's web process reports an EGL failure.
    let status = Command::new("/bin/sh")
        .args(["-c", "echo 'from a child' >&2"])
        .status()
        .unwrap();
    assert!(status.success());

    let mut got = Vec::new();
    while got.len() < 2 {
        match rx.recv_timeout(Duration::from_secs(5)) {
            Ok(line) => got.push(line),
            Err(_) => break,
        }
    }
    got.sort();
    assert_eq!(got, ["from a child", "from the shell"]);
}
