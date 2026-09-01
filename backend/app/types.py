from dataclasses import dataclass, field
from typing import Literal, TypedDict

ContentType = Literal[
    "book",
    "conversation",
    "notes",
    "paper",
    "audio",
    "video",
    "epub",
    "kindle_clippings",
    "tech_book",
    "tech_article",
    # Merged upload choice; classify_node resolves it to tech_book or
    # tech_article from the parsed text and persists the resolved value.
    "technical",
]


# Document facets
#
# `ContentType` above answers four questions with one value -- a container
# (audio, epub, kindle_clippings), a shape (book, paper, conversation), a
# subject (the tech_ prefix) and a size -- so it has to enumerate a cross
# product and enumerates eleven of its cells. The facets below separate the
# questions, and `format` on the row already carries the container.
#
# Being written alongside `content_type`, which stays authoritative until the
# wire moves. See docs/roadmap.md rung 0.9.0.

Form = Literal[
    "prose",        # continuous long-form read start to finish
    "article",      # one self-contained piece, shallow headings
    "reference",    # manual or textbook: numbered sections, admonitions, code
    "paper",        # abstract, method, results, references
    "dialogue",     # speaker turns: chat, interview, meeting, talk transcript
    "script",       # play or screenplay: scenes and stage directions
    "entries",      # independent delimited units: clippings, journal, notes
    "source_code",  # a program file
]

Domain = Literal["general", "technical"]

# Whether the text tells a story or explains a subject. Nullable everywhere:
# nothing populates it yet, and `card_genre` falls back to the behaviour that
# shipped before it existed.
Register = Literal["narrative", "expository"]

CardGenre = Literal["narrative", "non-fiction", "technical", "academic", "conversation"]

_FORM_BY_CONTENT_TYPE: dict[str, Form] = {
    "book": "prose",
    "epub": "prose",
    "paper": "paper",
    "tech_book": "reference",
    "tech_article": "article",
    "conversation": "dialogue",
    "audio": "dialogue",
    "video": "dialogue",
    "notes": "entries",
    "kindle_clippings": "entries",
    "code": "source_code",
    # Transient upload choice. classify_node resolves it to a tech_* variant
    # before persisting, so this only covers a row read mid-ingest.
    "technical": "article",
}

# Chunker settings per form. The values are the ones CHUNK_CONFIGS carried for
# the content type each form replaces, so sizing does not move in this rung.
# `reference` is 500/80 (tech_book) and `article` 350/60 (tech_article): what
# used to be a length decision made at ingest is now carried by the form itself.
_CHUNK_BY_FORM: dict[Form, tuple[int, int]] = {
    "paper": (900, 150),
    "prose": (600, 120),
    "reference": (500, 80),
    "dialogue": (450, 90),
    "article": (350, 60),
    "entries": (300, 75),
    "source_code": (300, 75),
    "script": (600, 120),
}

# Forms whose neighbouring chunks continue the same thought, so fetching them
# adds context rather than noise. Replaces `_EXPANSION_TYPES`.
_EXPANDING_FORMS: frozenset[str] = frozenset({"prose", "dialogue", "entries"})

# Forms whose topics are the people and places in them. Everything else gets
# concepts only: in a transcript or a manual, a PERSON is a speaker or a cited
# author, which is noise as a browseable tag.
_NARRATIVE_FORMS: frozenset[str] = frozenset({"prose", "entries", "script"})


def chunk_config_for_form(form: Form) -> dict[str, int]:
    """Chunker settings for a form, for the specialised chunkers that already
    know which form they are handling and have no profile to hand."""
    size, overlap = _CHUNK_BY_FORM[form]
    return {"chunk_size": size, "chunk_overlap": overlap}


@dataclass(frozen=True)
class DocumentProfile:
    """What a document is, and every policy derived from it.

    One definition per policy. Consumers ask this object rather than testing
    `content_type` themselves -- five sites did the latter for "is this
    technical" and disagreed with each other, two of them by matching the
    document's title against a keyword list.
    """

    form: Form
    domain: Domain
    register: Register | None = None

    @property
    def is_technical(self) -> bool:
        """Whether technical NER types and technical relation extraction apply."""
        return self.domain == "technical"

    @property
    def chunk_config(self) -> dict[str, int]:
        return chunk_config_for_form(self.form)

    @property
    def expands_context(self) -> bool:
        return self.form in _EXPANDING_FORMS

    @property
    def tag_entity_types(self) -> tuple[str, ...]:
        if self.form in _NARRATIVE_FORMS:
            return ("PERSON", "PLACE", "CONCEPT")
        return ("CONCEPT",)

    @property
    def card_genre(self) -> CardGenre:
        """What to ask of this material when writing flashcards.

        `paper` is tested before `domain` because a paper is technical and
        still wants the academic prompt. `narrative` is unreachable until
        something populates `register`; before facets it was unreachable
        outright, and a prose book reached the technical prompt only by its
        title matching a keyword list.
        """
        if self.form == "source_code":
            return "technical"
        if self.form == "paper":
            return "academic"
        if self.form == "dialogue":
            return "conversation"
        if self.domain == "technical":
            return "technical"
        if self.register == "narrative":
            return "narrative"
        return "non-fiction"

    @classmethod
    def from_legacy(
        cls,
        content_type: str | None,
        is_technical: bool | None = None,
        register: Register | None = None,
    ) -> "DocumentProfile":
        """Build a profile from the columns that predate the facets.

        Used to dual-write during ingest and to backfill. `is_technical`
        resolves exactly as `is_technical_content` does, so NER sees the same
        answer it saw before.
        """
        # `entries` for an unmapped type, because that is the smallest chunk
        # size and matches what the generic chunker fell back to. Guessing a
        # larger one costs recall on a document nobody has classified.
        form = _FORM_BY_CONTENT_TYPE.get(content_type or "", "entries")
        technical = is_technical_content(content_type, is_technical)
        domain: Domain = "technical" if technical else "general"
        return cls(form=form, domain=domain, register=register)


@dataclass
class Section:
    heading: str
    level: int
    text: str
    page_start: int
    page_end: int
    admonition_type: str | None = None  # 'note' | 'warning' | 'tip' | 'caution' | 'important'
    parent_heading: str | None = None
    # Character offsets in `text` where a new page begins, excluding the first
    # page (whose number is `page_start`). Without this a chunk can only report
    # the page its *section* began on: measured on one library, every section of
    # every PDF reported a single page, one of them across 2,329 chunks, so a
    # citation into a long chapter pointed a hundred pages from its own text.
    page_breaks: list[int] = field(default_factory=list)


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
    # Sheet number -> the number printed on that sheet, for PDFs that number
    # their front matter separately. Only entries that differ from the sheet
    # number are kept, so an empty map means counting sheets is already right.
    page_labels: dict[int, str] = field(default_factory=dict)
    # Non-fatal extraction notices surfaced to the user; empty when extraction was clean.
    warnings: list[str] = field(default_factory=list)
    # Layout discovered from the document's own markers: book|paper|script|chat.
    # None when the parser that ran does not discover structure.
    structure_type: str | None = None
    # What the importer captured and what it could not, persisted so an
    # incomplete import is visible to the reader instead of silent. None when
    # the parser does not measure its own fidelity.
    extraction_report: dict | None = None


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


# Chat Router types

IntentType = Literal[
    "summary",
    "factual",
    "relational",
    "comparative",
    "exploratory",
    "notes",
    "notes_gap",
    "socratic",
    "teach_back",
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
    # True when retrieval raised rather than returning nothing. Without it, a
    # failed search and an empty library are the same downstream state, and the
    # user is told to ingest a document while their library sits there.
    retrieval_failed: bool

    # Set by synthesize_node
    answer: str
    citations: list[dict]
    confidence: str  # 'high' | 'medium' | 'low'
    not_found: bool

    # Internal streaming fields: synthesize_node prepares the LLM prompt but does not
    # call the LLM; stream_answer() calls it and streams tokens as they are generated.
    _llm_prompt: str | None
    _system_prompt: str | None

    # Sliding-window conversation history (last N turns, role/content dicts)
    conversation_history: list[dict]

    # Confidence-adaptive retry fields
    # retry_attempted: True after augment_node runs — prevents a second retry loop.
    # primary_strategy: node name that handled the first-pass retrieval, used by
    #   augment_node to select the complementary strategy.
    retry_attempted: bool
    primary_strategy: str | None

    # Image retrieval: image_ids matched by similarity search on image descriptions.
    # Set by search_node; included in the SSE done event so Chat.tsx can render thumbnails.
    image_ids: list[str]

    # Web augmentation: optional per-conversation web search.
    # web_snippets is transient per graph invocation — never written to DB (privacy invariant).
    web_enabled: bool
    web_calls_used: int
    web_snippets: list[dict]

    # Chunk-derived citations (SourceCitation shape) collected by synthesize_node.
    # Separate from 'citations' (LLM-extracted prose citations) to avoid field collision.
    source_citations: list[dict]

    # chunks actually emitted into the prompt, in [S<n>] marker order, set by
    # synthesize_node. Resolves a marker citation to the chunk it names, so the
    # excerpt is filled from that chunk instead of retyped by the model (I-33).
    cited_chunks: list[dict]

    # Retrieval transparency metadata; emitted as a 'transparency' SSE event by
    # stream_answer() after token streaming.
    transparency: "TransparencyInfo | None"

    # Set by augment_node when context was augmented after low confidence;
    # synthesize_node reads it to set transparency.augmented.
    transparency_augmented: bool


# Retrieval transparency


class TransparencyInfo(TypedDict):
    """Retrieval transparency metadata emitted as a 'transparency' SSE event.

    strategy_used values: 'executive_summary' | 'hybrid_retrieval' |
        'graph_traversal' | 'comparative' | 'augmented_hybrid'
    """

    strategy_used: str
    chunk_count: int  # unique chunks
    section_count: int  # unique sections spanned
    augmented: bool  # True when augment_node extended context after low confidence


# Notes search


@dataclass
class NoteSearchResult:
    note_id: str
    content: str
    tags: list[str]
    group_name: str | None
    document_id: str | None
    score: float
    source: Literal["fts", "vector", "both"]


# Gap detection


class GapReport(TypedDict):
    gaps: list[str]
    covered: list[str]
    query_used: str
    weak: list[str]  # concepts in notes with mastery < 0.3


# Web search


class WebSnippet(TypedDict):
    url: str
    title: str
    content: str  # first 500 chars of fetched content
    source_quality: str  # "official_docs" | "spec" | "wiki" | "blog" | "unknown"
    version_info: str  # e.g. "Python 3.12" or "" if not detected
    domain: str  # extracted domain for [Web: domain.com] label


# Citation deep-links


class SourceCitation(TypedDict):
    """Chunk-derived citation emitted by synthesize_node for trust/navigation."""

    chunk_id: str
    document_id: str
    document_title: str
    section_id: str | None
    section_heading: str
    pdf_page_number: int | None
    # The number printed on that sheet, when it differs. Display only: the chip
    # navigates by pdf_page_number, which is what the viewer scrolls to.
    pdf_page_label: str | None
    section_preview_snippet: str  # first 150 chars of chunk text for hover tooltip


# Learning path


@dataclass
class LearningPathNode:
    entity_id: str
    name: str
    entity_type: str
    depth: int  # 0 = deepest prerequisite, increasing = closer to start (dependent)


class LearningPathResponse(TypedDict):
    start_entity: str
    document_id: str
    # topologically sorted; serialized to dicts on the wire
    nodes: list[LearningPathNode]
    edges: list[dict]  # list of {from_entity, to_entity, confidence}


# Study path


@dataclass
class StudyPathItem:
    concept: str
    mastery: float  # 0.0 to 1.0 — avg(fsrs_stability / 21.0) capped at 1.0
    skip: bool  # True when avg_stability_days >= 14
    reason: str  # e.g. "avg_stability=18d" or "no flashcards"
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


# Concept mastery


@dataclass
class ConceptMastery:
    concept: str
    mastery: float  # 0.0 to 1.0; 0.0 + no_flashcards=True means no cards
    card_count: int
    due_soon: int  # cards due within the next 3 days
    no_flashcards: bool
    document_ids: list[str]


@dataclass
class HeatmapCell:
    chapter: str  # section heading
    concept: str
    mastery: float | None  # None = no flashcards for this (chapter, concept) cell
    card_count: int


class MasteryConceptsResponse(TypedDict):
    document_ids: list[str]
    concepts: list[ConceptMastery]


class MasteryHeatmapResponse(TypedDict):
    document_id: str
    chapters: list[str]
    concepts: list[str]
    cells: list[HeatmapCell]


# Flashcard coverage audit


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


# Teach-back rubric


class TeachBackRubricDimension(TypedDict):
    score: int  # 0-100
    evidence: str  # quoted evidence from source or one-sentence comment


class TeachBackCompletenessDimension(TypedDict):
    score: int  # 0-100
    missed_points: list[str]  # concise concept phrases the student omitted


class TeachBackRubric(TypedDict):
    accuracy: TeachBackRubricDimension
    completeness: TeachBackCompletenessDimension
    clarity: TeachBackRubricDimension


# Deck health report


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


# Technical-content gate


TECHNICAL_CONTENT_TYPES = ("code", "tech_book", "tech_article")


def is_technical_content(content_type: str | None, is_technical: bool | None) -> bool:
    """Whether to apply technical NER types and technical relation extraction.

    The persisted flag wins when set. Rows predating it fall back to content_type,
    which is why media documents were never treated as technical: a conference talk
    is content_type "audio", so the tech entity types (TECHNOLOGY and the six
    tech-specific ones) were filtered out of its graph.
    """
    if is_technical is not None:
        return is_technical
    return content_type in TECHNICAL_CONTENT_TYPES
