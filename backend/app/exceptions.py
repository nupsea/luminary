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


class Forbidden(LuminaryError):
    """The caller is known and is not allowed to do this.

    Distinct from `NotFound`: the resource exists and the answer is no. Used
    where a secret decides, so the message may not say which half was wrong.
    """

    status_code = 403


class DependencyUnavailable(LuminaryError):
    """A required local component (Ollama, ffmpeg, a model) is not usable."""

    status_code = 503


class LocalInferenceRefused(DependencyUnavailable):
    """A local model call on a host that cannot run one at a usable speed.

    Its own type because it is a fact about the host under the chosen mode, not an
    outage: retrying cannot succeed, so background work records it as skipped
    rather than failed, and resumes when the mode changes.
    """
