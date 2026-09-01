"""Pydantic request/response schemas for the documents router.

Extracted from `app/routers/documents.py`.
The router re-exports these names under their original (private) aliases
via `__all__` so existing imports keep working.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.membership import CollectionRef
from app.types import ContentType


class DocumentFacets(BaseModel):
    """What the document is, and the card strategy that follows from it.

    `domain` and `register` are null when nothing has classified them, which is
    not the same as "general" or "expository" -- a null is shown to the reader
    as unclassified rather than as a decision nobody made.
    """

    form: str | None = None
    domain: str | None = None
    register: str | None = None
    # Derived, never stored: which flashcard strategy this document gets.
    card_genre: str | None = None


class DocumentListItem(BaseModel):
    id: str
    title: str
    format: str
    content_type: str
    facets: DocumentFacets | None = None
    word_count: int
    page_count: int
    stage: str
    tags: list[str]
    created_at: datetime
    last_accessed_at: datetime
    summary_one_sentence: str | None
    flashcard_count: int
    learning_status: Literal["not_started", "summarized", "flashcards_generated", "studied"]
    chapter_count: int | None
    chunk_count: int
    reading_progress_pct: float
    audio_duration_seconds: float | None
    source_url: str | None = None
    video_title: str | None = None
    channel_name: str | None = None
    youtube_url: str | None = None
    enrichment_status: str | None = None
    objective_progress_pct: float | None = None
    mastery_pct: float | None = None
    # Membership chips for the card surface (plan 2E.5). Ordered by
    # CollectionModel.sort_order ASC, created_at ASC -- stable across pages.
    collections: list[CollectionRef] = []


class DocumentFacetsResponse(BaseModel):
    """How many documents each filter would match, over the whole library.

    A filter offering zero results is not a filter, it is a dead end -- and the
    library has carried several: `code` is not even a storable content type,
    and `epub` is a format that no document carries as its type.
    """

    content_types: dict[str, int]
    formats: dict[str, int]
    total: int


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    total: int
    page: int
    page_size: int


class BulkDeleteRequest(BaseModel):
    ids: list[str]


class PatchTagsRequest(BaseModel):
    tags: list[str]


class PatchDocumentRequest(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    content_type: ContentType | None = None


class SectionItem(BaseModel):
    id: str
    heading: str
    level: int
    page_start: int
    page_end: int
    # What the section's first page is printed as, when the book numbers its
    # front matter separately. Display only -- `page_start` is the sheet, and
    # the sheet is what the viewer scrolls to. Without this the contents list
    # said "p.328" beside a page printed 324 and a citation that also said 324.
    page_label_start: str | None = None
    section_order: int
    preview: str
    admonition_type: str | None = None
    parent_section_id: str | None = None


class DocumentDiagnostics(BaseModel):
    chunk_count: int
    fts_count: int
    entity_count: int
    edge_count: int
    vector_count: int


class DocumentDetail(BaseModel):
    id: str
    title: str
    format: str
    content_type: str
    facets: DocumentFacets | None = None
    # Layout discovered while parsing: book|paper|script|chat.
    structure_type: str | None = None
    # What the importer captured and what it could not. Null means fidelity was
    # never measured for this document -- which is not the same as a clean import.
    extraction_report: dict | None = None
    word_count: int
    page_count: int
    stage: str
    tags: list[str]
    created_at: datetime
    last_accessed_at: datetime
    # Sheet number -> the number printed on that sheet, for PDFs whose front
    # matter is numbered separately. Derived at ingestion, so it covers books
    # that print their page numbers without declaring PDF page labels -- which
    # pdf.js cannot see, and which would otherwise leave the viewer's footer
    # disagreeing with the citation that sent the reader there.
    page_labels: dict[str, str] = {}
    sections: list[SectionItem]
    reading_progress_pct: float
    audio_duration_seconds: float | None = None
    source_url: str | None = None
    video_title: str | None = None
    channel_name: str | None = None
    youtube_url: str | None = None


class ChunkItem(BaseModel):
    id: str
    chunk_index: int
    text: str
    section_id: str | None = None
    speaker: str | None = None
    start_time: float | None = None


class UrlIngestRequest(BaseModel):
    url: str
    # Post-JS DOM captured by the desktop shell's hidden webview, when it has
    # one. Only pages that *compute* their content need it; everything else
    # imports identically from the static fetch, which is the only path in dev,
    # Docker and the script installs. Never required.
    rendered_html: str | None = None
    # Why the caller did or did not render: "ok" | "unavailable" | "failed".
    # Logged, never trusted for behaviour -- the presence of rendered_html is
    # what decides the path.
    render_state: str | None = None
    # The shell's own reason when render_state is "failed". Carried because the
    # desktop shell has no console anyone reads, so this log line is the only
    # place a rendering failure is visible at all.
    render_detail: str | None = None


class YouTubeIngestRequest(BaseModel):
    url: str


class IngestResponse(BaseModel):
    """Result of POST /documents/ingest.

    `status` distinguishes work started from a file we already hold. Ingestion
    dedupes on file hash, and a duplicate of an already-complete document used to
    be reported as "processing" -- so the client tracked a document that would
    never progress, and the user saw an upload that appeared to do nothing.
    """

    document_id: str
    status: Literal["processing", "duplicate"]


class KindleIngestResponse(BaseModel):
    document_ids: list[str]
    book_count: int


class CodeSnippetItem(BaseModel):
    id: str
    chunk_id: str
    section_id: str | None
    language: str | None
    signature: str | None
    content: str


class PDFMetaResponse(BaseModel):
    page_count: int
    has_toc: bool


class EpubChapterTocItem(BaseModel):
    chapter_index: int
    title: str
    word_count: int


class EpubTocResponse(BaseModel):
    document_id: str
    chapters: list[EpubChapterTocItem]


class EpubChapterResponse(BaseModel):
    chapter_index: int
    chapter_title: str
    html: str
    word_count: int
    section_ids: list[str]


# in-document FTS5 search response model
class DocumentSectionSearchResult(BaseModel):
    section_id: str
    section_heading: str
    match_count: int
    snippet: str  # FTS5 snippet() output with <mark> tags wrapping matched terms


class LearningObjectiveItem(BaseModel):
    id: str
    section_id: str
    text: str
    covered: bool


class LearningObjectivesResponse(BaseModel):
    document_id: str
    objectives: list[LearningObjectiveItem]


class LearningObjectiveUpdate(BaseModel):
    """Body for the manual covered-toggle PATCH (B)."""

    covered: bool


class ChapterProgressItem(BaseModel):
    section_id: str
    heading: str
    total_objectives: int
    covered_objectives: int
    progress_pct: float  # 0.0-100.0


class DocumentProgressResponse(BaseModel):
    document_id: str
    total_objectives: int
    covered_objectives: int
    progress_pct: float  # 0.0-100.0
    by_chapter: list[ChapterProgressItem]


class SavePositionRequest(BaseModel):
    last_section_id: str | None = None
    last_section_heading: str | None = None
    last_pdf_page: int | None = None
    last_epub_chapter_index: int | None = None


class ReadingPositionResponse(BaseModel):
    document_id: str
    last_section_id: str | None
    last_section_heading: str | None
    last_pdf_page: int | None
    last_epub_chapter_index: int | None


# Doc overview (docs/02-ingest-and-doc-overview.md) -- read aggregation


class DocumentOverviewResponse(BaseModel):
    id: str
    title: str
    format: str
    content_type: str
    tags: list[str]
    reading_progress_pct: float
    collections: list[CollectionRef]


class AssignCollectionsRequest(BaseModel):
    collection_ids: list[str]


class ReparseRequest(BaseModel):
    """`confirm=False` reports what a re-import would cost and changes nothing."""

    confirm: bool = False
    # The shell owns the webview, so a rendered page can only come from the
    # client. Absent on every install without a shell, where the static fetch
    # is what the original import used too.
    rendered_html: str | None = None


class ReparseResponse(BaseModel):
    document_id: str
    status: str  # preview | processing
    source: str  # url | file
    # Rows that survive the rebuild but whose section/chunk anchors will not resolve.
    anchored: dict[str, int]
    cleared: dict[str, int] = {}
    detail: str
