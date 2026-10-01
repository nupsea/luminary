"""The entities a note is about: named in its text, or matched by one of its tags."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GraphEntityModel, GraphNoteEntityModel, NoteLinkModel, NoteModel

Entity = GraphEntityModel
NoteEntity = GraphNoteEntityModel


class GraphNoteEntityRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve_names(self, names: list[str], document_id: str | None) -> dict[str, str]:
        """{lowercased name: entity id}. Several documents can hold one name; the note's own
        document wins, then the entity mentioned most."""
        if not names:
            return {}
        lowered = sorted({n.lower() for n in names if n})
        own_document = case((Entity.document_id == document_id, 0), else_=1)
        result = await self.session.execute(
            select(func.lower(Entity.name), Entity.id)
            .where(func.lower(Entity.name).in_(lowered))
            .order_by(own_document, Entity.mention_count.desc(), Entity.id)
        )
        resolved: dict[str, str] = {}
        for name, entity_id in result:
            resolved.setdefault(name, entity_id)
        return resolved

    async def replace(self, note_id: str, rows: list[dict[str, Any]]) -> None:
        """Make `rows` the note's entity links. Nothing is stored for a deleted note.

        Each row: entity_id, kind ('written_about' | 'tag'), confidence, tag.
        """
        await self.session.execute(delete(NoteEntity).where(NoteEntity.note_id == note_id))
        if not rows or not await self.session.scalar(
            select(exists().where(NoteModel.id == note_id))
        ):
            return
        unique = {(r["entity_id"], r["kind"]): r for r in rows}
        self.session.add_all(
            NoteEntity(
                note_id=note_id,
                entity_id=entity_id,
                kind=kind,
                confidence=r.get("confidence", 1.0),
                tag=r.get("tag"),
            )
            for (entity_id, kind), r in unique.items()
        )

    async def entities_for_note(self, note_id: str) -> list[tuple[str, str, str, float]]:
        """(name, type, kind, confidence), written_about first."""
        result = await self.session.execute(
            select(Entity.name, Entity.type, NoteEntity.kind, NoteEntity.confidence)
            .join(Entity, Entity.id == NoteEntity.entity_id)
            .where(NoteEntity.note_id == note_id)
            .order_by(NoteEntity.kind.desc(), Entity.name)
        )
        return [(n, t, k, float(c)) for n, t, k, c in result]

    async def note_ids_for_name(self, name: str) -> list[str]:
        result = await self.session.execute(
            select(NoteEntity.note_id)
            .join(Entity, Entity.id == NoteEntity.entity_id)
            .where(func.lower(Entity.name) == name.lower())
            .distinct()
        )
        return [row[0] for row in result]

    async def links_for_entities(
        self, entity_ids: set[str]
    ) -> list[tuple[str, str, str, float, str]]:
        """(note id, note content, entity id, confidence, kind) for notes about `entity_ids`."""
        if not entity_ids:
            return []
        result = await self.session.execute(
            select(
                NoteEntity.note_id,
                NoteModel.content,
                NoteEntity.entity_id,
                NoteEntity.confidence,
                NoteEntity.kind,
            )
            .join(NoteModel, NoteModel.id == NoteEntity.note_id)
            .where(NoteEntity.entity_id.in_(list(entity_ids)))
            .order_by(NoteEntity.note_id, NoteEntity.kind.desc())
        )
        return [tuple(row) for row in result]

    async def note_links_among(self, note_ids: list[str]) -> list[tuple[str, str]]:
        if not note_ids:
            return []
        result = await self.session.execute(
            select(NoteLinkModel.source_note_id, NoteLinkModel.target_note_id).where(
                NoteLinkModel.source_note_id.in_(note_ids),
                NoteLinkModel.target_note_id.in_(note_ids),
            )
        )
        return [tuple(row) for row in result]
