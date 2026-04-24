import logging
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
    # YouTube channel/uploader name returned by yt-dlp metadata.
    channel_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # Canonical YouTube video URL -- set during YouTube ingestion, same value as source_url.
    # Separate field so API consumers can identify YouTube docs without heuristic URL parsing.
    youtube_url: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # S146: PDF page number (1-based) for chunks from PDF documents.
    # Null for non-PDF content types (txt, docx, epub, audio, code, etc.).
    pdf_page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    # S154: cloze deletion text with {{term}} markers; null for non-cloze cards
    cloze_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # S169: 16-char hex SHA-256 prefix of note.content[:500]; enables content-hash deduplication
    # for collection-based generation. Null for non-collection cards.
    source_content_hash: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # S173: note_id FK for note-sourced cards; enables per-note coverage tracking
    note_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # S179: chunk classifier label (concept/definition/example/analogy/narrative/transition);
    # null for note/gap/context-sourced cards that bypass the classifier
    chunk_classification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # S188: section heading denormalized at generation time for source grounding display
    section_heading: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class StudySessionModel(Base):
    __tablename__ = "study_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str | None] = mapped_column(String, nullable=True)
    collection_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cards_reviewed: Mapped[int] = mapped_column(Integer, default=0)
    cards_correct: Mapped[int] = mapped_column(Integer, default=0)
    accuracy_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # flashcard|teachback|socratic|synthesis
    mode: Mapped[str] = mapped_column(String, nullable=False)
    # Planned flashcard queue captured at session start. Resume uses this to
    # reconstruct the remaining queue instead of re-querying due cards, which
    # would otherwise pull in cards that became due after the session began.
    planned_card_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)


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
    # S156: structured rubric JSON; null when rubric LLM call fails or for legacy rows
    rubric_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Async evaluation: "pending" | "complete" | "error"
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    # Link to study session for persistence across tab switches
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
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
    # S201: short hash of content for dedup (sha256[:16])
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    # S173: archived flag -- excluded from default GET /notes list; set by archive-stale
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
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
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
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


class FeynmanSessionModel(Base):
    """A guided Feynman technique session for a document section concept.

    status values: active | complete
    Note: any new delete path in documents.py must also delete these rows.
    """

    __tablename__ = "feynman_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    concept: Mapped[str] = mapped_column(String(300), nullable=False)
    # active|complete
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # S156: structured rubric JSON written at complete_session(); null until completion
    rubric_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # S159: model-generated explanation and key points (null until POST /model-explanation)
    model_explanation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_points_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class FeynmanTurnModel(Base):
    """One turn in a Feynman session (tutor or learner message).

    role values: tutor | learner
    gaps_identified: JSON list of gap strings; null for learner turns and opening.
    Note: any new delete path in documents.py must also delete these rows.
    """

    __tablename__ = "feynman_turns"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # tutor|learner
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON list of identified gap strings; null for learner turns
    gaps_identified: Mapped[list | None] = mapped_column(JSON, nullable=True)
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
    # PDF page number (1-based); null for non-PDF documents
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
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

    __table_args__ = (UniqueConstraint("document_id", "content_hash", name="uq_image_doc_hash"),)


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
    # S194: URL validation status — None = unchecked, True = reachable, False = dead link
    is_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "section_id",
            "term",
            "url",
            name="uq_web_ref_doc_section_term_url",
        ),
    )


class ClipModel(Base):
    """Persistent passage clip from any document reader view.

    selected_text is the raw clipped text.
    section_heading is denormalized at clip time to avoid JOIN in Reading Journal.
    pdf_page_number is null for non-PDF documents.
    user_note is editable and auto-saved by the Reading Journal card.

    Note: any new delete path in documents.py must also delete these rows
    (no FK CASCADE in SQLite without pragma enforcement).
    """

    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    section_heading: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pdf_page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selected_text: Mapped[str] = mapped_column(Text, nullable=False)
    user_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class ReadingPositionModel(Base):
    """Stores the last reading position per document — one row per document (PK = document_id).

    last_section_id and last_section_heading record the section visible when the user last read.
    last_pdf_page is set only for PDF documents; last_epub_chapter_index only for EPUB.
    updated_at is refreshed on every upsert so the banner can show a relative timestamp.

    Note: any new delete path in documents.py must also delete these rows
    (no FK CASCADE in SQLite without pragma enforcement).
    """

    __tablename__ = "reading_positions"

    document_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    last_section_heading: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_pdf_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_epub_chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class CollectionModel(Base):
    """A named collection of notes and documents supporting up to 2 levels of nesting.

    parent_collection_id is null for top-level collections.
    Max depth: child collections may not themselves have children (enforced at API layer).
    """

    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#6366F1")
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Self-FK for 2-level hierarchy; null = top-level collection
    parent_collection_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # S192: auto-collection for a document (one per document, nullable for manual collections)
    auto_document_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class CollectionMemberModel(Base):
    """Pivot table: maps members (notes, documents) to collections (many-to-many).

    Duplicate (member_id, collection_id, member_type) triples are silently ignored
    via ON CONFLICT DO NOTHING.
    """

    __tablename__ = "collection_members"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    collection_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    member_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # note | document
    member_type: Mapped[str] = mapped_column(String, nullable=False, default="note")
    added_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    __table_args__ = (
        UniqueConstraint("member_id", "collection_id", "member_type", name="uq_collection_member"),
    )


class NoteTagIndexModel(Base):
    """Shadow/denorm table: one row per (note, tag) pair for O(1) tag prefix lookup.

    note_id has no FK (shadow table -- avoids FK overhead and cascade complexity).
    tag_full: full tag path e.g. 'science/biology/genetics'
    tag_root: first segment e.g. 'science'
    tag_parent: all-but-last segment e.g. 'science/biology', empty string if top-level
    Composite PK on (note_id, tag_full) enforces uniqueness without a surrogate key.
    """

    __tablename__ = "note_tag_index"

    note_id: Mapped[str] = mapped_column(String, primary_key=True)
    tag_full: Mapped[str] = mapped_column(String, primary_key=True)
    tag_root: Mapped[str] = mapped_column(String, nullable=False)
    tag_parent: Mapped[str] = mapped_column(String, nullable=False, default="")


class CanonicalTagModel(Base):
    """Registry of canonical tag slugs with slash-convention hierarchy.

    id is the full slug (PK), e.g. 'science/biology'.
    parent_tag is the parent slug e.g. 'science', or None for top-level tags.
    note_count is denormalized -- kept accurate by _sync_tag_index.
    """

    __tablename__ = "canonical_tags"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # full slug
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    parent_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    note_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class TagAliasModel(Base):
    """Maps a deprecated/aliased tag slug to its canonical replacement.

    Created when tags are merged (source -> target).
    """

    __tablename__ = "tag_aliases"

    alias: Mapped[str] = mapped_column(String, primary_key=True)
    canonical_tag_id: Mapped[str] = mapped_column(String, nullable=False, index=True)


class TagMergeSuggestionModel(Base):
    """Suggested tag pair merges from SmartTagNormalizerService.

    status: 'pending' | 'accepted' | 'rejected'
    suggested_canonical_id: whichever of tag_a or tag_b has higher note_count (the merge target).
    """

    __tablename__ = "tag_merge_suggestions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tag_a_id: Mapped[str] = mapped_column(String, nullable=False)
    tag_b_id: Mapped[str] = mapped_column(String, nullable=False)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    suggested_canonical_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ClusterSuggestionModel(Base):
    """A cluster of semantically similar notes suggested as a collection.

    note_ids: JSON list of note id strings.
    confidence_score: mean pairwise cosine similarity of cluster members (0.0 - 1.0).
    status: 'pending' | 'accepted' | 'rejected'
    """

    __tablename__ = "cluster_suggestions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    suggested_name: Mapped[str] = mapped_column(String, nullable=False)
    note_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class NoteLinkModel(Base):
    """Explicit note-to-note Zettelkasten-style link (S171).

    Each row represents a directed typed connection from source_note_id to target_note_id.
    Bidirectionality is achieved by querying both directions in GET /notes/{id}/links.
    FK cascades ensure rows are removed when either note is deleted.
    UniqueConstraint prevents duplicate (source, target, link_type) triples.
    """

    __tablename__ = "note_links"
    __table_args__ = (
        UniqueConstraint("source_note_id", "target_note_id", "link_type", name="uq_note_link"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_note_id: Mapped[str] = mapped_column(
        String, ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_note_id: Mapped[str] = mapped_column(
        String, ForeignKey("notes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # elaborates | contradicts | see-also | supports | questions
    link_type: Mapped[str] = mapped_column(String(20), nullable=False, default="see-also")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class NoteSourceModel(Base):
    """Pivot table: maps notes to source documents (many-to-many).

    NoteModel.document_id (single nullable FK) is kept for backward compatibility.
    New multi-document source linkage is stored here.
    Composite PK (note_id, document_id) enforces uniqueness without a surrogate key.
    note_id has FK+cascade; document_id is a plain string (matching NoteModel.document_id
    pattern -- no FK to documents to avoid constraint failures when documents are deleted
    asynchronously or in test scenarios).
    """

    __tablename__ = "note_sources"

    note_id: Mapped[str] = mapped_column(
        String, ForeignKey("notes.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[str] = mapped_column(String, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


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


class ChatSuggestionHistoryModel(Base):
    """Tracks shown/asked chat suggestion pills for Bloom-progressive dedup (S195)."""

    __tablename__ = "chat_suggestion_history"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    suggestion_text: Mapped[str] = mapped_column(Text, nullable=False)
    bloom_level: Mapped[int] = mapped_column(Integer, nullable=False)
    was_asked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    shown_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)


class GlossaryTermModel(Base):
    """Persistent glossary term extracted from a document via LLM."""

    __tablename__ = "glossary_terms"
    __table_args__ = (UniqueConstraint("document_id", "term", name="uq_glossary_doc_term"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    term: Mapped[str] = mapped_column(String, nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    first_mention_section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


# ---------------------------------------------------------------------------
# Engagement: Streaks, XP, Achievements, Focus Sessions (Phase 7)
# ---------------------------------------------------------------------------


class StudyStreakModel(Base):
    """Tracks daily study streak and freeze tokens for the local user."""

    __tablename__ = "study_streaks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    current_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    longest_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_study_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    streak_freezes_available: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    streak_freezes_used_this_week: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    week_start_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class XPLedgerModel(Base):
    """Individual XP award events -- append-only ledger."""

    __tablename__ = "xp_ledger"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    xp_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class AchievementModel(Base):
    """Tracks unlock state and progress for each achievement."""

    __tablename__ = "achievements"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    icon_name: Mapped[str] = mapped_column(String(50), nullable=False, default="trophy")
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_target: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unlocked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )


class FocusSessionModel(Base):
    """A timed focus session (Pomodoro-style)."""

    __tablename__ = "focus_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    planned_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=25)
    actual_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_type: Mapped[str] = mapped_column(String(20), nullable=False, default="study")
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    xp_awarded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC)
    )
