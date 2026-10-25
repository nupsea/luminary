"""Detect a file's kind in a child process, without ingesting it.

PyMuPDF holds the GIL through its C calls, so a parse in a thread still stalls
the one event loop: every await waits ~0.3s while it runs. A thread also cannot
be stopped, so a timed-out parse kept stalling the upload that followed it. A
child process has its own GIL and is killed when detection gives up.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import app

logger = logging.getLogger(__name__)


def _child_argv(path: Path, fmt: str, filename: str) -> list[str]:
    return [sys.executable, "-m", "app.services.type_detection", str(path), fmt, filename]


def _child_env() -> dict[str, str]:
    root = str(Path(app.__file__).resolve().parent.parent)
    existing = os.environ.get("PYTHONPATH")
    return {**os.environ, "PYTHONPATH": f"{root}{os.pathsep}{existing}" if existing else root}


async def detect_kind(path: Path, fmt: str, filename: str, *, timeout: float) -> str | None:
    """The kind to offer at upload, or None if detection gave up or failed."""
    proc = await asyncio.create_subprocess_exec(
        *_child_argv(path, fmt, filename),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=_child_env(),
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        logger.info("detect-type gave up on %s after %ss", filename, timeout)
        return None
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    lines = stdout.decode(errors="replace").strip().splitlines()
    if proc.returncode != 0 or not lines:
        logger.warning("detect-type failed for %s (exit %s)", filename, proc.returncode)
        return None
    return lines[-1].strip()


# The rule classifier answers in the retired content types; this is the one reader left.
_KIND_OF_LABEL = {
    "paper": "paper",
    "conversation": "conversation",
    "notes": "notes",
    "kindle_clippings": "notes",
    "code": "code",
    "tech_book": "technical",
    "tech_article": "technical",
}


def _detect_in_process(path: Path, fmt: str, filename: str) -> str:
    from app.services.content_classifier import classify_content
    from app.services.parser import DocumentParser

    parsed = DocumentParser().parse(path, fmt)
    label = classify_content(
        parsed.raw_text,
        [s.__dict__ for s in parsed.sections],
        parsed.word_count,
        fmt,
        filename,
    )
    return _KIND_OF_LABEL.get(label, "book")


if __name__ == "__main__":
    # The last stdout line is the answer: PyMuPDF prints its own warnings there.
    print(_detect_in_process(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
