import asyncio
import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal, TypedDict

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, START, StateGraph

from app.database import get_session_factory
from app.models import ChunkModel, CodeSnippetModel, SectionModel
from app.services.parser import DocumentParser
from app.telemetry import trace_chain, trace_ingestion_node

logger = logging.getLogger(__name__)

ContentType = Literal[
    "book",
    "conversation",
    "notes",
    "audio",
    "video",
    "epub",
    "kindle_clippings",
    "tech_book",
    "tech_article",
]

_parser = DocumentParser()

CHUNK_CONFIGS: dict[str, dict[str, int]] = {
    "paper": {"chunk_size": 300, "chunk_overlap": 45},
    "book": {"chunk_size": 600, "chunk_overlap": 120},
    "conversation": {"chunk_size": 450, "chunk_overlap": 90},
    "notes": {"chunk_size": 300, "chunk_overlap": 75},
    "code": {"chunk_size": 300, "chunk_overlap": 75},
    "tech_book": {"chunk_size": 500, "chunk_overlap": 80},
    "tech_article": {"chunk_size": 350, "chunk_overlap": 60},
    "epub": {"chunk_size": 600, "chunk_overlap": 120},
    "kindle_clippings": {"chunk_size": 300, "chunk_overlap": 75},
}

STAGE_PROGRESS: dict[str, int] = {
    "parsing": 10,
    "transcribing": 15,
    "classifying": 25,
    "chunking": 40,
    "embedding": 70,
    "indexing": 80,
    "entity_extract": 90,
    "enriching": 95,
    "complete": 100,
    "error": 0,
}


class IngestionState(TypedDict):
    document_id: str
    file_path: str
    format: str
    parsed_document: dict[str, Any] | None
    content_type: str | None
    chunks: list[dict[str, Any]] | None
    status: str
    error: str | None
    section_summary_count: int | None
    audio_duration_seconds: float | None
    _audio_chunks: list[dict[str, Any]] | None


def _classify(
    raw_text: str, sections: list[dict], word_count: int, file_ext: str, filename: str = ""
) -> str:
    if file_ext in ("mp3", "m4a", "wav"):
        return "audio"
    if file_ext == "mp4":
        return "video"
    if file_ext == "epub":
        return "book"

    if file_ext in ("py", "js", "ts", "go", "java", "rs", "cpp", "c", "rb"):
        return "code"
    # Kindle My Clippings.txt detection: filename pattern or content signature
    if re.search(r"clippings", filename, re.IGNORECASE) or re.search(
        r"^==========", raw_text[:2000], re.MULTILINE
    ):
        return "kindle_clippings"
    headings_lower = " ".join(s.get("heading", "").lower() for s in sections)
    text_lower = raw_text[:5000].lower()
    speaker_pattern = re.compile(r"\b[A-Z][a-zA-Z]+:\s")
    if speaker_pattern.search(raw_text[:3000]):
        return "conversation"
    if re.search(r"\b(speaker|interviewer|host|guest):", text_lower):
        return "conversation"
    if re.search(r"\b(abstract|methodology|references|hypothesis)\b", text_lower):
        return "paper"
    if re.search(r"\b(abstract|methodology)\b", headings_lower):
        return "paper"
    # tech_book: >= 3 fenced code blocks (= >= 6 triple-backtick tokens) in first 5000 chars,
    # OR >= 2 numbered section headings (e.g. "1.1", "2.3") in first 5000 chars.
    first_5k = raw_text[:5000]
    code_fence_count = len(re.findall(r"```", first_5k))
    numbered_section_count = len(re.findall(r"\b\d+\.\d+\b", first_5k))
    if code_fence_count >= 6 or numbered_section_count >= 2:
        return "tech_book"
    chapter_count = len(re.findall(r"\bchapter\b", headings_lower))
    if chapter_count >= 2 and word_count > 40000:
        return "book"
    return "notes"


async def _update_stage(document_id: str, stage: str) -> None:
    from sqlalchemy import update

    from app.models import DocumentModel

    async with get_session_factory()() as session:
        await session.execute(
            update(DocumentModel).where(DocumentModel.id == document_id).values(stage=stage)
        )
        await session.commit()


def parse_node(state: IngestionState) -> IngestionState:
    logger.debug("node_start", extra={"node": "parse", "doc_id": state["document_id"]})
    # Audio/video files: DocumentParser cannot handle them; transcribe_node takes over.
    # EPUB and other text-based formats are handled by DocumentParser below.
    if Path(state["file_path"]).suffix.lstrip(".").lower() in ("mp3", "m4a", "wav", "mp4"):
        return {**state, "parsed_document": None, "status": "classifying"}
    with trace_ingestion_node("parse", state):
        try:
            fp = Path(state["file_path"])
            parsed = _parser.parse(fp, state["format"])
            sections = [
                {
                    "heading": s.heading,
                    "level": s.level,
                    "text": s.text,
                    "page_start": s.page_start,
                    "page_end": s.page_end,
                }
                for s in parsed.sections
            ]
            return {
                **state,
                "parsed_document": {
                    "title": parsed.title,
                    "format": parsed.format,
                    "pages": parsed.pages,
                    "word_count": parsed.word_count,
                    "sections": sections,
                    "raw_text": parsed.raw_text,
                },
                "status": "classifying",
            }
        except Exception as exc:
            logger.error("parse_node failed", exc_info=exc)
            return {**state, "status": "error", "error": str(exc)}


async def classify_node(state: IngestionState) -> IngestionState:
    logger.debug("node_start", extra={"node": "classify", "doc_id": state["document_id"]})
    # Fast-path: content_type was provided by the user — skip all heuristics and LLM.
    # Classification only runs for legacy paths where content_type is unknown.
    if state.get("content_type") is not None:
        logger.info(
            "classify_node: skipping (user-provided content_type)",
            extra={"doc_id": state["document_id"], "content_type": state["content_type"]},
        )
        return {**state, "status": "chunking"}
    with trace_ingestion_node("classify", state):
        try:
            pd = state["parsed_document"]
            if pd is None:
                return {**state, "content_type": "notes", "status": "chunking"}
            fp_obj = Path(state["file_path"])
            file_ext = fp_obj.suffix.lstrip(".")
            filename = fp_obj.name
            content_type = _classify(
                pd["raw_text"], pd["sections"], pd["word_count"], file_ext, filename
            )

            # LLM reclassification: heuristic result is uncertain for large documents.
            # 'notes' on a long doc may be book/paper; 'conversation' on a very long doc
            # (>20k words) is likely misclassified — epics/plays have speaker patterns too.
            needs_llm = (content_type == "notes" and pd["word_count"] > 5000) or (
                content_type == "conversation" and pd["word_count"] > 20000
            )
            if needs_llm:
                try:
                    from app.services.llm import get_llm_service

                    snippet = pd["raw_text"][:2000]
                    prompt = (
                        "Classify this document as exactly one of: "
                        "paper, book, conversation, notes, code, tech_book, tech_article.\n"
                        f"Document snippet (first 2000 chars):\n{snippet}\n\n"
                        "Reply with exactly one word from the list above."
                    )
                    llm_result = await get_llm_service().generate(prompt)
                    llm_type = str(llm_result).strip().lower().split()[0]
                    _valid_types = {
                        "paper",
                        "book",
                        "conversation",
                        "notes",
                        "code",
                        "tech_book",
                        "tech_article",
                    }
                    if llm_type in _valid_types:
                        content_type = llm_type
                        logger.info(
                            "LLM reclassified document",
                            extra={
                                "doc_id": state["document_id"],
                                "content_type": content_type,
                            },
                        )
                except Exception as exc:
                    # Expected when Ollama is offline — log the one-line cause only,
                    # not the full traceback (ConnectionRefusedError is not a bug).
                    logger.warning(
                        "LLM reclassification failed, keeping heuristic result: %s",
                        type(exc).__name__,
                    )

            logger.info(
                "Classified document",
                extra={"doc_id": state["document_id"], "content_type": content_type},
            )
            return {**state, "content_type": content_type, "status": "chunking"}
        except Exception as exc:
            logger.error("classify_node failed", exc_info=exc)
            return {**state, "status": "error", "error": str(exc)}


def _chunk_code_file(raw_text: str, file_path: str, doc_id: str) -> tuple[list[dict], list[dict]]:
    """Parse a code file into function/class chunks using CodeParser.

    Returns (chunks_for_db, definitions_with_metadata) where definitions include
    function_name, start_line, end_line for call-graph extraction.
    """
    from app.services.code_parser import get_code_parser  # noqa: PLC0415

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
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy import update as _update

    from app.models import DocumentModel  # noqa: PLC0415

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

            # S146: populate pdf_page_number for PDF-format documents (1-based page).
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
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy import update as _update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415
    from app.services.tech_book_chunker import chunk_mixed_content  # noqa: PLC0415
    from app.services.tech_section_parser import (  # noqa: PLC0415
        assign_parent_headings_dicts,
        detect_admonition,
        is_objective_candidate,
    )

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

        # S146: populate pdf_page_number for PDF-format documents (1-based page)
        tech_fmt = state.get("format", "").lower()

        for section_model, s in zip(section_models, raw_sections, strict=False):
            section_text = s.get("text", "")
            if not section_text.strip():
                continue

            context_header = f"[{doc_title} > {section_model.heading}] "
            # S146: pdf_page_number for this section (None for non-PDF)
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
    from sqlalchemy import update as _update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415
    from app.services.conversation_chunker import ConversationChunker  # noqa: PLC0415

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


def _chunk_audio(
    segments: list[dict],
    doc_id: str,
    window_seconds: float = 60.0,
) -> list[dict]:
    """Group Whisper segments into ~60-second windows.

    Each returned dict has: id, document_id, text, index, start_time, end_time.
    """
    import uuid as _uuid  # noqa: PLC0415

    chunks: list[dict] = []
    bucket_texts: list[str] = []
    bucket_start: float = 0.0
    bucket_end: float = 0.0
    chunk_idx: int = 0

    def _flush(start: float, end: float, texts: list[str]) -> None:
        nonlocal chunk_idx
        if not texts:
            return
        chunks.append(
            {
                "id": str(_uuid.uuid4()),
                "document_id": doc_id,
                "text": " ".join(texts),
                "index": chunk_idx,
                "start_time": start,
                "end_time": end,
            }
        )
        chunk_idx += 1

    for seg in segments:
        if not bucket_texts:
            bucket_start = seg["start"]
        if seg["end"] - bucket_start >= window_seconds and bucket_texts:
            _flush(bucket_start, bucket_end, bucket_texts)
            bucket_texts = []
            bucket_start = seg["start"]
        bucket_texts.append(seg["text"])
        bucket_end = seg["end"]

    _flush(bucket_start, bucket_end, bucket_texts)
    return chunks


async def transcribe_node(state: IngestionState) -> IngestionState:
    """Transcribe audio/video files using faster-whisper.

    For non-audio/video content types this is a pass-through.
    For audio files: calls AudioTranscriber directly.
    For video files: runs ffmpeg to extract audio first, then transcribes.
    Builds parsed_document from segments, writes audio_duration_seconds to
    DocumentModel, stores pre-built _audio_chunks.
    """
    content_type = state.get("content_type")
    if content_type not in ("audio", "video"):
        return state

    doc_id = state["document_id"]
    await _update_stage(doc_id, "transcribing")
    logger.info("transcribe_node: start", extra={"doc_id": doc_id, "content_type": content_type})

    try:
        from sqlalchemy import update as _update  # noqa: PLC0415

        from app.models import DocumentModel  # noqa: PLC0415
        from app.services.audio_transcriber import get_audio_transcriber  # noqa: PLC0415

        fp = Path(state["file_path"])

        # For video: extract audio with ffmpeg before passing to Whisper
        wav_path: Path | None = None
        if content_type == "video":
            if not shutil.which("ffmpeg"):
                return {
                    **state,
                    "status": "error",
                    "error": (
                        "ffmpeg is not installed. Install ffmpeg to ingest video files. "
                        "On macOS: brew install ffmpeg  On Linux: apt install ffmpeg"
                    ),
                }
            wav_path = Path(f"/tmp/{doc_id}_audio.wav")
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(fp),
                "-vn",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                str(wav_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode != 0:
                return {
                    **state,
                    "status": "error",
                    "error": (
                        "ffmpeg audio extraction failed. Ensure the video file is a valid MP4."
                    ),
                }
            transcribe_fp = wav_path
            logger.info(
                "transcribe_node: ffmpeg extracted audio",
                extra={"doc_id": doc_id, "wav": str(wav_path)},
            )
        else:
            transcribe_fp = fp

        transcriber = get_audio_transcriber()
        loop = asyncio.get_running_loop()
        # CPU-bound -- run in thread pool to keep event loop free for status polls
        segments, duration = await loop.run_in_executor(None, transcriber.transcribe, transcribe_fp)

        # Clean up temp wav extracted from video
        if wav_path is not None:
            try:
                wav_path.unlink(missing_ok=True)
            except OSError:
                pass

        raw_text = " ".join(s["text"] for s in segments)
        audio_chunks = _chunk_audio(segments, doc_id)

        # Sections for section_summarize_node: one section per audio window
        sections = [
            {
                "heading": f"Segment {i + 1} ({c['start_time']:.0f}s-{c['end_time']:.0f}s)",
                "level": 1,
                "text": c["text"],
                "page_start": 0,
                "page_end": 0,
            }
            for i, c in enumerate(audio_chunks)
        ]

        parsed_document = {
            "title": fp.stem,
            "format": fp.suffix.lstrip("."),
            "pages": 0,
            "word_count": len(raw_text.split()),
            "sections": sections,
            "raw_text": raw_text,
        }

        # Persist duration to DocumentModel
        async with get_session_factory()() as session:
            await session.execute(
                _update(DocumentModel)
                .where(DocumentModel.id == doc_id)
                .values(
                    audio_duration_seconds=duration,
                    word_count=len(raw_text.split()),
                )
            )
            await session.commit()

        logger.info(
            "transcribe_node: done",
            extra={"doc_id": doc_id, "segments": len(segments), "duration": duration},
        )
        return {
            **state,
            "parsed_document": parsed_document,
            "audio_duration_seconds": duration,
            "_audio_chunks": audio_chunks,
            "status": "chunking",
        }
    except Exception as exc:
        logger.error("transcribe_node failed", exc_info=exc)
        return {**state, "status": "error", "error": str(exc)}


async def chunk_node(state: IngestionState) -> IngestionState:
    logger.debug("node_start", extra={"node": "chunk", "doc_id": state["document_id"]})
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


async def embed_node(state: IngestionState) -> IngestionState:
    import asyncio

    logger.debug("node_start", extra={"node": "embed", "doc_id": state["document_id"]})
    with trace_ingestion_node("embed", state):
        try:
            doc_id = state["document_id"]
            chunks = state.get("chunks") or []
            if not chunks:
                logger.warning("embed_node: no chunks to embed", extra={"doc_id": doc_id})
                await _update_stage(doc_id, "embedding")
                return {**state, "status": "indexing"}

            from app.services.embedder import get_embedding_service
            from app.services.vector_store import get_lancedb_service

            content_type = state.get("content_type") or "notes"
            texts = [c["text"] for c in chunks]
            embedder = get_embedding_service()

            # Update stage BEFORE encoding so UI reflects current work immediately
            await _update_stage(doc_id, "embedding")
            logger.info(
                "Embedding started",
                extra={"doc_id": doc_id, "num_chunks": len(chunks)},
            )

            # Run CPU-bound encoding in a thread pool so the event loop stays free
            # for status poll requests during the (potentially long) embedding pass.
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(None, embedder.encode, texts)

            lancedb_rows = [
                {
                    "chunk_id": c["id"],
                    "document_id": doc_id,
                    "content_type": content_type,
                    "section_heading": "",
                    "page": 0,
                    "chunk_index": c.get("index", 0),
                    "speaker": "",
                    "text": c["text"],
                    "vector": embeddings[i],
                }
                for i, c in enumerate(chunks)
            ]

            # Upsert in batches to avoid memory/spill issues in LanceDB/DataFusion
            # with very large documents (like the Bible with 9400+ chunks).
            batch_size = 1000
            lancedb_svc = get_lancedb_service()
            for start_idx in range(0, len(lancedb_rows), batch_size):
                end_idx = start_idx + batch_size
                batch = lancedb_rows[start_idx:end_idx]
                lancedb_svc.upsert_chunks(batch)
                logger.info(
                    "Upserted batch %d-%d to LanceDB",
                    start_idx,
                    min(end_idx, len(lancedb_rows)),
                )

            logger.info("Embedded %d chunks", len(chunks), extra={"doc_id": doc_id})
            return {**state, "status": "indexing"}
        except Exception as exc:
            logger.error("embed_node failed", exc_info=exc)
            return {**state, "status": "error", "error": str(exc)}


async def keyword_index_node(state: IngestionState) -> IngestionState:
    from sqlalchemy import text

    doc_id = state["document_id"]
    logger.debug("node_start", extra={"node": "keyword_index", "doc_id": doc_id})
    with trace_ingestion_node("keyword_index", state):
        try:
            async with get_session_factory()() as session:
                await session.execute(
                    text(
                        "INSERT INTO chunks_fts(rowid, text, chunk_id, document_id) "
                        "SELECT rowid, text, id, document_id FROM chunks "
                        "WHERE document_id = :doc_id"
                    ),
                    {"doc_id": doc_id},
                )
                await session.commit()
            logger.info("FTS5 index populated", extra={"doc_id": doc_id})
        except Exception as exc:
            logger.error("keyword_index_node failed", exc_info=exc)
        await _update_stage(doc_id, "indexing")
    return {**state, "status": "extracting"}


def _build_call_graph(chunks: list[dict], graph, doc_id: str) -> None:
    """Build call graph for code document: create function Entity nodes and CALLS edges."""
    from app.services.code_parser import CodeParser  # noqa: PLC0415

    # Collect function chunks (have function_name metadata)
    fn_chunks = [c for c in chunks if c.get("function_name")]
    if not fn_chunks:
        return

    # Upsert each function as an Entity node with type=FUNCTION
    fn_id_map: dict[str, str] = {}  # function_name → entity id
    for c in fn_chunks:
        name = c["function_name"]
        entity_id = f"fn_{doc_id}_{name}"
        graph.upsert_entity(entity_id, name, "FUNCTION")
        graph.add_mention(entity_id, doc_id)
        fn_id_map[name] = entity_id

    # Detect call edges via body_text substring matching
    defs = [
        {
            "name": c["function_name"],
            "kind": "function",
            "body_text": c.get("body_text", ""),
        }
        for c in fn_chunks
        if c.get("function_name")
    ]
    call_pairs = CodeParser.build_call_edges(defs)  # type: ignore[arg-type]
    for caller_name, callee_name in call_pairs:
        caller_id = fn_id_map.get(caller_name)
        callee_id = fn_id_map.get(callee_name)
        if caller_id and callee_id:
            graph.add_call_edge(caller_id, callee_id, doc_id)

    logger.info(
        "Call graph built",
        extra={"doc_id": doc_id, "functions": len(fn_chunks), "edges": len(call_pairs)},
    )


async def entity_extract_node(state: IngestionState) -> IngestionState:
    doc_id = state["document_id"]
    chunks = state.get("chunks") or []
    logger.debug("node_start", extra={"node": "entity_extract", "doc_id": doc_id})
    await _update_stage(doc_id, "entity_extract")
    with trace_ingestion_node("entity_extract", state):
        entity_count = 0
        try:
            from app.config import get_settings as _get_settings  # noqa: PLC0415

            if not _get_settings().GLINER_ENABLED:
                logger.info(
                    "entity_extract_node: skipped (GLINER_ENABLED=false)",
                    extra={"doc_id": doc_id},
                )
                await _update_stage(doc_id, "complete")
                return {**state, "status": "complete"}

            from itertools import combinations  # noqa: PLC0415

            from sqlalchemy import select  # noqa: PLC0415

            from app.models import DocumentModel  # noqa: PLC0415
            from app.services.graph import get_graph_service  # noqa: PLC0415
            from app.services.ner import get_entity_extractor  # noqa: PLC0415

            extractor = get_entity_extractor()
            # Cap NER at 500 chunks — sufficient for graph coverage, avoids multi-hour
            # runs on large documents (e.g. 2000+ chunk books).
            # Sample evenly across the document to get representative entities.
            import asyncio as _asyncio

            NER_CHUNK_LIMIT = 5000
            if len(chunks) > NER_CHUNK_LIMIT:
                step = len(chunks) // NER_CHUNK_LIMIT
                ner_chunks = chunks[::step][:NER_CHUNK_LIMIT]
                logger.info(
                    "NER sampling %d of %d chunks",
                    len(ner_chunks),
                    len(chunks),
                    extra={"doc_id": doc_id},
                )
            else:
                ner_chunks = chunks
            # CPU-bound — run in thread pool to keep event loop free for status polls
            loop = _asyncio.get_event_loop()
            content_type = state.get("content_type") or "unknown"
            entities = await loop.run_in_executor(None, extractor.extract, ner_chunks, content_type)
            entity_count = len(entities)

            graph = get_graph_service()

            # Upsert the document node in Kuzu
            async with get_session_factory()() as session:
                result = await session.execute(
                    select(DocumentModel.title, DocumentModel.content_type).where(
                        DocumentModel.id == doc_id
                    )
                )
                row = result.first()
                if row:
                    graph.upsert_document(doc_id, row.title or "", row.content_type or "notes")

            # Disambiguate: collapse surface-form variants to canonical names
            # before writing to Kuzu (e.g. "Mr. Holmes" -> "sherlock holmes").
            from app.services.entity_disambiguator import canonicalize_batch  # noqa: PLC0415

            entity_tuples = [(ent["name"], ent["type"]) for ent in entities]
            existing_by_type = graph.get_entities_by_type_for_document(doc_id)
            canonical_triples = canonicalize_batch(entity_tuples, existing_by_type)

            alias_map: dict[str, list[str]] = {}
            canonical_entities = []
            chunk_to_entities: dict[str, set[str]] = {}
            for (canonical, etype, original), ent in zip(canonical_triples, entities):
                canonical_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:{canonical}"))
                if original != canonical:
                    alias_map.setdefault(canonical_id, []).append(original)
                canonical_entities.append({**ent, "id": canonical_id, "name": canonical})
                chunk_to_entities.setdefault(ent["chunk_id"], set()).add(canonical)

            # Entity Injection: Append canonical entities to chunk text in memory & DB
            if chunk_to_entities:
                from sqlalchemy import update as _update  # noqa: PLC0415
                from app.models import ChunkModel  # noqa: PLC0415
                async with get_session_factory()() as update_session:
                    for chunk in chunks:
                        cid = chunk["id"]
                        if cid in chunk_to_entities:
                            ents_str = ", ".join(sorted(chunk_to_entities[cid]))
                            injection = f"\n[Entities: {ents_str}]"
                            chunk["text"] += injection
                            await update_session.execute(
                                _update(ChunkModel).where(ChunkModel.id == cid).values(text=chunk["text"])
                            )
                    await update_session.commit()

            # Upsert entities and add mentions; re-raise on Kuzu failure when
            # entities were successfully extracted (data loss must not be silent).
            try:
                for ent in canonical_entities:
                    aliases = alias_map.get(ent["id"])
                    graph.upsert_entity(ent["id"], ent["name"], ent["type"], aliases=aliases)
                    graph.add_mention(ent["id"], doc_id)

                # Co-occurrence: entities sharing the same chunk
                chunk_entities: dict[str, list[str]] = {}
                for ent in canonical_entities:
                    chunk_entities.setdefault(ent["chunk_id"], []).append(ent["id"])

                for chunk_ent_ids in chunk_entities.values():
                    for eid_a, eid_b in combinations(chunk_ent_ids, 2):
                        graph.add_co_occurrence(eid_a, eid_b, doc_id)
            except Exception:
                if entity_count > 0:
                    # Entities were extracted but Kuzu write failed — re-raise so the
                    # outer except captures it and the root cause is visible in logs.
                    raise

            # Prerequisite detection: scan chunk texts for marker phrases.
            # Only creates edges between entities already confirmed by GLiNER.
            try:
                from app.services.prerequisite_detector import detect_prerequisites  # noqa: PLC0415

                canonical_name_to_id: dict[str, str] = {
                    ent["name"]: ent["id"] for ent in canonical_entities
                }
                known_names: set[str] = set(canonical_name_to_id.keys())
                prereq_pairs = detect_prerequisites(ner_chunks, known_names)
                prereq_count = 0
                for dep_name, prereq_name, confidence in prereq_pairs:
                    dep_id = canonical_name_to_id.get(dep_name)
                    prereq_id = canonical_name_to_id.get(prereq_name)
                    if dep_id and prereq_id and dep_id != prereq_id:
                        graph.add_prerequisite(dep_id, prereq_id, doc_id, confidence)
                        prereq_count += 1
                logger.info(
                    "prerequisite edges created: %d",
                    prereq_count,
                    extra={"doc_id": doc_id},
                )
            except Exception as prereq_exc:
                logger.warning(
                    "prerequisite detection failed (non-fatal)",
                    extra={"doc_id": doc_id},
                    exc_info=prereq_exc,
                )

            # Tech relationship extraction: IMPLEMENTS, EXTENDS, USES, REPLACES, DEPENDS_ON
            # Only run for tech-relevant content types to avoid false edges in prose.
            content_type_for_tech = state.get("content_type") or ""
            if content_type_for_tech in ("code", "tech_book", "tech_article"):
                try:
                    from app.services.tech_relation_extractor import (
                        extract_tech_relations,  # noqa: PLC0415
                    )

                    canonical_name_to_id_tech: dict[str, str] = {
                        ent["name"]: ent["id"] for ent in canonical_entities
                    }
                    known_names_tech: set[str] = set(canonical_name_to_id_tech.keys())
                    tech_rel_pairs = extract_tech_relations(ner_chunks, known_names_tech)
                    tech_rel_count = 0
                    for name_a, name_b, rel_label in tech_rel_pairs:
                        id_a = canonical_name_to_id_tech.get(name_a)
                        id_b = canonical_name_to_id_tech.get(name_b)
                        if id_a and id_b and id_a != id_b:
                            try:
                                graph.add_tech_relation(id_a, id_b, rel_label, doc_id)
                                tech_rel_count += 1
                            except ValueError:
                                logger.debug("Skipped unknown tech relation label: %r", rel_label)
                    logger.info(
                        "tech relation edges created: %d",
                        tech_rel_count,
                        extra={"doc_id": doc_id},
                    )

                    # Version-of edges: for LIBRARY entities with version qualifiers,
                    # link the versioned entity to its major-version base entity.
                    from app.services.entity_disambiguator import (
                        _extract_version_qualifier,  # noqa: PLC0415
                    )

                    version_base_count = 0
                    for ent in canonical_entities:
                        if ent["type"] != "LIBRARY":
                            continue
                        name = ent["name"]
                        base_name, version_str = _extract_version_qualifier(name)
                        if version_str is None or base_name == name:
                            continue
                        # Create or find the base entity node
                        import uuid as _uuid  # noqa: PLC0415

                        base_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, f"{doc_id}:{base_name}"))
                        # Upsert base entity if it doesn't exist yet
                        graph.upsert_entity(base_id, base_name, "LIBRARY")
                        graph.add_mention(base_id, doc_id)
                        graph.add_version_of(ent["id"], base_id, doc_id)
                        version_base_count += 1
                    if version_base_count:
                        logger.info(
                            "version_of edges created: %d",
                            version_base_count,
                            extra={"doc_id": doc_id},
                        )
                except Exception as tech_exc:
                    logger.warning(
                        "tech relation extraction failed (non-fatal)",
                        extra={"doc_id": doc_id},
                        exc_info=tech_exc,
                    )

            # Build call graph for code documents
            content_type = state.get("content_type") or ""
            if content_type == "code":
                _build_call_graph(chunks, graph, doc_id)
        except MemoryError as exc:
            logger.error(
                "entity_extract_node: OOM loading GLiNER model -- "
                "set GLINER_ENABLED=false in .env to skip NER on low-memory machines",
                extra={"doc_id": doc_id},
                exc_info=exc,
            )
        except Exception as exc:
            logger.warning(
                "entity_extract_node failed (non-fatal, proceeding to complete)",
                extra={"doc_id": doc_id, "entity_count": entity_count},
                exc_info=exc,
            )
        finally:
            logger.info(
                "entity_extract_node finished",
                extra={"doc_id": doc_id, "entity_count": entity_count},
            )

        await _update_stage(doc_id, "embedding")
    return {**state, "status": "embedding"}


# Strong references to background tasks — prevents GC before they complete.
# asyncio only holds weak refs to tasks; without this they can be collected mid-run.
_background_tasks: set[asyncio.Task] = set()


async def _run_objective_extraction(doc_id: str, sections: list[tuple[str, str, str]]) -> None:
    """Background task: extract and store learning objectives for qualifying sections.

    sections is a list of (section_id, section_heading, section_text) tuples.
    Non-fatal: failure is logged and does not interrupt ingestion.
    """
    from app.services.learning_objective_extractor import (  # noqa: PLC0415
        LearningObjectiveExtractorService,
    )

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


async def _run_pregenerate(doc_id: str) -> None:
    """Background task: pre-generate summaries and invalidate library cache."""
    from app.services.summarizer import get_summarization_service  # noqa: PLC0415

    svc = get_summarization_service()
    try:
        await svc.generate_all_summaries(doc_id)
        logger.info("background summarize: done", extra={"doc_id": doc_id})
    except Exception as exc:
        logger.warning(
            "background summarize: failed (non-fatal)",
            extra={"doc_id": doc_id},
            exc_info=exc,
        )
    finally:
        # Always invalidate library cache — a new document was ingested regardless
        # of whether its individual summaries could be generated (e.g. Ollama offline).
        await svc.invalidate_library_cache()


async def section_summarize_node(state: IngestionState) -> IngestionState:
    """Generate section-level summaries (bounded to 100 units) before document summarization.

    Non-fatal: if Ollama is offline or summarization fails, ingestion continues.
    """
    doc_id = state["document_id"]
    logger.debug("node_start", extra={"node": "section_summarize", "doc_id": doc_id})
    try:
        from app.services.section_summarizer import get_section_summarizer_service  # noqa: PLC0415

        svc = get_section_summarizer_service()
        count = await svc.generate(doc_id)
        logger.info("section_summarize_node: %d units stored", count, extra={"doc_id": doc_id})
        return {**state, "section_summary_count": count}
    except Exception as exc:
        logger.warning(
            "section_summarize_node failed (non-fatal): %s",
            exc,
            extra={"doc_id": doc_id},
        )
        return {**state, "section_summary_count": 0}


async def summarize_node(state: IngestionState) -> IngestionState:
    """Fire off summary pre-generation as a background task and return immediately.

    The document is already marked complete by entity_extract_node.  Summaries
    generate asynchronously so ingestion does not block on LLM calls.
    """
    doc_id = state["document_id"]
    task = asyncio.create_task(_run_pregenerate(doc_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    logger.info("summarize_node: background task scheduled", extra={"doc_id": doc_id})
    return state


async def error_finalize_node(state: IngestionState) -> IngestionState:
    """Terminal node reached when any upstream node sets status='error'.

    Persists the human-readable error detail to DocumentModel.error_message so
    GET /documents/{id}/status can surface it to the UI (e.g. 'ffmpeg not found').
    """
    from sqlalchemy import update as _update  # noqa: PLC0415

    from app.models import DocumentModel  # noqa: PLC0415

    doc_id = state["document_id"]
    error_detail = state.get("error")
    async with get_session_factory()() as session:
        await session.execute(
            _update(DocumentModel)
            .where(DocumentModel.id == doc_id)
            .values(stage="error", error_message=error_detail)
        )
        await session.commit()
    logger.error(
        "Ingestion failed at node",
        extra={"document_id": doc_id, "error": error_detail},
    )
    return state


async def enrichment_enqueue_node(state: IngestionState) -> IngestionState:
    """Create enrichment jobs: image_extract (PDF/EPUB only) and concept_link (always).

    Non-fatal: enrichment failure does not prevent document from being usable.
    """
    import uuid as _uuid  # noqa: PLC0415

    from sqlalchemy import update as _update  # noqa: PLC0415

    from app.models import DocumentModel, EnrichmentJobModel  # noqa: PLC0415
    from app.services.enrichment_worker import get_enrichment_worker  # noqa: PLC0415

    doc_id = state["document_id"]
    fmt = state.get("format", "").lower()
    _IMAGE_FORMATS = {"pdf", "epub", "md", "markdown"}

    # Image extraction: PDF, EPUB, and MD (web articles)
    if fmt in _IMAGE_FORMATS:
        try:
            job_id = str(_uuid.uuid4())
            async with get_session_factory()() as session:
                session.add(
                    EnrichmentJobModel(
                        id=job_id,
                        document_id=doc_id,
                        job_type="image_extract",
                        status="pending",
                    )
                )
                await session.execute(
                    _update(DocumentModel)
                    .where(DocumentModel.id == doc_id)
                    .values(stage="enriching")
                )
                await session.commit()

            worker = get_enrichment_worker()
            task = asyncio.create_task(worker._dispatch_pending())
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

            logger.info(
                "enrichment_enqueue_node: enqueued image_extract job=%s doc=%s",
                job_id,
                doc_id,
            )
        except Exception as exc:
            logger.warning(
                "enrichment_enqueue_node: image_extract enqueue failed (non-fatal): %s",
                exc,
                extra={"doc_id": doc_id},
            )
    else:
        logger.info(
            "enrichment_enqueue_node: skipping image_extract (format=%s has no images)",
            fmt,
            extra={"doc_id": doc_id},
        )

    # Concept linking: always enqueue for cross-document concept comparison (S141)
    try:
        cl_job_id = str(_uuid.uuid4())
        async with get_session_factory()() as session:
            session.add(
                EnrichmentJobModel(
                    id=cl_job_id,
                    document_id=doc_id,
                    job_type="concept_link",
                    status="pending",
                )
            )
            await session.commit()

        worker = get_enrichment_worker()
        task = asyncio.create_task(worker._dispatch_pending())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        logger.info(
            "enrichment_enqueue_node: enqueued concept_link job=%s doc=%s",
            cl_job_id,
            doc_id,
        )
    except Exception as exc:
        logger.warning(
            "enrichment_enqueue_node: concept_link enqueue failed (non-fatal): %s",
            exc,
            extra={"doc_id": doc_id},
        )

    await _update_stage(doc_id, "complete")
    return {**state, "status": "complete"}


def _route_on_status(next_node: str):
    """Return a router that goes to error_finalize if status=='error', else next_node."""

    def _router(state: IngestionState) -> str:
        return "error_finalize" if state.get("status") == "error" else next_node

    return _router


def _build_graph():
    builder: StateGraph = StateGraph(IngestionState)
    builder.add_node("parse", parse_node)
    builder.add_node("classify", classify_node)
    builder.add_node("transcribe", transcribe_node)
    builder.add_node("chunk", chunk_node)
    builder.add_node("embed", embed_node)
    builder.add_node("keyword_index", keyword_index_node)
    builder.add_node("entity_extract", entity_extract_node)
    builder.add_node("section_summarize", section_summarize_node)
    builder.add_node("summarize", summarize_node)
    builder.add_node("enrichment_enqueue", enrichment_enqueue_node)
    builder.add_node("error_finalize", error_finalize_node)
    builder.add_edge(START, "parse")
    builder.add_conditional_edges("parse", _route_on_status("classify"))
    builder.add_conditional_edges("classify", _route_on_status("transcribe"))
    builder.add_conditional_edges("transcribe", _route_on_status("chunk"))
    builder.add_conditional_edges("chunk", _route_on_status("entity_extract"))
    builder.add_edge("entity_extract", "embed")
    builder.add_edge("embed", "keyword_index")
    builder.add_edge("keyword_index", "section_summarize")
    builder.add_edge("section_summarize", "summarize")
    builder.add_edge("summarize", "enrichment_enqueue")
    builder.add_edge("enrichment_enqueue", END)
    builder.add_edge("error_finalize", END)
    return builder.compile()


ingestion_graph = _build_graph()


async def run_ingestion(
    document_id: str,
    file_path: str,
    format: str,
    content_type: str | None = None,
    parsed_document: dict[str, Any] | None = None,
) -> None:
    initial_state: IngestionState = {
        "document_id": document_id,
        "file_path": file_path,
        "format": format,
        "parsed_document": parsed_document,
        "content_type": content_type,
        "chunks": None,
        "status": "parsing" if parsed_document is None else "classifying",
        "error": None,
        "section_summary_count": None,
        "audio_duration_seconds": None,
        "_audio_chunks": None,
    }
    logger.info(
        "Ingestion task started",
        extra={"document_id": document_id, "format": format, "content_type": content_type},
    )
    if parsed_document is None:
        await _update_stage(document_id, "parsing")
    else:
        await _update_stage(document_id, "classifying")
    with trace_chain(
        "ingestion.workflow",
        input_value=f"doc={document_id} format={format}",
    ) as root_span:
        root_span.set_attribute("ingestion.document_id", document_id)
        root_span.set_attribute("ingestion.format", format)
        try:
            await ingestion_graph.ainvoke(initial_state)
            root_span.set_attribute("output.value", "complete")
            logger.info("Ingestion task complete", extra={"document_id": document_id})
        except Exception as exc:
            root_span.set_attribute("error", True)
            root_span.set_attribute("error.message", str(exc))
            logger.error(
                "Ingestion task failed",
                extra={"document_id": document_id},
                exc_info=exc,
            )
            await _update_stage(document_id, "error")
