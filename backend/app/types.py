from dataclasses import dataclass, field
from typing import Literal, TypedDict


@dataclass
class Section:
    heading: str
    level: int
    text: str
    page_start: int
    page_end: int


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

IntentType = Literal["summary", "factual", "relational", "comparative", "exploratory"]


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
