"""Pure helpers extracted from `app/routers/documents.py`.

These are reused across documents endpoints (and `routers/study.py` imports
`safe_tags` for sort/filter logic). The router re-exports them under their
original private aliases via `__all__`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import get_settings
from app.types import ParsedDocument, Section

logger = logging.getLogger(__name__)


def delete_raw_file(document_id: str) -> None:
    """Remove any raw uploaded file matching ~/.luminary/raw/{doc_id}.*"""
    settings = get_settings()
    raw_dir = Path(settings.DATA_DIR).expanduser() / "raw"
    for match in raw_dir.glob(f"{document_id}.*"):
        try:
            match.unlink()
            logger.info("Deleted raw file %s", match)
        except OSError:
            logger.warning("Failed to delete raw file %s", match)


def safe_tags(raw: object) -> list[str]:
    """Deserialize tags regardless of how they were stored.

    SQLite's JSON column occasionally surfaces the raw JSON text string instead
    of a Python list (e.g. when rows were written by a different code path).
    This helper normalises all three cases: already-a-list, JSON string, or
    None.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(t) for t in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(t) for t in parsed]
        except (json.JSONDecodeError, ValueError):
            pass
    return []


def section_to_dict(s: Section) -> dict:
    return {
        "heading": s.heading,
        "level": s.level,
        "text": s.text,
        "page_start": s.page_start,
        "page_end": s.page_end,
    }


def parsed_to_dict(p: ParsedDocument) -> dict:
    return {
        "title": p.title,
        "format": p.format,
        "pages": p.pages,
        "word_count": p.word_count,
        "sections": [section_to_dict(s) for s in p.sections],
        "raw_text": p.raw_text,
    }


def derive_learning_status(
    study_session_count: int,
    flashcard_count: int,
    summary_count: int,
) -> str:
    if study_session_count > 0:
        return "studied"
    if flashcard_count > 0:
        return "flashcards_generated"
    if summary_count > 0:
        return "summarized"
    return "not_started"
