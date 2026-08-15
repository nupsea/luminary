"""Tolerant parsing of JSON objects and arrays out of LLM completions.

Local models routinely wrap JSON in markdown fences or prose, emit string
content containing backslash sequences that are not legal JSON escapes, or
hit the generation token limit mid-array. A strict json.loads throws the
whole completion away on any of these; this module recovers what is
recoverable instead. Repairs are attempted only after a strict parse fails,
so already-valid JSON is never rewritten.
"""

import json
import re

from app.services import llm_output_stats as stats

# A backslash pair is consumed intact; a lone backslash not opening a legal
# JSON escape is doubled so the string parses instead of failing.
_BAD_ESCAPE_RE = re.compile(r'(\\\\)|\\(?!["\\/bfnrtu]|u[0-9a-fA-F]{4})')


def _repair_escapes(text: str) -> str:
    return _BAD_ESCAPE_RE.sub(lambda m: m.group(1) or "\\\\", text)


def _strip_fences(text: str) -> tuple[str, bool]:
    """(cleaned, was_fenced). The flag is counted, not just consumed."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) > 2:
            return "\n".join(lines[1:-1]), True
        return cleaned, True
    return cleaned, False


def _skip(text: str, i: int, chars: str = " \t\r\n") -> int:
    """Advance past `chars`. raw_decode does not skip leading whitespace itself."""
    n = len(text)
    while i < n and text[i] in chars:
        i += 1
    return i


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
        i = _skip(text, i, " \t\r\n,")
        if i >= n or text[i] == "]":
            break
        try:
            obj, i = decoder.raw_decode(text, i)
        except ValueError:
            break
        items.append(obj)
    return items


def parse_object_with_repairs(raw: str) -> tuple[dict | None, frozenset[str]]:
    """Parse, and report which repairs the completion needed to be usable.

    The repair set is the model-quality signal: clean output and output that
    was fenced, mis-escaped or truncated produce identical objects downstream,
    so without this the difference between models is unobservable.
    """
    cleaned, fenced = _strip_fences(raw)
    repairs: set[str] = {stats.FENCED} if fenced else set()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end < start:
        return None, frozenset(repairs)
    candidate = cleaned[start : end + 1]
    # Prose around the object is a deviation from the format the prompt asked
    # for, whether or not json.loads then succeeds.
    if candidate.strip() != cleaned.strip():
        repairs.add("surrounded_by_prose")
    for attempt, text in enumerate((candidate, _repair_escapes(candidate))):
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if attempt:
            repairs.add(stats.BAD_ESCAPE)
        return (parsed if isinstance(parsed, dict) else None), frozenset(repairs)
    return None, frozenset(repairs)


def parse_llm_json_object(raw: str) -> dict | None:
    """Extract a JSON object from an LLM completion, tolerating markdown
    fences, surrounding prose, and illegal escape sequences.

    All-or-nothing: a truncated object returns None here. Callers willing to
    accept a partial result opt into salvage_llm_json_object instead.
    """
    parsed, repairs = parse_object_with_repairs(raw)
    stats.record_parse(ok=parsed is not None, repairs=repairs)
    return parsed


def salvage_llm_json_object(raw: str) -> dict | None:
    """Recover the complete key/value pairs of a truncated JSON object.

    The object counterpart of the array salvage: decoding stops at the first pair
    that was cut off mid-generation, keeping everything the model had already
    committed to. Kept out of parse_llm_json_object because a partial object is a
    lossy result its callers should opt into knowingly.

    Returns None when not even one pair is recoverable.
    """
    cleaned, fenced = _strip_fences(raw)
    text = _repair_escapes(cleaned)
    repairs: set[str] = {stats.TRUNCATED}
    if fenced:
        repairs.add(stats.FENCED)
    if text != cleaned:
        repairs.add(stats.BAD_ESCAPE)
    start = text.find("{")
    if start == -1:
        stats.record_parse(ok=False, repairs=frozenset(repairs))
        return None

    decoder = json.JSONDecoder()
    i = start + 1
    n = len(text)
    out: dict = {}
    while i < n:
        i = _skip(text, i, " \t\r\n,")
        if i >= n or text[i] == "}":
            break
        try:
            key, i = decoder.raw_decode(text, i)
        except ValueError:
            break
        i = _skip(text, i)
        if i >= n or text[i] != ":":
            break
        i = _skip(text, i + 1)
        try:
            value, i = decoder.raw_decode(text, i)
        except ValueError:
            # The cut landed inside the value. An array still has complete
            # elements worth keeping -- that is where a label list gets lost.
            if i < n and text[i] == "[":
                salvaged = _salvage_elements(text[i:])
                if salvaged and isinstance(key, str):
                    out[key] = salvaged
            break
        if isinstance(key, str):
            out[key] = value
    stats.record_parse(ok=bool(out), repairs=frozenset(repairs))
    return out or None


def parse_llm_json_array(raw: str) -> list:
    """Extract a JSON array from an LLM completion, tolerating markdown
    fences, surrounding prose, illegal escape sequences, and truncation.

    Returns [] when no array content is recoverable. Truncation recovery
    keeps every complete element and drops the partial trailing one.
    """
    cleaned, fenced = _strip_fences(raw)
    repairs: set[str] = {stats.FENCED} if fenced else set()
    start = cleaned.find("[")
    if start == -1:
        stats.record_parse(ok=False, repairs=frozenset(repairs))
        return []
    end = cleaned.rfind("]")
    if end <= start:
        repairs.add(stats.TRUNCATED)
    candidate = cleaned[start : end + 1] if end > start else cleaned[start:]
    if candidate.strip() != cleaned.strip():
        repairs.add("surrounded_by_prose")
    for attempt, text in enumerate((candidate, _repair_escapes(candidate))):
        try:
            parsed = json.loads(text)
        except ValueError:
            continue
        if attempt:
            repairs.add(stats.BAD_ESCAPE)
        ok = isinstance(parsed, list)
        stats.record_parse(ok=ok, repairs=frozenset(repairs))
        return parsed if ok else []
    salvaged = _salvage_elements(_repair_escapes(candidate))
    repairs.add(stats.TRUNCATED)
    stats.record_parse(ok=bool(salvaged), repairs=frozenset(repairs))
    return salvaged
