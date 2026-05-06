"""S224: tests for index-time entity injection.

- Unit tests for build_entity_tail (pure function: dedupe, cap, sort, capitalize).
- Integration test for FTS5 surface-form bridging via the
  `text || ' ' || entities_text` concatenation in chunks_fts.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel
from app.workflows.ingestion import ENTITY_TAIL_MAX, build_entity_tail

# ---------------------------------------------------------------------------
# Unit tests: build_entity_tail
# ---------------------------------------------------------------------------


def test_build_entity_tail_empty_input_returns_empty_string():
    assert build_entity_tail([]) == ""
    assert build_entity_tail(set()) == ""
    assert build_entity_tail(()) == ""


def test_build_entity_tail_single_entity():
    assert build_entity_tail({"weena"}) == "[Entities: Weena]"


def test_build_entity_tail_dedupes_case_insensitive():
    # "Weena", "weena", "WEENA" must collapse to a single entry.
    out = build_entity_tail(["Weena", "weena", "WEENA"])
    assert out.startswith("[Entities: ")
    inner = out[len("[Entities: ") : -1]
    assert inner.split(", ") == ["Weena"]


def test_build_entity_tail_alphabetical_order():
    out = build_entity_tail({"weena", "morlock", "eloi", "time machine"})
    inner = out[len("[Entities: ") : -1]
    labels = inner.split(", ")
    # Case-insensitive sort: eloi, morlock, time machine, weena
    assert labels == ["Eloi", "Morlock", "Time Machine", "Weena"]


def test_build_entity_tail_caps_at_max():
    names = [f"entity-{i:02d}" for i in range(20)]  # 20 distinct entities
    out = build_entity_tail(names)
    inner = out[len("[Entities: ") : -1]
    labels = inner.split(", ")
    assert len(labels) == ENTITY_TAIL_MAX  # 12


def test_build_entity_tail_capitalizes_each_token():
    out = build_entity_tail({"sherlock holmes"})
    assert out == "[Entities: Sherlock Holmes]"


def test_build_entity_tail_skips_blank_strings():
    out = build_entity_tail(["  ", "", "weena", "   "])
    assert out == "[Entities: Weena]"


def test_build_entity_tail_skips_non_strings():
    out = build_entity_tail(["weena", None, 42, "morlock"])  # type: ignore[list-item]
    inner = out[len("[Entities: ") : -1]
    assert inner.split(", ") == ["Morlock", "Weena"]


# ---------------------------------------------------------------------------
# Integration: FTS5 surface-form bridging
# ---------------------------------------------------------------------------


@pytest.fixture
async def fts_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_fts5_match_finds_canonical_when_only_surface_form_in_text(fts_db):
    """A chunk that mentions 'Mr. Holmes' (surface form) should be matched by
    FTS5 on the canonical name 'Sherlock Holmes' once entities_text concatenation
    is included in the FTS5 indexed text."""
    _engine, factory = fts_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="Holmes test",
                format="txt",
                content_type="book",
                file_path="/tmp/holmes.txt",
            )
        )
        session.add(
            ChunkModel(
                id=chunk_id,
                document_id=doc_id,
                chunk_index=0,
                text="Mr. Holmes greeted the inspector calmly at the door.",
                entities_text=build_entity_tail({"sherlock holmes"}),
            )
        )
        await session.commit()

        # Mirror the keyword_index_node insert: text || ' ' || entities_text.
        await session.execute(
            sa_text(
                "INSERT INTO chunks_fts(rowid, text, chunk_id, document_id) "
                "SELECT rowid, "
                "       text || CASE "
                "         WHEN entities_text IS NOT NULL AND entities_text != '' "
                "         THEN ' ' || entities_text "
                "         ELSE '' END, "
                "       id, document_id FROM chunks "
                "WHERE document_id = :doc_id"
            ),
            {"doc_id": doc_id},
        )
        await session.commit()

        # Sanity: search for the surface form -- must match.
        rows_surface = (
            await session.execute(
                sa_text("SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH :q"),
                {"q": "Holmes"},
            )
        ).all()
        assert any(r[0] == chunk_id for r in rows_surface)

        # The bridge: search for the canonical form 'Sherlock' -- must match the same
        # chunk via the entity tail, even though chunk.text never contains 'Sherlock'.
        rows_canonical = (
            await session.execute(
                sa_text("SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH :q"),
                {"q": "Sherlock"},
            )
        ).all()
        assert any(r[0] == chunk_id for r in rows_canonical), (
            "FTS5 must match canonical entity name through entities_text concatenation"
        )


@pytest.mark.asyncio
async def test_fts5_skips_concat_when_entities_text_null(fts_db):
    """When entities_text is NULL the FTS5 row must equal chunk.text exactly --
    the COALESCE/CASE branch must not introduce a trailing space or 'None'."""
    _engine, factory = fts_db
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="No entities",
                format="txt",
                content_type="notes",
                file_path="/tmp/none.txt",
            )
        )
        session.add(
            ChunkModel(
                id=chunk_id,
                document_id=doc_id,
                chunk_index=0,
                text="A plain chunk with no named entities at all.",
                entities_text=None,
            )
        )
        await session.commit()

        await session.execute(
            sa_text(
                "INSERT INTO chunks_fts(rowid, text, chunk_id, document_id) "
                "SELECT rowid, "
                "       text || CASE "
                "         WHEN entities_text IS NOT NULL AND entities_text != '' "
                "         THEN ' ' || entities_text "
                "         ELSE '' END, "
                "       id, document_id FROM chunks "
                "WHERE document_id = :doc_id"
            ),
            {"doc_id": doc_id},
        )
        await session.commit()

        # The shadow content table c0 holds the text that was indexed.
        # I-4 pattern: query the shadow table directly via UNINDEXED column.
        row = (
            await session.execute(
                sa_text("SELECT c0 FROM chunks_fts_content WHERE c1 = :cid"),
                {"cid": chunk_id},
            )
        ).first()
        assert row is not None
        assert row[0] == "A plain chunk with no named entities at all."
