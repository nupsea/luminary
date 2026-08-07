"""Domain exceptions, mapped to HTTP status codes by a handler in main.py.

Services and repos raise these instead of `HTTPException` so business logic
carries no transport dependency.
"""

from __future__ import annotations


class LuminaryError(Exception):
    """Base for every domain error. Maps to 500 unless a subclass says otherwise."""

    status_code = 500

    def __init__(self, detail: str = "", **extra: object) -> None:
        super().__init__(detail)
        self.detail = detail or self.__class__.__name__
        self.extra = extra


class NotFound(LuminaryError):
    status_code = 404


class Conflict(LuminaryError):
    """State collision, e.g. a second active session. `extra` reaches the body."""

    status_code = 409


class InvalidInput(LuminaryError):
    status_code = 422


class DependencyUnavailable(LuminaryError):
    """A required local component (Ollama, ffmpeg, a model) is not usable."""

    status_code = 503
