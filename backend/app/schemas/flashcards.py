"""Pydantic request/response schemas for the flashcards router.

Extracted from `app/routers/flashcards.py`.
The router re-exports these names verbatim via `__all__` so existing
imports in `routers/study.py` and `schemas/study.py` keep working.
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# provider/name, the shape LiteLLM routes on. Validated rather than passed
# through so a typo fails loudly here instead of silently falling back to the
# configured default, which would make a model comparison in the UI a lie.
_MODEL_ID_RE = re.compile(r"^(ollama|openai|anthropic|gemini)/[A-Za-z0-9._:-]+$")


def _validate_model_id(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not _MODEL_ID_RE.match(value):
        raise ValueError(
            "model must look like 'provider/name', e.g. ollama/qwen3.5:4b"
        )
    return value


class FlashcardGenerateRequest(BaseModel):
    document_id: str
    scope: Literal["full", "section"] = "full"
    section_heading: str | None = None
    count: int = 10
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    context: str | None = None  # selected text from reader; used directly when provided
    # None follows the model chosen in Settings, exactly as /qa does when its
    # selector reads "Auto". A concrete id overrides it for this request only.
    model: str | None = None

    @field_validator("model")
    @classmethod
    def _check_model(cls, value: str | None) -> str | None:
        return _validate_model_id(value)


class FromGapsRequest(BaseModel):
    gaps: list[str] = Field(min_length=1)
    document_id: str = ""


class FromGapsResponse(BaseModel):
    created: int


class FlashcardUpdateRequest(BaseModel):
    question: str | None = None
    answer: str | None = None


class GenerateFromGraphRequest(BaseModel):
    document_id: str
    k: int = Field(default=5, ge=1, le=20)


class EntityPairPreview(BaseModel):
    name_a: str
    name_b: str
    relation_label: str
    confidence: float


class EntityPairsResponse(BaseModel):
    pairs: list[EntityPairPreview]


class ReviewRequest(BaseModel):
    rating: Literal["again", "hard", "good", "easy"]
    session_id: str | None = None
    predicted_rating: Literal["again", "hard", "good", "easy"] | None = None


class GenerateTechnicalRequest(BaseModel):
    document_id: str
    scope: Literal["full", "section"] = "full"
    section_heading: str | None = None
    count: int = 10
    model: str | None = None

    @field_validator("model")
    @classmethod
    def _check_model(cls, value: str | None) -> str | None:
        return _validate_model_id(value)


class FlashcardResponse(BaseModel):
    id: str
    document_id: str | None
    chunk_id: str | None
    source: str = "document"
    question: str
    answer: str
    source_excerpt: str
    difficulty: str = "medium"
    is_user_edited: bool
    fsrs_state: str
    fsrs_stability: float
    fsrs_difficulty: float
    due_date: datetime | None
    reps: int
    lapses: int
    created_at: datetime
    # Bloom's Taxonomy fields
    flashcard_type: str | None = None
    bloom_level: int | None = None
    # section_id derived from chunk -- populated by endpoints that do the join
    section_id: str | None = None
    # cloze deletion text with {{term}} markers; null for non-cloze cards
    cloze_text: str | None = None
    # chunk classifier label; null for non-document-chunk cards
    chunk_classification: str | None = None
    # section heading for source grounding display
    section_heading: str | None = None
    # unchecked | verified | unsupported | unverifiable -- whether this card's
    # source_excerpt was found in the text the card came from. The review UI needs
    # it to decide whether it may present that excerpt as a source.
    grounding: str = "unchecked"
    # unchecked | supported | unsupported | unverifiable -- whether the answer
    # follows from the passage. Distinct from `grounding`: a real quote does not
    # make the answer true.
    factuality: str = "unchecked"

    model_config = {"from_attributes": True}

    @field_validator("grounding", "factuality", mode="before")
    @classmethod
    def _default_grounding(cls, value: str | None) -> str:
        """A card read before its row was flushed has no verdict yet, not a passing
        one. Coerced here so every reader sees the same four states."""
        return value or "unchecked"


class GroundingAuditRequest(BaseModel):
    """Body for POST /flashcards/grounding/audit."""

    document_id: str | None = Field(
        default=None, description="Audit one document's cards; omit to audit the library."
    )


class GroundingReport(BaseModel):
    """Counts by grounding state. Every state is reported, including the ones that
    mean 'not proven' -- collapsing those into a pass rate is what made an
    unverifiable card indistinguishable from a verified one."""

    scanned: int
    changed: int = 0
    verified: int = 0
    unsupported: int = 0
    unverifiable: int = 0
    unchecked: int = 0


class FactualityAuditRequest(BaseModel):
    """Body for POST /flashcards/factuality/audit."""

    document_id: str | None = None
    # One model call per card, so a whole library is minutes of inference. The
    # audit is resumable: call it again while `remaining` is above zero.
    limit: int = Field(default=50, ge=1, le=500)


class FactualityReport(BaseModel):
    """What one bounded pass of the factuality audit judged.

    `skipped_no_passage` is reported rather than folded into a rate: a card whose
    passage cannot be rebuilt was not judged, and counting it either way would
    invent a verdict.
    """

    judged: int
    skipped_no_passage: int
    remaining: int
    supported: int = 0
    unsupported: int = 0
    unverifiable: int = 0


class RepairReport(BaseModel):
    """What POST /flashcards/repair actually changed. Zeroes on a healthy library."""

    index_rows_removed: int
    cards_indexed: int
    orphan_rows_removed: int


class CoverageReportResponse(BaseModel):
    """Response schema for GET /flashcards/audit/{document_id}"""

    total_cards: int
    by_bloom_level: dict[str, int]  # JSON keys are always strings
    by_section: dict[str, dict]  # BloomSectionStat as plain dict
    coverage_score: float
    gaps: list[dict]  # BloomGap as plain dict


class FillGapsResponse(BaseModel):
    """Response schema for POST /flashcards/audit/{document_id}/fill"""

    created: int


class DeckHealthReportResponse(BaseModel):
    """Response schema for GET /flashcards/health/{document_id}"""

    orphaned: int
    orphaned_ids: list[str]
    mastered: int
    mastered_ids: list[str]
    stale: int
    stale_ids: list[str]
    uncovered_sections: int
    uncovered_section_ids: list[str]
    hotspot_sections: list[dict]


class ArchiveMasteredResponse(BaseModel):
    """Response schema for POST /flashcards/health/{document_id}/archive-mastered"""

    archived: int


class FillUncoveredRequest(BaseModel):
    """Request body for POST /flashcards/health/{document_id}/fill-uncovered"""

    section_ids: list[str] = Field(min_length=1)


class FillUncoveredResponse(BaseModel):
    """Response schema for POST /flashcards/health/{document_id}/fill-uncovered"""

    queued: int


class SourceContextResponse(BaseModel):
    """Response schema for GET /flashcards/{card_id}/source-context"""

    section_heading: str
    section_preview: str
    document_title: str
    pdf_page_number: int | None
    section_id: str
    document_id: str


class FlashcardSearchResponse(BaseModel):
    items: list[FlashcardResponse]
    total: int
    page: int
    page_size: int


class TraceFlashcardRequest(BaseModel):
    question: str  # typically the code block (front of card)
    answer: str  # correct output + diff explanation (back of card)
    source_excerpt: str
    document_id: str | None = None
    chunk_id: str | None = None


class DeckItem(BaseModel):
    deck: str
    source_type: str  # "document" | "collection" | "note"
    card_count: int
    document_id: str | None
    collection_id: str | None


class BulkDeleteRequest(BaseModel):
    ids: list[str] = Field(min_length=1)


class BulkDeleteResponse(BaseModel):
    deleted: int
