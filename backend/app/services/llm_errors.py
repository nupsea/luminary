"""What to tell the user when a model call failed: the cause, and what they can do.

Every surface said "LLM unreachable ... run: ollama serve" for a model that was not
installed, still loading, or erroring, and the desktop app has no terminal to run it in.
The cause is in the exception; this reads it once for Ask, Practice, teach-back and
summaries alike.
"""

import re

from app.exceptions import DependencyUnavailable
from app.paths import is_packaged
from app.services.llm import (
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMTimeoutError,
    missing_model_from,
)

# Ollama's own reason, e.g. {"error":"llama runner process has terminated: ..."}.
_PROVIDER_REASON = re.compile(r"\"error\"\s*:\s*\"([^\"]{3,200})\"")


def _chain(exc: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    cur: BaseException | None = exc
    while cur is not None and cur not in seen:
        seen.append(cur)
        cur = cur.__cause__ or cur.__context__
    return seen


def _routes_locally() -> bool:
    from app.services.settings_service import get_effective_routing  # noqa: PLC0415

    try:
        return get_effective_routing()[0].startswith("ollama/")
    except ValueError:
        return False


def _bare(model: str) -> str:
    return model.split("/", 1)[-1]


def describe(exc: BaseException) -> tuple[str, str]:
    """(reason, sentence). `reason` lets a surface offer the fix, e.g. a model choice."""
    chain = _chain(exc)
    text = " ".join(str(e) for e in chain)
    local = "ollama" in text.lower() or _routes_locally()

    if isinstance(exc, DependencyUnavailable):
        return "unavailable", exc.detail
    if isinstance(exc, ValueError):
        return "no_key", "No API key is set for the cloud model. Add one in Settings, or use Local."
    if any(isinstance(e, LLMAuthenticationError) for e in chain):
        return "bad_key", "The cloud provider refused the API key. Check it in Settings."
    if any(isinstance(e, LLMRateLimitError) for e in chain):
        return (
            "rate_limited",
            "The cloud provider's rate limit was reached. Wait a minute and try again.",
        )
    if (missing := missing_model_from(exc)) is not None:
        return (
            "model_missing",
            f"The model {_bare(missing)} is not installed on this computer. "
            "Choose a chat model to install it.",
        )
    if any(isinstance(e, LLMTimeoutError) for e in chain):
        return (
            "timeout",
            "The model took too long to answer. The first answer after Luminary starts can "
            "take a minute while the model loads. Try again.",
        )
    if local and (match := _PROVIDER_REASON.search(text)):
        return (
            "model_error",
            f"The local model could not answer ({match.group(1)}). Try again. If it fails "
            "again, quit Luminary and reopen it.",
        )
    if local:
        restart = (
            "Quit Luminary and reopen it; that restarts the model server."
            if is_packaged()
            else "Start it with `ollama serve`, then try again."
        )
        return "server_down", f"The local model server is not answering. {restart}"
    return (
        "provider_down",
        "The cloud provider could not be reached. Check your internet connection and try again.",
    )
