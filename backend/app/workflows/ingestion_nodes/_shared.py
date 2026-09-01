"""Shared types + foundation helpers for ingestion nodes.

Holds the cross-node infrastructure that several nodes import:
- `IngestionState` TypedDict (the StateGraph state shape)
- `ContentType` literal
- `CHUNK_CONFIGS` per-content-type chunker settings
- `ENTITY_TAIL_MAX` + `build_entity_tail`
- `STAGE_PROGRESS` map
- `_classify` heuristic that picks the content type
- `_update_stage` async helper that writes the document's stage column
- `_parser` shared `DocumentParser` instance
- `_background_tasks` set for fire-and-forget tasks

Re-exported from `app.workflows.ingestion` for back-compat with
existing test imports.
"""

import asyncio
import logging
from typing import Any, TypedDict

from app.database import get_session_factory
from app.services.parser import DocumentParser
from app.types import ContentType  # noqa: F401  re-exported via app.workflows.ingestion

# Module-level set holding fire-and-forget background tasks (objective
# extraction, pregenerate, etc.). All ingestion nodes share this so the
# tasks aren't garbage-collected mid-execution. Each task should add
# `_background_tasks.discard` as a done-callback so finished tasks don't
# accumulate.
_background_tasks: set[asyncio.Task] = set()

logger = logging.getLogger(__name__)



_parser = DocumentParser()

CHUNK_CONFIGS: dict[str, dict[str, int]] = {
    # Papers are the densest content type and previously had the smallest budget,
    # tight enough that splits fell past word boundaries into mid-word cuts. The
    # chunk embedder (bge-small-en-v1.5) carries 512 tokens (~2000 chars), so this
    # still leaves headroom.
    "paper": {"chunk_size": 900, "chunk_overlap": 150},
    "book": {"chunk_size": 600, "chunk_overlap": 120},
    "conversation": {"chunk_size": 450, "chunk_overlap": 90},
    "notes": {"chunk_size": 300, "chunk_overlap": 75},
    "code": {"chunk_size": 300, "chunk_overlap": 75},
    "tech_book": {"chunk_size": 500, "chunk_overlap": 80},
    "tech_article": {"chunk_size": 350, "chunk_overlap": 60},
    "epub": {"chunk_size": 600, "chunk_overlap": 120},
    "kindle_clippings": {"chunk_size": 300, "chunk_overlap": 75},
}

# cap on canonical entities included in a chunk's entity tail.
# Bounds embedding distortion and BM25 dilution from very entity-dense chunks.
ENTITY_TAIL_MAX = 12


def build_entity_tail(canonical_names: set[str] | list[str] | tuple[str, ...]) -> str:
    """Build the deterministic entity tail '[Entities: A, B, C]' for a chunk.

    Rules per AC: dedupe (case-insensitive on the canonical key), sort
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
    "summarizing": 85,
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
    is_technical: bool | None
    structure_type: str | None
    defer_section_summaries: bool | None
    _audio_chunks: list[dict[str, Any]] | None


def resolve_technical_variant(raw_text: str, word_count: int | None = None) -> str:
    """Resolve the merged 'technical' upload choice into the sizing variant
    the chunker expects. The two variants share every other pipeline branch.

    Length decides it, because the choice is a chunk size and nothing else.
    Structure overrides length only for a short document that is plainly a
    manual. Each threshold is bracketed by the two library documents that
    decide it:

    - 5,000 words: `luminary_conceptual_foundations` at 5,312 is a book,
      `radiology_chexnet_cxr` at 3,764 is a paper.
    - 8 sections: below the length gate, `radiology_chexnet_cxr` is the only
      document with any numbered sections at all, at 6 -- and it must stay an
      article, so a threshold of 3 would misfile it.
    - 6 fence lines (3 blocks): keeps the previous rule's fence intent.
      `retrieval-and-memory-tutorial` at 4,920 words and 26 fences is a book;
      `Introducing Contextual Retrieval` at 4 fences is not.

    The previous rule read the first 5,000 characters and never looked at
    length. On a book that window is the title page and the table of contents,
    which is the same defect `classify_content` was rewritten to remove: it put
    a 120,000-word IAEA manual and `d2l_dive_into_deep_learning` in the article
    bucket, and a 3,764-word paper in the book one.
    """
    from app.services.content_classifier import (  # noqa: PLC0415
        _CODE_FENCE,
        count_numbered_sections,
        strip_boilerplate,
    )

    body = strip_boilerplate(raw_text)
    words = word_count if word_count is not None else len(body.split())
    if words >= 5000 or len(_CODE_FENCE.findall(body)) >= 6 or count_numbered_sections(body) >= 8:
        return "tech_book"
    return "tech_article"


def _classify(
    raw_text: str, sections: list[dict], word_count: int, file_ext: str, filename: str = ""
) -> str:
    """Deprecated alias for `classify_content`, kept for existing importers.

    The rules that used to live here scored 4 of 13 on the repo's own corpus:
    they read the first 5,000 characters (a Gutenberg licence, not the book),
    matched single words anywhere, and returned on the first hit so ordering
    decided the answer. `app.services.content_classifier` replaces them and
    scores 13 of 13 against `tests/fixtures/content_type_labels.json`.
    """
    from app.services.content_classifier import classify_content  # noqa: PLC0415

    return classify_content(raw_text, sections, word_count, file_ext, filename)


async def _update_stage(document_id: str, stage: str) -> None:
    from sqlalchemy import update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    async with get_session_factory()() as session:
        await session.execute(
            update(DocumentModel).where(DocumentModel.id == document_id).values(stage=stage)
        )
        await session.commit()


async def detect_technical_transcript(raw_text: str) -> bool | None:
    """Ask the LLM whether a transcript is technical content. None when undecidable.

    Transcripts carry none of the structural signals resolve_technical_variant()
    keys on (no fenced code, no numbered sections), so the decision has to come
    from the language itself.
    """
    from app.services.llm import get_llm_service  # noqa: PLC0415

    snippet = raw_text[:2000].strip()
    if not snippet:
        return None
    prompt = (
        "Does this transcript discuss technical subject matter — software, "
        "engineering, science, or mathematics?\n\n"
        f"Transcript excerpt:\n{snippet}\n\n"
        "Reply with exactly one word: yes or no."
    )
    try:
        raw = await get_llm_service().generate(prompt, background=True)
    except Exception as exc:
        logger.warning("technical detection failed (non-fatal): %s", exc)
        return None
    answer = str(raw).strip().lower()
    if answer.startswith("yes"):
        return True
    if answer.startswith("no"):
        return False
    return None


async def _persist_is_technical(document_id: str, is_technical: bool) -> None:
    from sqlalchemy import update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    async with get_session_factory()() as session:
        await session.execute(
            update(DocumentModel)
            .where(DocumentModel.id == document_id)
            .values(is_technical=is_technical)
        )
        await session.commit()


async def _persist_extraction_report(document_id: str, report: dict | None) -> None:
    """Store what the importer captured and what it could not.

    Null on the column means "fidelity was never measured", which is not the
    same as a clean import -- so the ingest path only writes when a parser
    actually measured. A re-import writes whatever it measured including None,
    because the stored report has to describe the import that is in the
    database, not the one it replaced.
    """
    from sqlalchemy import update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    async with get_session_factory()() as session:
        await session.execute(
            update(DocumentModel)
            .where(DocumentModel.id == document_id)
            .values(extraction_report=report)
        )
        await session.commit()


async def _persist_structure_type(document_id: str, structure_type: str) -> None:
    """Write the layout the parser discovered ('book'|'paper'|'script'|'chat')."""
    from sqlalchemy import update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    async with get_session_factory()() as session:
        await session.execute(
            update(DocumentModel)
            .where(DocumentModel.id == document_id)
            .values(structure_type=structure_type)
        )
        await session.commit()


async def _persist_content_type(document_id: str, content_type: str) -> None:
    """Write a resolved content_type back to the document row so the stored
    value always names a concrete pipeline variant, never a merged choice."""
    from sqlalchemy import update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    async with get_session_factory()() as session:
        await session.execute(
            update(DocumentModel)
            .where(DocumentModel.id == document_id)
            .values(content_type=content_type)
        )
        await session.commit()
