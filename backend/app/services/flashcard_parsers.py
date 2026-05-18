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

    # If it already looks like a clean array, try parsing directly
    if raw.startswith("["):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
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
