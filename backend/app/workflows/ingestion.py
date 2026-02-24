import logging
import re
import uuid
from pathlib import Path
from typing import Any, TypedDict

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import END, START, StateGraph

from app.database import get_session_factory
from app.models import ChunkModel
from app.services.parser import DocumentParser

logger = logging.getLogger(__name__)

_parser = DocumentParser()

CHUNK_CONFIGS: dict[str, dict[str, int]] = {
    "paper": {"chunk_size": 300, "chunk_overlap": 45},
    "book": {"chunk_size": 600, "chunk_overlap": 120},
    "conversation": {"chunk_size": 450, "chunk_overlap": 90},
    "notes": {"chunk_size": 300, "chunk_overlap": 75},
    "code": {"chunk_size": 300, "chunk_overlap": 75},
}

STAGE_PROGRESS: dict[str, int] = {
    "parsing": 10,
    "classifying": 25,
    "chunking": 40,
    "embedding": 70,
    "indexing": 90,
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


def _classify(raw_text: str, sections: list[dict], word_count: int, file_ext: str) -> str:
    if file_ext in ("py", "js", "ts", "go", "java", "rs", "cpp", "c", "rb"):
        return "code"
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


def classify_node(state: IngestionState) -> IngestionState:
    try:
        pd = state["parsed_document"]
        if pd is None:
            return {**state, "content_type": "notes", "status": "chunking"}
        file_ext = Path(state["file_path"]).suffix.lstrip(".")
        content_type = _classify(pd["raw_text"], pd["sections"], pd["word_count"], file_ext)
        logger.info(
            "Classified document",
            extra={"doc_id": state["document_id"], "content_type": content_type},
        )
        return {**state, "content_type": content_type, "status": "chunking"}
    except Exception as exc:
        logger.error("classify_node failed", exc_info=exc)
        return {**state, "status": "error", "error": str(exc)}


async def chunk_node(state: IngestionState) -> IngestionState:
    try:
        pd = state["parsed_document"]
        content_type = state["content_type"] or "notes"
        cfg = CHUNK_CONFIGS.get(content_type, CHUNK_CONFIGS["notes"])
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=cfg["chunk_size"], chunk_overlap=cfg["chunk_overlap"]
        )
        all_texts = (
            [s["text"] for s in pd["sections"] if s["text"]] if pd else []
        )
        raw_chunks = splitter.split_text("\n\n".join(all_texts))
        doc_id = state["document_id"]
        chunks = []
        async with get_session_factory()() as session:
            for idx, text in enumerate(raw_chunks):
                chunk_id = str(uuid.uuid4())
                chunk = ChunkModel(
                    id=chunk_id,
                    document_id=doc_id,
                    section_id=None,
                    text=text,
                    token_count=len(text.split()),
                    page_number=0,
                    speaker=None,
                    chunk_index=idx,
                )
                session.add(chunk)
                chunks.append({"id": chunk_id, "text": text, "index": idx})
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
        embeddings = embedder.encode(texts)

        lancedb_rows = [
            {
                "chunk_id": c["id"],
                "document_id": doc_id,
                "content_type": content_type,
                "section_heading": "",
                "page": 0,
                "speaker": "",
                "text": c["text"],
                "vector": embeddings[i],
            }
            for i, c in enumerate(chunks)
        ]
        get_lancedb_service().upsert_chunks(lancedb_rows)

        await _update_stage(doc_id, "embedding")
        logger.info("Embedded %d chunks", len(chunks), extra={"doc_id": doc_id})
        return {**state, "status": "indexing"}
    except Exception as exc:
        logger.error("embed_node failed", exc_info=exc)
        return {**state, "status": "error", "error": str(exc)}


async def keyword_index_node(state: IngestionState) -> IngestionState:
    from sqlalchemy import text

    doc_id = state["document_id"]
    try:
        async with get_session_factory()() as session:
            await session.execute(
                text(
                    "INSERT INTO chunks_fts(rowid, text, chunk_id, document_id) "
                    "SELECT rowid, text, id, document_id FROM chunks WHERE document_id = :doc_id"
                ),
                {"doc_id": doc_id},
            )
            await session.commit()
        logger.info("FTS5 index populated", extra={"doc_id": doc_id})
    except Exception as exc:
        logger.error("keyword_index_node failed", exc_info=exc)
    await _update_stage(doc_id, "indexing")
    return {**state, "status": "extracting"}


async def entity_extract_node(state: IngestionState) -> IngestionState:
    logger.info("entity extraction pending (S15b)", extra={"doc_id": state["document_id"]})
    await _update_stage(state["document_id"], "complete")
    return {**state, "status": "complete"}


def _build_graph():
    builder: StateGraph = StateGraph(IngestionState)
    builder.add_node("parse", parse_node)
    builder.add_node("classify", classify_node)
    builder.add_node("chunk", chunk_node)
    builder.add_node("embed", embed_node)
    builder.add_node("keyword_index", keyword_index_node)
    builder.add_node("entity_extract", entity_extract_node)
    builder.add_edge(START, "parse")
    builder.add_edge("parse", "classify")
    builder.add_edge("classify", "chunk")
    builder.add_edge("chunk", "embed")
    builder.add_edge("embed", "keyword_index")
    builder.add_edge("keyword_index", "entity_extract")
    builder.add_edge("entity_extract", END)
    return builder.compile()


ingestion_graph = _build_graph()


async def run_ingestion(document_id: str, file_path: str, format: str) -> None:
    initial_state: IngestionState = {
        "document_id": document_id,
        "file_path": file_path,
        "format": format,
        "parsed_document": None,
        "content_type": None,
        "chunks": None,
        "status": "parsing",
        "error": None,
    }
    await _update_stage(document_id, "parsing")
    try:
        await ingestion_graph.ainvoke(initial_state)
    except Exception as exc:
        logger.error("Ingestion workflow failed", exc_info=exc)
        await _update_stage(document_id, "error")
