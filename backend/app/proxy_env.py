"""Use the operating system's proxy for the internet, and never for this machine.

`requests` and `httpx` read the Windows or macOS system proxy, but httpx never
reads its bypass list, so a proxy set in Windows' settings received the app's own
calls to Ollama on 127.0.0.1, which a company proxy cannot reach. Pinning the
system proxy into the environment with loopback exempt gives every client one
answer. An explicit `*_proxy` environment wins; only loopback is added to it.
"""

import os
import sys
import urllib.request
from collections.abc import MutableMapping

_LOOPBACK = ("localhost", "127.0.0.1", "::1")


def _windows_bypass() -> list[str]:
    """Hosts from Windows' "Don't use the proxy server for" list, as NO_PROXY entries."""
    if sys.platform != "win32":
        return []
    try:
        import winreg  # noqa: PLC0415

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "ProxyOverride")
    except OSError:
        return []
    entries = (e.strip() for e in str(value).split(";"))
    return [e.lstrip("*") for e in entries if e and e != "<local>"]


def _windows_pac_url() -> str:
    """Windows' "Use setup script" address, or "" where none is set."""
    if sys.platform != "win32":
        return ""
    try:
        import winreg  # noqa: PLC0415

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AutoConfigURL")
    except OSError:
        return ""
    return str(value).strip()


def pac_only() -> bool:
    """Whether the only proxy is a setup script (PAC), which neither this app nor Ollama
    reads (#155). Call after `pin_system_proxy`: a manual proxy is then in the environment."""
    if not _windows_pac_url():
        return False
    proxies = urllib.request.getproxies_environment()
    return not any(proxies.get(s) for s in ("http", "https", "all"))


def pin_system_proxy(environ: MutableMapping[str, str] = os.environ) -> None:
    configured = urllib.request.getproxies_environment()
    system = {} if configured else urllib.request.getproxies()
    for scheme in ("http", "https"):
        if system.get(scheme):
            environ[f"{scheme}_proxy"] = system[scheme]

    proxies = configured or system
    if not any(proxies.get(s) for s in ("http", "https", "all")):
        return
    kept = [h.strip() for h in (configured.get("no") or "").split(",") if h.strip()]
    wanted = kept + [h for h in (*_LOOPBACK, *_windows_bypass()) if h not in kept]
    environ["no_proxy"] = environ["NO_PROXY"] = ",".join(wanted)
