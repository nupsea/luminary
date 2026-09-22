"""The reindex_entities CLI: flags, a missing document, and one document end to end.

Moved out of smoke S224, which ran the CLI from the smoke shell. The CLI opens the
database its own DATA_DIR names, not the backend's, so against the bundled app or
any backend on another data dir it read an empty database and failed.
"""

import argparse
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel
from app.scripts.reindex_entities import _run, main


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    await create_all_tables(engine)
    f = async_sessionmaker(engine, expire_on_commit=False)
    orig = db_module._engine, db_module._session_factory
    db_module._engine, db_module._session_factory = engine, f
    yield f
    db_module._engine, db_module._session_factory = orig
    get_settings.cache_clear()
    await engine.dispose()


def _args(document_id: str) -> argparse.Namespace:
    return argparse.Namespace(all=False, document_id=document_id, rebuild_graph=False)


def test_help_lists_both_modes(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--document-id" in out
    assert "--all" in out


@pytest.mark.asyncio
async def test_missing_document_exits_zero(factory):
    assert await _run(_args("no-such-document")) == 0


@pytest.mark.asyncio
async def test_reindex_writes_entity_tail_fts_and_vectors(factory):
    async with factory() as s:
        s.add(
            DocumentModel(
                id="d1",
                title="t",
                format="txt",
                content_type="book",
                word_count=8,
                page_count=0,
                file_path="x.txt",
                stage="complete",
                tags=[],
            )
        )
        s.add(ChunkModel(id="c1", document_id="d1", text="Holmes met Watson.", chunk_index=0))
        s.add(ChunkModel(id="c2", document_id="d1", text="It rained.", chunk_index=1))
        await s.commit()

    extractor = MagicMock()
    extractor.extract.return_value = [
        {"chunk_id": "c1", "name": "holmes", "type": "PERSON"},
        {"chunk_id": "c1", "name": "watson", "type": "PERSON"},
    ]
    embedder = MagicMock()
    embedder.encode.side_effect = lambda texts: [[0.0] * 4 for _ in texts]
    lancedb = MagicMock()
    graph = MagicMock()
    graph.get_entities_by_type_for_document.return_value = {}

    with (
        patch("app.services.ner.get_entity_extractor", return_value=extractor),
        patch("app.services.embedder.get_embedding_service", return_value=embedder),
        patch("app.services.vector_store.get_lancedb_service", return_value=lancedb),
        patch("app.services.graph.get_graph_service", return_value=graph),
    ):
        assert await _run(_args("d1")) == 0

    async with factory() as s:
        tails = dict((await s.execute(select(ChunkModel.id, ChunkModel.entities_text))).all())
        fts = (
            await s.execute(text("SELECT text FROM chunks_fts WHERE chunk_id = 'c1'"))
        ).scalar_one()
    assert tails["c2"] is None
    assert "Holmes" in tails["c1"] and "Watson" in tails["c1"]
    assert tails["c1"] in fts, "the FTS row carries the entity tail"
    rows = [r for call in lancedb.upsert_chunks.call_args_list for r in call.args[0]]
    assert {r["chunk_id"] for r in rows} == {"c1", "c2"}
