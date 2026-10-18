"""Repository for `CanonicalTagModel` and related tag tables.

The uncommitted writes serve the multi-step flows (merge, migrate-naming) that
commit once at their end.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    CanonicalTagModel,
    DocumentTagIndexModel,
    DocumentTagProvenanceModel,
    NoteTagIndexModel,
    TagAliasModel,
    TagMergeSuggestionModel,
)
from app.repos._helpers import get_or_404

# Fixed table and column names: the only text interpolated into the scoped queries.
_SCOPE_INDEX = {
    "note": ("note_tag_index", "note_id"),
    "document": ("document_tag_index", "document_id"),
}


class TagRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- single-row reads --------------------------------------------------

    async def find_by_id(self, tag_id: str) -> CanonicalTagModel | None:
        result = await self.session.execute(
            select(CanonicalTagModel).where(CanonicalTagModel.id == tag_id)
        )
        return result.scalar_one_or_none()

    async def get_or_404(self, tag_id: str) -> CanonicalTagModel:
        return await get_or_404(self.session, CanonicalTagModel, tag_id, name="Tag")

    # -- list reads --------------------------------------------------------

    async def list_by_count(self) -> Sequence[CanonicalTagModel]:
        result = await self.session.execute(
            select(CanonicalTagModel).order_by(CanonicalTagModel.usage_count.desc())
        )
        return result.scalars().all()

    async def list_by_id(self) -> Sequence[CanonicalTagModel]:
        result = await self.session.execute(
            select(CanonicalTagModel).order_by(CanonicalTagModel.id)
        )
        return result.scalars().all()

    async def by_ids(self, tag_ids: Collection[str]) -> dict[str, CanonicalTagModel]:
        result = await self.session.execute(
            select(CanonicalTagModel).where(CanonicalTagModel.id.in_(list(tag_ids)))
        )
        return {t.id: t for t in result.scalars().all()}

    async def alias_pairs(self) -> set[frozenset[str]]:
        """{alias, canonical id} for every alias, unordered."""
        result = await self.session.execute(
            select(TagAliasModel.alias, TagAliasModel.canonical_tag_id)
        )
        return {frozenset(pair) for pair in result.all()}

    # -- merge suggestions -------------------------------------------------

    async def suggested_pairs(self) -> set[frozenset[str]]:
        """Both tags of every merge suggestion in any status, unordered."""
        result = await self.session.execute(
            select(TagMergeSuggestionModel.tag_a_id, TagMergeSuggestionModel.tag_b_id)
        )
        return {frozenset(pair) for pair in result.all()}

    async def pending_suggestions(self) -> list[TagMergeSuggestionModel]:
        result = await self.session.execute(
            select(TagMergeSuggestionModel)
            .where(TagMergeSuggestionModel.status == "pending")
            .order_by(TagMergeSuggestionModel.similarity.desc())
        )
        return list(result.scalars().all())

    async def find_suggestion(self, suggestion_id: str) -> TagMergeSuggestionModel | None:
        return await self.session.get(TagMergeSuggestionModel, suggestion_id)

    async def all_in_storage_order(self) -> list[CanonicalTagModel]:
        """Every tag, unsorted: the naming migration's tie-break follows this order."""
        return list((await self.session.execute(select(CanonicalTagModel))).scalars().all())

    async def scoped_counts(self, scope: Literal["note", "document"]) -> dict[str, int]:
        """{tag id: distinct notes or documents carrying it}."""
        table, member = _SCOPE_INDEX[scope]
        rows = (
            await self.session.execute(
                text(
                    f"SELECT tag_full, COUNT(DISTINCT {member}) "  # noqa: S608
                    f"FROM {table} GROUP BY tag_full"
                )
            )
        ).all()
        return {tag: int(n) for tag, n in rows}

    async def scoped_tags(self, scope: Literal["note", "document"]) -> list[tuple]:
        """(id, display_name, parent_tag, usage_count, created_at, scoped count) of tags used
        in the scope, most used there first, so a note-heavy tag does not outrank a
        document-heavy one when the scope is documents."""
        table, member = _SCOPE_INDEX[scope]
        rows = await self.session.execute(
            text(
                "SELECT t.id, t.display_name, t.parent_tag, t.usage_count, "  # noqa: S608
                "t.created_at, "
                f"(SELECT COUNT(DISTINCT idx.{member}) FROM {table} idx "
                "  WHERE idx.tag_full = t.id) AS scoped_count "
                "FROM canonical_tags t "
                f"WHERE EXISTS (SELECT 1 FROM {table} idx2 WHERE idx2.tag_full = t.id) "
                "ORDER BY scoped_count DESC, t.usage_count DESC"
            )
        )
        return [tuple(r) for r in rows.all()]

    async def cross_content_counts(self, tag_id: str) -> tuple[int, int]:
        """(documents, notes) carrying exactly this tag."""
        row = (
            await self.session.execute(
                text(
                    "SELECT "
                    "  (SELECT COUNT(DISTINCT document_id) FROM document_tag_index "
                    "   WHERE tag_full = :tag) AS doc_count, "
                    "  (SELECT COUNT(DISTINCT note_id) FROM note_tag_index "
                    "   WHERE tag_full = :tag) AS note_count"
                ),
                {"tag": tag_id},
            )
        ).first()
        return (int(row[0] or 0), int(row[1] or 0)) if row else (0, 0)

    async def autocomplete(self, prefix: str, *, limit: int = 10) -> Sequence[CanonicalTagModel]:
        result = await self.session.execute(
            select(CanonicalTagModel)
            .where(CanonicalTagModel.id.like(f"{prefix}%"))
            .order_by(CanonicalTagModel.usage_count.desc())
            .limit(limit)
        )
        return result.scalars().all()

    # -- tag-index reads ---------------------------------------------------

    async def note_ids_with_tag(
        self, tag_id: str, *, include_descendants: bool = False
    ) -> list[str]:
        """Return note IDs that reference `tag_id` (optionally + descendants)."""
        stmt = select(NoteTagIndexModel.note_id).distinct()
        if include_descendants:
            stmt = stmt.where(
                (NoteTagIndexModel.tag_full == tag_id)
                | NoteTagIndexModel.tag_full.like(f"{tag_id}/%")
            )
        else:
            stmt = stmt.where(NoteTagIndexModel.tag_full == tag_id)
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]

    # -- writes ------------------------------------------------------------

    async def create(
        self,
        *,
        id: str,
        display_name: str,
        parent_tag: str | None,
    ) -> CanonicalTagModel:
        tag = CanonicalTagModel(
            id=id,
            display_name=display_name,
            parent_tag=parent_tag,
            usage_count=0,
            created_at=datetime.now(UTC),
        )
        self.session.add(tag)
        await self.session.commit()
        await self.session.refresh(tag)
        return tag

    async def update_fields(
        self,
        tag: CanonicalTagModel,
        *,
        display_name: str | None = None,
        parent_tag: str | None = None,
        parent_tag_set: bool = False,
    ) -> CanonicalTagModel:
        """Update mutable fields on `tag`.

        `parent_tag_set` distinguishes "not supplied" from "explicitly null"
        for the optional parent_tag column.
        """
        if display_name is not None:
            tag.display_name = display_name
        if parent_tag_set:
            tag.parent_tag = parent_tag
        await self.session.commit()
        await self.session.refresh(tag)
        return tag

    async def drop_with_note_index(self, tag_id: str) -> None:
        """Delete a tag and its note index rows, uncommitted."""
        await self.session.execute(
            delete(NoteTagIndexModel).where(NoteTagIndexModel.tag_full == tag_id)
        )
        await self.session.execute(delete(CanonicalTagModel).where(CanonicalTagModel.id == tag_id))

    async def insert_if_absent(self, tag_id: str, usage_count: int) -> None:
        """Create a tag named by its slug's last segment, uncommitted; an existing id wins."""
        segments = tag_id.split("/")
        await self.session.execute(
            text(
                "INSERT OR IGNORE INTO canonical_tags"
                " (id, display_name, parent_tag, usage_count, created_at)"
                " VALUES (:id, :display_name, :parent_tag, :usage_count, datetime('now'))"
            ),
            {
                "id": tag_id,
                "display_name": segments[-1],
                "parent_tag": "/".join(segments[:-1]) if len(segments) > 1 else None,
                "usage_count": usage_count,
            },
        )

    # -- per-member tag index (uncommitted, in the member's write transaction) --

    async def indexed_tags(self, scope: Literal["note", "document"], member_id: str) -> set[str]:
        table, member = _SCOPE_INDEX[scope]
        rows = await self.session.execute(
            text(f"SELECT tag_full FROM {table} WHERE {member} = :mid"),  # noqa: S608
            {"mid": member_id},
        )
        return set(rows.scalars().all())

    async def unindex(self, scope: Literal["note", "document"], member_id: str, tag: str) -> None:
        """Drop one tag from a member and its usage count; a document's provenance goes too."""
        table, member = _SCOPE_INDEX[scope]
        params = {"mid": member_id, "tag": tag}
        await self.session.execute(
            text(f"DELETE FROM {table} WHERE {member} = :mid AND tag_full = :tag"),  # noqa: S608
            params,
        )
        if scope == "document":
            await self.session.execute(
                text(
                    "DELETE FROM document_tag_provenance"
                    " WHERE document_id = :mid AND tag_full = :tag"
                ),
                params,
            )
        await self.session.execute(
            text("UPDATE canonical_tags SET usage_count = MAX(0, usage_count - 1) WHERE id = :tag"),
            {"tag": tag},
        )

    async def index(self, scope: Literal["note", "document"], member_id: str, tag: str) -> None:
        """Add one tag to a member, creating the canonical tag or counting one more use."""
        table, member = _SCOPE_INDEX[scope]
        segments = tag.split("/")
        tag_parent = "/".join(segments[:-1]) if len(segments) > 1 else ""
        await self.session.execute(
            text(
                f"INSERT OR IGNORE INTO {table}"  # noqa: S608
                f" ({member}, tag_full, tag_root, tag_parent)"
                " VALUES (:mid, :tag_full, :tag_root, :tag_parent)"
            ),
            {"mid": member_id, "tag_full": tag, "tag_root": segments[0], "tag_parent": tag_parent},
        )
        await self.session.execute(
            text(
                "INSERT INTO canonical_tags"
                " (id, display_name, parent_tag, usage_count, created_at)"
                " VALUES (:id, :display_name, :parent_tag, 1, datetime('now'))"
                " ON CONFLICT(id) DO UPDATE SET"
                " usage_count = canonical_tags.usage_count + 1"
            ),
            {"id": tag, "display_name": segments[-1], "parent_tag": tag_parent or None},
        )

    async def record_auto_provenance(
        self, document_id: str, tags: list[str], tagger_version: str, at: datetime
    ) -> None:
        for tag in tags:
            self.session.add(
                DocumentTagProvenanceModel(
                    document_id=document_id,
                    tag_full=tag,
                    source="auto",
                    tagger_version=tagger_version,
                    created_at=at,
                )
            )

    async def record_manual_provenance(self, document_id: str, tag: str) -> None:
        """INSERT OR IGNORE: an existing auto-tagger row stays authoritative."""
        await self.session.execute(
            text(
                "INSERT OR IGNORE INTO document_tag_provenance"
                " (document_id, tag_full, source, tagger_version, created_at)"
                " VALUES (:doc_id, :tag, 'manual', NULL, datetime('now'))"
            ),
            {"doc_id": document_id, "tag": tag},
        )

    async def document_index_rows(self) -> list[tuple[str, str]]:
        """Every (document_id, tag) in the document tag index."""
        rows = await self.session.execute(
            select(DocumentTagIndexModel.document_id, DocumentTagIndexModel.tag_full)
        )
        return [(d, t) for d, t in rows.all()]

    async def document_provenance_rows(self) -> list[tuple[str, str, str, str | None]]:
        """Every (document_id, tag, source, tagger_version) provenance row."""
        rows = await self.session.execute(
            select(
                DocumentTagProvenanceModel.document_id,
                DocumentTagProvenanceModel.tag_full,
                DocumentTagProvenanceModel.source,
                DocumentTagProvenanceModel.tagger_version,
            )
        )
        return [(d, t, s, v) for d, t, s, v in rows.all()]

    async def drop_document_index_rows(self, document_id: str, tags: set[str]) -> None:
        """Index and provenance rows only, uncommitted; canonical usage counts are untouched."""
        for model in (DocumentTagIndexModel, DocumentTagProvenanceModel):
            await self.session.execute(
                delete(model).where(model.document_id == document_id, model.tag_full.in_(tags))
            )

    async def find_alias(self, alias: str) -> TagAliasModel | None:
        result = await self.session.execute(
            select(TagAliasModel).where(TagAliasModel.alias == alias)
        )
        return result.scalar_one_or_none()

    async def index_usage(self, tag: str) -> int:
        """Notes plus documents carrying exactly this tag, per the shadow indexes."""
        notes = await self.session.execute(
            select(func.count())
            .select_from(NoteTagIndexModel)
            .where(NoteTagIndexModel.tag_full == tag)
        )
        documents = await self.session.execute(
            select(func.count())
            .select_from(DocumentTagIndexModel)
            .where(DocumentTagIndexModel.tag_full == tag)
        )
        return int(notes.scalar_one()) + int(documents.scalar_one())

    async def retarget_index_rows(self, old: str, new: str) -> None:
        """Point both shadow indexes' `old` rows at `new`, uncommitted; JSON tag columns are
        not rewritten."""
        segments = new.split("/")
        values = {
            "tag_full": new,
            "tag_root": segments[0],
            "tag_parent": "/".join(segments[:-1]) if "/" in new else "",
        }
        for model in (NoteTagIndexModel, DocumentTagIndexModel):
            await self.session.execute(update(model).where(model.tag_full == old).values(**values))

    async def delete_with_aliases(self, tag_id: str) -> None:
        """Delete the canonical tag and any aliases pointing to it.

        Caller is expected to have validated existence + usage_count == 0.
        """
        await self.session.execute(
            delete(TagAliasModel).where(TagAliasModel.canonical_tag_id == tag_id)
        )
        await self.session.execute(delete(CanonicalTagModel).where(CanonicalTagModel.id == tag_id))
        await self.session.commit()


def get_tag_repo(session: AsyncSession = Depends(get_db)) -> TagRepo:
    return TagRepo(session)
