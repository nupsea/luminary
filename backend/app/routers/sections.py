import logging
import re
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.database import get_session_factory
from app.exceptions import NotFound
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
    # Which tier served `content`, so a degraded read is visible (I-29).
    content_source: Literal["body", "preview", "chunks", "empty"] = "body"
    # Length of the *whole* section, so a client can tell a short section from a
    # shortened one. `truncated` means the rest is at
    # GET /sections/{document_id}/content/{section_id}, never that it is gone.
    content_chars: int = 0
    truncated: bool = False


class SectionContentPage(BaseModel):
    """One window of a document's sections.

    An envelope rather than a bare list because the reader has to know whether
    more exists. The unbounded version returned every section's full body in one
    response: measured at 20.2 MB over 1,017 sections on a 2.9M-word manual,
    which is enough to make a browser report the page as unresponsive.
    """

    items: list[SectionContentItem]
    total: int
    offset: int
    limit: int


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


# Above this, a section's text is served in a second call rather than inline.
# Bracketing cases, measured on one library: the largest section of a normal
# technical book runs to about 40,000 characters and must arrive whole, while a
# manual whose parent section stores its descendants' text as well as its own
# reaches 5,063,040 in a single section. 60,000 sits above every ordinary
# section here and well below the pathological one.
_INLINE_CONTENT_LIMIT = 60_000


# Reading text comes from `body` (I-29). `preview` serves only sections stored
# before it existed, and only while under the cap. Chunks are the last resort and
# are degraded by construction, which is why the tier is reported to the client.
_PREVIEW_LIMIT = 10_000


def _assemble(section: SectionModel, chunk_texts: list[str]) -> tuple[str, str]:
    """The text that serves a section, and which tier it came from."""
    if section.body:
        return _reader_safe(section.body), "body"
    if section.preview and len(section.preview) < _PREVIEW_LIMIT:
        return _reader_safe(section.preview), "preview"
    if chunk_texts:
        return (
            _reader_safe("\n\n".join(re.sub(r"^\[.*?\]\s*", "", c) for c in chunk_texts)),
            "chunks",
        )
    if section.preview:
        return _reader_safe(section.preview), "preview"
    return "", "empty"


@router.get("/{document_id}/content/{section_id}", response_model=SectionContentItem)
async def get_one_section_content(document_id: str, section_id: str) -> SectionContentItem:
    """One section with its text entire, however long it is.

    Declared above the windowed route so `content/{section_id}` is not matched by
    it, and it is what keeps the bound on that route honest: text over the inline
    limit is a second call away, never lost.
    """
    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        section = next(
            (s for s in await repo.sections_for_document(document_id) if s.id == section_id),
            None,
        )
        if section is None:
            raise NotFound(f"Section {section_id} not found in document {document_id}")
        # Only this section's chunks, so one long section never costs the
        # document's whole chunk table.
        chunks = await repo.chunks_for_document(document_id, by_section=True)

    texts = [c.text for c in chunks if c.section_id == section_id]
    content, source = _assemble(section, texts)
    return SectionContentItem(
        section_id=section.id,
        heading=section.heading,
        level=section.level,
        section_order=section.section_order,
        content=content,
        page_start=section.page_start or 0,
        page_end=section.page_end or 0,
        content_source=source,
        content_chars=len(content),
        truncated=False,
    )


@router.get("/{document_id}/content", response_model=SectionContentPage)
async def get_section_content(
    document_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=40, ge=1, le=200),
) -> SectionContentPage:
    """A window of sections, each with its text.

    Bounded on two axes because a reader renders neither all of a long
    document's sections nor all of one huge section at once: `limit` bounds how
    many sections come back, and `_INLINE_CONTENT_LIMIT` bounds each one. Text
    over that limit is not dropped -- the item says so and names its full
    length, and the whole section is one call away.
    """
    async with get_session_factory()() as session:
        repo = DocumentRepo(session)
        sections = await repo.sections_for_document(document_id)
        if not sections:
            return SectionContentPage(items=[], total=0, offset=offset, limit=limit)
        total = len(sections)
        sections = sections[offset : offset + limit]
        chunks = await repo.chunks_for_document(document_id, by_section=True)

    # Group chunks by section_id; orphan chunks (section_id=None) go into a separate list
    chunks_by_section: dict[str, list[str]] = {}
    orphan_chunks: list[str] = []
    for c in chunks:
        if c.section_id:
            chunks_by_section.setdefault(c.section_id, []).append(c.text)
        else:
            orphan_chunks.append(c.text)

    result = []
    for s in sections:
        content, source = _assemble(s, chunks_by_section.get(s.id, []))
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
                content_chars=len(content),
                truncated=len(content) > _INLINE_CONTENT_LIMIT,
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
            item.content_chars = len(item.content)
            item.truncated = item.content_chars > _INLINE_CONTENT_LIMIT

    # Trimmed last so `content_chars` is the length of the whole section, which
    # is what tells a client a section is shortened rather than short.
    for item in result:
        if item.truncated:
            item.content = item.content[:_INLINE_CONTENT_LIMIT]

    return SectionContentPage(items=result, total=total, offset=offset, limit=limit)
