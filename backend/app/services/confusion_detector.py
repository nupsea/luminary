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

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Base: sklearn's 318 English function words.
# Extended with app-specific noise: UI suggestion verbs (summarize, quiz, compare),
# generic learning vocabulary (themes, findings, concepts), and document-structural
# words (book, chapter, section).  These are content words that carry no signal
# about what the *learner* is confused about -- they appear in every question.
# Per core-belief #23: UI surface inputs must be tested against the classifier
# that handles them; this list must cover every word in Chat.tsx EXAMPLE_QUESTIONS.
_APP_STOPWORDS: frozenset[str] = frozenset(
    {
        # UI suggestion verbs (appear in Chat.tsx EXAMPLE_QUESTIONS / pill labels)
        "summarize", "summary", "quiz", "compare", "list", "review", "help",
        # Generic learning vocabulary
        "main", "key", "themes", "theme", "findings", "finding",
        "conclusions", "conclusion", "ideas", "idea", "concepts", "concept",
        "points", "point", "topics", "topic",
        # Document-structural words
        "book", "chapter", "text", "section", "passage", "document", "doc",
        "content", "read", "reading", "notes", "note", "gaps", "gap",
    }
)

_STOPWORDS: frozenset[str] = frozenset(ENGLISH_STOP_WORDS) | _APP_STOPWORDS


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
