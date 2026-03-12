import asyncio
import sqlite3
from pathlib import Path
from app.config import get_settings
from app.db_init import create_all_tables
from app.database import get_engine, make_engine
from sqlalchemy import text

async def check():
    engine = make_engine("sqlite+aiosqlite:///test_fts.db")
    await create_all_tables(engine)
    
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO notes_fts(content, note_id, document_id) VALUES (:c, :n, :d)"),
            {"c": "test content", "n": "test_id", "d": "test_doc"}
        )
        
        # Check shadow table
        result = await conn.execute(text("SELECT * FROM notes_fts_content"))
        row = result.fetchone()
        print(f"Shadow row: {row}")
        
        # Check column names if possible (SQLAlchemy might not show them easily for virtual tables)
        # We can use sqlite_master or table_info
        res = await conn.execute(text("PRAGMA table_info(notes_fts_content)"))
        columns = res.fetchall()
        print(f"Shadow table columns: {columns}")

    Path("test_fts.db").unlink(missing_ok=True)

if __name__ == "__main__":
    asyncio.run(check())
