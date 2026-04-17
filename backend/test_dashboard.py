"""Quick test to surface the actual traceback from the dashboard endpoint."""
import asyncio
import traceback
from app.db import get_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy import select, func, or_
from app.models import (
    CollectionModel, CollectionMemberModel, FlashcardModel,
    NoteModel, NoteTagIndexModel, DocumentModel,
)
from datetime import datetime, UTC

async def test():
    engine = get_engine()
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        collection_id = "0d2ba52e-d436-40ce-a7b5-1024cd8c0d79"

        # 1. Fetch collection name
        coll_result = await session.execute(
            select(CollectionModel.name).where(CollectionModel.id == collection_id)
        )
        coll_name = coll_result.scalar_one_or_none()
        print(f"Collection: {coll_name}")

        # 2. Members
        members_result = await session.execute(
            select(CollectionMemberModel.member_id, CollectionMemberModel.member_type)
            .where(CollectionMemberModel.collection_id == collection_id)
        )
        members = members_result.all()
        doc_ids = [m[0] for m in members if m[1] == "document"]
        note_ids = [m[0] for m in members if m[1] == "note"]
        print(f"doc_ids={doc_ids}, note_ids={note_ids}")

        # 3. Build the or_ clause — this is likely where it dies
        try:
            conditions = []
            if doc_ids:
                conditions.append(FlashcardModel.document_id.in_(doc_ids))
            if note_ids:
                conditions.append(FlashcardModel.note_id.in_(note_ids))

            if conditions:
                cards_stmt = select(FlashcardModel).where(or_(*conditions))
            else:
                # No members → empty result
                cards_stmt = select(FlashcardModel).where(False)

            cards_result = await session.execute(cards_stmt)
            all_cards = list(cards_result.scalars().all())
            print(f"Cards found: {len(all_cards)}")
        except Exception:
            traceback.print_exc()

    await engine.dispose()

asyncio.run(test())
