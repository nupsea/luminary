"""The environment block that travels with a bug report.

Requested in nupsea/luminary#41: a version and an OS name were not enough to
rebuild a reporter's setup, so answering an issue always cost a round trip.

Assembled here rather than in the desktop shell because the running app's UI is
served from the backend's own origin, where Tauri IPC is not granted -- and
because a browser or Docker install has no shell to ask.
"""

import os
import platform
import re
import subprocess
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.database import get_session_factory
from app.models import CollectionModel, DocumentModel
from app.paths import app_version, is_packaged
from app.services.settings_service import get_local_chat_model, get_vision_model

# Reports can come from a work computer, so anything naming a person, an organisation or a
# place is removed before the user sees it. The key shapes match the desktop shell's report.rs.
REPORT_EMAIL = "eanups@yahoo.com"
_LOG_LINES = 150
_KEY_SHAPES = re.compile(
    r"sk-ant-[A-Za-z0-9_\-]{16,}|sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,}|hf_[A-Za-z0-9]{20,}"
    r"|eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"
)
_ASSIGNED = re.compile(
    r"(?i)\b([a-z0-9_\-]*(?:api[_\-]?key|token|secret|password|passwd|authorization|bearer))\b"
    r"([\"']?\s*[:=]\s*[\"']?)([^\s\"',;}\)]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/]{8,}=*")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
# Download links can carry short-lived signed credentials in their query string.
_URL_QUERY = re.compile(r"(https?://[^\s?\"']+)\?[^\s\"']+")
# A company proxy or intranet host names the company; the model servers do not.
_URL_HOST = re.compile(r"(?i)\b(https?|wss?)://(?:[^/\s@\"']*@)?([^/\s:\"'?#]+)")
_PUBLIC_HOSTS = (
    "ollama.com",
    "ollama.ai",
    "github.com",
    "githubusercontent.com",
    "huggingface.co",
    "hf.co",
    "cloudflarestorage.com",
    "anthropic.com",
    "openai.com",
    "googleapis.com",
    "localhost",
    "127.0.0.1",
)
_IPV4 = re.compile(
    r"(?<![\d.])(?!127\.0\.0\.1(?![\d.]))(?!0\.0\.0\.0(?![\d.]))(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"
)
_TZ_OFFSET = re.compile(r"(\d{2}:\d{2}:\d{2}(?:\.\d+)?)[+-]\d{2}:\d{2}\b")
# Absolute paths, JSON-escaped Windows ones included. A folder may contain spaces
# ("OneDrive - Company"); a final file name is cut at its first space.
_SEG = r"[^\s\"'<>|:*?,;\\/]+"
_PATH = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]+|(?<![\w\\:])\\{2,}(?=\w)|~[\\/]+"
    r"|(?<![\w.:/\-])/(?:Users|home|Volumes|mnt|media|srv|opt|private|tmp|var|net|run)/)"
    rf"(?:{_SEG}(?: {_SEG})*[\\/]+)*(?:{_SEG})?"
)
_OWN_DIRS = {"sh.luminary.app", "luminary", ".luminary", ".ollama", "luminary.app"}
_STANDARD_DIRS = {
    "~",
    "appdata",
    "local",
    "roaming",
    "programs",
    "library",
    "application support",
    "logs",
    ".local",
    "share",
    "state",
    ".cache",
}
_GENERIC_LABELS = {"local", "lan", "home", "localdomain", "workgroup", "com", "net", "org"}


def _names(values, generic: frozenset[str] | set[str] = frozenset()) -> list[str]:
    """Longest first, so a full host name is replaced before its first label."""
    keep = {v for v in values if len(v) >= 3 and v.lower() not in generic}
    return sorted(keep, key=len, reverse=True)


def _replace_words(text: str, names: list[str], token: str) -> str:
    low = text.lower()
    for name in names:
        if name.lower() in low:
            pattern = rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])"
            text = re.sub(pattern, token, text, flags=re.IGNORECASE)
    return text


def _short_path(match: re.Match) -> str:
    """Keep where under Luminary's own folders a path points, never whose folder it is."""
    path = match.group(0)
    sep = "\\" if "\\" in path else "/"
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    for i, part in enumerate(parts):
        if part.lower() in _OWN_DIRS:
            standard = parts[0] == "~" and all(p.lower() in _STANDARD_DIRS for p in parts[:i])
            head = parts[: i + 1] if standard else ["…", part]
            tail = parts[i + 1 : i + 2] + (["…"] if len(parts) > i + 2 else [])
            return sep.join(head + tail)
    return "<path>"


def _host(match: re.Match) -> str:
    host = match.group(2).lower()
    if any(host == h or host.endswith("." + h) for h in _PUBLIC_HOSTS):
        return f"{match.group(1)}://{match.group(2)}"
    return f"{match.group(1)}://<host>"


def _scrub(text: str) -> str:
    """Remove the account, computer and network names, and every folder that is not ours."""
    home = str(Path.home())
    out = text.replace(home, "~").replace(home.replace("\\", "\\\\"), "~")
    node = platform.node()
    users = {os.path.basename(home), os.environ.get("USERNAME", ""), os.environ.get("USER", "")}
    users |= {node, node.split(".")[0]}
    domains = {os.environ.get("USERDOMAIN", ""), os.environ.get("USERDNSDOMAIN", "")}
    labels = {label for d in domains for label in d.split(".")} | set(node.split(".")[1:])
    out = _PATH.sub(_short_path, out)
    # Any host in the company's DNS domain, bare or in a URL: its subdomains name offices.
    for dns in (os.environ.get("USERDNSDOMAIN", ""), node.partition(".")[2]):
        if "." in dns:
            suffix = re.escape(".".join(dns.split(".")[-2:]))
            out = re.sub(rf"(?i)\b(?:[a-z0-9-]+\.)*{suffix}\b", "<host>", out)
    out = _replace_words(out, _names(users), "<user>")
    return _replace_words(out, _names(domains | labels, _GENERIC_LABELS), "<org>")


def redact(text: str, library_names: list[str] | None = None) -> str:
    """Remove keys, credentials, email addresses, hosts, paths and the names in them."""
    out = _KEY_SHAPES.sub("<redacted>", text)
    out = _BEARER.sub("Bearer <redacted>", out)
    out = _ASSIGNED.sub(r"\1\2<redacted>", out)
    out = _URL_QUERY.sub(r"\1?<redacted>", out)
    out = _EMAIL.sub("<redacted-email>", out)
    out = _URL_HOST.sub(_host, out)
    out = _IPV4.sub("<ip>", out)
    out = _TZ_OFFSET.sub(r"\1", out)
    out = _replace_words(out, library_names or [], "<document>")
    return _scrub(out)


async def _library_names() -> list[str] | None:
    """Document titles, file names and collection names; None if the library is unreadable."""
    try:
        async with get_session_factory()() as session:
            query = select(DocumentModel.title, DocumentModel.file_path)
            docs = (await session.execute(query)).all()
            collections = (await session.execute(select(CollectionModel.name))).scalars().all()
    except SQLAlchemyError:
        return None
    names = set(collections)
    for title, file_path in docs:
        name = Path(file_path or "").name
        names |= {title or "", name, Path(name).stem}
    return _names(n.strip() for n in names)


def log_tail(lines: int = _LOG_LINES) -> str:
    """The end of the desktop app's log, which the shell names; empty elsewhere."""
    path = os.environ.get("LUMINARY_LOG_FILE", "")
    if not path:
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 128 * 1024))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _kernel() -> str:
    u = platform.uname()
    return f"{u.system} {u.release} {u.machine}"


def _os_name() -> str:
    if platform.system() != "Darwin":
        return f"{platform.system()} {platform.release()}"
    try:
        product = subprocess.run(
            ["/usr/bin/sw_vers", "-productVersion"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        build = subprocess.run(
            ["/usr/bin/sw_vers", "-buildVersion"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "macOS (version unavailable)"
    return f"macOS {product} (build {build})"


async def _ollama() -> list[str]:
    url = get_settings().OLLAMA_URL
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            version = (await client.get(f"{url}/api/version")).json().get("version", "unknown")
            tags = (await client.get(f"{url}/api/tags")).json().get("models", [])
    except Exception:
        return ["ollama    not reachable"]

    names = [m.get("name", "") for m in tags if m.get("name")]
    lines = [f"ollama    running — {version}"]
    lines += [f"          {n}" for n in names] or ["          no models installed"]
    return lines


async def environment_report() -> str:
    """A paste-ready block for an issue. Every line is one a maintainer uses."""
    settings = get_settings()
    install = "desktop app" if is_packaged() else "source or CLI install"
    lines = [
        f"version   {app_version()} ({install})",
        f"library   {_scrub(str(Path(settings.DATA_DIR).expanduser()))}",
        f"os        {_os_name()}",
        f"kernel    {_kernel()}",
        f"python    {platform.python_version()}",
        f"mode      {settings.LUMINARY_MODE}",
        f"chat      {get_local_chat_model()}",
        f"vision    {get_vision_model()}",
    ]
    lines += await _ollama()
    return _scrub("\n".join(lines))


async def problem_report(problem: str = "", detail: str = "") -> dict:
    """What a user reviews before emailing it. All of it redacted."""
    names = await _library_names()
    log = log_tail()
    if names is None:
        # Without the titles to remove, backend lines are the ones that could name a document.
        log = "\n".join(line for line in log.splitlines() if "[backend]" not in line)
    return {
        "environment": redact(await environment_report(), names),
        "problem": redact(problem, names),
        "detail": redact(detail, names),
        "log": redact(log, names),
        "email": REPORT_EMAIL,
    }
