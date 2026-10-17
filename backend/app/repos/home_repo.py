"""Reads behind the home hub: recency feeds, active collections, weekly stats.

Raw SQL because most of these UNION documents with notes over `content_activity`, and
the date windows are SQLite's own `datetime('now', ...)` arithmetic.
"""

from __future__ import annotations

from sqlalchemy import Row, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession


class HomeRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _all(self, sql, params: dict | None = None) -> list[Row]:
        return list((await self.session.execute(sql, params or {})).all())

    async def _first(self, sql, params: dict | None = None) -> Row | None:
        return (await self.session.execute(sql, params or {})).first()

    async def recent_items(self, limit: int) -> list[Row]:
        """(member_type, member_id, title, preview, last_meaningful_at), newest first."""
        return await self._all(
            text(
                """
                SELECT 'document' AS member_type, ca.member_id, d.title AS title,
                       NULL AS preview, ca.last_meaningful_at
                FROM content_activity ca
                JOIN documents d ON d.id = ca.member_id
                WHERE ca.member_type = 'document'
                UNION ALL
                SELECT 'note' AS member_type, ca.member_id,
                       COALESCE(NULLIF(n.title, ''), substr(n.content, 1, 60)) AS title,
                       substr(n.content, 1, 120) AS preview,
                       ca.last_meaningful_at
                FROM content_activity ca
                JOIN notes n ON n.id = ca.member_id
                WHERE ca.member_type = 'note' AND n.archived = 0
                ORDER BY last_meaningful_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )

    async def active_collections(self, limit: int) -> list[Row]:
        """(id, name, color, doc_count, note_count, sort_key) by latest member activity.

        A collection with no touched member sorts by its created_at, so a new user's
        new collections still surface.
        """
        return await self._all(
            text(
                """
                SELECT c.id, c.name, c.color,
                       SUM(CASE WHEN cm.member_type = 'document' THEN 1 ELSE 0 END) AS doc_count,
                       SUM(CASE WHEN cm.member_type = 'note' THEN 1 ELSE 0 END) AS note_count,
                       COALESCE(MAX(ca.last_meaningful_at), c.created_at) AS sort_key
                FROM collections c
                LEFT JOIN collection_members cm ON cm.collection_id = c.id
                LEFT JOIN content_activity ca
                       ON ca.member_id = cm.member_id AND ca.member_type = cm.member_type
                GROUP BY c.id, c.name, c.color, c.created_at
                ORDER BY sort_key DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )

    async def collection_card_counts(self, collection_ids: list[str]) -> dict[str, int]:
        """Cards per collection, document and note members alike.

        Apart from `active_collections` so its GROUP BY rows are not multiplied by cards.
        """
        rows = await self._all(
            text(
                """
                SELECT cm.collection_id, COUNT(DISTINCT fc.id)
                FROM collection_members cm
                JOIN flashcards fc ON (
                    (cm.member_type = 'document' AND fc.document_id = cm.member_id)
                    OR (cm.member_type = 'note' AND fc.note_id = cm.member_id)
                )
                WHERE cm.collection_id IN :col_ids
                GROUP BY cm.collection_id
                """
            ).bindparams(bindparam("col_ids", expanding=True)),
            {"col_ids": collection_ids},
        )
        return {cid: int(n) for cid, n in rows}

    async def collection_due_counts(self, collection_ids: list[str]) -> dict[str, int]:
        rows = await self._all(
            text(
                """
                SELECT cm.collection_id, COUNT(DISTINCT fc.id)
                FROM collection_members cm
                JOIN flashcards fc ON cm.member_type = 'document'
                                   AND fc.document_id = cm.member_id
                WHERE cm.collection_id IN :col_ids
                  AND fc.due_date IS NOT NULL
                  AND fc.due_date <= datetime('now')
                GROUP BY cm.collection_id
                """
            ).bindparams(bindparam("col_ids", expanding=True)),
            {"col_ids": collection_ids},
        )
        return {cid: int(n) for cid, n in rows}

    async def recent_tags(self, limit: int) -> list[Row]:
        """(id, display_name, doc_count, note_count), most used first."""
        return await self._all(
            text(
                """
                SELECT t.id, t.display_name,
                       (SELECT COUNT(DISTINCT document_id)
                        FROM document_tag_index WHERE tag_full = t.id) AS doc_count,
                       (SELECT COUNT(DISTINCT note_id)
                        FROM note_tag_index WHERE tag_full = t.id) AS note_count
                FROM canonical_tags t
                ORDER BY t.usage_count DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )

    async def due_card_count(self) -> int:
        row = await self._first(
            text(
                "SELECT COUNT(*) FROM flashcards "
                "WHERE due_date IS NOT NULL AND due_date <= datetime('now')"
            )
        )
        return int(row[0]) if row else 0

    async def collection_with_most_due(self) -> Row | None:
        """(id, name, color, due cards) of the collection holding the most due cards."""
        return await self._first(
            text(
                """
                SELECT c.id, c.name, c.color, COUNT(DISTINCT fc.id) AS n
                FROM collections c
                JOIN collection_members cm ON cm.collection_id = c.id
                                          AND cm.member_type = 'document'
                JOIN flashcards fc ON fc.document_id = cm.member_id
                WHERE fc.due_date IS NOT NULL AND fc.due_date <= datetime('now')
                GROUP BY c.id, c.name, c.color
                ORDER BY n DESC
                LIMIT 1
                """
            )
        )

    async def reading_progress(self, document_id: str) -> tuple[int, int]:
        """(sections, sections read) of one document."""
        row = await self._first(
            text(
                "SELECT "
                " (SELECT COUNT(*) FROM sections WHERE document_id = :d) AS total, "
                " (SELECT COUNT(*) FROM reading_progress WHERE document_id = :d) AS read"
            ),
            {"d": document_id},
        )
        return (int(row[0] or 0), int(row[1] or 0)) if row else (0, 0)

    async def recently_active_documents(self, limit: int) -> list[Row]:
        """(id, title, last_meaningful_at, word_count, sections, sections read)."""
        return await self._all(
            text(
                """
                SELECT
                  d.id, d.title, ca.last_meaningful_at, d.word_count,
                  (SELECT COUNT(*) FROM sections WHERE document_id = d.id) AS total,
                  (SELECT COUNT(*) FROM reading_progress WHERE document_id = d.id) AS read
                FROM content_activity ca
                JOIN documents d ON d.id = ca.member_id
                WHERE ca.member_type = 'document'
                ORDER BY ca.last_meaningful_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )

    async def recently_active_notes(self, limit: int) -> list[Row]:
        """(id, title, last_meaningful_at) of unarchived notes, newest first."""
        return await self._all(
            text(
                """
                SELECT n.id, n.title, ca.last_meaningful_at
                FROM content_activity ca
                JOIN notes n ON n.id = ca.member_id
                WHERE ca.member_type = 'note'
                  AND n.archived = 0
                ORDER BY ca.last_meaningful_at DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )

    async def latest_unended_session(self, max_age_days: int) -> Row | None:
        """(id, mode, planned_card_ids, cards_reviewed, started_at) of the newest open session."""
        return await self._first(
            text(
                """
                SELECT id, mode, planned_card_ids, cards_reviewed, started_at
                FROM study_sessions
                WHERE ended_at IS NULL
                  AND started_at >= datetime('now', :max_age)
                ORDER BY started_at DESC
                LIMIT 1
                """
            ),
            {"max_age": f"-{max_age_days} days"},
        )

    async def fading_items(self, min_days: int, max_days: int, limit: int) -> list[Row]:
        """(member_type, member_id, title, last_meaningful_at, days_since), oldest first."""
        return await self._all(
            text(
                """
                SELECT 'document' AS t, ca.member_id, d.title AS title,
                       ca.last_meaningful_at,
                       CAST(julianday('now') - julianday(ca.last_meaningful_at)
                            AS INTEGER) AS days_since
                FROM content_activity ca
                JOIN documents d ON d.id = ca.member_id
                WHERE ca.member_type = 'document'
                  AND ca.last_meaningful_at <= datetime('now', :min_days)
                  AND ca.last_meaningful_at >= datetime('now', :max_days)
                UNION ALL
                SELECT 'note' AS t, ca.member_id,
                       COALESCE(NULLIF(n.title, ''), substr(n.content, 1, 60)) AS title,
                       ca.last_meaningful_at,
                       CAST(julianday('now') - julianday(ca.last_meaningful_at)
                            AS INTEGER) AS days_since
                FROM content_activity ca
                JOIN notes n ON n.id = ca.member_id
                WHERE ca.member_type = 'note' AND n.archived = 0
                  AND ca.last_meaningful_at <= datetime('now', :min_days)
                  AND ca.last_meaningful_at >= datetime('now', :max_days)
                ORDER BY last_meaningful_at ASC
                LIMIT :limit
                """
            ),
            {"min_days": f"-{min_days} days", "max_days": f"-{max_days} days", "limit": limit},
        )

    async def week_study_minutes(self) -> float:
        row = await self._first(
            text(
                """
                SELECT COALESCE(
                  SUM(
                    (julianday(ended_at) - julianday(started_at)) * 24 * 60
                  ), 0
                )
                FROM study_sessions
                WHERE ended_at IS NOT NULL
                  AND started_at >= datetime('now', '-7 days')
                """
            )
        )
        return float(row[0] or 0) if row else 0.0

    async def week_cards_reviewed(self) -> int:
        return await self._count(
            "SELECT COUNT(*) FROM review_events WHERE reviewed_at >= datetime('now', '-7 days')"
        )

    async def week_notes_written(self) -> int:
        return await self._count(
            "SELECT COUNT(*) FROM notes "
            "WHERE archived = 0 AND created_at >= datetime('now', '-7 days')"
        )

    async def week_documents_read(self) -> int:
        """Documents read this week, from `reading_progress`.

        Not `content_activity`: adding a document bumps it, so a bulk ingest read as 28
        documents touched in a day.
        """
        return await self._count(
            "SELECT COUNT(DISTINCT document_id) FROM reading_progress "
            "WHERE last_seen_at >= datetime('now', '-7 days')"
        )

    async def _count(self, sql: str) -> int:
        row = await self._first(text(sql))
        return int(row[0] or 0) if row else 0
