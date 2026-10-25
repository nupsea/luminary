"""Retiring the document type: the upgrade writes down what it supplied, then drops it (#223).

A library from 0.16.2 carries `content_type` and `is_technical`, and a row whose facets
are null read its form and subject through them. The upgrade must leave every reader
the same answer, keep every row that hangs off a document, and drop both columns.
"""

import sqlite3

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import _alembic_config, init_database
from tests.factories import make_card

BEFORE_DROP = "bb347838d5f8"

# (id, format, content_type, is_technical, form, domain) as a 0.16.2 library holds them.
_LEGACY_ROWS = (
    ("novel", "txt", "book", None, None, None),
    ("manual", "pdf", "tech_book", None, None, None),
    ("talk", "mp3", "audio", 1, None, None),
    ("unanswered", "md", "tech_article", None, "article", None),
    ("measured", "pdf", "tech_book", 1, "prose", "general"),
)


def _rows(db, sql):
    c = sqlite3.connect(db)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


async def _migrate(engine, revision: str) -> None:
    async with engine.begin() as conn:

        def _downgrade(sync_conn) -> None:
            from alembic import command  # noqa: PLC0415

            command.downgrade(_alembic_config(sync_conn), revision)

        await conn.run_sync(_downgrade)


async def _legacy_library(db) -> None:
    engine = make_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await init_database(engine)
        await _migrate(engine, BEFORE_DROP)
        async with engine.begin() as conn:
            for doc_id, fmt, content_type, is_technical, form, domain in _LEGACY_ROWS:
                # Raw SQL: the ORM no longer declares the columns this schema still has.
                await conn.execute(
                    text(
                        "INSERT INTO documents (id, title, format, content_type, is_technical, "
                        "form, domain, word_count, page_count, file_path, stage, tags, "
                        "created_at, last_accessed_at) VALUES (:id, :id, :fmt, :ct, :tech, "
                        ":form, :domain, 0, 0, 'x', 'complete', '[]', '2026-10-01', '2026-10-01')"
                    ),
                    {
                        "id": doc_id,
                        "fmt": fmt,
                        "ct": content_type,
                        "tech": is_technical,
                        "form": form,
                        "domain": domain,
                    },
                )
        async with async_sessionmaker(engine)() as session:
            session.add_all([make_card(document_id=doc_id) for doc_id, *_ in _LEGACY_ROWS])
            await session.commit()
    finally:
        await engine.dispose()


async def test_the_upgrade_fills_what_the_type_supplied_and_keeps_every_card(tmp_path):
    db = tmp_path / "lib.db"
    await _legacy_library(db)

    engine = make_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await init_database(engine)
    finally:
        await engine.dispose()

    columns = {name for _cid, name, *_ in _rows(db, "PRAGMA table_info(documents)")}
    assert not columns & {"content_type", "is_technical"}
    facets = {d: (f, dom) for d, f, dom in _rows(db, "SELECT id, form, domain FROM documents")}
    assert facets == {
        "novel": ("prose", None),
        "manual": ("reference", "technical"),
        "talk": ("dialogue", "technical"),
        # A probe that never answered: the type named the subject.
        "unanswered": ("article", "technical"),
        # A measurement stands over the type.
        "measured": ("prose", "general"),
    }
    # With foreign keys on, a rebuild of `documents` would have cascaded into these.
    assert _rows(db, "SELECT count(*) FROM flashcards") == [(len(_LEGACY_ROWS),)]


async def test_the_downgrade_restores_both_columns_from_the_facets(tmp_path):
    db = tmp_path / "lib.db"
    await _legacy_library(db)
    engine = make_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await init_database(engine)
        await _migrate(engine, BEFORE_DROP)
    finally:
        await engine.dispose()

    restored = {
        d: (ct, tech)
        for d, ct, tech in _rows(db, "SELECT id, content_type, is_technical FROM documents")
    }
    assert restored == {
        "novel": ("book", None),
        "manual": ("tech_book", 1),
        "talk": ("audio", 1),
        "unanswered": ("tech_article", 1),
        "measured": ("book", 0),
    }
    assert _rows(db, "SELECT count(*) FROM flashcards") == [(len(_LEGACY_ROWS),)]
