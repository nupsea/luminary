"""Provider reachability checks for offline-aware routing.

A local-first app must not depend on the network being up. Probing whether a
cloud provider is reachable lets routing switch to the local model *before*
attempting a doomed call -- avoiding the SDK's retry storm (litellm wraps a
connection failure as InternalServerError only after several retries) and giving
the UI something to say.

Results are cached briefly so a chat turn does not open a socket per LLM call.
Both error directions are safe: a false "offline" routes local (the safe default
for a local-first app), and a false "online" simply falls through to the reactive
fallback in the LLM service.
"""

import logging
import socket
import time

logger = logging.getLogger(__name__)

# Cloud model prefixes mapped to the host a routed call would contact.
_PROVIDER_HOSTS: dict[str, str] = {
    "openai": "api.openai.com",
    "anthropic": "api.anthropic.com",
    "gemini": "generativelanguage.googleapis.com",
}

_CACHE_TTL_S = 15.0
_PROBE_TIMEOUT_S = 2.0

# host -> (checked_at_monotonic, reachable)
_cache: dict[str, tuple[float, bool]] = {}


def _probe(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def host_reachable(host: str, port: int = 443, timeout: float = _PROBE_TIMEOUT_S) -> bool:
    """Cached TCP reachability check. Blocking; call via to_thread on the loop."""
    now = time.monotonic()
    cached = _cache.get(host)
    if cached is not None and now - cached[0] < _CACHE_TTL_S:
        return cached[1]
    ok = _probe(host, port, timeout)
    _cache[host] = (now, ok)
    if not ok:
        logger.info("connectivity: %s unreachable; treating as offline", host)
    return ok


def is_cloud_model(model: str) -> bool:
    """True when the model string routes to an external provider."""
    return model.split("/", 1)[0] in _PROVIDER_HOSTS


def provider_reachable(model: str) -> bool:
    """Whether the provider for a model string is reachable. Local models -> True."""
    prefix = model.split("/", 1)[0]
    host = _PROVIDER_HOSTS.get(prefix)
    if host is None:
        return True
    return host_reachable(host)


def reset_cache() -> None:
    """Test hook: drop cached probe results."""
    _cache.clear()
