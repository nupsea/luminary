"""Only a document that exists and has finished ingesting is ever searched.

From a real failure on 2026-08-17: a 52,331-chunk PDF was 90 seconds into ingestion
when a question arrived scoped to it. Its chunk rows were already in SQLite but
embedding had not started, so retrieval returned nothing and the user was told to
"make sure at least one document has been ingested" -- with 52 finished documents in
the library, one of which answered the question immediately afterwards.

Two rules follow, and both are asserted here: an unready document contributes no
results, and when the scope named only unready documents the rest of the library
answers instead of nothing.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import DocumentModel
from app.runtime.chat_nodes.search import search_node
from app.types import ScoredChunk


@pytest.fixture()
async def test_db(tmp_path, monkeypatch):
    db_path = tmp_path / "search.db"
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_session_factory", factory)
    yield factory
    await engine.dispose()


async def _add_document(factory, doc_id: str, title: str, stage: str) -> None:
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title=title,
                format="pdf",
                content_type="general",
                word_count=10,
                page_count=1,
                file_path=f"/tmp/{title}",
                stage=stage,
                tags=[],
            )
        )
        await session.commit()


def _chunk(doc_id: str) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=str(uuid.uuid4()),
        document_id=doc_id,
        text="Ulysses fought the sea and Neptune's anger.",
        score=0.9,
        source="vector",
        section_heading=None,
        chunk_index=0,
        page=1,
    )


@pytest.mark.asyncio
async def test_a_document_being_ingested_is_not_searched(test_db):
    """Its chunks exist before its vectors do, so it can only displace ready ones."""
    ready_id = str(uuid.uuid4())
    ingesting_id = str(uuid.uuid4())
    await _add_document(test_db, ready_id, "the_odyssey", "complete")
    await _add_document(test_db, ingesting_id, "ibm-sdm-vol-2", "embedding")

    retriever = AsyncMock()
    retriever.retrieve_with_images = AsyncMock(
        return_value=([_chunk(ready_id), _chunk(ingesting_id)], [])
    )

    with patch("app.runtime.chat_nodes.search.get_retriever", return_value=retriever):
        result = await search_node(
            {"question": "who does Odysseus fight in the sea?", "scope": "all", "doc_ids": []}
        )

    returned_docs = {c["document_id"] for c in result["chunks"]}
    assert ingesting_id not in returned_docs, "an unfinished document must not reach the answer"
    assert ready_id in returned_docs

    passed_ids = retriever.retrieve_with_images.await_args.args[1]
    assert passed_ids == [ready_id], "retrieval should be told which documents are ready"


@pytest.mark.asyncio
async def test_scope_on_an_ingesting_document_falls_back_to_the_rest(test_db):
    """The question is about material the user has, not the file that is uploading."""
    ready_id = str(uuid.uuid4())
    ingesting_id = str(uuid.uuid4())
    await _add_document(test_db, ready_id, "the_odyssey", "complete")
    await _add_document(test_db, ingesting_id, "ibm-sdm-vol-2", "entity_extract")

    retriever = AsyncMock()
    retriever.retrieve_with_images = AsyncMock(return_value=([_chunk(ready_id)], []))

    with patch("app.runtime.chat_nodes.search.get_retriever", return_value=retriever):
        result = await search_node(
            {
                "question": "who does Odysseus fight in the sea?",
                "scope": "single",
                "doc_ids": [ingesting_id],
            }
        )

    passed_ids = retriever.retrieve_with_images.await_args.args[1]
    assert passed_ids == [ready_id], (
        "when every requested document is still indexing, search the ready library"
    )
    assert result["chunks"], "the answer should come from the documents that are ready"


@pytest.mark.asyncio
async def test_a_retrieval_exception_is_reported_as_a_failure_not_as_emptiness(test_db):
    await _add_document(test_db, str(uuid.uuid4()), "the_odyssey", "complete")

    retriever = AsyncMock()
    retriever.retrieve_with_images = AsyncMock(side_effect=RuntimeError("lancedb busy"))

    with patch("app.runtime.chat_nodes.search.get_retriever", return_value=retriever):
        result = await search_node({"question": "anything", "scope": "all", "doc_ids": []})

    assert result["chunks"] == []
    assert result["retrieval_failed"] is True, (
        "a failed search and an empty library must not be the same state"
    )


@pytest.mark.asyncio
async def test_scope_on_a_deleted_document_falls_back_to_the_library(test_db):
    """The reported failure: a chat scoped to a document that no longer exists.

    The id lived in the browser store, survived nine days, three chats and two
    re-uploads, and matched no row at all -- so retrieval filtered every question
    down to a document that was not there and answered nothing, while the header
    read "All documents" because a missing id has no title to render.
    """
    ready_id = str(uuid.uuid4())
    deleted_id = str(uuid.uuid4())
    await _add_document(test_db, ready_id, "the_odyssey", "complete")

    retriever = AsyncMock()
    retriever.retrieve_with_images = AsyncMock(return_value=([_chunk(ready_id)], []))

    with patch("app.runtime.chat_nodes.search.get_retriever", return_value=retriever):
        result = await search_node(
            {
                "question": "Who is the queen of Ithaca?",
                "scope": "single",
                "doc_ids": [deleted_id],
            }
        )

    passed_ids = retriever.retrieve_with_images.await_args.args[1]
    assert deleted_id not in (passed_ids or []), "a deleted document is not searchable"
    # None means no document filter at all, i.e. the whole library -- which is the
    # widened search. Either that or the explicit list of searchable ids is correct.
    assert passed_ids is None or passed_ids == [ready_id]
    assert result["chunks"], "the library still holds the answer and must be asked"
