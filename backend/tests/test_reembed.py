"""A re-embed rebuilds a library's vectors from its database, and a killed run resumes (#390)."""

import json
import uuid
from datetime import UTC, datetime

import lancedb
import pyarrow as pa
import pytest

from app.database import get_session_factory
from app.db_init import open_library
from app.exceptions import Conflict
from app.library import use_library
from app.models import ChunkModel, ConceptModel, ImageModel
from app.services import reembed as reembed_module
from app.services.embedder import EmbeddingService, get_embedding_service
from app.services.reembed import NEXT, PREVIOUS, STATE, reembed
from app.services.vector_store import (
    CONCEPT_TABLE_NAME,
    IMAGE_TABLE_NAME,
    NOTE_TABLE_NAME,
    SCHEMA,
    TABLE_NAME,
    TABLES,
    get_lancedb_service,
)
from app.storage import library_root
from tests.factories import make_chunk, make_document, make_note
from tests.test_library_context import _close

DOC = str(uuid.uuid4())
CHUNKS = [str(uuid.uuid4()) for _ in range(7)]
NOTES = [str(uuid.uuid4()) for _ in range(3)]
IMAGES = [str(uuid.uuid4()) for _ in range(3)]
CONCEPTS = [uuid.uuid4().hex for _ in range(3)]
GHOST = str(uuid.uuid4())


class _Killed(Exception):
    """The process dying mid-run."""


@pytest.fixture
async def libraries(tmp_path, monkeypatch):
    """Two libraries holding the same rows, over vectors written before 0.17.0."""
    from app.config import get_settings

    # Loaded before DATA_DIR moves: the weights live under the session's root.
    get_embedding_service().encode(["warm"])
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(reembed_module, "PAGE", 2)
    for library in ("first", "second"):
        await open_library(library)
        with use_library(library):
            await _seed()
    yield
    await _close("first", "second")
    get_settings.cache_clear()


async def _seed() -> None:
    async with get_session_factory()() as session:
        session.add(make_document(id=DOC, title="The Odyssey"))
        for i, chunk_id in enumerate(CHUNKS):
            session.add(
                make_chunk(
                    id=chunk_id,
                    document_id=DOC,
                    chunk_index=i,
                    # Lengths that differ, so a batch's padding shows in its vectors.
                    text=" ".join(
                        [f"Book {i}: Odysseus sails on from the {i}th king."] * (i * 9 + 1)
                    ),
                    entities_text="Odysseus | Ithaca" if i % 2 else None,
                )
            )
        for i, note_id in enumerate(NOTES):
            session.add(make_note(id=note_id, document_id=DOC, content=f"Note {i} on the voyage"))
        for i, image_id in enumerate(IMAGES):
            session.add(
                ImageModel(
                    id=image_id,
                    document_id=DOC,
                    page=i,
                    path=f"images/{DOC}/{i}.png",
                    width=10,
                    height=10,
                    content_hash=f"h{i}",
                    # The last is not yet described, so it has no vector.
                    description=None if i == 2 else f"A map of the voyage, plate {i}",
                    created_at=datetime.now(UTC),
                )
            )
        evidence = [
            [{"chunk_ids": CHUNKS[:3], "document_ids": [DOC], "members": ["Odysseus"]}],
            [{"chunk_id": CHUNKS[4], "document_id": DOC, "quote": "sails on"}],
            # Its chunks were re-ingested away: no centroid, so no vector.
            [{"chunk_ids": [str(uuid.uuid4())], "document_ids": [DOC], "members": ["Scylla"]}],
        ]
        for concept_id, items in zip(CONCEPTS, evidence, strict=True):
            session.add(
                ConceptModel(id=concept_id, slug=concept_id, label="voyage", evidence_json=items)
            )
        await session.commit()
    # The live chunk table as 0.16 made it: the retired type column, and a ghost row.
    legacy = pa.schema([*SCHEMA, pa.field("content_type", pa.string())])
    db = lancedb.connect(str(library_root() / "vectors"))
    db.create_table(
        TABLE_NAME,
        data=[
            {
                "chunk_id": GHOST,
                "document_id": DOC,
                "section_heading": "",
                "page": 0,
                "chunk_index": 0,
                "speaker": "",
                "text": "a chunk deleted long ago",
                "vector": [0.1] * 384,
                "content_type": "book",
            }
        ],
        schema=legacy,
    )


def _tables(library: str) -> dict[str, list[dict]]:
    with use_library(library):
        db = lancedb.connect(str(library_root() / "vectors"))
    out = {}
    for name in db.list_tables().tables:
        rows = db.open_table(name).to_arrow().to_pylist()
        out[name] = sorted(rows, key=lambda r: r[TABLES[name][0]])
    return out


def _killed_after(monkeypatch, calls: int) -> None:
    encode = EmbeddingService.encode
    seen = {"n": 0}

    def failing(self, texts):
        seen["n"] += 1
        if seen["n"] > calls:
            raise _Killed
        return encode(self, texts)

    monkeypatch.setattr(EmbeddingService, "encode", failing)


async def test_a_killed_reembed_resumes_and_matches_a_clean_run(libraries, monkeypatch):
    encode = EmbeddingService.encode
    _killed_after(monkeypatch, 2)
    with use_library("first"), pytest.raises(_Killed):
        await reembed()
    root = library_root(library="first")
    assert (root / NEXT).exists()
    assert "content_type" in _tables("first")[TABLE_NAME][0]  # the live vectors are untouched

    monkeypatch.setattr(EmbeddingService, "encode", encode)
    with use_library("first"):
        resumed = await reembed()
    with use_library("second"):
        clean = await reembed()

    assert resumed.written[TABLE_NAME] == len(CHUNKS) - 2 * 2
    assert clean.written[TABLE_NAME] == len(CHUNKS)
    assert resumed.rows == clean.rows
    assert _tables("first") == _tables("second")


async def test_the_rebuild_holds_exactly_what_the_database_does(libraries):
    with use_library("first"):
        report = await reembed()
    tables = _tables("first")

    assert report.rows == {
        TABLE_NAME: 7,
        NOTE_TABLE_NAME: 3,
        IMAGE_TABLE_NAME: 2,
        CONCEPT_TABLE_NAME: 2,
    }
    assert [r["chunk_id"] for r in tables[TABLE_NAME]] == sorted(CHUNKS)
    assert "content_type" not in tables[TABLE_NAME][0]
    assert {r["image_id"] for r in tables[IMAGE_TABLE_NAME]} == set(IMAGES[:2])
    assert {r["concept_id"] for r in tables[CONCEPT_TABLE_NAME]} == set(CONCEPTS[:2])
    # Each vector is what ingestion would write for that text, entity tail included.
    odd = next(r for r in tables[TABLE_NAME] if r["chunk_id"] == CHUNKS[1])
    expected = get_embedding_service().encode([odd["text"] + "\nOdysseus | Ithaca"])[0]
    assert odd["vector"] == pytest.approx(expected, abs=1e-6)
    # The replaced vectors are kept beside the new ones, ghost row and all.
    root = library_root(library="first")
    previous = lancedb.connect(str(root / PREVIOUS)).open_table(TABLE_NAME)
    assert previous.to_arrow().column("chunk_id").to_pylist() == [GHOST]
    assert report.previous == str(root / PREVIOUS)
    assert not (root / NEXT).exists() and not (root / STATE).exists()


async def test_a_vector_the_app_writes_during_the_run_refuses_the_swap(libraries, monkeypatch):
    encode = EmbeddingService.encode

    def writes_meanwhile(self, texts):
        get_lancedb_service().upsert_note_vector(NOTES[0], DOC, "edited", [0.2] * 384)
        return encode(self, texts)

    monkeypatch.setattr(EmbeddingService, "encode", writes_meanwhile)
    with use_library("first"), pytest.raises(Conflict, match="wrote vectors"):
        await reembed()
    root = library_root(library="first")
    assert (root / NEXT).exists() and not (root / PREVIOUS).exists()
    assert "content_type" in _tables("first")[TABLE_NAME][0]

    monkeypatch.setattr(EmbeddingService, "encode", encode)
    with use_library("first"):
        report = await reembed()
    assert report.written[TABLE_NAME] == 0  # every page was already written


async def test_a_run_stopped_between_the_renames_finishes_the_swap(libraries, monkeypatch):
    swap = reembed_module._swap

    def stops_midway(root, report):
        (root / "vectors").rename(root / PREVIOUS)
        raise _Killed

    monkeypatch.setattr(reembed_module, "_swap", stops_midway)
    with use_library("first"), pytest.raises(_Killed):
        await reembed()
    monkeypatch.setattr(reembed_module, "_swap", swap)

    with use_library("first"):
        report = await reembed()
    assert report.rows[TABLE_NAME] == len(CHUNKS)
    assert [r["chunk_id"] for r in _tables("first")[TABLE_NAME]] == sorted(CHUNKS)


@pytest.mark.parametrize(
    ("leftover", "message"),
    [(PREVIOUS, "earlier re-embed"), (NEXT, "not built with")],
)
async def test_a_leftover_folder_is_never_overwritten(libraries, leftover, message):
    root = library_root(library="first")
    (root / leftover).mkdir()
    (root / STATE).write_text(json.dumps({"embedder": {"model": "other", "dim": 768}}))
    with use_library("first"), pytest.raises(Conflict, match=message):
        await reembed()
    assert (root / leftover).exists()


async def test_no_reembed_while_a_document_is_ingesting(libraries):
    with use_library("first"):
        async with get_session_factory()() as session:
            session.add(make_document(stage="embedding"))
            await session.commit()
        with pytest.raises(Conflict, match="ingested"):
            await reembed()
    assert not (library_root(library="first") / NEXT).exists()


async def _delete_first(session) -> None:
    await session.delete(await session.get(ChunkModel, sorted(CHUNKS)[0]))


async def _edit_first(session) -> None:
    (await session.get(ChunkModel, sorted(CHUNKS)[0])).text = "Book 0, corrected."


@pytest.mark.parametrize("change", [_delete_first, _edit_first])
async def test_a_chunk_changed_before_the_resume_is_embedded_as_a_clean_run_would(
    libraries, monkeypatch, change
):
    encode = EmbeddingService.encode
    _killed_after(monkeypatch, 2)
    with use_library("first"), pytest.raises(_Killed):
        await reembed()
    monkeypatch.setattr(EmbeddingService, "encode", encode)
    for library in ("first", "second"):
        with use_library(library):
            async with get_session_factory()() as session:
                await change(session)
                await session.commit()
            await reembed()

    # A deletion shifts every page and an edit changes one: either way the pages written
    # before the kill no longer match, and the resume encodes them as the clean run did.
    assert _tables("first") == _tables("second")
