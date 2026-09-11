//! The OS-specific half of the desktop shell: process trees, disk, memory.
//!
//! Split out of `luminary-desktop` because it is the only code in the shell
//! whose *correctness* differs per platform, and the shell itself cannot be
//! compiled for Windows from a Mac -- `tauri-build` needs a resource compiler
//! that is not available here. This crate has no Tauri dependency, so
//! `cargo check --target x86_64-pc-windows-msvc -p luminary-host` and clippy
//! both run on any developer machine. Keep it that way: a Windows-only branch
//! that only CI can see is a branch nobody reads before pushing.
//!
//! # What differs, and why the caller has to care
//!
//! Unix kills a tree by signalling the process group the child leads. Windows
//! has no process groups reachable from a GUI process: console control events
//! need a shared console, and a `windows_subsystem = "windows"` binary has
//! none. The substitute is a Job Object per child, with
//! `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` -- the tree dies when the last handle
//! to the job closes, which includes the shell crashing or being force-quit.
//! That is the only mechanism on Windows that survives a parent that never got
//! to run cleanup.
//!
//! **There is no polite signal on Windows.** [`Tree::request_stop`] terminates
//! there, because the alternative is waiting out the full grace period on every
//! quit. Anything that needs to shut down cleanly must be asked some other way
//! first -- the backend is asked over HTTP, and only what refuses reaches here.

use std::process::{Child, Command, ExitStatus};

#[cfg_attr(unix, path = "unix.rs")]
#[cfg_attr(windows, path = "windows.rs")]
mod sys;

pub use sys::{alive, executable_of, free_space, total_memory_bytes};

/// One child and everything it spawns, as something that can be ended at once.
///
/// Dropping this on Windows closes the job handle, which kills the tree. That
/// is deliberate: it is what makes a crashed shell take its children with it.
pub struct Tree(sys::Tree);

impl Tree {
    /// End the tree, giving it the chance to exit on its own where the platform
    /// has one. Unix sends SIGTERM to the group; **Windows terminates.**
    pub fn request_stop(&self) {
        self.0.request_stop();
    }

    /// End the tree now, with no chance to run anything.
    ///
    /// Costly by nature: SQLite's WAL is left unmerged and Kuzu's exclusive
    /// lock is only released when the holder actually dies, so this belongs
    /// after a grace period, never instead of one.
    pub fn kill(&self) {
        self.0.kill();
    }

    /// Whether ending this tree reaches the child's own children.
    ///
    /// Always true on unix: `process_group(0)` cannot fail after the child
    /// exists. False on Windows means the job object could not be created or
    /// the child could not be assigned to it, and the tree has degraded to a
    /// single process -- the crash net is gone, and a caller that does not say
    /// so out loud leaves the user with orphans and no explanation.
    pub fn covers_descendants(&self) -> bool {
        self.0.covers_descendants()
    }

    /// What to persist so a later run can find this tree without this handle.
    ///
    /// The process group id on unix. On Windows a job object cannot outlive the
    /// process that made it, so this is the child's own pid and the recovery
    /// path is [`kill_stale_tree`].
    pub fn group_id(&self) -> i32 {
        self.0.group_id()
    }
}

/// Prepare a command so the child it spawns can be tracked as a tree.
///
/// Must be called before `spawn`; [`adopt`] finishes the job afterwards.
pub fn before_spawn(cmd: &mut Command) -> &mut Command {
    sys::before_spawn(cmd)
}

/// Take ownership of a freshly spawned child's tree.
///
/// Windows assigns the process to a job here rather than at creation, because
/// `std::process` exposes neither `CREATE_SUSPENDED` plus a resumable thread
/// handle nor `PROC_THREAD_ATTRIBUTE_JOB_LIST`. A grandchild spawned in the
/// microseconds before assignment escapes the job; neither child we spawn
/// forks anything that early, and the alternative is reimplementing
/// `CreateProcess`.
pub fn adopt(child: &Child) -> Tree {
    Tree(sys::adopt(child))
}

/// Kill a tree recorded by a previous run of this process.
///
/// The handle that owned it is gone, so this is by id: the recorded process
/// group on unix, the recorded pid and its descendants on Windows.
pub fn kill_stale_tree(pid: i32, group_id: i32) {
    sys::kill_stale_tree(pid, group_id);
}

/// How a child ended, in words, for the failure screen.
///
/// Separate from `ExitStatus`'s own `Display` because the signal number is what
/// identifies an OOM kill, and reading it needs a unix-only trait.
pub fn describe_exit(status: ExitStatus) -> String {
    sys::describe_exit(status)
}
