import asyncio

from sqlalchemy import JSON, String, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass

class DummyNote(Base):
    __tablename__ = "dummy_notes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    factory = async_sessionmaker(engine, expire_on_commit=False)
    
    async with factory() as session:
        note = DummyNote(id="1", tags=["old-tag"])
        session.add(note)
        await session.commit()
        
    async with factory() as session:
        note = (await session.execute(select(DummyNote).where(DummyNote.id == "1"))).scalar_one()
        note.tags = ["new-tag"]
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(note, "tags")
        session.add(note)
        await session.flush()
        await session.commit()
        
    async with factory() as session:
        note = (await session.execute(select(DummyNote).where(DummyNote.id == "1"))).scalar_one()
        print("Final tags:", note.tags)

asyncio.run(main())
