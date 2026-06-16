"""Pydantic request/response schemas for the notes router.

Extracted from `app/routers/notes.py`.
The router re-exports these names verbatim via `__all__` so existing
imports keep working.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.membership import CollectionRef


class NoteCreateRequest(BaseModel):
    document_id: str | None = None
    chunk_id: str | None = None
    section_id: str | None = None
    content: str
    tags: list[str] = []
    group_name: str | None = None
    # Optional user-provided title. When set, the note is flagged manual-title.
    title: str | None = None
    # multi-document source linkage; legacy document_id still accepted
    source_document_ids: list[str] = []


class NoteUpdateRequest(BaseModel):
    content: str | None = None
    tags: list[str] | None = None
    group_name: str | None = None
    # section_id=None means "field not sent" (PATCH semantics — cannot clear via PATCH)
    section_id: str | None = None
    # None means "not supplied" (do not change); [] means "remove all sources"
    source_document_ids: list[str] | None = None
    # Manual title edit. When supplied, the row is flipped to
    # title_auto_generated=False so subsequent auto-gen passes never
    # overwrite the user's choice. Empty string is a legal "clear to null".
    title: str | None = None
    # Auto-generated note summary. None = not supplied; "" clears to null.
    description: str | None = None


class NoteResponse(BaseModel):
    id: str
    document_id: str | None
    chunk_id: str | None
    section_id: str | None
    content: str
    tags: list[str]
    group_name: str | None
    # Replaces the bare collection_ids list (plan 2E.5). Same membership
    # data, enriched with name + color so cards can render chips without
    # a follow-up fetch. Ordered by CollectionModel.sort_order ASC.
    collections: list[CollectionRef] = []
    # all source document IDs from NoteSourceModel pivot
    source_document_ids: list[str] = []
    title: str | None = None
    title_auto_generated: bool = True
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GroupInfo(BaseModel):
    name: str
    count: int


class TagInfo(BaseModel):
    name: str
    count: int


class GroupsResponse(BaseModel):
    groups: list[GroupInfo]
    tags: list[TagInfo]
    total_notes: int


class SuggestedTagsResponse(BaseModel):
    tags: list[str]


class NoteTitleSuggestRequest(BaseModel):
    content: str


class NoteTitleSuggestResponse(BaseModel):
    title: str


class NoteDescriptionSuggestRequest(BaseModel):
    content: str


class NoteDescriptionSuggestResponse(BaseModel):
    description: str


class NoteSearchItem(BaseModel):
    note_id: str
    content: str
    tags: list[str]
    group_name: str | None
    document_id: str | None
    score: float
    source: str  # "fts" | "vector" | "both"


class NoteSearchResponse(BaseModel):
    query: str
    results: list[NoteSearchItem]
    total: int


class NoteEntityItem(BaseModel):
    name: str
    type: str
    confidence: float
    edge_type: str  # "WRITTEN_ABOUT" | "TAG_IS_CONCEPT"


class NoteFlashcardGenerateRequest(BaseModel):
    tag: str | None = None
    note_ids: list[str] | None = None
    collection_id: str | None = None
    count: int = 5
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    force_regenerate: bool = False


class NoteFlashcardItem(BaseModel):
    id: str
    question: str
    answer: str
    source_excerpt: str
    source: str

    model_config = {"from_attributes": True}


class NoteFlashcardGenerateResponse(BaseModel):
    created: int
    skipped: int
    deck: str


class ClusterNotePreview(BaseModel):
    note_id: str
    excerpt: str


class ClusterSuggestionResponse(BaseModel):
    id: str
    suggested_name: str
    note_ids: list[str] = []
    note_count: int
    confidence_score: float
    status: str
    created_at: datetime
    previews: list[ClusterNotePreview]


class BatchAcceptItem(BaseModel):
    suggestion_id: str
    name_override: str | None = None
    # If set, overrides the suggestion's note_ids (drag-and-drop)
    note_ids: list[str] | None = None


class BatchAcceptRequest(BaseModel):
    items: list[BatchAcceptItem]


class NamingViolation(BaseModel):
    type: str  # "tag" or "collection"
    id: str
    current_name: str
    suggested_name: str
    action: str  # "rename" or "merge"
    merge_target_id: str | None = None


class NamingFixItem(BaseModel):
    type: str
    id: str
    current_name: str
    suggested_name: str
    action: str = "rename"


class NamingFixRequest(BaseModel):
    fixes: list[NamingFixItem]


class NoteLinkCreateRequest(BaseModel):
    target_note_id: str
    link_type: str = "see-also"


class NoteLinkItem(BaseModel):
    id: str
    note_id: str
    preview: str
    link_type: str
    created_at: datetime


class NoteLinksResponse(BaseModel):
    outgoing: list[NoteLinkItem]
    incoming: list[NoteLinkItem]


class NoteAutocompleteItem(BaseModel):
    id: str
    preview: str


class GapDetectRequest(BaseModel):
    note_ids: list[str] = []
    document_id: str


class GapDetectResponse(BaseModel):
    gaps: list[str]
    covered: list[str]
    query_used: str
