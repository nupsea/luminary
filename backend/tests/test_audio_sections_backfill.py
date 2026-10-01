"""Audio ingested before 0.7.5 had chunks and no sections, so the reader showed
"No content available" for a transcript it could retrieve from (#97). Revision
087906440dcf writes one section per transcript window, as chunk_node does now."""

import sqlite3

from sqlalchemy import text

from app.database import make_engine
from app.db_init import init_database


def _rows(db, sql):
    c = sqlite3.connect(db)
    try:
        return c.execute(sql).fetchall()
    finally:
        c.close()


async def test_an_old_transcript_gets_one_section_per_window_and_a_replay_adds_none(tmp_path):
    db = tmp_path / "lib.db"
    engine = make_engine(f"sqlite+aiosqlite:///{db}")
    try:
        await init_database(engine)
        async with engine.begin() as conn:
            for doc, ct in (("talk", "audio"), ("book", "book")):
                await conn.execute(
                    text(
                        "INSERT INTO documents (id, title, format, content_type, word_count, "
                        "page_count, file_path, stage, tags, created_at, last_accessed_at) "
                        "VALUES (:d, :d, 'mp3', :ct, 9, 0, 'x', 'complete', '[]', "
                        "'2026-03-31', '2026-03-31')"
                    ),
                    {"d": doc, "ct": ct},
                )
                for i, words in enumerate(("Hey everyone.", "It is calculus.", "Three ideas.")):
                    await conn.execute(
                        text(
                            "INSERT INTO chunks (id, document_id, text, chunk_index, "
                            "token_count, page_number, has_code, created_at) "
                            "VALUES (:id, :d, :t, :i, 2, 0, 0, '2026-03-31')"
                        ),
                        {"id": f"{doc}-{2 - i}", "d": doc, "t": words, "i": i},
                    )
            await conn.execute(text("UPDATE alembic_version SET version_num = '45c26ee949d4'"))

        await init_database(engine)
        sections = _rows(
            db,
            "SELECT s.section_order, s.heading, s.body, c.id FROM sections s "
            "JOIN chunks c ON c.section_id = s.id WHERE s.document_id = 'talk' "
            "ORDER BY s.section_order",
        )
        assert sections == [
            (0, "", "Hey everyone.", "talk-2"),
            (1, "", "It is calculus.", "talk-1"),
            (2, "", "Three ideas.", "talk-0"),
        ]
        assert _rows(db, "SELECT count(*) FROM sections WHERE document_id = 'book'") == [(0,)]

        async with engine.begin() as conn:
            await conn.execute(text("UPDATE alembic_version SET version_num = '45c26ee949d4'"))
        await init_database(engine)
        assert _rows(db, "SELECT count(*) FROM sections WHERE document_id = 'talk'") == [(3,)]
    finally:
        await engine.dispose()
