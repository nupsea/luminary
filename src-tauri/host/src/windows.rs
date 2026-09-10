//! Process trees as Job Objects, which is what Windows has.
//!
//! `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is the whole point: the tree dies when
//! the last handle to the job closes, and a handle closes when the process
//! holding it exits *however* it exits. A force-quit, a crash or an End Task
//! therefore takes the backend and the model server with it. Nothing in the
//! parent has to run for that to happen, which is what makes it the only
//! reliable orphan net here.

use std::ffi::c_void;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::path::Path;
use std::process::{Child, Command, ExitStatus};

use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
use windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceExW;
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
use windows_sys::Win32::System::SystemInformation::{GlobalMemoryStatusEx, MEMORYSTATUSEX};
use windows_sys::Win32::System::Threading::{
    GetExitCodeProcess, OpenProcess, QueryFullProcessImageNameW, TerminateProcess,
    CREATE_NO_WINDOW, PROCESS_NAME_WIN32, PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_TERMINATE,
};

/// `GetExitCodeProcess` reports this for a process that has not exited.
///
/// A process that exits with 259 of its own accord is indistinguishable from a
/// running one. Neither child we spawn does; uvicorn exits 0 or 1, and ollama
/// exits 0 or 1. This is the documented liveness check regardless -- there is
/// no other one that does not also kill what it asks about (I-54).
const STILL_ACTIVE: u32 = 259;

/// Exit code handed to a terminated tree. Non-zero so a wait cannot read as
/// a clean stop.
const TERMINATED: u32 = 1;

/// A raw handle that may cross threads.
///
/// SAFETY: kernel object handles are process-wide and every call made on this
/// one (`AssignProcessToJobObject`, `TerminateJobObject`, `CloseHandle`) is
/// documented as thread-safe. The wrapper exists because `HANDLE` is a raw
/// pointer, which is neither `Send` nor `Sync` by default -- and the supervisor
/// holding this is Tauri state shared across threads.
struct Handle(HANDLE);

unsafe impl Send for Handle {}
unsafe impl Sync for Handle {}

impl Drop for Handle {
    fn drop(&mut self) {
        // SAFETY: owned, non-null, closed exactly once.
        unsafe { CloseHandle(self.0) };
    }
}

pub struct Tree {
    /// `None` when the job could not be created. The tree then degrades to the
    /// single process, which is worse than unix and better than nothing --
    /// and, crucially, is not silent: the caller logs what it got.
    job: Option<Handle>,
    pid: i32,
}

impl Tree {
    /// **Terminates.** Windows offers a GUI process no polite signal: console
    /// control events require a console shared with the target, and this binary
    /// is `windows_subsystem = "windows"`. Waiting out the grace period instead
    /// would add seconds to every quit and end in this same call.
    pub fn request_stop(&self) {
        self.kill();
    }

    pub fn kill(&self) {
        if let Some(job) = self.job.as_ref() {
            // SAFETY: an owned job handle.
            unsafe { TerminateJobObject(job.0, TERMINATED) };
            return;
        }
        let Some(process) = open(self.pid, PROCESS_TERMINATE) else {
            return;
        };
        // SAFETY: a handle opened for exactly this.
        unsafe { TerminateProcess(process.0, TERMINATED) };
    }

    /// The child's own pid: a job object cannot outlive the process that made
    /// it, so there is nothing group-shaped to write down.
    pub fn group_id(&self) -> i32 {
        self.pid
    }
}

pub fn before_spawn(cmd: &mut Command) -> &mut Command {
    // Without this, every console child of a GUI parent flashes up a console
    // window of its own -- two black boxes behind the splash screen.
    cmd.creation_flags(CREATE_NO_WINDOW)
}

pub fn adopt(child: &Child) -> Tree {
    let pid = child.id() as i32;
    Tree {
        job: assign(child),
        pid,
    }
}

/// Put a spawned child in a fresh job that kills its members when it closes.
fn assign(child: &Child) -> Option<Handle> {
    // SAFETY: an unnamed job with default security, per the documented call.
    let raw = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
    if raw.is_null() {
        return None;
    }
    let job = Handle(raw);

    let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    // SAFETY: an owned, correctly sized struct of the class we name.
    let set = unsafe {
        SetInformationJobObject(
            job.0,
            JobObjectExtendedLimitInformation,
            (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast::<c_void>(),
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        )
    };
    if set == 0 {
        // A job without the flag is worse than none: it looks like a net and
        // catches nothing, because closing it would leave the tree running.
        return None;
    }

    // SAFETY: the child is alive and owned by us; `std` opens its handle with
    // full access, which covers PROCESS_SET_QUOTA | PROCESS_TERMINATE.
    let assigned = unsafe { AssignProcessToJobObject(job.0, child.as_raw_handle() as HANDLE) };
    (assigned != 0).then_some(job)
}

pub fn kill_stale_tree(pid: i32, _group_id: i32) {
    if pid <= 1 {
        return;
    }
    // The job that owned this tree died with the run that made it, so there is
    // no handle left to close. `taskkill /T` walks the parent-pid chain, which
    // is the only tree-shaped thing still recorded anywhere.
    let _ = Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .creation_flags(CREATE_NO_WINDOW)
        .output();
}

fn open(pid: i32, access: u32) -> Option<Handle> {
    if pid <= 1 {
        return None;
    }
    // SAFETY: a pid and an access mask; returns null rather than trapping.
    let raw = unsafe { OpenProcess(access, 0, pid as u32) };
    (!raw.is_null()).then(|| Handle(raw))
}

pub fn alive(pid: i32) -> bool {
    let Some(process) = open(pid, PROCESS_QUERY_LIMITED_INFORMATION) else {
        return false;
    };
    let mut code: u32 = 0;
    // SAFETY: an owned handle and a stack u32.
    let read = unsafe { GetExitCodeProcess(process.0, &mut code) };
    read != 0 && code == STILL_ACTIVE
}

/// What is actually running under this pid, as the kernel sees it.
pub fn executable_of(pid: i32) -> Option<String> {
    let process = open(pid, PROCESS_QUERY_LIMITED_INFORMATION)?;
    let mut buffer = [0u16; 32768];
    let mut len = buffer.len() as u32;
    // SAFETY: an owned handle, an owned buffer, and its length by pointer.
    let ok = unsafe {
        QueryFullProcessImageNameW(process.0, PROCESS_NAME_WIN32, buffer.as_mut_ptr(), &mut len)
    };
    if ok == 0 || len == 0 {
        return None;
    }
    Some(String::from_utf16_lossy(&buffer[..len as usize]))
}

pub fn describe_exit(status: ExitStatus) -> String {
    // No signals here, so there is no second case to report.
    match status.code() {
        Some(code) => format!("exit code {code}"),
        None => "an unknown status".into(),
    }
}

pub fn free_space(path: &Path) -> Option<u64> {
    let wide = wide(path.as_os_str());
    let mut available: u64 = 0;
    // SAFETY: a NUL-terminated wide path and one owned out-parameter; the two
    // totals are optional and passed as null.
    let ok = unsafe {
        GetDiskFreeSpaceExW(
            wide.as_ptr(),
            &mut available,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    };
    // Free *to this caller*, not free on the volume: a per-user quota is the
    // number that decides whether the model download finishes.
    (ok != 0).then_some(available)
}

pub fn total_memory_bytes() -> Option<u64> {
    let mut status: MEMORYSTATUSEX = unsafe { std::mem::zeroed() };
    status.dwLength = std::mem::size_of::<MEMORYSTATUSEX>() as u32;
    // SAFETY: an owned struct whose `dwLength` is set, as the call requires.
    let ok = unsafe { GlobalMemoryStatusEx(&mut status) };
    (ok != 0 && status.ullTotalPhys > 0).then_some(status.ullTotalPhys)
}

fn wide(text: &std::ffi::OsStr) -> Vec<u16> {
    text.encode_wide().chain(std::iter::once(0)).collect()
}
