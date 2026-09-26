//! Process trees as process groups, which is what unix has.

use std::path::Path;
use std::process::{Child, Command, ExitStatus};

pub struct Tree {
    pgid: i32,
}

impl Tree {
    pub fn request_stop(&self) {
        signal_group(self.pgid, libc::SIGTERM);
    }

    pub fn kill(&self) {
        signal_group(self.pgid, libc::SIGKILL);
    }

    pub fn covers_descendants(&self) -> bool {
        true
    }

    pub fn group_id(&self) -> i32 {
        self.pgid
    }
}

pub fn before_spawn(cmd: &mut Command) -> &mut Command {
    use std::os::unix::process::CommandExt;

    // A child's own children -- ollama's model runners -- are in this group
    // too, so one signal reaches the whole tree. Signalling only the leader
    // used to strand them.
    cmd.process_group(0)
}

pub fn adopt(child: &Child) -> Tree {
    // Equal to the pid, because `process_group(0)` makes the child its leader.
    Tree {
        pgid: child.id() as i32,
    }
}

pub fn kill_stale_tree(pid: i32, group_id: i32) {
    signal_group(group_id, libc::SIGTERM);
    std::thread::sleep(std::time::Duration::from_millis(500));
    if alive(pid) {
        signal_group(group_id, libc::SIGKILL);
    }
}

fn signal_group(pgid: i32, sig: i32) {
    // pgid 1 is init's group and 0 means "this process's group", which would
    // signal the shell itself.
    if pgid > 1 {
        // SAFETY: a plain kill(2) against a process group we created.
        unsafe { libc::killpg(pgid, sig) };
    }
}

pub fn alive(pid: i32) -> bool {
    if pid <= 1 {
        return false;
    }
    // SAFETY: signal 0 performs error checking without sending anything.
    unsafe { libc::kill(pid, 0) == 0 }
}

/// What is actually running under this pid, as the kernel sees it.
pub fn executable_of(pid: i32) -> Option<String> {
    let out = Command::new("/bin/ps")
        .args(["-p", &pid.to_string(), "-o", "comm="])
        .output()
        .ok()?;
    let path = String::from_utf8_lossy(&out.stdout).trim().to_string();
    (!path.is_empty()).then_some(path)
}

pub fn on_termination(on_signal: impl FnOnce(i32) + Send + 'static) -> std::io::Result<()> {
    use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM};

    let mut signals = signal_hook::iterator::Signals::new([SIGTERM, SIGINT, SIGHUP])?;
    std::thread::Builder::new()
        .name("termination".into())
        .spawn(move || {
            let mut on_signal = Some(on_signal);
            // Keeps the handlers registered, so a repeat signal during the
            // bounded drain is absorbed rather than killing the shell mid-way.
            for signal in signals.forever() {
                if let Some(run) = on_signal.take() {
                    run(signal);
                }
            }
        })?;
    Ok(())
}

pub fn tee_stderr(on_line: impl Fn(&str) + Send + Sync + 'static) -> std::io::Result<()> {
    use std::fs::File;
    use std::io::{BufRead, BufReader, Write};
    use std::os::fd::FromRawFd;
    use std::sync::Arc;

    let mut fds = [0; 2];
    // SAFETY: pipe(2) writes two fds into a correctly sized array.
    if unsafe { libc::pipe(fds.as_mut_ptr()) } != 0 {
        return Err(std::io::Error::last_os_error());
    }
    let (read_end, write_end) = (fds[0], fds[1]);
    // SAFETY: dup(2) and dup2(2) on fds this function owns, plus fd 2. After
    // dup2 the write end lives on as fd 2 only, which children inherit; the
    // other two are close-on-exec so no child holds the pipe open.
    let original = unsafe {
        let original = libc::dup(libc::STDERR_FILENO);
        if original < 0 || libc::dup2(write_end, libc::STDERR_FILENO) < 0 {
            let err = std::io::Error::last_os_error();
            libc::close(read_end);
            libc::close(write_end);
            if original >= 0 {
                libc::close(original);
            }
            return Err(err);
        }
        libc::close(write_end);
        libc::fcntl(read_end, libc::F_SETFD, libc::FD_CLOEXEC);
        libc::fcntl(original, libc::F_SETFD, libc::FD_CLOEXEC);
        original
    };

    let on_line = Arc::new(on_line);
    let for_panic = on_line.clone();
    std::panic::set_hook(Box::new(move |info| {
        let text = format!("{info}\n");
        // SAFETY: write(2) of an owned buffer to an fd kept open for the process lifetime.
        unsafe { libc::write(original, text.as_ptr().cast(), text.len()) };
        for_panic(text.trim_end());
    }));

    // SAFETY: the read end is owned here. `original` is never closed: the panic
    // hook writes to it by number, and a reused fd would receive the panic.
    let reader = unsafe { File::from_raw_fd(read_end) };
    let mut terminal = std::mem::ManuallyDrop::new(unsafe { File::from_raw_fd(original) });
    std::thread::Builder::new()
        .name("stderr".into())
        .spawn(move || {
            for line in BufReader::new(reader).split(b'\n') {
                let Ok(line) = line else { break };
                let _ = terminal.write_all(&line);
                let _ = terminal.write_all(b"\n");
                let text = String::from_utf8_lossy(&line);
                if !text.trim().is_empty() {
                    on_line(text.trim_end());
                }
            }
        })?;
    Ok(())
}

#[cfg(target_os = "linux")]
pub fn end_with_appimage_runtime() {
    let Some(image) = std::env::var_os("APPIMAGE").and_then(|p| std::fs::canonicalize(p).ok())
    else {
        return;
    };
    // SAFETY: getppid, prctl and raise take no pointers.
    let parent = unsafe { libc::getppid() };
    // Only when the runtime itself is the parent (extract-and-run). Under FUSE
    // the parent is the desktop launcher, which may exit the moment it spawns us.
    if std::fs::read_link(format!("/proc/{parent}/exe")).ok() != Some(image) {
        return;
    }
    unsafe { libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM) };
    if unsafe { libc::getppid() } != parent {
        unsafe { libc::raise(libc::SIGTERM) };
    }
}

#[cfg(not(target_os = "linux"))]
pub fn end_with_appimage_runtime() {}

pub fn describe_exit(status: ExitStatus) -> String {
    use std::os::unix::process::ExitStatusExt;

    match (status.code(), status.signal()) {
        (Some(code), _) => format!("exit code {code}"),
        (None, Some(signal)) => format!("killed by signal {signal}"),
        _ => "an unknown status".into(),
    }
}

pub fn free_space(path: &Path) -> Option<u64> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;

    let c_path = CString::new(path.as_os_str().as_bytes()).ok()?;
    let mut stat: libc::statvfs = unsafe { std::mem::zeroed() };
    // SAFETY: a valid NUL-terminated path and an owned, correctly sized struct.
    if unsafe { libc::statvfs(c_path.as_ptr(), &mut stat) } != 0 {
        return None;
    }
    Some(stat.f_bavail as u64 * stat.f_frsize as u64)
}

/// Physical RAM in bytes, or `None` if the kernel will not say.
#[cfg(target_os = "macos")]
pub fn total_memory_bytes() -> Option<u64> {
    let mut bytes: u64 = 0;
    let mut len = std::mem::size_of::<u64>();
    let name = c"hw.memsize";
    // SAFETY: a read-only sysctl into a stack u64 whose size we pass by value.
    let rc = unsafe {
        libc::sysctlbyname(
            name.as_ptr(),
            (&mut bytes as *mut u64).cast(),
            &mut len,
            std::ptr::null_mut(),
            0,
        )
    };
    (rc == 0 && bytes > 0).then_some(bytes)
}

#[cfg(not(target_os = "macos"))]
pub fn total_memory_bytes() -> Option<u64> {
    // SAFETY: two read-only sysconf(3) queries.
    let (pages, page_size) = unsafe {
        (
            libc::sysconf(libc::_SC_PHYS_PAGES),
            libc::sysconf(libc::_SC_PAGESIZE),
        )
    };
    (pages > 0 && page_size > 0).then(|| pages as u64 * page_size as u64)
}
