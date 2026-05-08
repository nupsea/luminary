"""Shared types + foundation helpers for ingestion nodes.

Holds the cross-node infrastructure that several nodes import:
- `IngestionState` TypedDict (the StateGraph state shape)
- `ContentType` literal
- `CHUNK_CONFIGS` per-content-type chunker settings
- `ENTITY_TAIL_MAX` + `build_entity_tail` (S224)
- `STAGE_PROGRESS` map
- `_classify` heuristic that picks the content type
- `_update_stage` async helper that writes the document's stage column
- `_parser` shared `DocumentParser` instance

Re-exported from `app.workflows.ingestion` for back-compat with
existing test imports.
"""

import logging
import re
from typing import Any, Literal, TypedDict

from app.database import get_session_factory
from app.services.parser import DocumentParser

logger = logging.getLogger(__name__)


ContentType = Literal[
    "book",
    "conversation",
    "notes",
    "audio",
    "video",
    "epub",
    "kindle_clippings",
    "tech_book",
    "tech_article",
]

_parser = DocumentParser()

CHUNK_CONFIGS: dict[str, dict[str, int]] = {
    "paper": {"chunk_size": 300, "chunk_overlap": 45},
    "book": {"chunk_size": 600, "chunk_overlap": 120},
    "conversation": {"chunk_size": 450, "chunk_overlap": 90},
    "notes": {"chunk_size": 300, "chunk_overlap": 75},
    "code": {"chunk_size": 300, "chunk_overlap": 75},
    "tech_book": {"chunk_size": 500, "chunk_overlap": 80},
    "tech_article": {"chunk_size": 350, "chunk_overlap": 60},
    "epub": {"chunk_size": 600, "chunk_overlap": 120},
    "kindle_clippings": {"chunk_size": 300, "chunk_overlap": 75},
}

# S224: cap on canonical entities included in a chunk's entity tail.
# Bounds embedding distortion and BM25 dilution from very entity-dense chunks.
ENTITY_TAIL_MAX = 12


def build_entity_tail(canonical_names: set[str] | list[str] | tuple[str, ...]) -> str:
    """Build the deterministic entity tail '[Entities: A, B, C]' for a chunk.

    Rules per S224 AC: dedupe (case-insensitive on the canonical key), sort
    alphabetically (case-insensitive), capitalize each label, cap at
    ENTITY_TAIL_MAX entries. Returns '' for empty input so callers can store
    NULL when there are no entities.
    """
    if not canonical_names:
        return ""
    seen: dict[str, str] = {}
    for raw in canonical_names:
        if not isinstance(raw, str):
            continue
        name = raw.strip()
        if not name:
            continue
        key = name.casefold()
        if key not in seen:
            seen[key] = name
    if not seen:
        return ""
    ordered = sorted(seen.values(), key=lambda s: s.casefold())[:ENTITY_TAIL_MAX]
    capitalized = [
        " ".join(part[:1].upper() + part[1:] if part else part for part in label.split(" "))
        for label in ordered
    ]
    return f"[Entities: {', '.join(capitalized)}]"


STAGE_PROGRESS: dict[str, int] = {
    "parsing": 10,
    "transcribing": 15,
    "classifying": 25,
    "chunking": 40,
    "entity_extract": 60,
    "embedding": 70,
    "indexing": 80,
    "enriching": 95,
    "complete": 100,
    "error": 0,
}


class IngestionState(TypedDict):
    document_id: str
    file_path: str
    format: str
    parsed_document: dict[str, Any] | None
    content_type: str | None
    chunks: list[dict[str, Any]] | None
    status: str
    error: str | None
    section_summary_count: int | None
    audio_duration_seconds: float | None
    _audio_chunks: list[dict[str, Any]] | None


def _classify(
    raw_text: str, sections: list[dict], word_count: int, file_ext: str, filename: str = ""
) -> str:
    if file_ext in ("mp3", "m4a", "wav"):
        return "audio"
    if file_ext == "mp4":
        return "video"
    if file_ext == "epub":
        return "book"

    if file_ext in ("py", "js", "ts", "go", "java", "rs", "cpp", "c", "rb"):
        return "code"
    # Kindle My Clippings.txt detection: filename pattern or content signature
    if re.search(r"clippings", filename, re.IGNORECASE) or re.search(
        r"^==========", raw_text[:2000], re.MULTILINE
    ):
        return "kindle_clippings"
    headings_lower = " ".join(s.get("heading", "").lower() for s in sections)
    text_lower = raw_text[:5000].lower()
    speaker_pattern = re.compile(r"\b[A-Z][a-zA-Z]+:\s")
    if speaker_pattern.search(raw_text[:3000]):
        return "conversation"
    if re.search(r"\b(speaker|interviewer|host|guest):", text_lower):
        return "conversation"
    if re.search(r"\b(abstract|methodology|references|hypothesis)\b", text_lower):
        return "paper"
    if re.search(r"\b(abstract|methodology)\b", headings_lower):
        return "paper"
    # tech_book: >= 3 fenced code blocks (= >= 6 triple-backtick tokens) in first 5000 chars,
    # OR >= 2 numbered section headings (e.g. "1.1", "2.3") in first 5000 chars.
    first_5k = raw_text[:5000]
    code_fence_count = len(re.findall(r"```", first_5k))
    numbered_section_count = len(re.findall(r"\b\d+\.\d+\b", first_5k))
    if code_fence_count >= 6 or numbered_section_count >= 2:
        return "tech_book"
    chapter_count = len(re.findall(r"\bchapter\b", headings_lower))
    if chapter_count >= 2 and word_count > 40000:
        return "book"
    return "notes"


async def _update_stage(document_id: str, stage: str) -> None:
    from sqlalchemy import update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    async with get_session_factory()() as session:
        await session.execute(
            update(DocumentModel).where(DocumentModel.id == document_id).values(stage=stage)
        )
        await session.commit()
