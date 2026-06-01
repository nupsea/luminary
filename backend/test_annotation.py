import asyncio

from sqlalchemy import select

from app.database import get_db
from app.models import AnnotationModel


async def main():
    async for session in get_db():
        result = await session.execute(select(AnnotationModel))
        annotations = result.scalars().all()
        for a in annotations:
            print(f"ID: {a.id}, Color: {a.color}")

if __name__ == "__main__":
    asyncio.run(main())
