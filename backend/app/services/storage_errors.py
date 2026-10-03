"""Steps for a write the file system refused, chosen by looking at the folder.

A raw `mkdir ...: operation not permitted` told a new user nothing and offered no fix. The
folder itself says which fix applies: another owner, a Finder lock, no write permission, or
none of these, which on macOS means the system refused a folder whose permissions allow it.
"""

import os
import re
import stat
import sys
from pathlib import Path

# Go's wording on each platform: macOS and Linux name errno, Windows says "Access is denied."
_REFUSED = re.compile(
    r"(?:mkdir|open|rename|remove|create)\s+(/.+?|[A-Za-z]:\\.+?):\s+"
    r"(?:operation not permitted|permission denied|access is denied)",
    re.IGNORECASE,
)


def _existing(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if candidate.exists():
            return candidate
    return None


def folder_problem(path: Path) -> str | None:
    """Why this account cannot write into *path*, or None when the folder allows it."""
    folder = _existing(path)
    if folder is None:
        return None
    info = folder.stat()
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        try:
            import pwd  # noqa: PLC0415

            owner = pwd.getpwuid(info.st_uid).pw_name
        except (ImportError, KeyError):
            owner = str(info.st_uid)
        return f"it belongs to another account ({owner})"
    if getattr(info, "st_flags", 0) & (stat.UF_IMMUTABLE | stat.SF_IMMUTABLE):
        return "it is locked"
    if not os.access(folder, os.W_OK):
        return "your account cannot write to it"
    return None


def _permission_fix() -> str:
    if sys.platform == "darwin":
        return "In Finder, choose Get Info on it, give your account Read & Write and clear Locked."
    if sys.platform == "win32":
        return "In File Explorer, open its Properties > Security and give your account Modify."
    return "Give your account write access to it (for example `chown -R $USER` on the folder)."


def explain(text: str) -> str | None:
    """A sentence with the steps for a refused write in *text*, or None if there is none."""
    match = _REFUSED.search(text)
    if match is None:
        return None
    path = Path(match.group(1))
    folder = _existing(path.parent) or path.parent
    problem = folder_problem(path.parent)
    if problem is not None:
        return f"Luminary cannot save into {folder}: {problem}. {_permission_fix()} Then try again."
    if sys.platform == "darwin":
        return (
            f"macOS refused to let Luminary save into {folder}, although the folder allows it. "
            "Quit Luminary (Cmd+Q), reopen it and try again. If it is refused again, open "
            "System Settings > Privacy & Security > Full Disk Access, turn on Luminary, "
            "reopen it and try again."
        )
    if sys.platform == "win32":
        return (
            f"Windows refused to let Luminary save into {folder}, although the folder allows "
            "it. Restart Luminary and try again. If it is refused again, open Windows "
            "Security > Virus & threat protection > Ransomware protection > Controlled folder "
            "access, allow Luminary and ollama through it, and try again."
        )
    return (
        f"The system refused to let Luminary save into {folder}, although the folder allows "
        "it. Restart Luminary and try again. If it is refused again, check whether SELinux, "
        "AppArmor or security software restricts which programs may write there."
    )
