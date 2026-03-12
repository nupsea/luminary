"""Confusion detection service -- surfaces concepts the learner has asked repeatedly.

ConfusionDetectorService.detect:
  1. Query qa_history within lookback window.
  2. Format each question as a chunk dict for GLiNER entity extraction.
  3. Extract named entities; count distinct questions per entity name.
  4. Return top 3 entities with distinct-question count >= threshold, ordered by count desc.
"""

import logging
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import TypedDict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ner import get_entity_extractor

logger = logging.getLogger(__name__)


class ConfusionSignal(TypedDict):
    concept: str
    count: int
    last_asked: str  # ISO datetime string (as stored in SQLite)


class ConfusionDetectorService:
    async def detect(
        self,
        session: AsyncSession,
        lookback_days: int = 30,
        threshold: int = 3,
    ) -> list[ConfusionSignal]:
        """Return entities asked about in >= threshold distinct questions in the lookback window.

        Uses string comparison against SQLite's stored datetime format
        (YYYY-MM-DD HH:MM:SS.ffffff) by formatting the cutoff without timezone.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=lookback_days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        result = await session.execute(
            text(
                "SELECT id, question, created_at FROM qa_history"
                " WHERE created_at >= :cutoff ORDER BY created_at DESC"
            ),
            {"cutoff": cutoff},
        )
        rows = result.fetchall()

        if len(rows) < threshold:
            return []

        # Format each question as a chunk dict. All questions share the same document_id
        # so GLiNER's frequency filter (>= 30 chunks) counts cross-question appearances.
        chunks = [
            {"id": str(row_id), "document_id": "__confusion_detection__", "text": question}
            for row_id, question, created_at in rows
        ]
        id_to_created_at: dict[str, str] = {
            str(row_id): str(created_at) for row_id, question, created_at in rows
        }

        try:
            entities = get_entity_extractor().extract(chunks, content_type="general")
        except Exception as exc:
            logger.warning("GLiNER extraction failed during confusion detection: %s", exc)
            return []

        # Count distinct questions (chunk_ids) per entity name.
        entity_questions: dict[str, set[str]] = {}
        for ent in entities:
            name = ent["name"]
            chunk_id = ent["chunk_id"]
            if name not in entity_questions:
                entity_questions[name] = set()
            entity_questions[name].add(chunk_id)

        signals: list[ConfusionSignal] = [
            ConfusionSignal(
                concept=name,
                count=len(qids),
                last_asked=max(id_to_created_at.get(cid, "") for cid in qids),
            )
            for name, qids in entity_questions.items()
            if len(qids) >= threshold
        ]
        signals.sort(key=lambda s: s["count"], reverse=True)
        return signals[:3]


@lru_cache
def get_confusion_detector() -> ConfusionDetectorService:
    return ConfusionDetectorService()
