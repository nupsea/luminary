//! Turning a boot failure into something a stranger can safely send us.
//!
//! Two rules govern everything here. The report is shown in full before it can
//! be sent, and it is scrubbed before it is shown -- a crash report from a
//! personal knowledge app carries the user's real name in every path and may
//! carry API keys from their settings.

use std::sync::OnceLock;

use percent_encoding::{utf8_percent_encode, AsciiSet, NON_ALPHANUMERIC};
use regex::Regex;

pub const REPO: &str = "nupsea/luminary";

/// GitHub rejects very long URLs, and browsers have their own limits well below
/// the theoretical maximum. Stay comfortably under both.
const MAX_URL: usize = 6000;

/// Present at an absolute path on macOS; on Windows it ships in System32 and is
/// found on `PATH`, which is where every modern Windows install has it.
#[cfg(windows)]
const CURL: &str = "curl.exe";
#[cfg(not(windows))]
const CURL: &str = "/usr/bin/curl";

/// `-`, `.`, `_` and `~` are unreserved in RFC 3986 and need no escaping.
const QUERY: &AsciiSet = &NON_ALPHANUMERIC
    .remove(b'-')
    .remove(b'.')
    .remove(b'_')
    .remove(b'~');

pub struct Report {
    pub step: String,
    pub message: String,
    pub detail: String,
    pub log: Vec<String>,
    /// Port the bundled Ollama was started on, 0 when it never started. Its
    /// HTTP API is asked for the version and model list rather than the `ollama`
    /// binary: the bundled one is not on PATH and answers on a private port.
    pub ollama_port: u16,
}

fn rx(slot: &'static OnceLock<Regex>, pattern: &str) -> &'static Regex {
    slot.get_or_init(|| Regex::new(pattern).expect("static pattern compiles"))
}

/// Remove personal and secret material.
///
/// Deliberately aggressive: over-redacting costs a round trip asking for more,
/// under-redacting publishes someone's API key on a public issue tracker.
pub fn redact(text: &str) -> String {
    static KEYS: OnceLock<Regex> = OnceLock::new();
    static ASSIGN: OnceLock<Regex> = OnceLock::new();
    static EMAIL: OnceLock<Regex> = OnceLock::new();

    // Recognisable key shapes first: these are unambiguous wherever they appear,
    // including inside prose that no assignment pattern would match.
    let out = rx(
        &KEYS,
        r"(?x)
          sk-ant-[A-Za-z0-9_\-]{16,}
        | sk-[A-Za-z0-9]{16,}
        | gh[pousr]_[A-Za-z0-9]{16,}
        | github_pat_[A-Za-z0-9_]{20,}
        | AKIA[0-9A-Z]{16}
        | eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}
        ",
    )
    .replace_all(text, "<redacted>");

    // Then anything named like a credential, however it is spelled.
    let out = rx(
        &ASSIGN,
        r#"(?i)\b([a-z0-9_\-]*(?:api[_\-]?key|token|secret|password|passwd|authorization|bearer))\b(["']?\s*[:=]\s*["']?)([^\s"',;}\)]+)"#,
    )
    .replace_all(&out, "$1$2<redacted>");

    let out = rx(
        &EMAIL,
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
    )
    .replace_all(&out, "<redacted-email>");

    scrub_home(&out)
}

/// Paths carry the user's real name. Replace the home directory, then any bare
/// occurrence of the account name left behind by other tools.
fn scrub_home(text: &str) -> String {
    match home_dir() {
        Some(home) => scrub_home_in(text, &home),
        None => text.to_string(),
    }
}

/// The user's home, whatever this platform calls it.
///
/// Windows leaves `HOME` unset, so reading only that would have shipped every
/// `C:\Users\<their real name>\...` path in every Windows report unredacted.
fn home_dir() -> Option<String> {
    let key = if cfg!(windows) { "USERPROFILE" } else { "HOME" };
    std::env::var_os(key).map(|h| h.to_string_lossy().into_owned())
}

/// Split out so it can be tested without mutating the process environment,
/// which would race every other test that calls `redact`.
fn scrub_home_in(text: &str, home: &str) -> String {
    if home.is_empty() {
        return text.to_string();
    }
    let out = text.replace(home, "~");

    match home.rsplit(['/', '\\']).next() {
        // A very short account name would collide with ordinary words.
        Some(user) if user.len() >= 3 => out.replace(user, "<user>"),
        _ => out,
    }
}

/// A short stable id for "this same failure", so duplicate reports of one bug
/// can be recognised as duplicates. Digits and paths are dropped first so that
/// ports, pids and home directories do not split one bug into many.
pub fn fingerprint(step: &str, message: &str) -> String {
    static NOISE: OnceLock<Regex> = OnceLock::new();
    let normalized = rx(&NOISE, r#"[0-9]+|/[^\s"']+"#).replace_all(message, "");

    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in step
        .bytes()
        .chain(b":".iter().copied())
        .chain(normalized.bytes())
    {
        hash ^= byte as u64;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("{hash:016x}")[..8].to_string()
}

fn run(bin: &str, args: &[&str]) -> Option<String> {
    let mut cmd = std::process::Command::new(bin);
    cmd.args(args);
    // Same treatment every child of this shell gets: no console window flashing
    // up behind the report dialog on Windows.
    let out = luminary_host::before_spawn(&mut cmd).output().ok()?;
    let text = String::from_utf8_lossy(&out.stdout).trim().to_string();
    (!text.is_empty()).then_some(text)
}

#[cfg(target_os = "macos")]
pub fn os_version() -> String {
    let product = run("/usr/bin/sw_vers", &["-productVersion"]).unwrap_or_else(|| "unknown".into());
    format!("macOS {product} ({})", std::env::consts::ARCH)
}

/// macOS build and kernel, which distinguish two machines reporting the same
/// product version -- the pair asked for in nupsea/luminary#41.
#[cfg(target_os = "macos")]
fn os_detail() -> String {
    let build = run("/usr/bin/sw_vers", &["-buildVersion"]).unwrap_or_else(|| "unknown".into());
    let kernel = run("/usr/bin/uname", &["-r"]).unwrap_or_else(|| "unknown".into());
    format!("build {build}, Darwin {kernel}")
}

#[cfg(windows)]
pub fn os_version() -> String {
    let raw = run("cmd", &["/c", "ver"]).unwrap_or_default();
    format!(
        "Windows {} ({})",
        windows_release(&raw),
        std::env::consts::ARCH
    )
}

#[cfg(windows)]
fn os_detail() -> String {
    run("cmd", &["/c", "ver"]).unwrap_or_else(|| "unknown".into())
}

#[cfg(all(unix, not(target_os = "macos")))]
pub fn os_version() -> String {
    let release = run("/usr/bin/uname", &["-r"]).unwrap_or_else(|| "unknown".into());
    format!("Linux {release} ({})", std::env::consts::ARCH)
}

#[cfg(all(unix, not(target_os = "macos")))]
fn os_detail() -> String {
    run(
        "/bin/sh",
        &["-c", ". /etc/os-release && echo \"$PRETTY_NAME\""],
    )
    .unwrap_or_else(|| "unknown distribution".into())
}

/// The build out of `cmd /c ver`, which prints
/// `Microsoft Windows [Version 10.0.22631.4317]`.
///
/// The build number is the whole point: "Windows 11" is not a version anyone
/// can act on, and 10.0.22000 versus 10.0.19045 is the difference between the
/// two supported releases. Falls back to the raw line rather than to
/// "unknown" -- an unexpected format still says more than nothing.
#[cfg(any(windows, test))]
fn windows_release(raw: &str) -> String {
    raw.rsplit_once("Version ")
        .and_then(|(_, rest)| rest.split_once(']'))
        .map(|(version, _)| version.trim().to_string())
        .filter(|v| !v.is_empty())
        .unwrap_or_else(|| {
            let raw = raw.trim();
            if raw.is_empty() {
                "unknown".into()
            } else {
                raw.to_string()
            }
        })
}

/// Blocking, and deliberately so: a report is assembled on demand, not on a hot
/// path, and a short timeout beats an async runtime here.
fn ollama_get(port: u16, path: &str) -> Option<String> {
    if port == 0 {
        return None;
    }
    let url = format!("http://127.0.0.1:{port}{path}");
    run(CURL, &["-sf", "--max-time", "3", &url])
}

fn json_strings(body: &str, key: &str) -> Vec<String> {
    let needle = format!("\"{key}\":\"");
    body.match_indices(&needle)
        .filter_map(|(at, _)| {
            let rest = &body[at + needle.len()..];
            rest.find('"').map(|end| rest[..end].to_string())
        })
        .collect()
}

/// Version and installed models, as issue #41 asked for. Absent rather than
/// guessed when Ollama is not answering -- "unknown" here is itself a useful
/// fact in a bug report.
fn ollama_summary(port: u16) -> String {
    let version = ollama_get(port, "/api/version")
        .and_then(|body| json_strings(&body, "version").into_iter().next())
        .unwrap_or_else(|| "not answering".into());

    let models = ollama_get(port, "/api/tags")
        .map(|body| json_strings(&body, "name"))
        .unwrap_or_default();

    let listed = if models.is_empty() {
        "no models installed".to_string()
    } else {
        models.join(", ")
    };
    format!("Ollama {version} -- {listed}")
}

pub fn app_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

impl Report {
    /// Everything needed to reproduce, on its own lines.
    ///
    /// One line was not enough once this had to carry the OS build, the kernel
    /// and the model list, so the issue form's field is a textarea.
    pub fn environment(&self) -> String {
        format!(
            "Luminary {} (desktop app)\n{}, {}\n{}\nLast boot step: {}",
            app_version(),
            os_version(),
            os_detail(),
            ollama_summary(self.ollama_port),
            self.step,
        )
    }

    pub fn what_happened(&self) -> String {
        let opening = if self.failed() {
            "Luminary did not finish starting up."
        } else {
            "Reported from a running Luminary."
        };
        format!(
            "{}\n\nWhat the app reported: {}\n\nDetails: {}\n\n\
             (Please add what you were doing just before this.)",
            opening,
            self.message,
            if self.detail.is_empty() {
                "none"
            } else {
                &self.detail
            },
        )
    }

    /// A report raised from Settings while everything works is a feature request
    /// or a non-fatal bug, not a startup failure, and must not claim to be one.
    fn failed(&self) -> bool {
        !self.message.is_empty() && self.step != "ready"
    }

    /// The whole thing as plain text, for the clipboard.
    pub fn to_text(&self) -> String {
        redact(&format!(
            "{}\n\n{}\n\nLog:\n{}",
            self.environment(),
            self.what_happened(),
            self.log.join("\n"),
        ))
    }

    /// A prefilled issue form. Nothing is sent by opening this -- the user still
    /// reviews the form and presses Submit on GitHub.
    ///
    /// Field names are the `id`s in `.github/ISSUE_TEMPLATE/bug_report.yml`.
    pub fn issue_url(&self) -> String {
        let title = if self.failed() {
            format!(
                "[Bug]: startup failed at '{}' ({})",
                self.step,
                fingerprint(&self.step, &self.message)
            )
        } else {
            "[Bug]: ".to_string()
        };
        let desc = redact(&self.what_happened());
        let env = redact(&self.environment());

        let base = format!(
            "https://github.com/{REPO}/issues/new?template=bug_report.yml&title={}&env_info={}&bug_desc={}",
            enc(&title),
            enc(&env),
            enc(&desc),
        );

        // Give the log whatever budget is left, trimming from the oldest lines.
        let mut lines: Vec<&str> = self.log.iter().map(String::as_str).collect();
        loop {
            let logs = redact(&lines.join("\n"));
            let url = format!("{base}&logs={}", enc(&logs));
            if url.len() <= MAX_URL || lines.is_empty() {
                return url;
            }
            lines.remove(0);
        }
    }
}

fn enc(value: &str) -> String {
    utf8_percent_encode(value, QUERY).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn report(detail: &str) -> Report {
        Report {
            step: "backend".into(),
            message: "Luminary's engine stopped during startup".into(),
            detail: detail.into(),
            log: vec!["line one".into(), "line two".into()],
            // 0 = never started, so no request is made from a test.
            ollama_port: 0,
        }
    }

    #[test]
    fn known_key_shapes_never_survive() {
        for secret in [
            "sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAA",
            "sk-AAAAAAAAAAAAAAAAAAAAAAAA",
            "ghp_AAAAAAAAAAAAAAAAAAAAAAAA",
            "github_pat_AAAAAAAAAAAAAAAAAAAAAAAA",
            "AKIAIOSFODNN7EXAMPLE",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        ] {
            let out = redact(&format!("something failed: {secret} was rejected"));
            assert!(!out.contains(secret), "leaked {secret}: {out}");
        }
    }

    #[test]
    fn credential_assignments_are_redacted_however_spelled() {
        for line in [
            "OPENAI_API_KEY=hunter2trustno1",
            "apikey: hunter2trustno1",
            "Authorization: hunter2trustno1",
            "\"password\": \"hunter2trustno1\"",
            "ANTHROPIC_TOKEN = hunter2trustno1",
        ] {
            let out = redact(line);
            assert!(
                !out.contains("hunter2trustno1"),
                "leaked in {line:?}: {out}"
            );
        }
    }

    #[test]
    fn the_home_directory_and_account_name_are_scrubbed() {
        let out = scrub_home_in(
            "failed to open /Users/aurelia/Library/Logs/x, owner aurelia",
            "/Users/aurelia",
        );
        assert!(!out.contains("aurelia"), "leaked the account name: {out}");
        assert!(out.contains('~'));
    }

    #[test]
    fn a_windows_home_is_scrubbed_too() {
        // `HOME` is unset on Windows, so this ran with nothing to strip until
        // `home_dir` learned about `USERPROFILE` -- every report from there
        // carried the user's real name in every path.
        let out = scrub_home_in(
            r"could not open C:\Users\aurelia\AppData\Local\Luminary\Logs, owner aurelia",
            r"C:\Users\aurelia",
        );
        assert!(!out.contains("aurelia"), "leaked the account name: {out}");
        assert!(out.contains('~'));
    }

    #[test]
    fn an_absent_home_is_not_a_panic() {
        assert_eq!(scrub_home_in("nothing to do", ""), "nothing to do");
    }

    #[test]
    fn the_windows_build_number_survives_the_version_banner() {
        // The build is the whole value of the line: 10.0.19045 and 10.0.22631
        // are the two supported releases, and "Windows 11" separates nothing.
        assert_eq!(
            windows_release("Microsoft Windows [Version 10.0.22631.4317]"),
            "10.0.22631.4317"
        );
        // Localised banners keep the bracketed version; only the words change.
        assert_eq!(
            windows_release("Microsoft Windows [Version 10.0.19045.5011]\r\n"),
            "10.0.19045.5011"
        );
    }

    #[test]
    fn an_unrecognised_version_banner_is_reported_rather_than_dropped() {
        // "unknown" in a bug report costs a round trip with the reporter. Any
        // line at all is worth more than that.
        assert_eq!(windows_release("Windows, probably"), "Windows, probably");
        assert_eq!(windows_release("   "), "unknown");
    }

    #[test]
    fn the_same_failure_fingerprints_the_same_despite_ports_and_paths() {
        let a = fingerprint("backend", "did not answer on 127.0.0.1:52341 within 180s");
        let b = fingerprint("backend", "did not answer on 127.0.0.1:61002 within 180s");
        assert_eq!(a, b);

        let c = fingerprint("stage", "did not answer on 127.0.0.1:52341 within 180s");
        assert_ne!(a, c, "the step must participate in the fingerprint");
        assert_eq!(a.len(), 8);
    }

    #[test]
    fn the_issue_url_stays_within_limits_by_dropping_oldest_log_lines() {
        let mut r = report("boom");
        r.log = (0..5000)
            .map(|i| format!("log line number {i} with padding"))
            .collect();

        let url = r.issue_url();
        assert!(url.len() <= MAX_URL, "url was {} chars", url.len());
        // The newest lines are the ones that matter, so they are what survives.
        assert!(url.contains("4999"));
    }

    #[test]
    fn the_url_targets_the_bug_form_and_carries_every_field() {
        let url = report("boom").issue_url();
        assert!(url.starts_with(&format!("https://github.com/{REPO}/issues/new?")));
        for field in [
            "template=bug_report.yml",
            "title=",
            "env_info=",
            "bug_desc=",
            "logs=",
        ] {
            assert!(url.contains(field), "missing {field}");
        }
        assert!(!url.contains(' '), "unencoded space in {url}");
    }

    /// What the OS line must name on the host running this test.
    ///
    /// Not the whole `os_detail` string: macOS reports a build and a Darwin
    /// version, Windows a single banner, and a shared assertion would only be
    /// whichever one is weaker. The platform name plus the architecture is the
    /// part every host owes the report.
    #[cfg(target_os = "macos")]
    const OS_MARKERS: [&str; 3] = ["macOS ", "build ", "Darwin "];
    #[cfg(windows)]
    const OS_MARKERS: [&str; 2] = ["Windows ", "Version "];
    #[cfg(all(unix, not(target_os = "macos")))]
    const OS_MARKERS: [&str; 1] = ["Linux "];

    #[test]
    fn the_environment_carries_what_reproducing_needs() {
        // nupsea/luminary#41: a version and an OS name were not enough to
        // rebuild someone's setup.
        let env = report("boom").environment();
        for expected in ["Luminary ", "Ollama "].iter().chain(OS_MARKERS.iter()) {
            assert!(env.contains(expected), "missing {expected:?} in {env}");
        }
        assert!(
            env.contains(std::env::consts::ARCH),
            "no architecture in {env}"
        );
        // The probe answering with "unknown" is the failure this whole field
        // has: a report that names no version costs a round trip with the
        // person who filed it.
        let version = os_version();
        assert!(
            !version.contains("unknown"),
            "the OS probe failed: {version}"
        );
        assert!(env.lines().count() >= 4, "collapsed to one line: {env}");
    }

    #[test]
    fn an_unreachable_ollama_says_so_rather_than_guessing() {
        assert!(ollama_summary(0).contains("not answering"));
    }

    #[test]
    fn model_names_are_read_out_of_the_tags_response() {
        let body = r#"{"models":[{"name":"llama3.2:latest","size":2019393189},
                       {"name":"qwen2.5vl:7b","size":6000000000}]}"#;
        assert_eq!(
            json_strings(body, "name"),
            vec!["llama3.2:latest", "qwen2.5vl:7b"]
        );
    }

    #[test]
    fn a_report_from_a_running_app_is_not_dressed_as_a_crash() {
        let mut r = report("");
        r.step = "ready".into();
        r.message = "".into();

        assert!(!r.what_happened().contains("did not finish starting up"));
        // No fingerprint in the title: there is no failure to deduplicate.
        assert!(r.issue_url().contains("title=%5BBug%5D%3A%20"));
    }

    #[test]
    fn clipboard_text_is_redacted_too() {
        let mut r = report("OPENAI_API_KEY=hunter2trustno1");
        r.log = vec!["token: hunter2trustno1".into()];
        let text = r.to_text();
        assert!(!text.contains("hunter2trustno1"), "leaked: {text}");
    }
}
