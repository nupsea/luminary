//! The proxy the shell's children should use, as environment variables (#155).
//!
//! The supervisor clears the environment before spawning, so neither a proxy
//! the user exported nor the Windows system proxy reached Ollama. Ollama is Go,
//! and Go reads only `HTTPS_PROXY`/`HTTP_PROXY`/`NO_PROXY`, never the registry,
//! so a model pull on a proxied company network failed however the proxy was set.
//!
//! The rules mirror the backend's `app/proxy_env.py`, so both children get one
//! answer: an exported `*_PROXY` wins and the system proxy is not read; loopback
//! is always exempt, because the backend reaches Ollama on 127.0.0.1.
//! PAC files (`AutoConfigURL`) are not read.

/// What Windows' Internet Settings hold when "Use a proxy server" is on.
pub struct SystemProxy {
    /// `ProxyServer`: `host:port`, or `http=host:port;https=host:port;...`.
    pub server: String,
    /// `ProxyOverride`: `;`-separated hosts, `*.` wildcards, and `<local>`.
    pub bypass: String,
}

const PROXY_VARS: &[&str] = &["HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"];
const LOOPBACK: &[&str] = &["localhost", "127.0.0.1", "::1"];

/// Variables to set on a child. `inherited` reads the shell's own environment.
pub fn proxy_env(
    inherited: impl Fn(&str) -> Option<String>,
    system: Option<SystemProxy>,
) -> Vec<(String, String)> {
    let read = |name: &str| {
        inherited(name)
            .or_else(|| inherited(&name.to_lowercase()))
            .filter(|v| !v.trim().is_empty())
    };

    let mut vars: Vec<(String, String)> = PROXY_VARS
        .iter()
        .filter_map(|name| read(name).map(|v| (name.to_string(), v)))
        .collect();
    let mut bypass: Vec<String> = Vec::new();

    if vars.is_empty() {
        let Some(system) = system else {
            return vars;
        };
        vars = system_vars(&system.server);
        bypass = system
            .bypass
            .split(';')
            .map(|e| e.trim().trim_start_matches('*').to_string())
            .filter(|e| !e.is_empty() && e != "<local>")
            .collect();
        if vars.is_empty() {
            return vars;
        }
    }

    let mut no_proxy: Vec<String> = read("NO_PROXY")
        .map(|v| v.split(',').map(|h| h.trim().to_string()).collect())
        .unwrap_or_default();
    for host in LOOPBACK.iter().map(|h| h.to_string()).chain(bypass) {
        if !host.is_empty() && !no_proxy.contains(&host) {
            no_proxy.push(host);
        }
    }
    vars.push(("NO_PROXY".to_string(), no_proxy.join(",")));
    vars
}

/// `ProxyServer` as `HTTP_PROXY`/`HTTPS_PROXY`, with Python's `urllib` rules:
/// one address serves both schemes, a per-scheme list names each, and an
/// address with no scheme is `http://`.
fn system_vars(server: &str) -> Vec<(String, String)> {
    let with_scheme = |addr: &str| {
        let addr = addr.trim();
        if addr.contains("://") {
            addr.to_string()
        } else {
            format!("http://{addr}")
        }
    };
    let server = server.trim();
    if server.is_empty() {
        return Vec::new();
    }
    if !server.contains('=') {
        let addr = with_scheme(server);
        return vec![
            ("HTTPS_PROXY".to_string(), addr.clone()),
            ("HTTP_PROXY".to_string(), addr),
        ];
    }
    let mut vars = Vec::new();
    for entry in server.split(';') {
        let Some((scheme, addr)) = entry.split_once('=') else {
            continue;
        };
        let name = match scheme.trim().to_ascii_lowercase().as_str() {
            "https" => "HTTPS_PROXY",
            "http" => "HTTP_PROXY",
            _ => continue,
        };
        if !addr.trim().is_empty() {
            vars.push((name.to_string(), with_scheme(addr)));
        }
    }
    vars
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn env(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
        let map: HashMap<String, String> = pairs
            .iter()
            .map(|(k, v)| (k.to_string(), v.to_string()))
            .collect();
        move |name| map.get(name).cloned()
    }

    fn get(vars: &[(String, String)], name: &str) -> Option<String> {
        vars.iter().find(|(k, _)| k == name).map(|(_, v)| v.clone())
    }

    fn windows(server: &str, bypass: &str) -> Option<SystemProxy> {
        Some(SystemProxy {
            server: server.to_string(),
            bypass: bypass.to_string(),
        })
    }

    #[test]
    fn no_proxy_anywhere_sets_nothing() {
        assert!(proxy_env(env(&[]), None).is_empty());
    }

    #[test]
    fn the_windows_system_proxy_reaches_the_child() {
        let vars = proxy_env(env(&[]), windows("corp-proxy:8080", ""));
        assert_eq!(
            get(&vars, "HTTPS_PROXY").as_deref(),
            Some("http://corp-proxy:8080")
        );
        assert_eq!(
            get(&vars, "HTTP_PROXY").as_deref(),
            Some("http://corp-proxy:8080")
        );
    }

    #[test]
    fn a_per_scheme_list_names_each_scheme_and_ignores_the_rest() {
        let vars = proxy_env(
            env(&[]),
            windows("http=p1:80;https=p2:443;ftp=p3:21;socks=p4:1080", ""),
        );
        assert_eq!(get(&vars, "HTTP_PROXY").as_deref(), Some("http://p1:80"));
        assert_eq!(get(&vars, "HTTPS_PROXY").as_deref(), Some("http://p2:443"));
        assert_eq!(vars.len(), 3, "{vars:?}");
    }

    #[test]
    fn loopback_is_always_exempt_and_the_bypass_list_is_kept() {
        let vars = proxy_env(
            env(&[]),
            windows("p:8080", "*.corp.example;<local>;intranet"),
        );
        let no_proxy = get(&vars, "NO_PROXY").unwrap();
        for host in ["localhost", "127.0.0.1", "::1", ".corp.example", "intranet"] {
            assert!(
                no_proxy.split(',').any(|h| h == host),
                "{host} missing: {no_proxy}"
            );
        }
        assert!(!no_proxy.contains("<local>"));
    }

    #[test]
    fn an_exported_proxy_wins_and_the_system_one_is_not_read() {
        let vars = proxy_env(
            env(&[
                ("https_proxy", "http://mine:3128"),
                ("NO_PROXY", "internal"),
            ]),
            windows("corp-proxy:8080", "other"),
        );
        assert_eq!(
            get(&vars, "HTTPS_PROXY").as_deref(),
            Some("http://mine:3128")
        );
        assert_eq!(get(&vars, "HTTP_PROXY"), None);
        let no_proxy = get(&vars, "NO_PROXY").unwrap();
        assert!(no_proxy.starts_with("internal,"), "{no_proxy}");
        assert!(!no_proxy.contains("other"), "{no_proxy}");
        assert!(no_proxy.contains("127.0.0.1"));
    }

    #[test]
    fn an_empty_server_is_no_proxy() {
        assert!(proxy_env(env(&[]), windows("  ", "x")).is_empty());
    }
}
