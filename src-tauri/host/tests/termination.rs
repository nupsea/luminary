//! A termination signal reaches the shell's cleanup instead of killing it.
//!
//! Its own test binary: the handler is process-wide, and a SIGTERM raised in a
//! binary shared with other tests would take them down if the handler failed.
#![cfg(unix)]

use std::sync::mpsc;
use std::time::Duration;

#[test]
fn sigterm_runs_the_callback_and_the_process_survives() {
    let (tx, rx) = mpsc::channel();
    luminary_host::on_termination(move |signal| tx.send(signal).unwrap()).unwrap();

    // SAFETY: raise(3) on this process; the handler above owns SIGTERM.
    unsafe { libc::raise(libc::SIGTERM) };
    let got = rx.recv_timeout(Duration::from_secs(5));
    assert_eq!(got, Ok(libc::SIGTERM));

    // A repeat during the drain is absorbed: unhandled, it would end this
    // process here and the test binary would report the signal, not a pass.
    unsafe { libc::raise(libc::SIGTERM) };
    std::thread::sleep(Duration::from_millis(300));
}
