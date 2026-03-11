"""Confusion detection service -- surfaces concepts the learner has asked repeatedly.

ConfusionDetectorService.detect:
  1. Query qa_history within lookback window.
  2. Tokenize each question (lowercase, split on non-alphanumeric, remove stopwords).
  3. Count term frequencies; track the most-recent created_at per term.
  4. Return top 3 terms with count >= threshold as ConfusionSignal, ordered by count desc.
"""

import logging
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import TypedDict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_STOPWORDS: frozenset[str] = frozenset(
    {
        "what", "is", "the", "a", "an", "how", "does", "who", "where", "when", "why",
        "do", "did", "are", "was", "were", "which", "in", "on", "at", "to", "for",
        "of", "and", "or", "not", "i", "me", "my", "this", "that", "it", "its",
        "with", "from", "by", "about", "can", "tell", "explain", "describe",
    }
)


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
        """Return terms asked >= threshold times in the lookback window.

        Uses string comparison against SQLite's stored datetime format
        (YYYY-MM-DD HH:MM:SS.ffffff) by formatting the cutoff without timezone.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=lookback_days)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        result = await session.execute(
            text(
                "SELECT question, created_at FROM qa_history"
                " WHERE created_at >= :cutoff ORDER BY created_at DESC"
            ),
            {"cutoff": cutoff},
        )
        rows = result.fetchall()

        if len(rows) < threshold:
            return []

        term_counts: dict[str, int] = {}
        term_last_asked: dict[str, str] = {}

        for question, created_at in rows:
            tokens = re.split(r"[^a-z0-9]+", question.lower())
            for token in tokens:
                if not token or token in _STOPWORDS:
                    continue
                if token not in term_counts:
                    # Rows are DESC by created_at -- first encounter is most recent.
                    term_last_asked[token] = str(created_at)
                    term_counts[token] = 0
                term_counts[token] += 1

        signals: list[ConfusionSignal] = [
            ConfusionSignal(concept=term, count=count, last_asked=term_last_asked[term])
            for term, count in term_counts.items()
            if count >= threshold
        ]
        signals.sort(key=lambda s: s["count"], reverse=True)
        return signals[:3]


@lru_cache
def get_confusion_detector() -> ConfusionDetectorService:
    return ConfusionDetectorService()
