from dataclasses import dataclass, field
from typing import Literal, TypedDict


@dataclass
class Section:
    heading: str
    level: int
    text: str
    page_start: int
    page_end: int
    admonition_type: str | None = None   # 'note'|'warning'|'tip'|'caution'|'important' or None
    parent_heading: str | None = None    # heading string of the logical parent section


@dataclass
class ParsedDocument:
    title: str
    format: str
    pages: int
    word_count: int
    sections: list[Section] = field(default_factory=list)
    raw_text: str = ""
    # Character offsets in raw_text where each new page begins
    page_breaks: list[int] = field(default_factory=list)


@dataclass
class ScoredChunk:
    chunk_id: str
    document_id: str
    text: str
    section_heading: str
    page: int
    score: float
    source: Literal["vector", "keyword", "both", "context_expansion"]
    chunk_index: int = 0
    speaker: str | None = None


# ---------------------------------------------------------------------------
# Chat Router types (V2 agentic chat — S77+)
# ---------------------------------------------------------------------------

IntentType = Literal[
    "summary", "factual", "relational", "comparative", "exploratory", "notes", "notes_gap",
    "socratic", "teach_back",
]


class ChatState(TypedDict):
    """LangGraph state for the V2 chat router.

    All fields must be provided in the initial state dict. Optional fields
    (those that nodes may or may not populate) use | None with a None default.
    """

    # Inputs (set once at the start of stream_answer)
    question: str
    doc_ids: list[str]
    scope: str  # 'single' | 'all'
    model: str | None

    # Set by classify_node
    intent: str | None  # IntentType | None
    rewritten_question: str | None

    # Set by strategy nodes
    chunks: list[dict]
    section_context: str | None

    # Set by synthesize_node
    answer: str
    citations: list[dict]
    confidence: str  # 'high' | 'medium' | 'low'
    not_found: bool

    # Internal streaming fields — set by synthesize_node, consumed by stream_answer().
    # synthesize_node prepares the LLM prompt but does NOT call the LLM; stream_answer()
    # calls the LLM streaming to yield tokens progressively as they are generated.
    _llm_prompt: str | None
    _system_prompt: str | None

    # Sliding-window conversation history (last N turns, role/content dicts)
    conversation_history: list[dict]

    # Confidence-adaptive retry fields (S81)
    # retry_attempted: True after augment_node runs — prevents a second retry loop.
    # primary_strategy: node name that handled the first-pass retrieval, used by
    #   augment_node to select the complementary strategy.
    retry_attempted: bool
    primary_strategy: str | None

    # Image retrieval (S134): image_ids matched by similarity search on image descriptions.
    # Set by search_node; included in the SSE done event so Chat.tsx can render thumbnails.
    image_ids: list[str]

    # Web augmentation (S142): optional per-conversation web search.
    # web_snippets is transient per graph invocation -- never written to DB (privacy invariant).
    web_enabled: bool
    web_calls_used: int
    web_snippets: list[dict]

    # S148: chunk-derived source citations (SourceCitation dicts) collected by synthesize_node.
    # Separate from 'citations' (LLM-extracted prose citations) to avoid field collision.
    # Keys: chunk_id, document_id, document_title, section_id, section_heading, pdf_page_number
    source_citations: list[dict]

    # S158: retrieval transparency metadata set by synthesize_node.
    # Emitted as a 'transparency' SSE event by stream_answer() after token streaming.
    transparency: "TransparencyInfo | None"

    # S158: flag set by augment_node to indicate context was augmented after low confidence.
    # Checked by synthesize_node to set transparency.augmented = True.
    transparency_augmented: bool


# ---------------------------------------------------------------------------
# Retrieval transparency (S158)
# ---------------------------------------------------------------------------


class TransparencyInfo(TypedDict):
    """Retrieval transparency metadata emitted as SSE event after answer streaming.

    strategy_used values: 'executive_summary' | 'hybrid_retrieval' |
        'graph_traversal' | 'comparative' | 'augmented_hybrid'
    """
    strategy_used: str   # how context was retrieved
    chunk_count: int     # number of unique chunks used as context
    section_count: int   # number of unique sections those chunks span
    augmented: bool      # True if augment_node ran (context extended after low confidence)


# ---------------------------------------------------------------------------
# Notes search (S91)
# ---------------------------------------------------------------------------


@dataclass
class NoteSearchResult:
    note_id: str
    content: str
    tags: list[str]
    group_name: str | None
    document_id: str | None
    score: float
    source: Literal["fts", "vector", "both"]


# ---------------------------------------------------------------------------
# Gap detection (S94)
# ---------------------------------------------------------------------------


class GapReport(TypedDict):
    gaps: list[str]
    covered: list[str]
    query_used: str
    weak: list[str]   # S145: concepts in notes with mastery < 0.3


# ---------------------------------------------------------------------------
# Web search (S142)
# ---------------------------------------------------------------------------


class WebSnippet(TypedDict):
    url: str
    title: str
    content: str        # first 500 chars of fetched content
    source_quality: str  # "official_docs" | "spec" | "wiki" | "blog" | "unknown"
    version_info: str   # e.g. "Python 3.12" or "" if not detected
    domain: str         # extracted domain for [Web: domain.com] label


# ---------------------------------------------------------------------------
# Citation deep-links (S148)
# ---------------------------------------------------------------------------


class SourceCitation(TypedDict):
    """Chunk-derived citation emitted by synthesize_node for trust/navigation."""
    chunk_id: str
    document_id: str
    document_title: str
    section_id: str | None
    section_heading: str
    pdf_page_number: int | None
    section_preview_snippet: str  # S157: first 150 chars of chunk text for hover tooltip


# ---------------------------------------------------------------------------
# Learning path (S117)
# ---------------------------------------------------------------------------


@dataclass
class LearningPathNode:
    entity_id: str
    name: str
    entity_type: str
    depth: int  # 0 = deepest prerequisite, increasing = closer to start (dependent)


class LearningPathResponse(TypedDict):
    start_entity: str
    document_id: str
    # nodes: topologically sorted LearningPathNode dataclasses (serialized to dicts on wire)
    nodes: list[LearningPathNode]
    edges: list[dict]  # list of {from_entity, to_entity, confidence}


# ---------------------------------------------------------------------------
# Study path (S139)
# ---------------------------------------------------------------------------


@dataclass
class StudyPathItem:
    concept: str
    mastery: float        # 0.0 to 1.0 -- avg(fsrs_stability / 21.0) capped at 1.0
    skip: bool            # True when avg_stability_days >= 14
    reason: str           # e.g. "avg_stability=18d" or "no flashcards"
    avg_stability_days: float


class StudyPathResponse(TypedDict):
    concept: str
    document_id: str
    path: list[StudyPathItem]  # ordered from earliest prereq to start concept


@dataclass
class StartConceptItem:
    concept: str
    prereq_chain_length: int
    flashcard_count: int
    rationale: str  # e.g. "0 prerequisites unskipped; 3 flashcards"


class StartConceptsResponse(TypedDict):
    document_id: str
    concepts: list[StartConceptItem]  # up to 3, sorted by shortest chain then fewest cards


# ---------------------------------------------------------------------------
# Concept mastery (S145)
# ---------------------------------------------------------------------------


@dataclass
class ConceptMastery:
    concept: str
    mastery: float           # 0.0 to 1.0; 0.0 + no_flashcards=True means no cards
    card_count: int
    due_soon: int            # cards due within the next 3 days
    no_flashcards: bool
    document_ids: list[str]


@dataclass
class HeatmapCell:
    chapter: str             # section heading
    concept: str
    mastery: float | None    # None = no flashcards for this (chapter, concept) cell
    card_count: int


class MasteryConceptsResponse(TypedDict):
    document_ids: list[str]
    concepts: list[ConceptMastery]


class MasteryHeatmapResponse(TypedDict):
    document_id: str
    chapters: list[str]
    concepts: list[str]
    cells: list[HeatmapCell]


# ---------------------------------------------------------------------------
# Flashcard coverage audit (S153)
# ---------------------------------------------------------------------------


class BloomGap(TypedDict):
    section_id: str
    section_heading: str
    missing_bloom_levels: list[int]  # levels 1-6 absent from section's cards


class BloomSectionStat(TypedDict):
    section_heading: str
    by_bloom_level: dict[int, int]  # level -> count (only levels present)
    has_level_3_plus: bool


class CoverageReport(TypedDict):
    total_cards: int
    by_bloom_level: dict[int, int]  # global level -> count across levels 1-6
    by_section: dict[str, BloomSectionStat]  # keyed by section_id
    coverage_score: float  # fraction of sections with >= 1 card at bloom_level >= 3
    gaps: list[BloomGap]


# ---------------------------------------------------------------------------
# Teach-back rubric (S156)
# ---------------------------------------------------------------------------


class TeachBackRubricDimension(TypedDict):
    score: int          # 0-100
    evidence: str       # quoted evidence from source or one-sentence comment


class TeachBackCompletenessDimension(TypedDict):
    score: int          # 0-100
    missed_points: list[str]  # concise concept phrases the student omitted


class TeachBackRubric(TypedDict):
    accuracy: TeachBackRubricDimension
    completeness: TeachBackCompletenessDimension
    clarity: TeachBackRubricDimension


# ---------------------------------------------------------------------------
# Deck Health Report (S160)
# ---------------------------------------------------------------------------


class HealthSection(TypedDict):
    section_id: str
    section_heading: str
    card_count: int


class DeckHealthReport(TypedDict):
    orphaned: int
    orphaned_ids: list[str]
    mastered: int
    mastered_ids: list[str]
    stale: int
    stale_ids: list[str]
    uncovered_sections: int
    uncovered_section_ids: list[str]
    hotspot_sections: list[HealthSection]
