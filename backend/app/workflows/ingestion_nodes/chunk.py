"""The chunker family: chunk_node + content-type-specific chunkers.

chunk_node is the dispatcher. Based on `content_type` it delegates to
one of:
- _chunk_book           books / EPUBs / kindle clippings / notes / papers
- _chunk_tech_book      technical books with fenced code + numbered headings
- _chunk_conversation   conversation transcripts with speaker turns
- audio path            uses pre-built `_audio_chunks` from transcribe_node
- _chunk_code_file      source-code files (function/class granularity via CodeParser)

Each chunker writes ChunkModel rows (and CodeSnippetModel for code) and
returns an updated IngestionState. The shared chunker contract is:
populate `state["chunks"]` with dicts that have `id`, `document_id`,
`text`, `index`, plus optional section/page metadata.
"""

import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy import update as _update

from app.database import get_session_factory
from app.models import ChunkModel, CodeSnippetModel, DocumentModel, SectionModel
from app.services.code_parser import get_code_parser
from app.services.conversation_chunker import ConversationChunker
from app.services.learning_objective_extractor import LearningObjectiveExtractorService
from app.services.tech_book_chunker import chunk_mixed_content
from app.services.tech_section_parser import (
    assign_parent_headings_dicts,
    detect_admonition,
    is_objective_candidate,
)
from app.telemetry import trace_ingestion_node
from app.types import DocumentProfile, chunk_config_for_form
from app.workflows.ingestion_nodes._shared import (
    IngestionState,
    _background_tasks,
    _update_stage,
)

logger = logging.getLogger(__name__)

# `preview` is a bounded snippet; reading text lives in `body`, uncapped (I-29).
PREVIEW_CHARS = 10000


def _context_header(doc_title: str, section_heading: str) -> str:
    """Retrieval breadcrumb prepended to every chunk.

    A section may carry no heading (I-30); the document name alone avoids a
    dangling separator that would tokenise as content.
    """
    heading = (section_heading or "").strip()
    return f"[{doc_title} > {heading}]" if heading else f"[{doc_title}]"


def _splitter_cls():
    """Import lazily: `langchain_text_splitters` pulls in sentence-transformers
    and therefore torch at module scope, which cost 5.4s of every cold start
    for something only used once a document is being chunked."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: PLC0415

    return RecursiveCharacterTextSplitter



async def _run_objective_extraction(doc_id: str, sections: list[tuple[str, str, str]]) -> None:
    """Background task: extract and store learning objectives for qualifying sections.

    sections is a list of (section_id, section_heading, section_text) tuples.
    Non-fatal: failure is logged and does not interrupt ingestion.
    """

    extractor = LearningObjectiveExtractorService()
    # Accumulate all extracted objectives first, then store in a single transaction
    # to avoid successive store() calls overwriting each other's rows.
    all_section_objectives: list[tuple[str, list[str]]] = []
    for section_id, section_heading, section_text in sections:
        objectives = await extractor.extract(doc_id, section_id, section_heading, section_text)
        if objectives:
            all_section_objectives.append((section_id, objectives))
            logger.info(
                "Objectives extracted for section",
                extra={"doc_id": doc_id, "section_id": section_id, "count": len(objectives)},
            )
    if all_section_objectives:
        await extractor.store_all(doc_id, all_section_objectives)


def _chunk_code_file(raw_text: str, file_path: str, doc_id: str) -> tuple[list[dict], list[dict]]:
    """Parse a code file into function/class chunks using CodeParser.

    Returns (chunks_for_db, definitions_with_metadata) where definitions include
    function_name, start_line, end_line for call-graph extraction.
    """

    parser = get_code_parser()
    lang = parser.detect_language(file_path) or "python"
    definitions = parser.parse_file(raw_text, lang, file_path)

    chunks: list[dict] = []
    chunk_metas: list[dict] = []
    for idx, defn in enumerate(definitions):
        # Prepend metadata header to chunk text for retrieval context
        header = (
            f"# {defn['kind']}: {defn['name']}"
            f" | language: {defn['language']}"
            f" | file: {file_path}"
            f" | lines: {defn['start_line']}-{defn['end_line']}\n"
        )
        text = header + defn["body_text"]
        chunk_id = str(uuid.uuid4())
        chunks.append({"id": chunk_id, "text": text, "index": idx})
        chunk_metas.append(
            {
                "chunk_id": chunk_id,
                "function_name": defn["name"] if defn["kind"] == "function" else None,
                "class_name": defn["name"] if defn["kind"] == "class" else None,
                "start_line": defn["start_line"],
                "end_line": defn["end_line"],
                "language": defn["language"],
                "file_path": file_path,
                "body_text": defn["body_text"],
                "kind": defn["kind"],
            }
        )

    # Fallback: if no definitions parsed, use text splitter
    if not chunks:
        splitter = _splitter_cls()(chunk_size=300, chunk_overlap=75)
        for idx, t in enumerate(splitter.split_text(raw_text)):
            chunk_id = str(uuid.uuid4())
            chunks.append({"id": chunk_id, "text": t, "index": idx})
            chunk_metas.append({})

    return chunks, chunk_metas


async def _chunk_book(state: IngestionState, pd: dict | None, doc_id: str) -> IngestionState:
    """Book-specific chunking: process each section independently with context injection.

    Implements Hybrid Contextual strategy:
    1. Structural Splitting: Paragraph-first, then sentence, then characters.
    2. Context Injection: Prepend [Book Title > Chapter] to every chunk text.
    3. Cross-Boundary Protection: No chunk crosses a section (chapter) boundary.
    """
    cfg = chunk_config_for_form("prose")
    # Smart splitting: try paragraphs, then sentences, then words.
    splitter = _splitter_cls()(
        chunk_size=cfg["chunk_size"],
        chunk_overlap=cfg["chunk_overlap"],
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    async with get_session_factory()() as session:
        # Fetch book title for context injection
        doc_result = await session.execute(
            select(DocumentModel.title).where(DocumentModel.id == doc_id)
        )
        book_title = doc_result.scalar_one_or_none() or "Unknown Book"

        raw_sections = pd["sections"] if pd else []
        if not raw_sections:
            raw_text = pd["raw_text"] if pd else ""
            raw_sections = [
                {
                    "heading": "Full Text",
                    "level": 1,
                    "text": raw_text,
                    "page_start": 0,
                    "page_end": 0,
                }
            ]

        section_models: list[SectionModel] = []
        for s_idx, s in enumerate(raw_sections):
            section_model = SectionModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                heading=s.get("heading", ""),
                level=s.get("level", 1),
                page_start=s.get("page_start", 0),
                page_end=s.get("page_end", 0),
                section_order=s_idx,
                body=s.get("text", ""),
                preview=s.get("text", "")[:PREVIEW_CHARS],
            )
            session.add(section_model)
            section_models.append(section_model)

        await session.flush()

        chunks: list[dict] = []
        chunk_idx = 0
        chunk_models: list[ChunkModel] = []
        is_pdf = state.get("format", "").lower() == "pdf"
        for section_model, s in zip(section_models, raw_sections, strict=False):
            section_text = s.get("text", "")
            if not section_text.strip():
                continue

            section_heading = section_model.heading
            context_header = _context_header(book_title, section_heading)

            # populate pdf_page_number for PDF-format documents (1-based page).
            # Use \f (form feed) markers inserted by book_parser to compute per-chunk
            # page numbers instead of assigning the section start page to every chunk.
            section_page_start = s.get("page_start", 0) or (1 if is_pdf else 0)
            book_page_labels: dict = (pd.get("page_labels") if pd else None) or {}

            # Strip \f from the text used for splitting (it's a control char, not content),
            # but first compute page-break positions in clean-text coordinates.
            if is_pdf and "\f" in section_text:
                # Convert \f positions from original-text coords to clean-text coords.
                # Original pos `fp` maps to clean pos `fp - n` where n = count of \f before it.
                ff_clean_positions: list[int] = []
                for i, ch in enumerate(section_text):
                    if ch == "\f":
                        ff_clean_positions.append(i - len(ff_clean_positions))
                clean_section_text = section_text.replace("\f", "")
            else:
                # No form feeds: this section came from DocumentParser, which
                # records page starts as offsets instead of inserting markers.
                # They are already in this text's coordinates, so they slot
                # straight into the same counting below. Without this the book
                # path degrades exactly like the technical one used to -- every
                # chunk claiming the page its section opened on, measured as 26
                # sections over 26 distinct pages across 3,425 chunks.
                ff_clean_positions = list(s.get("page_breaks") or [])
                clean_section_text = section_text

            # Track search position to handle overlapping chunks correctly
            search_start = 0
            for raw_chunk_text in splitter.split_text(clean_section_text):
                # Compute per-chunk PDF page from \f positions
                chunk_pdf_page: int | None = None
                if is_pdf:
                    pos = clean_section_text.find(raw_chunk_text[:80], search_start)
                    if pos >= 0:
                        # Count how many page breaks occur before this chunk's start
                        ff_before = sum(1 for fp in ff_clean_positions if fp <= pos)
                        chunk_pdf_page = section_page_start + ff_before
                        search_start = pos  # allow overlap
                    else:
                        chunk_pdf_page = section_page_start

                # text stays clean; the header rides in context_header (FTS +
                # display), never the embedding -- see ChunkModel.context_header.
                chunk_id = str(uuid.uuid4())
                chunk_models.append(
                    ChunkModel(
                        id=chunk_id,
                        document_id=doc_id,
                        section_id=section_model.id,
                        text=raw_chunk_text,
                        token_count=len(raw_chunk_text.split()),
                        page_number=s.get("page_start", 0),
                        speaker=None,
                        chunk_index=chunk_idx,
                        pdf_page_number=chunk_pdf_page,
                        pdf_page_label=_printed_label_for(book_page_labels, chunk_pdf_page),
                        context_header=context_header,
                    )
                )
                chunks.append(
                    {
                        "id": chunk_id,
                        "document_id": doc_id,
                        "text": raw_chunk_text,
                        "index": chunk_idx,
                    }
                )
                chunk_idx += 1

        session.add_all(chunk_models)
        await session.execute(
            _update(DocumentModel)
            .where(DocumentModel.id == doc_id)
            .values(chapter_count=len(section_models))
        )
        await session.commit()

    logger.info(
        "Hybrid Book chunking complete",
        extra={
            "doc_id": doc_id,
            "num_chunks": len(chunks),
            "context_injected": True,
            "chapter_count": len(section_models),
        },
    )
    return {**state, "chunks": chunks, "status": "embedding"}


class _SectionPageCursor:
    """Per-chunk PDF page within one section, advanced as chunks are emitted.

    Four chunking paths need this and three of them assigned the section's start
    page to every chunk in it, which is why a citation into a long chapter named
    the page the chapter opened on -- measured at 2,329 chunks all claiming one
    page. Chunks are emitted in order, so the search cursor only moves forward
    and repeated text later in the section cannot drag the page backwards.
    """

    def __init__(self, section_text: str, page_start: int | None, page_breaks: list[int]):
        self._text = section_text
        self._start = page_start
        self._breaks = page_breaks
        self._cursor = 0

    def page_for(self, chunk_text: str) -> int | None:
        if self._start is None:
            return None
        if not self._breaks:
            return self._start
        probe = chunk_text[:80]
        position = self._text.find(probe, self._cursor) if probe else -1
        if position < 0:
            # Some paths rewrite chunk text, so it cannot always be located.
            # The section's page is imprecise; a wrong page is worse.
            return self._start
        self._cursor = position
        return self._start + sum(1 for offset in self._breaks if offset <= position)


def _printed_label_for(page_labels: dict, page: int | None) -> str | None:
    """The number printed on a sheet, when the PDF says it differs.

    Keys survive the pipeline state as strings on one path and integers on
    another, so both are tried rather than depending on which serialiser ran.
    """
    if page is None or not page_labels:
        return None
    label = page_labels.get(page) or page_labels.get(str(page))
    return str(label) if label else None


async def _chunk_tech_book(state: IngestionState, pd: dict | None, doc_id: str) -> IngestionState:
    """Tech-book chunking: prose splits normally; code blocks are atomic (never sub-split).

    For each section:
    1. Detect fenced (```) and indented code blocks.
    2. Emit each code block as one atomic ChunkModel with has_code=True.
    3. Split surrounding prose with RecursiveCharacterTextSplitter.
    4. Store extracted code blocks in CodeSnippetModel with language and AST signature.
    """


    content_type = state.get("content_type") or "tech_book"
    cfg = DocumentProfile.from_legacy(content_type, state.get("is_technical")).chunk_config

    async with get_session_factory()() as session:
        doc_result = await session.execute(
            select(DocumentModel.title).where(DocumentModel.id == doc_id)
        )
        doc_title = doc_result.scalar_one_or_none() or "Unknown"

        raw_sections = pd["sections"] if pd else []
        if not raw_sections:
            raw_text = pd["raw_text"] if pd else ""
            raw_sections = [
                {
                    "heading": "Full Text",
                    "level": 1,
                    "text": raw_text,
                    "page_start": 0,
                    "page_end": 0,
                }
            ]

        # Enrich section dicts with level, parent_heading, and admonition_type
        assign_parent_headings_dicts(raw_sections)
        for s in raw_sections:
            s["admonition_type"] = detect_admonition(s.get("text", ""))

        section_models: list[SectionModel] = []
        for s_idx, s in enumerate(raw_sections):
            section_model = SectionModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                heading=s.get("heading", ""),
                level=s.get("level", 2),
                page_start=s.get("page_start", 0),
                page_end=s.get("page_end", 0),
                section_order=s_idx,
                body=s.get("text", ""),
                preview=s.get("text", "")[:PREVIEW_CHARS],
                admonition_type=s.get("admonition_type"),
                parent_section_id=None,  # resolved after flush below
            )
            session.add(section_model)
            section_models.append(section_model)

        await session.flush()

        # Resolve parent_section_id: build heading->id map, then update
        heading_to_id: dict[str, str] = {sm.heading: sm.id for sm in section_models}
        for s, sm in zip(raw_sections, section_models, strict=False):
            ph = s.get("parent_heading")
            if ph:
                sm.parent_section_id = heading_to_id.get(ph)
        await session.flush()

        chunks: list[dict] = []
        chunk_idx = 0
        chunk_models: list[ChunkModel] = []
        snippet_models: list[CodeSnippetModel] = []

        # populate pdf_page_number for PDF-format documents (1-based page)
        tech_fmt = state.get("format", "").lower()

        for section_model, s in zip(section_models, raw_sections, strict=False):
            section_text = s.get("text", "")
            if not section_text.strip():
                continue

            context_header = _context_header(doc_title, section_model.heading)
            # pdf_page_number for this section (None for non-PDF)
            section_pdf_page: int | None = None
            if tech_fmt == "pdf":
                section_pdf_page = s.get("page_start", 0) or 1  # ensure at least page 1
            # Offsets recorded by the parser where each later page begins. The
            # book path already computes a per-chunk page; this path assigned the
            # section's start page to every chunk in it, which on one library
            # meant every section of every PDF reported one page -- 2,329 chunks
            # all claiming p167 -- so a citation landed wherever the chapter
            # began rather than where its sentence is.
            page_breaks: list[int] = s.get("page_breaks") or []
            page_search_start = 0
            # Sheet -> printed page. Keyed by string after a round trip through
            # the pipeline state, which JSON-encodes integer keys.
            page_labels: dict = (pd.get("page_labels") if pd else None) or {}

            for chunk_dict in chunk_mixed_content(
                section_text,
                section_model.id,
                doc_id,
                cfg["chunk_size"],
                cfg["chunk_overlap"],
            ):
                chunk_id = str(uuid.uuid4())
                # text stays clean; header rides in context_header (FTS/display),
                # kept out of the embedding -- see ChunkModel.context_header.
                clean_text = chunk_dict["text"]
                chunk_pdf_page = section_pdf_page
                if section_pdf_page is not None and page_breaks:
                    probe = clean_text[:80]
                    pos = section_text.find(probe, page_search_start) if probe else -1
                    if pos >= 0:
                        # Falls back to the section's page when the chunk cannot be
                        # located -- mixed-content chunking rewrites some text, and
                        # a wrong page is worse than an imprecise one.
                        chunk_pdf_page = section_pdf_page + sum(
                            1 for offset in page_breaks if offset <= pos
                        )
                        page_search_start = pos
                chunk_page_label = _printed_label_for(page_labels, chunk_pdf_page)
                chunk_model = ChunkModel(
                    id=chunk_id,
                    document_id=doc_id,
                    section_id=section_model.id,
                    text=clean_text,
                    token_count=len(clean_text.split()),
                    page_number=s.get("page_start", 0),
                    speaker=None,
                    chunk_index=chunk_idx,
                    has_code=chunk_dict["has_code"],
                    code_language=chunk_dict["code_language"],
                    code_signature=chunk_dict["code_signature"],
                    pdf_page_number=chunk_pdf_page,
                    pdf_page_label=chunk_page_label,
                    context_header=context_header,
                )
                chunk_models.append(chunk_model)
                chunks.append(
                    {
                        "id": chunk_id,
                        "document_id": doc_id,
                        "text": clean_text,
                        "index": chunk_idx,
                    }
                )
                chunk_idx += 1

                if chunk_dict["is_code_block"]:
                    snippet_models.append(
                        CodeSnippetModel(
                            id=str(uuid.uuid4()),
                            document_id=doc_id,
                            chunk_id=chunk_id,
                            section_id=section_model.id,
                            language=chunk_dict["code_language"],
                            signature=chunk_dict["code_signature"],
                            content=chunk_dict["text"],
                        )
                    )

        session.add_all(chunk_models)
        await session.flush()
        session.add_all(snippet_models)
        await session.execute(
            _update(DocumentModel)
            .where(DocumentModel.id == doc_id)
            .values(chapter_count=len(section_models))
        )
        await session.commit()

    # Fire-and-forget objective extraction for qualifying sections
    qualifying_sections = [
        (sm.id, sm.heading, s.get("text", ""))
        for sm, s in zip(section_models, raw_sections, strict=False)
        if is_objective_candidate(s.get("text", ""))
    ]
    if qualifying_sections:
        task = asyncio.create_task(_run_objective_extraction(doc_id, qualifying_sections))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    logger.info(
        "Tech-book chunking complete",
        extra={
            "doc_id": doc_id,
            "num_chunks": len(chunks),
            "num_snippets": len(snippet_models),
            "content_type": content_type,
        },
    )
    return {**state, "chunks": chunks, "status": "embedding"}


async def _chunk_conversation(
    state: IngestionState, pd: dict | None, doc_id: str
) -> IngestionState:
    """Conversation-specific chunking: speaker-turn chunks with speaker field populated.

    Uses ConversationChunker.detect() to decide whether to use speaker-aware
    chunking or fall back to RecursiveCharacterTextSplitter.  After chunking,
    extracts roster + timeline and writes them to DocumentModel.conversation_metadata.

    Creates SectionModel rows so the Read view can display conversation content.
    """


    raw_text = (pd["raw_text"] if pd else "") or ""
    raw_sections = pd["sections"] if pd else []
    chunker = ConversationChunker()

    chunks: list[dict] = []
    async with get_session_factory()() as session:
        chunk_models: list[ChunkModel] = []

        # -- Create SectionModel rows from parsed sections so the Read view works --
        section_models: list[SectionModel] = []
        if raw_sections:
            for s_idx, s in enumerate(raw_sections):
                section_model = SectionModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    heading=s.get("heading", ""),
                    level=s.get("level", 1),
                    page_start=s.get("page_start", 0),
                    page_end=s.get("page_end", 0),
                    section_order=s_idx,
                    body=s.get("text", ""),
                    preview=s.get("text", "")[:PREVIEW_CHARS],
                )
                session.add(section_model)
                section_models.append(section_model)
        else:
            # No parsed sections -- create a single section from raw_text
            section_model = SectionModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                heading="Conversation",
                level=1,
                page_start=0,
                page_end=0,
                section_order=0,
                body=raw_text,
                preview=raw_text[:PREVIEW_CHARS],
            )
            session.add(section_model)
            section_models.append(section_model)

        await session.flush()

        if chunker.detect(raw_text):
            conv_chunks = chunker.chunk(raw_text)
            for idx, cc in enumerate(conv_chunks):
                chunk_id = str(uuid.uuid4())
                chunk_models.append(
                    ChunkModel(
                        id=chunk_id,
                        document_id=doc_id,
                        section_id=None,
                        text=cc.text,
                        token_count=len(cc.text) // 4,
                        page_number=0,
                        speaker=cc.speaker,
                        chunk_index=idx,
                    )
                )
                chunks.append(
                    {"id": chunk_id, "document_id": doc_id, "text": cc.text, "index": idx}
                )
            # Extract metadata
            roster = chunker.extract_roster(conv_chunks)
            timeline = chunker.extract_timeline(raw_text)
            conversation_metadata = {**roster, **timeline}
        else:
            # Fallback: plain text splitter (no speaker detection)
            cfg = chunk_config_for_form("dialogue")
            splitter = _splitter_cls()(
                chunk_size=cfg["chunk_size"], chunk_overlap=cfg["chunk_overlap"]
            )
            all_texts = [s["text"] for s in raw_sections if s["text"]]
            raw_chunks_text = splitter.split_text("\n\n".join(all_texts) or raw_text)
            for idx, text in enumerate(raw_chunks_text):
                chunk_id = str(uuid.uuid4())
                chunk_models.append(
                    ChunkModel(
                        id=chunk_id,
                        document_id=doc_id,
                        section_id=None,
                        text=text,
                        token_count=len(text.split()),
                        page_number=0,
                        speaker=None,
                        chunk_index=idx,
                    )
                )
                chunks.append({"id": chunk_id, "document_id": doc_id, "text": text, "index": idx})
            conversation_metadata = {
                "speakers": [],
                "total_turns": 0,
                "has_timestamps": False,
                "first_timestamp": None,
                "last_timestamp": None,
            }
        session.add_all(chunk_models)

        await session.execute(
            _update(DocumentModel)
            .where(DocumentModel.id == doc_id)
            .values(conversation_metadata=conversation_metadata)
        )
        await session.commit()

    logger.info(
        "Conversation chunked",
        extra={
            "doc_id": doc_id,
            "num_chunks": len(chunks),
            "num_sections": len(section_models),
            "speaker_count": len(conversation_metadata.get("speakers", [])),
        },
    )
    return {**state, "chunks": chunks, "status": "embedding"}



async def chunk_node(state: IngestionState) -> IngestionState:
    logger.debug("node_start", extra={"node": "chunk", "doc_id": state["document_id"]})
    await _update_stage(state["document_id"], "chunking")
    with trace_ingestion_node("chunk", state):
        try:
            pd = state["parsed_document"]
            content_type = state["content_type"] or "notes"
            doc_id = state["document_id"]
            file_path = state["file_path"]

            if content_type in ("audio", "video"):
                audio_chunks = state.get("_audio_chunks") or []
                chunks = []
                async with get_session_factory()() as session:
                    # A transcript needs sections like any other document. This
                    # branch alone wrote chunks with section_id=None and created
                    # none, so `GET /sections/{id}/content` returned [] and the
                    # reader showed "No content available" for a document whose
                    # whole transcript was sitting in chunks -- retrievable and
                    # unreadable. The orphan-chunk fallback in sections.py could
                    # not cover it either: that fires when sections exist but are
                    # empty, and here there were none at all.
                    #
                    # One section per transcript chunk, and the heading stays
                    # empty: nobody wrote one. I-30 -- a heading is a label the
                    # source authored, and a timestamp dressed up as one would
                    # be this pipeline inventing structure it was not given.
                    section_models: list[SectionModel] = []
                    for order, c in enumerate(audio_chunks):
                        section_models.append(
                            SectionModel(
                                id=str(uuid.uuid4()),
                                document_id=doc_id,
                                heading="",
                                level=1,
                                page_start=0,
                                page_end=0,
                                section_order=order,
                                body=c["text"],
                                preview=c["text"][:PREVIEW_CHARS],
                            )
                        )
                    session.add_all(section_models)
                    await session.flush()

                    chunk_models: list[ChunkModel] = []
                    for c, section in zip(audio_chunks, section_models, strict=True):
                        chunk_models.append(
                            ChunkModel(
                                id=c["id"],
                                document_id=doc_id,
                                section_id=section.id,
                                text=c["text"],
                                token_count=len(c["text"].split()),
                                page_number=0,
                                speaker=None,
                                chunk_index=c["index"],
                            )
                        )
                        chunks.append(
                            {
                                "id": c["id"],
                                "document_id": doc_id,
                                "text": c["text"],
                                "index": c["index"],
                                "start_time": c["start_time"],
                                "end_time": c["end_time"],
                            }
                        )
                    session.add_all(chunk_models)
                    await session.commit()
                logger.info(
                    "%s chunked",
                    content_type,
                    extra={"doc_id": doc_id, "num_chunks": len(chunks)},
                )
                return {**state, "chunks": chunks, "status": "embedding"}

            if content_type == "code":
                raw_text = pd["raw_text"] if pd else ""
                raw_chunks, code_metas = _chunk_code_file(raw_text, file_path, doc_id)
                chunks = []
                async with get_session_factory()() as session:
                    chunk_models: list[ChunkModel] = []
                    for idx, (rc, meta) in enumerate(zip(raw_chunks, code_metas, strict=False)):
                        chunk_models.append(
                            ChunkModel(
                                id=rc["id"],
                                document_id=doc_id,
                                section_id=None,
                                text=rc["text"],
                                token_count=len(rc["text"].split()),
                                page_number=meta.get("start_line", 0),
                                speaker=None,
                                chunk_index=idx,
                            )
                        )
                        chunks.append(
                            {
                                "id": rc["id"],
                                "document_id": doc_id,
                                "text": rc["text"],
                                "index": idx,
                                **{k: v for k, v in meta.items() if k != "chunk_id"},
                            }
                        )
                    session.add_all(chunk_models)
                    await session.commit()
                logger.info(
                    "Code chunked document",
                    extra={"doc_id": doc_id, "num_chunks": len(chunks)},
                )
                return {**state, "chunks": chunks, "status": "embedding"}

            if content_type in ("tech_book", "tech_article"):
                return await _chunk_tech_book(state, pd, doc_id)

            if content_type == "book":
                return await _chunk_book(state, pd, doc_id)

            if content_type == "conversation":
                return await _chunk_conversation(state, pd, doc_id)

            if content_type == "paper":
                return await _chunk_paper(state, pd, doc_id)

            return await _chunk_generic(state, pd, doc_id, content_type)
        except Exception as exc:
            logger.exception("chunk_node failed", exc_info=exc)
            return {**state, "status": "error", "error": str(exc)}


async def _chunk_paper(state: IngestionState, pd: dict | None, doc_id: str) -> IngestionState:
    """Research-paper chunking: captions atomic, figure internals and reference
    lists kept out of the index, prose split sentence-aware.

    Falls back to generic chunking when the document does not present recognisable
    paper structure, or on any failure -- a paper that ingests imperfectly beats
    one that does not ingest at all.
    """
    from app.services.paper_chunker import (  # noqa: PLC0415
        chunk_paper_section,
        is_references_heading,
        looks_like_paper,
    )

    raw_sections = (pd["sections"] if pd else []) or []
    if not looks_like_paper(raw_sections):
        logger.info(
            "Paper structure not recognised; using generic chunking",
            extra={"doc_id": doc_id, "num_sections": len(raw_sections)},
        )
        return await _chunk_generic(state, pd, doc_id, "paper")

    try:
        cfg = chunk_config_for_form("paper")
        chunks: list[dict] = []
        async with get_session_factory()() as session:
            doc_result = await session.execute(
                select(DocumentModel.title).where(DocumentModel.id == doc_id)
            )
            paper_title = doc_result.scalar_one_or_none() or "Unknown Paper"

            section_models: list[SectionModel] = []
            for s_idx, s in enumerate(raw_sections):
                section_model = SectionModel(
                    id=str(uuid.uuid4()),
                    document_id=doc_id,
                    heading=s.get("heading", ""),
                    level=s.get("level", 1),
                    page_start=s.get("page_start", 0),
                    page_end=s.get("page_end", 0),
                    section_order=s_idx,
                    body=s.get("text", ""),
                    preview=s.get("text", "")[:PREVIEW_CHARS],
                )
                session.add(section_model)
                section_models.append(section_model)
            await session.flush()

            chunk_models: list[ChunkModel] = []
            chunk_idx = 0
            is_pdf = state.get("format", "").lower() == "pdf"
            skipped_reference_sections = 0

            for section_model, s in zip(section_models, raw_sections, strict=False):
                section_text = s.get("text", "")
                if not section_text.strip():
                    continue

                # Reference lists stay readable as a section but are not indexed:
                # they are author/venue strings that dilute both vector and BM25
                # results without ever being the answer to a question.
                if is_references_heading(section_model.heading):
                    skipped_reference_sections += 1
                    continue

                context_header = _context_header(paper_title, section_model.heading)
                pages = _SectionPageCursor(
                    section_text,
                    (s.get("page_start", 0) or 1) if is_pdf else None,
                    s.get("page_breaks") or [],
                )
                paper_page_labels: dict = (pd.get("page_labels") if pd else None) or {}

                for text in chunk_paper_section(
                    section_text, cfg["chunk_size"], cfg["chunk_overlap"]
                ):
                    chunk_pdf_page = pages.page_for(text)
                    chunk_id = str(uuid.uuid4())
                    chunk_models.append(
                        ChunkModel(
                            id=chunk_id,
                            document_id=doc_id,
                            section_id=section_model.id,
                            text=text,
                            token_count=len(text.split()),
                            page_number=s.get("page_start", 0),
                            speaker=None,
                            chunk_index=chunk_idx,
                            pdf_page_number=chunk_pdf_page,
                            pdf_page_label=_printed_label_for(
                                paper_page_labels, chunk_pdf_page
                            ),
                            context_header=context_header,
                        )
                    )
                    chunks.append(
                        {
                            "id": chunk_id,
                            "document_id": doc_id,
                            "text": text,
                            "index": chunk_idx,
                        }
                    )
                    chunk_idx += 1

            session.add_all(chunk_models)
            await session.commit()

        logger.info(
            "Paper chunking complete",
            extra={
                "doc_id": doc_id,
                "num_chunks": len(chunks),
                "num_sections": len(section_models),
                "skipped_reference_sections": skipped_reference_sections,
            },
        )
        return {**state, "chunks": chunks, "status": "embedding"}
    except Exception as exc:
        logger.warning(
            "Paper chunking failed; falling back to generic chunking",
            exc_info=exc,
            extra={"doc_id": doc_id},
        )
        return await _chunk_generic(state, pd, doc_id, "paper")


async def _chunk_generic(
    state: IngestionState, pd: dict | None, doc_id: str, content_type: str
) -> IngestionState:
    """Section-aware chunking with the default splitter.

    Also the fallback for content types with a specialised chunker, so an
    unrecognised or malformed document still ingests instead of failing.
    """
    cfg = DocumentProfile.from_legacy(content_type, state.get("is_technical")).chunk_config
    splitter = _splitter_cls()(
        chunk_size=cfg["chunk_size"], chunk_overlap=cfg["chunk_overlap"]
    )
    chunks = []
    async with get_session_factory()() as session:
        raw_sections = pd["sections"] if pd else []
        if not raw_sections:
            raw_text = pd["raw_text"] if pd else ""
            raw_sections = [
                {
                    "heading": "Full Text",
                    "level": 1,
                    "text": raw_text,
                    "page_start": 0,
                    "page_end": 0,
                }
            ]

        section_models: list[SectionModel] = []
        for s_idx, s in enumerate(raw_sections):
            section_model = SectionModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                heading=s.get("heading", ""),
                level=s.get("level", 1),
                page_start=s.get("page_start", 0),
                page_end=s.get("page_end", 0),
                section_order=s_idx,
                body=s.get("text", ""),
                preview=s.get("text", "")[:PREVIEW_CHARS],
            )
            session.add(section_model)
            section_models.append(section_model)
        await session.flush()

        chunk_models: list[ChunkModel] = []
        chunk_idx = 0
        fmt = state.get("format", "").lower()

        for section_model, s in zip(section_models, raw_sections, strict=False):
            section_text = s.get("text", "")
            if not section_text.strip():
                continue

            pages = _SectionPageCursor(
                section_text,
                (s.get("page_start", 0) or 1) if fmt == "pdf" else None,
                s.get("page_breaks") or [],
            )
            generic_page_labels: dict = (pd.get("page_labels") if pd else None) or {}

            for text in splitter.split_text(section_text):
                chunk_pdf_page = pages.page_for(text)
                chunk_id = str(uuid.uuid4())
                chunk_models.append(
                    ChunkModel(
                        id=chunk_id,
                        document_id=doc_id,
                        section_id=section_model.id,
                        text=text,
                        token_count=len(text.split()),
                        page_number=s.get("page_start", 0),
                        speaker=None,
                        chunk_index=chunk_idx,
                        pdf_page_number=chunk_pdf_page,
                        pdf_page_label=_printed_label_for(
                            generic_page_labels, chunk_pdf_page
                        ),
                    )
                )
                chunks.append(
                    {
                        "id": chunk_id,
                        "document_id": doc_id,
                        "text": text,
                        "index": chunk_idx,
                    }
                )
                chunk_idx += 1
        session.add_all(chunk_models)
        await session.commit()
    logger.info(
        "Chunked document",
        extra={"doc_id": doc_id, "num_chunks": len(chunks)},
    )
    return {**state, "chunks": chunks, "status": "embedding"}


