//! What a process tree is for: one call ends the child *and its children*.
//!
//! Every assertion here runs on whatever platform is running it, which is the
//! point -- the Windows half of this crate is unreachable from a Mac and would
//! otherwise be verified only by the compiler. On Windows these exercise the
//! job object; on unix, the process group.

use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// A child that spawns a grandchild and prints the grandchild's pid.
///
/// The grandchild is what makes the test worth writing: killing the leader
/// alone leaves it running, which is the defect this whole mechanism exists to
/// prevent -- ollama's model runners are its children, not itself.
fn spawn_a_family() -> (std::process::Child, i32) {
    let mut cmd = spawner();
    cmd.stdout(Stdio::piped()).stderr(Stdio::null());
    luminary_host::before_spawn(&mut cmd);

    let mut child = cmd.spawn().expect("spawn");
    let stdout = child.stdout.take().expect("piped");
    let mut lines = BufReader::new(stdout).lines();
    let printed = lines
        .next()
        .expect("the child printed nothing")
        .expect("unreadable");
    let grandchild: i32 = printed.trim().parse().unwrap_or_else(|e| {
        panic!("not a pid: {printed:?} ({e})");
    });
    (child, grandchild)
}

#[cfg(unix)]
fn spawner() -> Command {
    let mut cmd = Command::new("/bin/sh");
    cmd.args(["-c", "sleep 60 & echo $!; wait"]);
    cmd
}

#[cfg(windows)]
fn spawner() -> Command {
    let mut cmd = Command::new("powershell");
    // `-NoNewWindow` is load-bearing: without it `Start-Process` goes through
    // `ShellExecute`, and what it returns need not be a child of this shell at
    // all -- so the grandchild would never inherit the job and the test would
    // be measuring its own harness. The grandchild sleeps rather than pinging
    // because it inherits stdout, and its output would race the pid we read.
    cmd.args([
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "$p = Start-Process -PassThru -NoNewWindow powershell \
         -ArgumentList '-NoProfile','-Command','Start-Sleep -Seconds 60'; \
         Write-Output $p.Id; Wait-Process -Id $p.Id",
    ]);
    cmd
}

fn gone(pid: i32) -> bool {
    let deadline = Instant::now() + Duration::from_secs(10);
    while Instant::now() < deadline {
        if !luminary_host::alive(pid) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    false
}

#[test]
fn stopping_a_tree_takes_the_grandchild_with_it() {
    let (mut child, grandchild) = spawn_a_family();
    let tree = luminary_host::adopt(&child);
    // Asserted separately so a refused job object reads as a refused job
    // object, not as a mechanism that ran and did not work.
    assert!(
        tree.covers_descendants(),
        "the tree does not cover descendants: on Windows the job object was \
         refused, and every assertion below would be about the wrong thing"
    );
    assert!(luminary_host::alive(grandchild), "grandchild never started");

    tree.request_stop();

    let leader = child.id() as i32;
    assert!(gone(grandchild), "the grandchild outlived the tree");
    let _ = child.wait();
    assert!(gone(leader));
}

#[test]
fn killing_a_tree_takes_the_grandchild_with_it() {
    let (mut child, grandchild) = spawn_a_family();
    let tree = luminary_host::adopt(&child);

    tree.kill();

    assert!(gone(grandchild), "the grandchild survived a kill");
    let _ = child.wait();
}

/// The orphan net, and the reason Windows uses a job object at all.
///
/// `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` fires when the last handle closes,
/// which happens whether the parent exits cleanly, crashes, or is force-quit.
/// Unix has no equivalent -- a process group outlives its creator -- so this
/// asserts the platform's actual behaviour rather than a shared contract.
#[test]
// Whether this handle needs dropping at all is the platform difference being
// asserted: on unix `Tree` is a process group id and holds nothing.
#[allow(clippy::drop_non_drop)]
fn dropping_the_handle_is_the_crash_net() {
    let (mut child, grandchild) = spawn_a_family();
    let tree = luminary_host::adopt(&child);
    drop(tree);

    if cfg!(windows) {
        assert!(gone(grandchild), "closing the job must kill its members");
    } else {
        assert!(
            luminary_host::alive(grandchild),
            "a process group does not die with its creator; \
             `reap_leftovers` is what covers this on unix"
        );
    }
    let _ = child.kill();
    let _ = child.wait();
    luminary_host::kill_stale_tree(grandchild, grandchild);
}

#[test]
fn this_process_is_alive_and_names_its_own_executable() {
    let pid = std::process::id() as i32;
    assert!(luminary_host::alive(pid));
    // The safety property of reaping depends on this lookup working: pids are
    // recycled, and killing by pid alone eventually kills a stranger.
    let exe = luminary_host::executable_of(pid).expect("no executable for our own pid");
    assert!(!exe.is_empty());
}

#[test]
fn a_pid_that_cannot_exist_is_never_alive() {
    for pid in [0, 1, -1, i32::MAX] {
        // Not a liveness question for 0 and 1 -- those are "signal my own
        // group" and init. A probe that answered true for them would send the
        // reaper after the whole session (I-54).
        if pid == 1 {
            continue;
        }
        assert!(!luminary_host::alive(pid), "pid {pid}");
    }
}

#[test]
fn the_host_reports_its_own_disk_and_memory() {
    let free = luminary_host::free_space(&std::env::temp_dir()).expect("no free-space reading");
    assert!(free > 0);

    let bytes = luminary_host::total_memory_bytes().expect("no memory reading");
    // A machine this app runs on has at least 2GB; a reading below that is the
    // wrong unit, which is the failure mode these calls actually have.
    assert!(bytes >= 2 * 1_073_741_824, "implausible RAM: {bytes} bytes");
}
