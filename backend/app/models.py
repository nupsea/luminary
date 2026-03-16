import logging
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

logger = logging.getLogger(__name__)


class DocumentModel(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    format: Mapped[str] = mapped_column(String, nullable=False)  # pdf|docx|txt|md|code
    # book|paper|conversation|notes|code
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    # SHA-256 hex digest of the original file — used for upload deduplication.
    # Nullable so rows created before this column was added are not affected.
    file_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # parsing|chunking|embedding|complete|enriching|error
    stage: Mapped[str] = mapped_column(String, default="parsing")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    # Number of detected sections/chapters (set during book ingestion).
    chapter_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Speaker roster and timeline for conversation documents (set during ingestion).
    conversation_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Duration in seconds for audio documents (set during transcription).
    audio_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Human-readable error detail written by error_finalize_node (e.g. "ffmpeg not found").
    # Surfaced to the UI via GET /documents/{id}/status as error_message.
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Original URL for YouTube-ingested documents (e.g. https://www.youtube.com/watch?v=...).
    # Null for locally uploaded files.
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Human-readable title returned by yt-dlp metadata (YouTube video title).
    video_title: Mapped[str | None] = mapped_column(String, nullable=True)
    # Approximate publication year parsed from document front matter (Copyright YYYY).
    # Nullable: most documents will not have explicit year information.
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class SectionModel(Base):
    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False)
    heading: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-6
    page_start: Mapped[int] = mapped_column(Integer, default=0)
    page_end: Mapped[int] = mapped_column(Integer, default=0)
    section_order: Mapped[int] = mapped_column(Integer, nullable=False)
    preview: Mapped[str] = mapped_column(Text, default="")
    # Tech section detection fields (set by tech_book/tech_article content type)
    admonition_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    parent_section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Prerequisite chain depth (number of hops from root to this section's concepts; S139)
    difficulty_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ChunkModel(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    page_number: Mapped[int] = mapped_column(Integer, default=0)
    speaker: Mapped[str | None] = mapped_column(String, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Code-aware chunking fields (set by tech_book/tech_article content type)
    has_code: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    code_language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    code_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class SummaryModel(Base):
    __tablename__ = "summaries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False)
    # one_sentence|executive|detailed|conversation
    mode: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class FlashcardModel(Base):
    __tablename__ = "flashcards"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # 'document' for book-chunk cards, 'note' for note-sourced cards, 'gap' for gap-bridge cards
    source: Mapped[str] = mapped_column(String, nullable=False, default="document")
    # Logical deck name; 'gaps' for cards created via POST /flashcards/from-gaps (S97)
    deck: Mapped[str] = mapped_column(String, nullable=False, default="default")
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    source_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    is_user_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    fsrs_stability: Mapped[float] = mapped_column(Float, default=0.0)
    fsrs_difficulty: Mapped[float] = mapped_column(Float, default=0.0)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fsrs_state: Mapped[str] = mapped_column(String, default="new")  # new|learning|review|relearning
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    last_review: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # S137: Bloom's Taxonomy fields — set by generate_technical(); null for non-tech cards
    flashcard_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    bloom_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class StudySessionModel(Base):
    __tablename__ = "study_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cards_reviewed: Mapped[int] = mapped_column(Integer, default=0)
    cards_correct: Mapped[int] = mapped_column(Integer, default=0)
    accuracy_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # flashcard|teachback|socratic|synthesis
    mode: Mapped[str] = mapped_column(String, nullable=False)


class ReviewEventModel(Base):
    __tablename__ = "review_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    flashcard_id: Mapped[str] = mapped_column(String, nullable=False)
    rating: Mapped[str] = mapped_column(String, nullable=False)  # again|hard|good|easy
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class TeachbackResultModel(Base):
    __tablename__ = "teachback_results"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    flashcard_id: Mapped[str] = mapped_column(String, nullable=False)
    user_explanation: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_points: Mapped[list] = mapped_column(JSON, default=list)
    missing_points: Mapped[list] = mapped_column(JSON, default=list)
    misconceptions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class MisconceptionModel(Base):
    __tablename__ = "misconceptions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False)
    flashcard_id: Mapped[str] = mapped_column(String, nullable=False)
    user_answer: Mapped[str] = mapped_column(Text, nullable=False)
    # misconception|incomplete|unrelated|memory_lapse
    error_type: Mapped[str] = mapped_column(String, nullable=False)
    correction_note: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class NoteModel(Base):
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str | None] = mapped_column(String, nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(String, nullable=True)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    group_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class QAHistoryModel(Base):
    __tablename__ = "qa_history"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scope: Mapped[str] = mapped_column(String, nullable=False)  # single|all
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[str] = mapped_column(String, nullable=False)  # high|medium|low
    model_used: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class LibrarySummaryModel(Base):
    __tablename__ = "library_summaries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # one_sentence|executive|detailed
    mode: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class SectionSummaryModel(Base):
    __tablename__ = "section_summaries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    heading: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    unit_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class SettingsModel(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)


class EvalRunModel(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_name: Mapped[str] = mapped_column(String, nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    hit_rate_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_used: Mapped[str] = mapped_column(String, nullable=False)


class ReadingProgressModel(Base):
    """Track which sections a user has read and for how long.

    Note: any new delete path in documents.py must also delete these rows
    (no FK CASCADE in SQLite without pragma enforcement).
    """
    __tablename__ = "reading_progress"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    section_id: Mapped[str] = mapped_column(String, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False,
                                                    default=lambda: datetime.now(UTC))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False,
                                                   default=lambda: datetime.now(UTC))
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("document_id", "section_id", name="uq_reading_progress_doc_section"),
    )


class LearningGoalModel(Base):
    """A user-defined learning goal with a target date.

    Note: any new delete path in documents.py must also delete these rows
    (no FK CASCADE in SQLite without pragma enforcement).
    """

    __tablename__ = "learning_goals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    # ISO date string: 'YYYY-MM-DD' — stored as TEXT for SQLite portability
    target_date: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class CodeSnippetModel(Base):
    """Extracted code block from a tech_book or tech_article document.

    Each row corresponds to one atomic code block (fenced or indented) found
    during tech_book chunking.  The language and AST-derived signature are
    stored for downstream use (flashcard generation, Run button, filtering).

    Note: any new delete path in documents.py must also delete these rows.
    """

    __tablename__ = "code_snippets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    chunk_id: Mapped[str] = mapped_column(String, nullable=False)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str | None] = mapped_column(String(50), nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class LearningObjectiveModel(Base):
    """Learning objective extracted from a tech_book/tech_article chapter introduction.

    Rows are created by LearningObjectiveExtractorService as a background task
    during ingestion.  They are shown in the Learning tab Chapter Goals panel.

    Note: any new delete path in documents.py must also delete these rows
    (no FK CASCADE in SQLite without pragma enforcement).
    """

    __tablename__ = "learning_objectives"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    section_id: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    covered: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class AnnotationModel(Base):
    """Persistent text highlights anchored to a document section.

    Note: any new delete path in documents.py must also delete these rows
    (no FK CASCADE in SQLite without pragma enforcement).
    """

    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    section_id: Mapped[str] = mapped_column(String, nullable=False)
    # chunk_id is nullable: sections do not map 1:1 to chunks
    chunk_id: Mapped[str | None] = mapped_column(String, nullable=True)
    selected_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    # yellow|green|blue|pink
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="yellow")
    note_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class EnrichmentJobModel(Base):
    """Async enrichment job queue entry.

    job_type values registered so far:
      image_extract    -- S133: PDF/EPUB image extraction
      image_analyze    -- S134: vision LLM image description
      diagram_extract  -- S136: diagram-type routing and COMPONENT node extraction
      prerequisites    -- S139: prerequisite graph extraction
      web_refs         -- S138: web reference resolution
      concept_link     -- S141: cross-document concept linking

    status values:
      pending  -- queued, not yet started
      running  -- worker has picked this job up
      done     -- completed successfully
      failed   -- error_message contains the cause

    Note: any new delete path in documents.py must also delete these rows
    (no FK CASCADE in SQLite without FK pragma enforcement).
    """

    __tablename__ = "enrichment_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ImageModel(Base):
    """Extracted image from a PDF or EPUB document.

    chunk_id is the nearest preceding prose chunk by page/index (set during
    extraction; null if no prose chunk precedes the image on the same page).
    image_type and description are null until S134 (vision analysis) runs.

    Note: any new delete path in documents.py must also delete these rows.
    """

    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    chunk_id: Mapped[str | None] = mapped_column(String, nullable=True)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    # Relative path from DATA_DIR, e.g. "images/{doc_id}/{page}_{index}.png"
    path: Mapped[str] = mapped_column(String, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    # null until S134 vision analysis populates it
    image_type: Mapped[str | None] = mapped_column(String, nullable=True)
    # null until S134 vision analysis populates it
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("document_id", "content_hash", name="uq_image_doc_hash"),
    )


class WebReferenceModel(Base):
    """LLM-generated canonical web reference for a technical term in a section.

    source_quality values (ordered best to worst):
      official_docs | spec | wiki | tutorial | blog | unknown

    is_llm_suggested=True means URL was produced by the LLM from training knowledge
    and has not been verified via a live HEAD request.
    is_llm_suggested=False means a HEAD request confirmed the URL is reachable.

    Note: any new delete path in documents.py must also delete these rows
    (no FK CASCADE in SQLite without pragma enforcement).
    """

    __tablename__ = "web_references"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # official_docs | spec | wiki | tutorial | blog | unknown
    source_quality: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    is_llm_suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint(
            "document_id", "section_id", "term", "url",
            name="uq_web_ref_doc_section_term_url",
        ),
    )


class PredictionEventModel(Base):
    """Records each Predict-then-Run attempt by the user.

    strip() comparison is used for prediction_correct:
      expected='hello' vs actual='hello\\n' yields correct=True
      (trailing newlines are normalized).

    chunk_id is nullable because the PredictPanel is section-scoped.
    code_content is truncated to 2000 chars at write time.
    document_id has no FK constraint (same pattern as review_events).
    """

    __tablename__ = "prediction_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    chunk_id: Mapped[str | None] = mapped_column(String, nullable=True)
    document_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    code_content: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    actual: Mapped[str] = mapped_column(Text, nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=False, default="python")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
