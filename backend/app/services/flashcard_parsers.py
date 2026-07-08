"""Pure JSON parsers for flashcard LLM responses.

Extracted from ``flashcard.py``. No I/O, no DB, no LLM calls.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def _parse_concept_extract(raw: str) -> tuple[str, list[dict]]:
    """Parse the concept-extraction response: {"domain": "...", "concepts": [...]}.

    Returns (domain, concepts). Falls back gracefully if the LLM deviates from the format.
    """
    raw = raw.strip()
    # Strip markdown fences if present.
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0].strip()
    # Try to find the outermost JSON object.
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        try:
            obj = json.loads(raw[start:end])
            domain = str(obj.get("domain", "")).strip()
            concepts = [
                c for c in obj.get("concepts", []) if isinstance(c, dict) and c.get("concept")
            ]
            return domain, concepts
        except (json.JSONDecodeError, ValueError):
            pass
    # Fallback: try to extract a bare array (old format compatibility).
    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start != -1 and end > start:
        try:
            concepts = json.loads(raw[start:end])
            return "", [c for c in concepts if isinstance(c, dict) and c.get("concept")]
        except (json.JSONDecodeError, ValueError):
            pass
    logger.warning("Concept extract parse failed: %r", raw[:200])
    return "", []


def _parse_llm_response(raw: str, document_id: str) -> list[dict]:
    """Extract a JSON array from the LLM response.

    Handles:
    - Clean JSON array responses
    - Responses wrapped in markdown code fences
    - Responses with preamble prose before the array
    - Responses with trailing text after the array
    """
    raw = raw.strip()

    # Strip markdown code fences
    raw = re.sub(r"^```[^\n]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    raw = raw.strip()

    # Try the whole thing as JSON: an array, or (json-mode models) an object wrapping the array
    # like {"flashcards": [...]}, or even a single card object.
    try:
        coerced = _coerce_cards(json.loads(raw))
        if coerced is not None:
            return coerced
    except (json.JSONDecodeError, ValueError):
        pass

    # Fall back: find the first '[' and last ']' and parse that slice
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning("Flashcard JSON parse failed for doc %s: %r", document_id, raw[:200])
    return []


def _coerce_cards(data: object) -> list | None:
    """A flashcard array from either a bare list, an object wrapping it, or a single card object."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("flashcards", "cards", "questions", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        for v in data.values():
            if isinstance(v, list):
                return v
        if data.get("question") or data.get("front"):
            return [data]
    return None


def card_field(item: dict, *names: str) -> str:
    """First non-empty string among the given keys -- tolerates local models that use alternate
    field names (front/back, q/a, term/definition) instead of question/answer."""
    for n in names:
        v = item.get(n)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


# A trailing source pointer the model sometimes appends despite instructions,
# e.g. "... rather than assuming independence. In Part I. Foundations of Data
# Systems." The source is tracked separately, so strip it from the answer.
_TRAILING_SOURCE_REF = re.compile(
    r"[\s.]*(?:In|See)\s+(?:Part|Chapter|Section|Ch\.?|Sec\.?)\b.*$",
    re.IGNORECASE | re.DOTALL,
)


def strip_source_ref(answer: str) -> str:
    """Remove a trailing 'In Part/Chapter/Section ...' citation from an answer.

    Conservative: only fires when such a pointer starts a clause at the very end,
    and only when a real answer remains before it (never strips the whole thing).
    """
    stripped = _TRAILING_SOURCE_REF.sub("", answer).strip()
    if len(stripped.split()) >= _MIN_ANSWER_WORDS:
        return stripped if stripped[-1:] in ".!?" or not stripped else stripped + "."
    return answer.strip()


# Quality gate for generated Q/A cards. FLASHCARD_SYSTEM already forbids these
# shapes, but small local models still emit them; this is the deterministic
# backstop so a weak card never reaches the deck regardless of model.
_MIN_ANSWER_WORDS = 2
_BLOATED_QUESTION_WORDS = 22
_TRIVIAL_ANSWER_WORDS = 3

# Source-referencing / deictic phrases that make no sense on a standalone card.
_LEADING_PHRASES = (
    "in this passage",
    "in this text",
    "in this excerpt",
    "in this book",
    "in this document",
    "according to the text",
    "as described",
    "as stated",
    "this scenario",
    "the scenario",
    "this situation",
    "this case",
    "this context",
    "this example",
    "the author",
    "the writer",
)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def card_rejection_reason(question: str, answer: str) -> str | None:
    """Why this Q/A card is low quality, or None if it passes the gate.

    Catches the failure modes the generation prompt forbids but weak models
    still produce: empty fields, one-word answers (which includes bare yes/no),
    source-referencing/leading questions, and bloated leading questions paired
    with a trivial answer. Cloze cards use a separate builder and are
    intentionally not run through this gate.
    """
    q = question.strip()
    a = answer.strip()
    if not q or not a:
        return "empty question or answer"

    q_words = _word_count(q)
    a_words = _word_count(a)

    if a_words < _MIN_ANSWER_WORDS:
        return f"answer too short ({a_words} word)"

    q_lower = q.lower()
    for phrase in _LEADING_PHRASES:
        if phrase in q_lower:
            return f"leading/deictic phrase in question ({phrase!r})"

    if q_words >= _BLOATED_QUESTION_WORDS and a_words <= _TRIVIAL_ANSWER_WORDS:
        return f"bloated question ({q_words}w) with trivial answer ({a_words}w)"

    return None


def _parse_gap_flashcard(raw: str, gap: str) -> dict | None:
    """Parse a single {front, back} JSON object from LLM response for one gap."""
    raw = raw.strip()
    raw = re.sub(r"^```[^\n]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    raw = raw.strip()

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
            if isinstance(data, dict) and data.get("front") and data.get("back"):
                return data
        except (json.JSONDecodeError, ValueError):
            pass

    logger.warning("Gap flashcard JSON parse failed for gap %r: %r", gap[:50], raw[:200])
    return None


_CLOZE_BLANK_RE = re.compile(r"\{\{(.+?)\}\}")


def _parse_cloze_text(cloze_text: str) -> list[str]:
    """Return list of blank terms extracted from {{term}} markers in order."""
    return _CLOZE_BLANK_RE.findall(cloze_text)


def _build_cloze_question(cloze_text: str) -> str:
    """Replace {{term}} markers with [____] for list-view display."""
    return _CLOZE_BLANK_RE.sub("[____]", cloze_text)


def _parse_cloze_llm_response(raw: str) -> list[dict]:
    """Parse the LLM JSON array response for cloze cards.

    Filters out any element whose cloze_text has no {{}} markers (malformed).
    Returns only valid elements.
    """
    items = _parse_llm_response(raw, "cloze")
    valid = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cloze_text = str(item.get("cloze_text", "")).strip()
        if not cloze_text:
            continue
        blanks = _parse_cloze_text(cloze_text)
        if not blanks:
            logger.warning("Cloze item has no {{}} markers, skipping: %r", cloze_text[:100])
            continue
        valid.append(item)
    return valid
