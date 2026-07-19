"""Tolerant parsing of JSON arrays out of LLM completions.

Local models routinely wrap JSON in markdown fences or prose, emit string
content containing backslash sequences that are not legal JSON escapes, or
hit the generation token limit mid-array. A strict json.loads throws the
whole completion away on any of these; this module recovers what is
recoverable instead. Repairs are attempted only after a strict parse fails,
so already-valid JSON is never rewritten.
"""

import json
import re

# A backslash pair is consumed intact; a lone backslash not opening a legal
# JSON escape is doubled so the string parses instead of failing.
_BAD_ESCAPE_RE = re.compile(r'(\\\\)|\\(?!["\\/bfnrtu]|u[0-9a-fA-F]{4})')


def _repair_escapes(text: str) -> str:
    return _BAD_ESCAPE_RE.sub(lambda m: m.group(1) or "\\\\", text)


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
    return cleaned


def _salvage_elements(text: str) -> list:
    """Decode complete top-level elements from a (possibly truncated) array,
    stopping at the first element that cannot be decoded."""
    decoder = json.JSONDecoder()
    i = text.find("[")
    if i == -1:
        return []
    i += 1
    items: list = []
    n = len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if i >= n or text[i] == "]":
            break
        try:
            obj, i = decoder.raw_decode(text, i)
        except ValueError:
            break
        items.append(obj)
    return items


def parse_llm_json_object(raw: str) -> dict | None:
    """Extract a JSON object from an LLM completion, tolerating markdown
    fences, surrounding prose, and illegal escape sequences.

    Returns None when no object is recoverable (truncated objects are not
    salvaged: unlike array elements, a partial object has no complete
    sub-units to keep).
    """
    cleaned = _strip_fences(raw)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end < start:
        return None
    candidate = cleaned[start : end + 1]
    for text in (candidate, _repair_escapes(candidate)):
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        return parsed if isinstance(parsed, dict) else None
    return None


def parse_llm_json_array(raw: str) -> list:
    """Extract a JSON array from an LLM completion, tolerating markdown
    fences, surrounding prose, illegal escape sequences, and truncation.

    Returns [] when no array content is recoverable. Truncation recovery
    keeps every complete element and drops the partial trailing one.
    """
    cleaned = _strip_fences(raw)
    start = cleaned.find("[")
    if start == -1:
        return []
    end = cleaned.rfind("]")
    candidate = cleaned[start : end + 1] if end > start else cleaned[start:]
    for text in (candidate, _repair_escapes(candidate)):
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        return parsed if isinstance(parsed, list) else []
    return _salvage_elements(_repair_escapes(candidate))
