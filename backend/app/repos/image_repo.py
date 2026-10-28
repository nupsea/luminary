"""Extracted figures, their vision descriptions, and the images_fts index. Nothing here commits."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ImageModel


class ImageRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def content_hashes(self, document_id: str) -> set[str]:
        result = await self.session.execute(
            select(ImageModel.content_hash).where(ImageModel.document_id == document_id)
        )
        return set(result.scalars().all())

    async def stale(self, document_id: str, fresh_hashes: Collection[str]) -> list[tuple[str, str]]:
        """(id, path) of the document's images whose hash is not among `fresh_hashes`."""
        result = await self.session.execute(
            select(ImageModel.id, ImageModel.path).where(
                ImageModel.document_id == document_id,
                ImageModel.content_hash.notin_(list(fresh_hashes)),
            )
        )
        return [(image_id, path) for image_id, path in result.all()]

    async def delete(self, image_ids: Sequence[str]) -> None:
        await self.session.execute(delete(ImageModel).where(ImageModel.id.in_(list(image_ids))))

    async def delete_fts(self, image_ids: Sequence[str]) -> None:
        for image_id in image_ids:
            await self.session.execute(
                text("DELETE FROM images_fts WHERE image_id = :image_id"), {"image_id": image_id}
            )

    async def undescribed(self, document_id: str) -> list[ImageModel]:
        result = await self.session.execute(
            select(ImageModel).where(
                ImageModel.document_id == document_id, ImageModel.description.is_(None)
            )
        )
        return list(result.scalars().all())

    async def count_undescribed(self, document_id: str) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(ImageModel)
            .where(ImageModel.document_id == document_id, ImageModel.description.is_(None))
        )
        return int(result.scalar_one())

    async def describe(
        self, image_id: str, document_id: str, image_type: str, description: str
    ) -> None:
        """Store the description and index it; commit both together or neither."""
        await self.session.execute(
            update(ImageModel)
            .where(ImageModel.id == image_id)
            .values(image_type=image_type, description=description)
        )
        await self.session.execute(
            text(
                "INSERT INTO images_fts(image_id, document_id, body) "
                "VALUES (:image_id, :document_id, :body)"
            ),
            {"image_id": image_id, "document_id": document_id, "body": description},
        )

    async def described(self, document_id: str, image_types: Sequence[str]) -> list[ImageModel]:
        result = await self.session.execute(
            select(ImageModel).where(
                ImageModel.document_id == document_id,
                ImageModel.image_type.in_(list(image_types)),
                ImageModel.description.is_not(None),
            )
        )
        return list(result.scalars().all())

    async def has_described(self, document_id: str, image_types: Sequence[str]) -> bool:
        result = await self.session.execute(
            select(ImageModel.id)
            .where(
                ImageModel.document_id == document_id,
                ImageModel.image_type.in_(list(image_types)),
                ImageModel.description.is_not(None),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def all_descriptions(self) -> list[tuple[str, str, str]]:
        """(id, document id, description) of every described image, by id."""
        result = await self.session.execute(
            select(ImageModel.id, ImageModel.document_id, ImageModel.description)
            .where(ImageModel.description.is_not(None))
            .order_by(ImageModel.id)
        )
        return [tuple(row) for row in result.all()]

    async def described_by_ids(self, image_ids: Sequence[str]) -> list[ImageModel]:
        """The given images that carry a description and are not decorative."""
        result = await self.session.execute(
            select(ImageModel).where(
                ImageModel.id.in_(image_ids),
                ImageModel.description.is_not(None),
                ImageModel.image_type != "decorative",
            )
        )
        return list(result.scalars().all())
