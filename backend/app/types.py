from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict, overload

# A card written ahead for a chapter, outside the review schedule until the chapter is practised.
CARD_HELD = "held"

# A section's `preview` is a bounded snippet; reading text lives in `body`, uncapped (I-29).
PREVIEW_CHARS = 10000

# Document facets. The retired content type answered four questions with one value --
# container, shape, subject, size -- and so enumerated eleven cells of a cross
# product. These separate the questions; `format` carries the container (#223).

Form = Literal[
    "prose",  # continuous long-form read start to finish
    "article",  # one self-contained piece, shallow headings
    "reference",  # manual or textbook: sections nested or numbered for lookup
    "paper",  # abstract, method, results, references
    "dialogue",  # speaker turns: chat, interview, meeting, talk transcript
    "script",  # play or screenplay: scenes and stage directions
    "entries",  # independent delimited units: clippings, journal, notes
    "source_code",  # a program file
]

# Null is not "general". Only a measurement or a reader's choice establishes a
# domain; a failed probe leaves null, and calling that "general" would show the
# reader a decision nobody made.
Domain = Literal["general", "technical"]

# Whether the text tells a story or explains a subject.
Register = Literal["narrative", "expository"]

CardGenre = Literal["narrative", "non-fiction", "technical", "academic", "conversation"]

# Chunk sizes, carried over from the content type each form replaced, so sizing did not move.
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

# Forms whose neighbouring chunks continue the same thought.
_EXPANDING_FORMS: frozenset[str] = frozenset({"prose", "dialogue", "entries"})

# Forms whose topics are their people and places. Elsewhere a PERSON is a
# speaker or a cited author -- noise as a browseable tag.
_NARRATIVE_FORMS: frozenset[str] = frozenset({"prose", "entries", "script"})


# Forms whose register follows from the shape. `dialogue` is deliberately
# absent: a meeting explains but an audiobook narrates, and both are turns.
_REGISTER_BY_FORM: dict[str, Register] = {
    "paper": "expository",
    "reference": "expository",
}


UNCLASSIFIED_FORM: Form = "entries"


def register_for_form(form: Form) -> "Register | None":
    """The register a form settles on its own, or None when it must be measured."""
    return _REGISTER_BY_FORM.get(form)


def chunk_config_for_form(form: Form) -> dict[str, int]:
    """Chunker settings for a form, for the specialised chunkers that already
    know which form they are handling and have no profile to hand."""
    size, overlap = _CHUNK_BY_FORM[form]
    return {"chunk_size": size, "chunk_overlap": overlap}


@dataclass(frozen=True)
class DocumentProfile:
    """What a document is, and every policy derived from it.

    One definition per policy. Consumers ask this object rather than testing a
    type: five sites once did that for "is this technical" and disagreed, two of
    them by matching the document title against a keyword list.
    """

    form: Form
    domain: Domain | None = None
    register: Register | None = None

    @property
    def is_technical(self) -> bool:
        """Whether technical NER types and relation extraction apply; an unknown domain is not."""
        return self.domain == "technical"

    @property
    def chunk_config(self) -> dict[str, int]:
        return chunk_config_for_form(self.form)

    @property
    def expands_context(self) -> bool:
        return self.form in _EXPANDING_FORMS

    @property
    def is_narrative_prose(self) -> bool:
        """Whether cards are written about a story's characters and plot."""
        return self.form == "prose"

    @property
    def tag_entity_types(self) -> tuple[str, ...]:
        if self.form in _NARRATIVE_FORMS:
            return ("PERSON", "PLACE", "CONCEPT")
        return ("CONCEPT",)

    @property
    def card_genre(self) -> CardGenre | None:
        """What to ask of this material when writing flashcards.

        None when the facets do not determine it: a default here is how "The
        Odyssey" came to be shown as non-fiction. A caller that must have a
        strategy picks one itself.

        `paper` is tested before `domain` -- a paper is technical and still
        wants the academic prompt.
        """
        if self.form == "source_code":
            return "technical"
        if self.form == "paper":
            return "academic"
        if self.form == "dialogue":
            # A talk is not a meeting: "what was decided, who owns it" is a
            # meeting's question, and a talk's value is the technique.
            if self.domain == "technical":
                return "technical"
            return "conversation" if self.domain == "general" else None
        # Register before domain: it is sampled from the body, the domain from the opening,
        # which is a preface on a Gutenberg book (The Odyssey read technical, #253).
        if self.register == "narrative":
            return "narrative"
        if self.domain == "technical":
            return "technical"
        if self.register == "expository":
            return "non-fiction"
        return None

    @classmethod
    def from_row(cls, row: Any) -> "DocumentProfile | None":
        """The profile a stored document carries, or None if nothing measured it.

        `form` is the axis every other facet hangs off, so a row without one has
        no profile -- callers fall back rather than reading `domain` alone.
        """
        if row is None or not getattr(row, "form", None):
            return None
        return cls(form=row.form, domain=row.domain, register=row.register)

    @classmethod
    def of(cls, doc: Any) -> "DocumentProfile":
        """The profile policy reads for a stored document.

        An unclassified one -- mid-ingest, or a parse that failed -- reads as
        `entries`: the smallest chunks, and what the generic chunker falls back to.
        """
        measured = cls.from_row(doc)
        if measured is not None:
            return measured
        return cls(form=UNCLASSIFIED_FORM, domain=getattr(doc, "domain", None))


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
    direct: bool  # ask model directly without library grounding

    # Set by classify_node
    intent: str | None  # IntentType | None
    rewritten_question: str | None

    # Set by strategy nodes
    chunks: list[dict]
    section_context: str | None
    # notes_node answered a subject-less notes question from the most recent notes.
    notes_recent: bool
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

    # What the answer cost to assemble, carried out for the receipt under it. A key
    # a node returns but ChatState does not declare is dropped by the graph, so
    # these read null in the receipt until they are listed here -- which is exactly
    # how they shipped null the first time.
    _passages_sent: int | None
    _context_chars: int | None
    _context_budget: int | None
    _budget_reason: str | None

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


# Audio files ingestion transcribes. FLAC is how YouTube audio is stored (`download_audio`).
AUDIO_EXTENSIONS = ("mp3", "m4a", "wav", "flac")

# What the library calls a document, derived from its stored format and facets (#223).
DocumentKind = Literal[
    "book", "technical", "paper", "conversation", "notes", "code", "audio", "video"
]

# First match wins. `document_kind_repo.kind_expr` compiles the same table to SQL for filters.
_KindRule = tuple[Literal["format", "form", "domain"], tuple[str, ...], DocumentKind]
KIND_RULES: tuple[_KindRule, ...] = (
    ("format", AUDIO_EXTENSIONS, "audio"),
    ("format", ("mp4",), "video"),
    ("form", ("dialogue",), "conversation"),
    ("form", ("paper",), "paper"),
    ("form", ("source_code",), "code"),
    ("form", ("entries",), "notes"),
    ("domain", ("technical",), "technical"),
)
DEFAULT_KIND: DocumentKind = "book"


def document_kind(format: str | None, form: str | None, domain: str | None) -> DocumentKind:
    """The document's kind from the stored columns alone, as the list filter computes it."""
    values = {"format": format, "form": form, "domain": domain}
    for column, matches, kind in KIND_RULES:
        if values[column] in matches:
            return kind
    return DEFAULT_KIND


# What a reader can choose from a card. Media follows the file's format, and code its extension.
EditableKind = Literal["book", "technical", "paper", "conversation", "notes"]
MEDIA_FORMATS = (*AUDIO_EXTENSIONS, "mp4")
FACETS_FROM_READER = "reader"

_FORM_OF_KIND: dict[str, str] = {"paper": "paper", "conversation": "dialogue", "notes": "entries"}
_KIND_FORMS = frozenset(f for column, forms, _ in KIND_RULES if column == "form" for f in forms)


def facets_for_kind(kind: EditableKind, form: str | None) -> dict[str, str]:
    """The form and domain that make `document_kind` answer `kind`, keeping what it can.

    A book or technical document keeps a form of its own (prose, article, reference,
    script); a form that names another kind gives way to the kind's usual shape.
    """
    if kind in _FORM_OF_KIND:
        return {"form": _FORM_OF_KIND[kind]}
    if not form or form in _KIND_FORMS:
        form = "prose" if kind == "book" else "reference"
    return {"form": form, "domain": "general" if kind == "book" else "technical"}


@dataclass(frozen=True)
class Principal:
    """Who a request acts for. `local` is the app's own origin on loopback;
    `device` carries a paired device's token. 0.17.0 hangs the library off this."""

    kind: Literal["local", "device"]
    device_id: str | None = None


LOCAL_PRINCIPAL = Principal(kind="local")


# Stored timestamps


@overload
def as_utc(dt: datetime) -> datetime: ...
@overload
def as_utc(dt: None) -> None: ...
def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite hands DateTime columns back tz-naive; what they hold is UTC."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)
