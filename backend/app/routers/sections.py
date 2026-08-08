import logging
import re
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.database import get_session_factory
from app.models import SectionModel
from app.repos.document_repo import DocumentRepo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sections", tags=["sections"])


_SETEXT_UNDERLINE_RE = re.compile(r"^[ \t]*(-{1,}|={1,})[ \t]*$")


def _reader_safe(text: str) -> str:
    """Neutralise markdown that document text triggers by accident.

    Extracted PDF text is rendered as markdown, so a line of dashes directly
    under a line of prose becomes a setext heading -- a hyphen left alone on its
    own line by the PDF text layer silently promoted whole sentences to <h2>.
    Inserting a blank line demotes it to a horizontal rule, which is what a
    reader would expect, and leaves deliberate rules and lists untouched.
    """
    if not text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        if out and out[-1].strip() and _SETEXT_UNDERLINE_RE.match(line):
            out.append("")
        out.append(line)
    return "\n".join(out)


class SectionContentItem(BaseModel):
    section_id: str
    heading: str
    level: int
    section_order: int
    content: str
    page_start: int = 0
    page_end: int = 0
    # Which tier served `content`, so a degraded read is visible rather than
    # silent. See I-29 and docs/universal-reader.md.
    content_source: Literal["body", "preview", "chunks", "empty"] = "body"


class SectionResponse(BaseModel):
    id: str
    heading: str
    level: int
    page_start: int
    section_order: int
    chunk_count: int
    has_summary: bool
    admonition_type: str | None = None
    parent_section_id: str | None = None


@router.get("/{document_id}", response_model=list[SectionResponse])
async def get_sections(document_id: str) -> list[SectionResponse]:
    """Return sections for a document with accurate chunk_count per section."""
    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        sections = await repo.sections_for_document(document_id)
        if not sections:
            return []
        chunk_counts = await repo.chunk_counts_by_section(document_id)

    logger.debug("Sections fetched", extra={"document_id": document_id, "count": len(sections)})
    return [
        SectionResponse(
            id=s.id,
            heading=s.heading,
            level=s.level,
            page_start=s.page_start,
            section_order=s.section_order,
            chunk_count=chunk_counts.get(s.id, 0),
            # Section-level summaries not yet implemented — always False.
            has_summary=False,
            admonition_type=s.admonition_type,
            parent_section_id=s.parent_section_id,
        )
        for s in sections
    ]


@router.get("/{document_id}/content", response_model=list[SectionContentItem])
async def get_section_content(document_id: str) -> list[SectionContentItem]:
    """Return all sections with full text assembled from their chunks."""
    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        sections = await repo.sections_for_document(document_id)
        if not sections:
            return []
        chunks = await repo.chunks_for_document(document_id, by_section=True)

    # Group chunks by section_id; orphan chunks (section_id=None) go into a separate list
    chunks_by_section: dict[str, list[str]] = {}
    orphan_chunks: list[str] = []
    for c in chunks:
        if c.section_id:
            chunks_by_section.setdefault(c.section_id, []).append(c.text)
        else:
            orphan_chunks.append(c.text)

    # Reading text comes from `body`, which is uncapped (I-29). `preview` is
    # capped at PREVIEW_CHARS and serves only sections stored before `body`
    # existed -- past the cap it is truncated mid-sentence, so the chunk tier
    # takes over. Chunks are the last resort and are degraded by construction:
    # they cut mid-sentence and carry "[Title > Section] " enrichment prefixes,
    # so re-joining them fabricates paragraph breaks. Documents on that tier
    # need re-ingestion, which is why the tier is reported to the client.
    PREVIEW_LIMIT = 10000

    def _section_content(s: SectionModel) -> tuple[str, str]:
        if s.body:
            return _reader_safe(s.body), "body"
        if s.preview and len(s.preview) < PREVIEW_LIMIT:
            return _reader_safe(s.preview), "preview"
        chunk_texts = chunks_by_section.get(s.id, [])
        if chunk_texts:
            return (
                _reader_safe("\n\n".join(re.sub(r"^\[.*?\]\s*", "", c) for c in chunk_texts)),
                "chunks",
            )
        if s.preview:
            return _reader_safe(s.preview), "preview"
        return "", "empty"

    result = []
    for s in sections:
        content, source = _section_content(s)
        result.append(
            SectionContentItem(
                section_id=s.id,
                heading=s.heading,
                level=s.level,
                section_order=s.section_order,
                content=content,
                page_start=s.page_start or 0,
                page_end=s.page_end or 0,
                content_source=source,
            )
        )

    # If all sections ended up empty (chunks lacked section_id mapping),
    # distribute orphan chunks evenly across sections as a best-effort fallback.
    # Strip enrichment headers ([...] prefix) so the text reads naturally.
    if orphan_chunks and all(not r.content for r in result) and result:
        cleaned = [re.sub(r"^\[.*?\]\s*", "", c) for c in orphan_chunks]
        per_section = max(1, len(cleaned) // len(result))
        for i, item in enumerate(result):
            start = i * per_section
            end = start + per_section if i < len(result) - 1 else len(cleaned)
            item.content = "\n\n".join(cleaned[start:end])
            item.content_source = "chunks"

    return result
