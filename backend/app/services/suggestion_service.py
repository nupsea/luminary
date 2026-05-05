"""Bloom-progressive chat suggestion generation with LLM + dedup (S195)."""

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import func, select, update

from app.database import get_session_factory
from app.models import ChatSuggestionHistoryModel, SummaryModel
from app.services.llm import LLMUnavailableError, get_llm_service

logger = logging.getLogger(__name__)

_BLOOM_LABELS = {
    6: "Create",
    5: "Evaluate",
    4: "Analyze",
    3: "Apply",
    2: "Understand",
    1: "Remember",
}

_SYSTEM_PROMPT = (
    "You are an expert tutor generating study questions about a book or document. "
    "Given a summary and key entities, generate exactly 6 questions at Bloom taxonomy "
    "level {bloom_level} ({bloom_label}). "
    "Avoid these previously asked questions:\n{history}\n\n"
    "Output ONLY a JSON array of objects with keys 'question' and 'bloom_level' (integer). "
    'Example: [{{"question": "...", "bloom_level": 5}}]. '
    "No explanation, no markdown fences."
)

_USER_PROMPT = (
    "Document summary:\n{summary}\n\n"
    "Key entities: {entities}\n\n"
    "Generate 6 questions at Bloom level {bloom_level} ({bloom_label})."
)

_CROSS_DOC_SYSTEM = (
    "You are an expert tutor generating cross-document analytical questions. "
    "Given summaries from multiple documents and key entities, generate exactly 6 "
    "questions at Bloom taxonomy level {bloom_level} ({bloom_label}) that connect "
    "ideas across documents. "
    "Avoid these previously asked questions:\n{history}\n\n"
    "Output ONLY a JSON array of objects with keys 'question' and 'bloom_level' (integer). "
    "No explanation, no markdown fences."
)


def _jaccard_similarity(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _parse_questions(raw: str) -> list[dict]:
    """Parse LLM JSON output into list of {question, bloom_level}."""
    if not raw:
        return []
    cleaned = re.sub(r"```[^\n]*\n?", "", raw).strip()
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return [
                {
                    "question": str(item.get("question", "")),
                    "bloom_level": int(item.get("bloom_level", 5)),
                }
                for item in result
                if isinstance(item, dict) and item.get("question")
            ]
    except (json.JSONDecodeError, ValueError):
        pass
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return [
                    {
                        "question": str(item.get("question", "")),
                        "bloom_level": int(item.get("bloom_level", 5)),
                    }
                    for item in result
                    if isinstance(item, dict) and item.get("question")
                ]
        except (json.JSONDecodeError, ValueError):
            pass
    return []


class SuggestionService:
    """Generates Bloom-progressive, LLM-powered chat suggestions with dedup."""

    async def get_target_bloom_level(self, document_id: str | None) -> int:
        """Bloom level: starts at 5, -1 per 4 asked. Floor=2."""
        factory = get_session_factory()
        async with factory() as session:
            query = (
                select(func.count())
                .select_from(ChatSuggestionHistoryModel)
                .where(
                    ChatSuggestionHistoryModel.was_asked.is_(True),
                )
            )
            if document_id is not None:
                query = query.where(ChatSuggestionHistoryModel.document_id == document_id)
            else:
                query = query.where(ChatSuggestionHistoryModel.document_id.is_(None))
            asked_count = (await session.execute(query)).scalar() or 0

        level = 5 - (asked_count // 4)
        return max(level, 2)

    async def get_recent_history(self, document_id: str | None, limit: int = 50) -> list[str]:
        """Return recent suggestion texts for dedup."""
        factory = get_session_factory()
        async with factory() as session:
            query = (
                select(ChatSuggestionHistoryModel.suggestion_text)
                .where(ChatSuggestionHistoryModel.document_id == document_id)
                .order_by(ChatSuggestionHistoryModel.shown_at.desc())
                .limit(limit)
            )
            result = await session.execute(query)
            return [row[0] for row in result.all()]

    async def get_executive_summary(self, document_id: str) -> str | None:
        """Fetch executive summary for a document."""
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(SummaryModel.content)
                .where(SummaryModel.document_id == document_id, SummaryModel.mode == "executive")
                .order_by(SummaryModel.created_at.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return row

    async def get_multi_doc_summaries(self, limit: int = 5) -> str:
        """Fetch executive summaries from multiple documents for cross-doc context."""
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(SummaryModel.content)
                .where(SummaryModel.mode == "executive")
                .order_by(SummaryModel.created_at.desc())
                .limit(limit)
            )
            summaries = [row[0] for row in result.all()]
            return "\n---\n".join(summaries) if summaries else ""

    def filter_near_duplicates(
        self,
        candidates: list[dict],
        history: list[str],
        threshold: float = 0.7,
    ) -> list[dict]:
        """Remove candidates that are near-duplicates of history items."""
        filtered = []
        for c in candidates:
            q = c["question"]
            is_dup = any(_jaccard_similarity(q, h) > threshold for h in history)
            if not is_dup:
                filtered.append(c)
        return filtered

    async def persist_shown(
        self,
        suggestions: list[dict],
        document_id: str | None,
    ) -> list[dict]:
        """Persist shown suggestions to history and return with IDs."""
        factory = get_session_factory()
        results = []
        async with factory() as session:
            for s in suggestions:
                row_id = str(uuid.uuid4())
                row = ChatSuggestionHistoryModel(
                    id=row_id,
                    document_id=document_id,
                    suggestion_text=s["question"],
                    bloom_level=s["bloom_level"],
                    was_asked=False,
                    shown_at=datetime.now(UTC),
                    session_id=None,
                )
                session.add(row)
                results.append({"id": row_id, "text": s["question"]})
            await session.commit()
        return results

    async def mark_asked(self, suggestion_id: str) -> bool:
        """Mark a suggestion as asked. Returns True if found."""
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                update(ChatSuggestionHistoryModel)
                .where(ChatSuggestionHistoryModel.id == suggestion_id)
                .values(was_asked=True)
            )
            await session.commit()
            return result.rowcount > 0

    async def generate_suggestions(
        self,
        document_id: str | None,
        summary: str,
        entity_names: list[str],
        target_bloom: int,
    ) -> list[dict]:
        """Call LLM to generate Bloom-level questions. Returns parsed list."""
        history = await self.get_recent_history(document_id)
        history_text = "\n".join(f"- {h}" for h in history) if history else "(none)"
        bloom_label = _BLOOM_LABELS.get(target_bloom, "Evaluate")

        if document_id is not None:
            system = _SYSTEM_PROMPT.format(
                bloom_level=target_bloom,
                bloom_label=bloom_label,
                history=history_text,
            )
            user = _USER_PROMPT.format(
                summary=summary[:3000],
                entities=", ".join(entity_names[:10]),
                bloom_level=target_bloom,
                bloom_label=bloom_label,
            )
        else:
            system = _CROSS_DOC_SYSTEM.format(
                bloom_level=target_bloom,
                bloom_label=bloom_label,
                history=history_text,
            )
            user = (
                f"Document summaries:\n{summary[:4000]}\n\n"
                f"Key entities: {', '.join(entity_names[:10])}\n\n"
                f"Generate 6 cross-document questions at Bloom level "
                f"{target_bloom} ({bloom_label})."
            )

        try:
            raw = await get_llm_service().complete(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.7,
            )
            candidates = _parse_questions(raw)
            filtered = self.filter_near_duplicates(candidates, history)
            return filtered[:6]
        except LLMUnavailableError:
            logger.warning("LLM unavailable for suggestion generation; falling back to templates")
            raise


@lru_cache
def get_suggestion_service() -> SuggestionService:
    return SuggestionService()
