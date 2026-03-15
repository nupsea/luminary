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
