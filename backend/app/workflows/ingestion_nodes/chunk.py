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

from langchain_text_splitters import RecursiveCharacterTextSplitter
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
from app.workflows.ingestion_nodes._shared import (
    CHUNK_CONFIGS,
    IngestionState,
    _background_tasks,
    _update_stage,
)

logger = logging.getLogger(__name__)


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
        splitter = RecursiveCharacterTextSplitter(chunk_size=300, chunk_overlap=75)
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
    cfg = CHUNK_CONFIGS["book"]
    # Smart splitting: try paragraphs, then sentences, then words.
    splitter = RecursiveCharacterTextSplitter(
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
                heading=s.get("heading", "") or f"Section {s_idx + 1}",
                level=s.get("level", 1),
                page_start=s.get("page_start", 0),
                page_end=s.get("page_end", 0),
                section_order=s_idx,
                preview=s.get("text", "")[:10000],
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
            context_header = f"[{book_title} > {section_heading}] "

            # populate pdf_page_number for PDF-format documents (1-based page).
            # Use \f (form feed) markers inserted by book_parser to compute per-chunk
            # page numbers instead of assigning the section start page to every chunk.
            section_page_start = s.get("page_start", 0) or (1 if is_pdf else 0)

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
                ff_clean_positions = []
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

                # Inject context into the text that will be embedded/indexed
                enriched_text = context_header + raw_chunk_text
                chunk_id = str(uuid.uuid4())
                chunk_models.append(
                    ChunkModel(
                        id=chunk_id,
                        document_id=doc_id,
                        section_id=section_model.id,
                        text=enriched_text,
                        token_count=len(enriched_text.split()),
                        page_number=s.get("page_start", 0),
                        speaker=None,
                        chunk_index=chunk_idx,
                        pdf_page_number=chunk_pdf_page,
                    )
                )
                chunks.append(
                    {
                        "id": chunk_id,
                        "document_id": doc_id,
                        "text": enriched_text,
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


async def _chunk_tech_book(state: IngestionState, pd: dict | None, doc_id: str) -> IngestionState:
    """Tech-book chunking: prose splits normally; code blocks are atomic (never sub-split).

    For each section:
    1. Detect fenced (```) and indented code blocks.
    2. Emit each code block as one atomic ChunkModel with has_code=True.
    3. Split surrounding prose with RecursiveCharacterTextSplitter.
    4. Store extracted code blocks in CodeSnippetModel with language and AST signature.
    """


    content_type = state.get("content_type") or "tech_book"
    cfg = CHUNK_CONFIGS.get(content_type, CHUNK_CONFIGS["tech_book"])

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
                heading=s.get("heading", "") or f"Section {s_idx + 1}",
                level=s.get("level", 2),
                page_start=s.get("page_start", 0),
                page_end=s.get("page_end", 0),
                section_order=s_idx,
                preview=s.get("text", "")[:10000],
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

            context_header = f"[{doc_title} > {section_model.heading}] "
            # pdf_page_number for this section (None for non-PDF)
            section_pdf_page: int | None = None
            if tech_fmt == "pdf":
                section_pdf_page = s.get("page_start", 0) or 1  # ensure at least page 1

            for chunk_dict in chunk_mixed_content(
                section_text,
                section_model.id,
                doc_id,
                cfg["chunk_size"],
                cfg["chunk_overlap"],
            ):
                chunk_id = str(uuid.uuid4())
                # Inject context header for semantic richness (same as book chunking)
                enriched_text = context_header + chunk_dict["text"]
                chunk_model = ChunkModel(
                    id=chunk_id,
                    document_id=doc_id,
                    section_id=section_model.id,
                    text=enriched_text,
                    token_count=len(enriched_text.split()),
                    page_number=s.get("page_start", 0),
                    speaker=None,
                    chunk_index=chunk_idx,
                    has_code=chunk_dict["has_code"],
                    code_language=chunk_dict["code_language"],
                    code_signature=chunk_dict["code_signature"],
                    pdf_page_number=section_pdf_page,
                )
                chunk_models.append(chunk_model)
                chunks.append(
                    {
                        "id": chunk_id,
                        "document_id": doc_id,
                        "text": enriched_text,
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
                    heading=s.get("heading", "") or f"Part {s_idx + 1}",
                    level=s.get("level", 1),
                    page_start=s.get("page_start", 0),
                    page_end=s.get("page_end", 0),
                    section_order=s_idx,
                    preview=s.get("text", "")[:10000],
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
                preview=raw_text[:10000],
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
            cfg = CHUNK_CONFIGS["conversation"]
            splitter = RecursiveCharacterTextSplitter(
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
                    chunk_models: list[ChunkModel] = []
                    for c in audio_chunks:
                        chunk_models.append(
                            ChunkModel(
                                id=c["id"],
                                document_id=doc_id,
                                section_id=None,
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

            cfg = CHUNK_CONFIGS.get(content_type, CHUNK_CONFIGS["notes"])
            splitter = RecursiveCharacterTextSplitter(
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
                        heading=s.get("heading", "") or f"Section {s_idx + 1}",
                        level=s.get("level", 1),
                        page_start=s.get("page_start", 0),
                        page_end=s.get("page_end", 0),
                        section_order=s_idx,
                        preview=s.get("text", "")[:10000],
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

                    chunk_pdf_page: int | None = None
                    if fmt == "pdf":
                        chunk_pdf_page = s.get("page_start", 0) or 1

                    for text in splitter.split_text(section_text):
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
        except Exception as exc:
            logger.error("chunk_node failed", exc_info=exc)
            return {**state, "status": "error", "error": str(exc)}


