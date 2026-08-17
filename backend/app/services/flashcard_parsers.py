"""Pure JSON parsers for flashcard LLM responses.

Extracted from ``flashcard.py``. No I/O, no DB, no LLM calls.
"""

from __future__ import annotations

import json
import logging
import re

from app.services import llm_output_stats
from app.services.llm_json import (
    parse_array_with_repairs,
    parse_object_with_repairs,
    top_level_shape,
)

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


def _parse_llm_response(
    raw: str, document_id: str, *, expect: str | None = None
) -> list[dict]:
    """Extract flashcards from the LLM response, whichever shape it arrived in.

    Handles clean arrays, `{"flashcards": [...]}` objects, markdown fences,
    preamble or trailing prose, illegal escapes and truncation.

    **Dispatched on the shape the completion actually opens with, and counted
    once.** Trying the array parser first was not a harmless ordering: against
    the object the flashcard prompt asks for, it sliced out the inner array and
    recorded the `{"flashcards":` wrapper as prose around it. Every compliant
    generation was counted as repaired, so `first_pass_rate` read 0.0000 on a 3B
    model and on a 14B one -- a measurement of this function, not of either
    model.

    *expect* is the shape the prompt asked for, when the caller knows it. A
    clean parse in the other shape is a real deviation and is counted as one --
    separately from the repairs, because nothing had to be rewritten.
    """
    shape = top_level_shape(raw)
    attempts = (
        (_from_object, _from_array) if shape == "object" else (_from_array, _from_object)
    )

    first_repairs: frozenset[str] = frozenset()
    for i, attempt in enumerate(attempts):
        cards, repairs, got = attempt(raw)
        if i == 0:
            first_repairs = repairs
        if cards is not None:
            llm_output_stats.record_parse(ok=True, repairs=repairs)
            if expect is not None and got != expect:
                llm_output_stats.record_shape_deviation()
            return cards

    llm_output_stats.record_parse(ok=False, repairs=first_repairs)
    logger.warning("Flashcard JSON parse failed for doc %s: %r", document_id, raw[:200])
    return []


def _from_array(raw: str) -> tuple[list[dict] | None, frozenset[str], str]:
    parsed, repairs = parse_array_with_repairs(raw)
    return (parsed if parsed else None), repairs, "array"


def _from_object(raw: str) -> tuple[list[dict] | None, frozenset[str], str]:
    parsed, repairs = parse_object_with_repairs(raw)
    cards = _coerce_cards(parsed) if parsed is not None else None
    return (cards or None), repairs, "object"


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
    field names (front/back, q/a, term/definition) instead of question/answer.

    An alternate name is counted: the JSON was valid but the shape was not the
    one the prompt asked for, and that difference is otherwise erased here.
    """
    for index, n in enumerate(names):
        v = item.get(n)
        if isinstance(v, str) and v.strip():
            if index:
                llm_output_stats.record_key_alias()
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

# Two or more enumerated items make the answer a list, and a list is several cards
# wearing one question -- the primary defect in a flashcard (rules 4, 9 and 10 of
# the card-writing canon). Measured 2026-08-17: with the prompt asking for bulleted
# answers, the atomicity floor was 0.7778 and 9 of 12 sampled cards carried
# bullets. One item is a lead sentence plus its detail and stays allowed.
_MAX_ENUMERATED_ITEMS = 1
_ENUM_LINE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+\S")

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


# Stable kinds for the gate's verdicts. The message carries the specifics for a
# log line; the kind is what gets counted, so a metric survives a reworded
# message.
REJECT_EMPTY_FIELD = "empty_field"
REJECT_SHORT_ANSWER = "short_answer"
REJECT_DEICTIC = "deictic"
REJECT_BLOATED = "bloated"
REJECT_ENUMERATED = "enumerated"


def card_rejection(question: str, answer: str) -> tuple[str, str] | None:
    """(kind, message) for a low-quality Q/A card, or None if it passes.

    Catches the failure modes the generation prompt forbids but weak models
    still produce: empty fields, one-word answers (which includes bare yes/no),
    source-referencing/leading questions, answers that carry a list of facts
    instead of one, and bloated leading questions paired with a trivial answer.
    Cloze cards use a separate builder and are intentionally not run through this
    gate -- a cloze is one deletion by construction.

    The verdict used to be computed, logged and dropped. It is the one signal on
    this path that is deterministic, needs no judge, and measures whether the
    model followed the contract rather than whether its JSON parsed -- so it is
    counted now.
    """
    q = question.strip()
    a = answer.strip()
    if not q or not a:
        return REJECT_EMPTY_FIELD, "empty question or answer"

    q_words = _word_count(q)
    a_words = _word_count(a)

    if a_words < _MIN_ANSWER_WORDS:
        return REJECT_SHORT_ANSWER, f"answer too short ({a_words} word)"

    q_lower = q.lower()
    for phrase in _LEADING_PHRASES:
        if phrase in q_lower:
            return REJECT_DEICTIC, f"leading/deictic phrase in question ({phrase!r})"

    enumerated = sum(1 for line in a.splitlines() if _ENUM_LINE.match(line))
    if enumerated > _MAX_ENUMERATED_ITEMS:
        return (
            REJECT_ENUMERATED,
            f"answer lists {enumerated} items; split it into one card each",
        )

    if q_words >= _BLOATED_QUESTION_WORDS and a_words <= _TRIVIAL_ANSWER_WORDS:
        return (
            REJECT_BLOATED,
            f"bloated question ({q_words}w) with trivial answer ({a_words}w)",
        )

    return None


def card_rejection_reason(question: str, answer: str) -> str | None:
    """The gate's message alone, for callers that only report it."""
    verdict = card_rejection(question, answer)
    return verdict[1] if verdict else None


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
    items = _parse_llm_response(raw, "cloze", expect="array")
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
