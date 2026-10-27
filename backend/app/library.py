"""Which library the current work belongs to (#388).

Libraries are separated by root: each library's database, vectors, graph and files live
under its own `library_root`, so no query can reach another library's data. The library
rides in a ContextVar, which asyncio tasks and `to_thread` copy when they start: work
launched from a request stays in that request's library without being handed it.

The default library is the `DATA_DIR` root a desktop install has always used.
"""

from __future__ import annotations

import contextlib
import contextvars
import re
from collections.abc import Iterator

from app.types import DEFAULT_LIBRARY

# Lower-case, path-safe, and never `.` or `..`: the id names a directory under the machine root.
_LIBRARY_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")

_current: contextvars.ContextVar[str] = contextvars.ContextVar("library", default=DEFAULT_LIBRARY)


def current_library() -> str:
    return _current.get()


def valid_library(library: str) -> str:
    """*library* if it can name a library root, else ValueError."""
    if not _LIBRARY_ID.fullmatch(library):
        raise ValueError(f"not a library id: {library!r}")
    return library


@contextlib.contextmanager
def use_library(library: str) -> Iterator[None]:
    """Run the enclosed work, and every task it starts, in *library*."""
    token = _current.set(valid_library(library))
    try:
        yield
    finally:
        _current.reset(token)
