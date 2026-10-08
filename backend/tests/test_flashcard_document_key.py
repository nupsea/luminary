"""A flashcard's document_id is a foreign key that cascades from documents (#242).

Card generation outlives the request that started it, so a document deleted mid-generation used
to collect cards pointing at nothing. The key refuses them; revision 473a1ea0dabc removes the
orphans an older library already holds.
"""

import sqlite3
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import _alembic_config, init_database
from app.models import DocumentModel, FlashcardModel
from app.services.flashcard_search import _sync_flashcard_fts
from tests.graph_seed import add_documents


def _card(document_id: str | None) -> FlashcardModel:
    return FlashcardModel(
        id=str(uuid.uuid4()), document_id=document_id, question="Q?", answer="A.", source_excerpt=""
    )


async def test_a_card_for_a_missing_document_is_refused(test_db):
    async with test_db.factory() as session:
        session.add(_card("no-such-document"))
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            await session.commit()


async def test_deleting_the_document_row_takes_its_cards(test_db):
    await add_documents(test_db, "doc")
    async with test_db.factory() as session:
        session.add_all([_card("doc"), _card(None)])
        await session.commit()

    async with test_db.factory() as session:
        await session.execute(delete(DocumentModel).where(DocumentModel.id == "doc"))
        await session.commit()
        left = (await session.execute(select(FlashcardModel.document_id))).scalars().all()

    assert left == [None]


def _rows(db, sql):
    c = sqlite3.connect(db)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


async def test_the_upgrade_removes_orphan_cards_and_their_index_rows(tmp_path):
    db = tmp_path / "lib.db"
    engine = make_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await init_database(engine)
        async with engine.begin() as conn:

            def _downgrade(sync_conn) -> None:
                from alembic import command  # noqa: PLC0415

                command.downgrade(_alembic_config(sync_conn), "dc23a62094ab")

            await conn.run_sync(_downgrade)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add(
                DocumentModel(
                    id="kept", title="t", format="txt", content_type="notes", file_path="x"
                )
            )
            kept, orphan, note = _card("kept"), _card("gone"), _card(None)
            session.add_all([kept, orphan, note])
            for card in (kept, orphan, note):
                await _sync_flashcard_fts(card, session)
            await session.commit()

        await init_database(engine)

        assert sorted(_rows(db, "SELECT id FROM flashcards")) == sorted([(kept.id,), (note.id,)])
        assert sorted(_rows(db, "SELECT c2 FROM flashcards_fts_content")) == sorted(
            [(kept.id,), (note.id,)]
        )
        async with factory() as session:
            session.add(_card("gone"))
            with pytest.raises(IntegrityError, match="FOREIGN KEY"):
                await session.commit()
    finally:
        await engine.dispose()
