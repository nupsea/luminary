//! Render a page in a hidden webview and return its post-JavaScript DOM.
//!
//! # Why this exists
//!
//! Some articles *compute* their content instead of embedding it. Measured across
//! four JavaScript-heavy pages, rendering changed nothing on three; on the fourth
//! it was the difference between 0 and 78 figures, inserted by the page's own
//! script and present nowhere in the HTML. Embedded-payload extraction was
//! measured as the cheaper alternative and does not reach that class: the page
//! carries no `__NEXT_DATA__`, no `self.__next_f`, no JSON-LD article body.
//!
//! # Why the webview rather than a bundled browser
//!
//! The OS already provides the engine this application embeds -- WKWebView,
//! WebView2, WebKitGTK. The bundled alternative measured 308MB (Chromium plus
//! Playwright's own Node runtime), more than a fifth of the application, for one
//! page class in nine.
//!
//! # Why the title channel rather than IPC
//!
//! `eval` is fire-and-forget in Tauri v2, so a value has to come back some other
//! way. The documented way is IPC, which would mean granting a capability to a
//! window showing an arbitrary third-party page, and minting one per render
//! window because capabilities name windows by label. The title channel needs
//! neither: `on_document_title_changed` moves a string while the page's entire
//! capability stays "set your own title".
//!
//! Capabilities *do* gate application commands, contrary to what this comment
//! once claimed -- an app manifest (`build.rs`) generates an `allow-<command>`
//! permission per command, and `resolve_access` is consulted for every command
//! from a remote origin whether or not a manifest exists
//! (tauri-2.11.5/src/webview/mod.rs:1820). That mistake is what made this module
//! unreachable: the SPA is served over loopback and is therefore a remote
//! origin, so its `render_page` invokes were rejected before arriving. Granting
//! one command to one window is therefore possible, and an IPC-based rewrite is
//! the fallback if the title channel proves fragile in the field.

use std::sync::mpsc::{sync_channel, Receiver, SyncSender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use tauri::{AppHandle, Manager, Url, WebviewUrl, WebviewWindowBuilder};

/// Beyond this a page is not going to settle and the import should stop waiting.
/// Bracketing cases: a compute-heavy article finishes in about three seconds; one
/// still working at thirty is blocked on something the static fetch handles better.
const RENDER_TIMEOUT: Duration = Duration::from_secs(30);

/// Grace after `load` for scripts that insert nodes once the network goes quiet.
const SETTLE_MS: u32 = 1_500;

/// Percent-encoded characters per title.
///
/// WKWebView truncates `document.title` at exactly 1000 characters, measured:
/// a chunk declaring 4673 delivered 985, and 985 plus its 15-character header
/// is 1000. The payload is chunked *after* encoding, so this is an exact
/// ceiling rather than an estimate -- encoding first also means a multi-byte
/// character can no longer straddle a chunk boundary.
///
/// 900 leaves room for the longest header this can produce and still clears the
/// limit with margin. Each title declares its own length regardless, so a
/// platform with a smaller limit fails loudly instead of corrupting the
/// document -- which is how the 1000 was found.
const TITLE_PAYLOAD_CHARS: usize = 900;

/// Marks a title as ours. A page that animates its own title is noise to be
/// ignored, not a failure.
const PREFIX: &str = "LUMX:";

/// Installed before any of the page's own scripts. Serialises the document, then
/// feeds it out one title at a time, advancing only when Rust asks for the next.
/// The handshake is what makes the channel lossless: titles cannot be coalesced
/// or dropped when the next is not sent until the previous has been read.
const CAPTURE_SCRIPT: &str = r#"
(function () {
  var BUDGET = __BUDGET__, SETTLE = __SETTLE__, parts = null, index = 0;

  function split(text) {
    var encoded;
    // Encoding the whole document once, then slicing the result, is what makes
    // the budget exact: slicing first left the encoded size unknown until after
    // the title was set, and a multi-byte character could straddle the cut.
    try { encoded = encodeURIComponent(text); }
    catch (e) { return ['']; }
    var out = [], at = 0;
    while (at < encoded.length) {
      var take = Math.min(BUDGET, encoded.length - at);
      // Never end a piece inside a %XX escape, or the decoder drops it and the
      // next piece opens with two orphaned hex digits.
      if (at + take < encoded.length) {
        if (encoded.charAt(at + take - 1) === '%') take -= 1;
        else if (encoded.charAt(at + take - 2) === '%') take -= 2;
      }
      out.push(encoded.substr(at, take));
      at += take;
    }
    return out.length ? out : [''];
  }

  function send() {
    if (!parts || index >= parts.length) return;
    var piece = parts[index];
    // The declared length is what makes truncation detectable: a title clipped
    // by the platform still parses, and without this the missing tail would be
    // spliced into the document as if it had arrived.
    document.title =
      'LUMX:' + index + ':' + parts.length + ':' + piece.length + ':' + piece;
  }

  function start() {
    try { parts = split(document.documentElement.outerHTML); }
    catch (e) { parts = ['']; }
    index = 0;
    send();
  }

  window.__luminaryNext = function () { index += 1; send(); };

  if (document.readyState === 'complete') { setTimeout(start, SETTLE); }
  else { window.addEventListener('load', function () { setTimeout(start, SETTLE); }); }
})();
"#;

/// The URL pattern granting the SPA access to `render_page`.
///
/// Matched against the request origin by the ACL, so it has to be a URL pattern
/// and not a plain string. The port is included because it is known by the time
/// the grant is made: a wildcard would extend the grant to anything else
/// listening on loopback. Path, query and fragment are left off deliberately --
/// the pattern parser fills them with `*`, so every route of the SPA matches.
pub(crate) fn spa_origin_pattern(port: u16) -> String {
    format!("http://127.0.0.1:{port}")
}

/// One chunk of the document, as carried by a title.
#[derive(Debug, PartialEq, Eq)]
pub(crate) struct Chunk {
    pub index: usize,
    pub total: usize,
    /// Length the page said it sent, in UTF-16 code units -- `String.length`.
    pub declared_len: usize,
    pub payload: String,
}

impl Chunk {
    /// Whether all of the chunk survived the trip through the title.
    fn intact(&self) -> bool {
        self.payload.encode_utf16().count() == self.declared_len
    }
}

/// Parse a title into a chunk, or `None` when the page set its own title.
pub(crate) fn parse_chunk(title: &str) -> Option<Chunk> {
    let rest = title.strip_prefix(PREFIX)?;
    let mut parts = rest.splitn(4, ':');
    let index: usize = parts.next()?.parse().ok()?;
    let total: usize = parts.next()?.parse().ok()?;
    let declared_len: usize = parts.next()?.parse().ok()?;
    let payload = parts.next()?.to_string();
    if total == 0 || index >= total {
        return None;
    }
    Some(Chunk {
        index,
        total,
        declared_len,
        payload,
    })
}

/// Decode `encodeURIComponent` output. Hand-rolled to keep the shell free of a
/// dependency for twenty lines of work; invalid escapes are passed through rather
/// than failing, because a partially odd title should not lose a whole import.
pub(crate) fn percent_decode(input: &str) -> String {
    let bytes = input.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            let hi = (bytes[i + 1] as char).to_digit(16);
            let lo = (bytes[i + 2] as char).to_digit(16);
            if let (Some(h), Some(l)) = (hi, lo) {
                out.push((h * 16 + l) as u8);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// Hosts compare on their last two labels, so `www.x.com` and `cdn.x.com` count as
/// the site the user asked for. Deliberately coarse: this decides which
/// navigations to refuse, not a cookie-policy boundary.
pub(crate) fn registrable(host: &str) -> String {
    let mut labels: Vec<&str> = host.rsplit('.').take(2).collect();
    labels.reverse();
    labels.join(".")
}

pub(crate) fn same_site(a: &Url, b: &Url) -> bool {
    match (a.host_str(), b.host_str()) {
        (Some(x), Some(y)) => registrable(x) == registrable(y),
        _ => false,
    }
}

/// What the capture channel carries: the assembled document, or why it stopped.
type Captured = Result<String, String>;

/// Chunks as they arrive, assembled once the last one lands.
struct Assembly {
    parts: Vec<Option<String>>,
    done: Option<SyncSender<Captured>>,
}

impl Assembly {
    fn new(done: SyncSender<Captured>) -> Self {
        Self {
            parts: Vec::new(),
            done: Some(done),
        }
    }

    /// Chunks in hand and chunks expected, for reporting a stalled transfer.
    fn progress(&self) -> (usize, usize) {
        (
            self.parts.iter().filter(|p| p.is_some()).count(),
            self.parts.len(),
        )
    }

    fn finish(&mut self, outcome: Captured) {
        if let Some(tx) = self.done.take() {
            let _ = tx.try_send(outcome);
        }
    }

    /// Record a chunk. Returns true when the caller should ask for the next one.
    fn accept(&mut self, chunk: Chunk) -> bool {
        // A truncated chunk is not a smaller document, it is a corrupt one, and
        // the extraction downstream cannot tell the difference. Abandon the
        // render so the import falls back to the static fetch.
        if !chunk.intact() {
            self.finish(Err(format!(
                "the title channel truncated chunk {} of {}: {} of {} characters arrived",
                chunk.index + 1,
                chunk.total,
                chunk.payload.encode_utf16().count(),
                chunk.declared_len,
            )));
            return false;
        }
        if self.parts.len() != chunk.total {
            self.parts = vec![None; chunk.total];
        }
        self.parts[chunk.index] = Some(chunk.payload);
        if self.parts.iter().all(Option::is_some) {
            let html: String = self
                .parts
                .iter()
                .map(|p| percent_decode(p.as_deref().unwrap_or("")))
                .collect();
            self.finish(Ok(html));
            return false;
        }
        true
    }
}

/// Load `url` in a hidden webview and return the DOM its scripts produced.
///
/// Every failure is the caller's cue to fall back to the static fetch, never to
/// fail the import: the overwhelming majority of pages import identically without
/// this, and a page that will not render is not a broken article.
#[tauri::command]
pub async fn render_page(app: AppHandle, url: String) -> Result<String, String> {
    let target = Url::parse(&url).map_err(|e| format!("not a url: {e}"))?;
    if !matches!(target.scheme(), "http" | "https") {
        return Err("only http and https pages can be rendered".into());
    }

    let label = format!("luminary-render-{}", nanos());
    let (tx, rx): (SyncSender<Captured>, Receiver<Captured>) = sync_channel(1);
    let assembly = Arc::new(Mutex::new(Assembly::new(tx)));

    let script = CAPTURE_SCRIPT
        .replace("__BUDGET__", &TITLE_PAYLOAD_CHARS.to_string())
        .replace("__SETTLE__", &SETTLE_MS.to_string());

    let nav_guard = target.clone();
    let sink = assembly.clone();

    WebviewWindowBuilder::new(&app, &label, WebviewUrl::External(target))
        .title("")
        .visible(false)
        .focused(false)
        .skip_taskbar(true)
        .initialization_script(&script)
        // The page may not leave the site the user asked for, so no redirect
        // chain, ad frame or tracker hop reaches the network.
        .on_navigation(move |candidate| same_site(candidate, &nav_guard))
        .on_document_title_changed(move |window, title| {
            let Some(chunk) = parse_chunk(&title) else {
                return;
            };
            let wants_more = sink.lock().map(|mut a| a.accept(chunk)).unwrap_or(false);
            if wants_more {
                let _ = window.eval("window.__luminaryNext && window.__luminaryNext()");
            }
        })
        .build()
        .map_err(|e| format!("could not open the render view: {e}"))?;

    // Blocking receive on a worker so the async runtime keeps serving the app
    // while a page settles.
    let html = tauri::async_runtime::spawn_blocking(move || rx.recv_timeout(RENDER_TIMEOUT))
        .await
        .map_err(|e| format!("render worker failed: {e}"))?;

    // Destroy before interpreting the outcome: a hidden window that outlives its
    // request is a page still executing with nobody reading it.
    if let Some(window) = app.get_webview_window(&label) {
        let _ = window.destroy();
    }

    match html {
        Ok(Ok(dom)) if !dom.trim().is_empty() => Ok(dom),
        Ok(Ok(_)) => Err("the page rendered nothing".into()),
        Ok(Err(reason)) => Err(reason),
        // How far the transfer got separates a page that never started from one
        // whose document is simply larger than the budget allows in the time.
        Err(_) => Err(match assembly.lock().map(|a| a.progress()) {
            Ok((got, total)) if total > 0 => {
                format!("the page did not settle in time: {got} of {total} chunks arrived")
            }
            _ => "the page did not settle in time".into(),
        }),
    }
}

/// A label unique within this process. Not a UUID: nothing depends on it beyond
/// two concurrent renders not colliding.
fn nanos() -> u128 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_title_we_sent_parses() {
        let c = parse_chunk("LUMX:0:3:3:abc").unwrap();
        assert_eq!(
            c,
            Chunk {
                index: 0,
                total: 3,
                declared_len: 3,
                payload: "abc".into()
            }
        );
        assert!(c.intact());
    }

    #[test]
    fn a_payload_containing_colons_survives() {
        let c = parse_chunk("LUMX:1:2:7:a%3Ab:c").unwrap();
        assert_eq!(c.payload, "a%3Ab:c");
        assert!(c.intact());
    }

    #[test]
    fn a_page_setting_its_own_title_is_ignored() {
        assert!(parse_chunk("Breaking news").is_none());
        assert!(parse_chunk("LUMX:notanumber:2:1:x").is_none());
        assert!(parse_chunk("LUMX:5:2:1:x").is_none(), "index past total");
        assert!(parse_chunk("LUMX:0:0:1:x").is_none(), "zero total");
    }

    #[test]
    fn a_full_title_stays_under_the_platform_limit() {
        // WKWebView truncates document.title at exactly 1000 characters. Found
        // the hard way: a 3000-character chunk declared 4673 encoded characters
        // and delivered 985, and 985 + its 15-character header is 1000. Raising
        // the payload past this ceiling does not fail loudly at the call site --
        // it silently clips every title.
        const OBSERVED_TITLE_LIMIT: usize = 1000;

        // Widest header this protocol can emit: implausible index and total, so
        // the assertion holds for any document rather than a typical one.
        let header = format!(
            "{PREFIX}{}:{}:{}:",
            usize::MAX,
            usize::MAX,
            TITLE_PAYLOAD_CHARS
        );
        assert!(
            header.len() + TITLE_PAYLOAD_CHARS <= OBSERVED_TITLE_LIMIT,
            "a full title is {} characters, over the {OBSERVED_TITLE_LIMIT} the platform keeps",
            header.len() + TITLE_PAYLOAD_CHARS,
        );
    }

    #[test]
    fn a_truncated_title_is_refused_rather_than_spliced_in() {
        // A platform that clips the title still yields a parseable chunk. Without
        // the declared length the missing tail would land in the document as if
        // it had arrived, and the extraction downstream cannot tell.
        let clipped = parse_chunk("LUMX:0:2:900:abc").unwrap();
        assert!(!clipped.intact());

        let (tx, rx) = sync_channel(1);
        let mut a = Assembly::new(tx);
        assert!(!a.accept(clipped), "a truncated chunk must stop the render");
        let err = rx.recv().unwrap().unwrap_err();
        assert!(err.contains("truncated"), "{err}");
        assert!(err.contains("3 of 900"), "{err}");
    }

    #[test]
    fn percent_decoding_round_trips_real_markup() {
        assert_eq!(percent_decode("%3Cp%3Ehi%3C%2Fp%3E"), "<p>hi</p>");
        assert_eq!(percent_decode("a%20b%0Ac"), "a b\nc");
        assert_eq!(percent_decode("caf%C3%A9"), "café");
    }

    #[test]
    fn a_malformed_escape_is_passed_through_not_dropped() {
        assert_eq!(percent_decode("100%"), "100%");
        assert_eq!(percent_decode("%zz"), "%zz");
    }

    #[test]
    fn chunks_assemble_in_any_order() {
        let (tx, rx) = sync_channel(1);
        let mut a = Assembly::new(tx);
        assert!(a.accept(Chunk {
            index: 1,
            total: 2,
            declared_len: 10,
            payload: "%3C%2Fp%3E".into(),
        }));
        assert!(!a.accept(Chunk {
            index: 0,
            total: 2,
            declared_len: 7,
            payload: "%3Cp%3E".into(),
        }));
        assert_eq!(rx.recv().unwrap().unwrap(), "<p></p>");
    }

    #[test]
    fn the_spa_grant_matches_the_origin_the_shell_navigates_to() {
        use tauri::utils::acl::RemoteUrlPattern;

        // main.rs navigates the main window to exactly this, so the ACL must
        // match it or every `render_page` invoke is rejected before reaching
        // Rust -- which is precisely the failure this pattern was written for.
        let pattern: RemoteUrlPattern = spa_origin_pattern(7820).parse().unwrap();
        assert!(pattern.test(&Url::parse("http://127.0.0.1:7820").unwrap()));
        assert!(pattern.test(&Url::parse("http://127.0.0.1:7820/").unwrap()));
        assert!(pattern.test(&Url::parse("http://127.0.0.1:7820/library?q=1").unwrap()));

        // A different port is a different process, and no port at all is a
        // different origin again.
        assert!(!pattern.test(&Url::parse("http://127.0.0.1:7821/").unwrap()));
        assert!(!pattern.test(&Url::parse("http://127.0.0.1/").unwrap()));
        assert!(!pattern.test(&Url::parse("https://127.0.0.1:7820/").unwrap()));
        assert!(!pattern.test(&Url::parse("http://example.test:7820/").unwrap()));
    }

    #[test]
    fn subdomains_are_the_same_site_but_lookalikes_are_not() {
        let page = Url::parse("https://anthropic.com/x").unwrap();
        assert!(same_site(
            &Url::parse("https://www.anthropic.com/y").unwrap(),
            &page
        ));
        assert!(!same_site(
            &Url::parse("https://googletagmanager.com/g.js").unwrap(),
            &page
        ));
        assert!(!same_site(
            &Url::parse("https://anthropic.com.evil.test/x").unwrap(),
            &page
        ));
    }
}
