"""Libraries are separated by root: one library's stores cannot see another's (#388)."""

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.library import DEFAULT_LIBRARY, current_library, use_library, valid_library
from app.models import DocumentModel, FlashcardModel, GraphEntityModel, NoteModel
from tests.factories import make_card, make_document, make_note

DOC = str(uuid.uuid4())
_CHUNK = {
    "chunk_id": "c-1",
    "section_heading": "",
    "page": 0,
    "chunk_index": 0,
    "speaker": "",
    "text": "Penelope weaves by day and unpicks by night.",
    "vector": [0.1] * 384,
}


@pytest.fixture
def two_libraries(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


async def _close(*libraries: str) -> None:
    from app.database import close_library
    from app.runtime.library_work import stop_library
    from app.services import vector_store
    from app.storage import library_root

    for library in libraries:
        await stop_library(library)
        await close_library(library)
        # The tmp root goes with the test; a later test must not reuse a handle into it.
        vector_store._library_services.pop(library_root(library=library), None)


def test_the_default_library_is_the_data_dir_and_others_live_beside_it(two_libraries):
    from app.storage import library_root, machine_root

    assert library_root() == machine_root() == two_libraries
    with use_library("odyssey"):
        assert library_root() == two_libraries / "libraries" / "odyssey"
    assert library_root(library="iliad") == two_libraries / "libraries" / "iliad"


@pytest.mark.parametrize("library", ["", ".", "..", "../x", "a/b", "Odyssey", "a" * 64])
def test_an_id_that_could_leave_its_root_is_refused(library):
    with pytest.raises(ValueError):
        valid_library(library)


async def test_tasks_and_threads_inherit_the_library():
    async def in_task() -> str:
        return current_library()

    with use_library("odyssey"):
        task = asyncio.create_task(in_task())
        thread = await asyncio.to_thread(current_library)
    assert (await task, thread) == ("odyssey", "odyssey")
    assert current_library() == DEFAULT_LIBRARY


async def _rows(model) -> int:
    from app.database import get_session_factory

    async with get_session_factory()() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_a_second_library_sees_none_of_the_first(two_libraries):
    from app.database import get_session_factory
    from app.db_init import open_library
    from app.services.vector_store import get_lancedb_service
    from app.storage import library_root

    await open_library("first")
    await open_library("second")
    try:
        with use_library("first"):
            async with get_session_factory()() as session:
                session.add(make_document(id=DOC, title="The Odyssey"))
                await session.flush()
                session.add_all(
                    [
                        make_note(document_id=DOC, content="The suitors eat everything."),
                        make_card(document_id=DOC),
                        GraphEntityModel(id="e-1", document_id=DOC, name="Penelope", type="PERSON"),
                    ]
                )
                await session.commit()
            await asyncio.to_thread(
                get_lancedb_service().upsert_chunks, [{**_CHUNK, "document_id": DOC}]
            )
            first = {
                m.__tablename__: await _rows(m)
                for m in (DocumentModel, NoteModel, FlashcardModel, GraphEntityModel)
            }
            first_vectors = get_lancedb_service().count_for_document(DOC)

        with use_library("second"):
            second = {
                m.__tablename__: await _rows(m)
                for m in (DocumentModel, NoteModel, FlashcardModel, GraphEntityModel)
            }
            second_vectors = get_lancedb_service().count_for_document(DOC)
            second_root = library_root()
    finally:
        await _close("first", "second")

    assert first == {"documents": 1, "notes": 1, "flashcards": 1, "graph_entities": 1}
    assert first_vectors == 1
    assert second == {"documents": 0, "notes": 0, "flashcards": 0, "graph_entities": 0}
    assert second_vectors == 0
    assert second_root != library_root(library="first")
    assert (library_root(library="first") / "luminary.db").exists()
    assert (second_root / "luminary.db").exists()


async def test_a_library_id_under_another_root_gets_that_roots_stores(tmp_path, monkeypatch):
    """A handle left open under one `DATA_DIR` is never handed to the same id under another."""
    from app.config import get_settings
    from app.database import get_engine
    from app.services.vector_store import get_lancedb_service

    roots = (tmp_path / "a", tmp_path / "b")
    seen = []
    try:
        for data_dir in roots:
            monkeypatch.setenv("DATA_DIR", str(data_dir))
            get_settings.cache_clear()
            with use_library("second"):
                seen.append((get_engine().url.database, get_lancedb_service()))
    finally:
        for data_dir in roots:
            monkeypatch.setenv("DATA_DIR", str(data_dir))
            get_settings.cache_clear()
            await _close("second")
        get_settings.cache_clear()

    (db_a, vectors_a), (db_b, vectors_b) = seen
    assert db_a.startswith(str(tmp_path / "a")) and db_b.startswith(str(tmp_path / "b"))
    assert vectors_a is not vectors_b
