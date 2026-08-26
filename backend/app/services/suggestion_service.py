"""Bloom-progressive chat suggestion generation with LLM + dedup"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import func, select, update

from app.config import get_settings
from app.database import get_session_factory
from app.models import ChatSuggestionHistoryModel, ChunkModel, SectionSummaryModel, SummaryModel
from app.services.llm import LLMUnavailableError, get_llm_service
from app.services.llm_admission import YieldedToInteractive, run_yielding_to_interactive
from app.services.prompt_spec import NO_FENCES, PromptSpec, render_for

logger = logging.getLogger(__name__)

# Bloom levels name a depth of understanding; they are NOT phrasing instructions.
# Putting the taxonomy verb in the prompt ("generate questions at level 5
# (Evaluate)") made a small local model write exam papers -- "Evaluate how X's
# reliance on Y can be advantageous", which no reader would ever type, and which
# reads to the intent classifier as a learner's explanation awaiting a grade.
# The level selects a description of what the question should reach for; the word
# itself never leaves this module.
_LEVEL_GUIDANCE = {
    2: "Ask what the main ideas mean and how they work.",
    3: "Ask how the ideas would play out in a specific, concrete situation.",
    4: "Ask how the ideas relate to each other, or why the material makes the choices it does.",
    5: "Ask where an approach breaks down, and what it is traded off against.",
}

_STYLE_RULES = (
    "Write each question the way a curious reader would type it into a chat box: "
    "short, plain, and specific. Do not open with a command verb and do not address "
    "the reader -- a question asks for something, it never assigns a task. "
    "Every question must be answerable from the material shown below; never ask about "
    "something that is not there."
)

SUGGESTION_SPEC = PromptSpec(
    task="suggestions",
    contract=(
        "You are helping someone study a document they are reading. "
        "Write exactly 6 questions they could ask about it.\n"
        "{guidance}\n"
        f"{_STYLE_RULES}\n"
        "These topics are already covered -- prefer different ones: {history}\n\n"
        "Output a JSON array of objects with keys 'question' and 'depth' "
        "(integer, always {bloom_level})."
    ),
    accommodations=(NO_FENCES,),
)

def _system_prompt() -> str:
    return render_for(SUGGESTION_SPEC, "background")

_USER_PROMPT = (
    "Passages from the document:\n{passages}\n\n"
    "Key entities: {entities}\n\n"
    "Write the 6 questions."
)

CROSS_DOC_SUGGESTION_SPEC = PromptSpec(
    task="suggestions_cross_doc",
    contract=(
        "You are helping someone study their own library. Write exactly 6 questions "
        "that connect ideas across the documents shown.\n"
        "{guidance}\n"
        f"{_STYLE_RULES}\n"
        "These topics are already covered -- prefer different ones: {history}\n\n"
        "Output a JSON array of objects with keys 'question' and 'depth' "
        "(integer, always {bloom_level})."
    ),
    accommodations=(NO_FENCES,),
)

def _cross_doc_system() -> str:
    return render_for(CROSS_DOC_SUGGESTION_SPEC, "background")


# Words that carry no subject matter. Only used to reduce past questions to the
# topics they covered -- see _history_topics.
_TOPIC_STOPWORDS: frozenset[str] = frozenset(
    {
        "what", "when", "where", "which", "whose", "does", "define", "extent",
        "that", "this", "these", "those", "there", "their", "them", "they",
        "with", "from", "into", "about", "would", "could", "should", "have",
        "been", "being", "then", "than", "some", "such", "used", "using",
        "your", "ways", "role", "make", "makes", "made", "given", "specific",
        "between", "within", "across", "under", "over", "more", "most", "less",
        "other", "another", "each", "both", "also", "however", "while",
        "explain", "describe", "discuss", "compare", "contrast", "evaluate",
        "assess", "critique", "analyze", "analyse", "summarize", "summarise",
        "important", "significance", "significant", "influence", "impact",
        "advantages", "disadvantages", "effectively", "effective",
    }
)


def _history_topics(history: list[str], limit: int = 20) -> list[str]:
    """Reduce past questions to bare topic words.

    The prompt used to carry the previous questions verbatim under "avoid
    these". On a document with a long history that is dozens of in-context
    exemplars, and a small model copies their register -- which is how exam
    phrasing survived being removed from the instructions. Topics preserve the
    avoid-signal and carry no phrasing to imitate.
    """
    topics: list[str] = []
    for question in history:
        for word in re.findall(r"[a-z][a-z'\-]{3,}", question.lower()):
            if word in _TOPIC_STOPWORDS:
                continue
            if word not in topics:
                topics.append(word)
    return topics[:limit]


def _jaccard_similarity(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _depth_of(item: dict) -> int:
    """Read the level off a parsed item.

    The wire key is 'depth' so the taxonomy word never appears in the prompt;
    'bloom_level' stays accepted because it is the column name and older models
    still echo it.
    """
    raw = item.get("depth", item.get("bloom_level", 2))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 2


def _items_from(result: object) -> list[dict]:
    """Normalise a parsed JSON array into question records."""
    if not isinstance(result, list):
        return []
    return [
        {"question": str(item.get("question", "")), "bloom_level": _depth_of(item)}
        for item in result
        if isinstance(item, dict) and item.get("question")
    ]


def _parse_questions(raw: str) -> list[dict]:
    """Parse LLM JSON output into list of {question, bloom_level}.

    Small local models routinely emit six well-formed objects and then simply
    stop, never closing the array. Strict parsing and the bracket-match fallback
    both need the closing "]", so every one of those responses scored as zero
    candidates and fell back to templates -- the suggestion feature looked like
    it was off. The last stage salvages whole objects from an unterminated array,
    mirroring the truncated-citations salvage in the QA path.
    """
    if not raw:
        return []
    cleaned = re.sub(r"```[^\n]*\n?", "", raw).strip()

    try:
        items = _items_from(json.loads(cleaned))
        if items:
            return items
    except (json.JSONDecodeError, ValueError):
        pass

    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            items = _items_from(json.loads(match.group(0)))
            if items:
                return items
        except (json.JSONDecodeError, ValueError):
            pass

    salvaged: list[dict] = []
    for obj in re.findall(r"\{[^{}]*\}", cleaned):
        try:
            parsed = json.loads(obj)
        except (json.JSONDecodeError, ValueError):
            continue
        salvaged.extend(_items_from([parsed]))
    return salvaged


class SuggestionService:
    """Generates Bloom-progressive, LLM-powered chat suggestions with dedup."""

    async def get_target_bloom_level(self, document_id: str | None) -> int:
        """Question depth: starts at 2, +1 per 4 asked. Ceiling=5.

        The ladder used to run the other way -- a document you had never opened
        led with level 5, so first contact with new material was a demand to
        evaluate it. Depth is earned by engagement, so it climbs.
        """
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

        # Level 6 ("Create") is deliberately unreachable: the chat answers from
        # the learner's own documents, and a create-level task has no grounded
        # answer to retrieve.
        level = 2 + (asked_count // 4)
        return min(level, 5)

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

    async def get_grounding_passages(self, document_id: str, limit: int = 6) -> list[str]:
        """Real text from across the document, for grounding question generation.

        An executive summary alone gives the model a paraphrase to riff on, which
        is how questions came to presuppose framings the document never makes.
        Section summaries are preferred (already condensed, one per section);
        chunks are the fallback for documents ingested before section summaries.

        Sampled evenly across the document rather than taking the first N, so the
        questions are not all drawn from the preface.
        """
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(SectionSummaryModel.heading, SectionSummaryModel.content)
                    .where(SectionSummaryModel.document_id == document_id)
                    .order_by(SectionSummaryModel.unit_index)
                )
            ).all()
            passages = [f"{heading}: {content}" for heading, content in rows if content]

            if not passages:
                chunk_rows = (
                    await session.execute(
                        select(ChunkModel.text)
                        .where(ChunkModel.document_id == document_id)
                        .order_by(ChunkModel.chunk_index)
                    )
                ).all()
                passages = [r[0] for r in chunk_rows if r[0]]

        if len(passages) > limit:
            step = len(passages) / limit
            passages = [passages[int(i * step)] for i in range(limit)]
        return [p[:800] for p in passages]

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
        passages: list[str] | None = None,
    ) -> list[dict]:
        """Call LLM to generate questions at the target depth. Returns parsed list."""
        history = await self.get_recent_history(document_id)
        topics = _history_topics(history)
        history_text = ", ".join(topics) if topics else "(none)"
        guidance = _LEVEL_GUIDANCE.get(target_bloom, _LEVEL_GUIDANCE[2])

        if document_id is not None:
            grounding = "\n\n".join(passages) if passages else summary[:3000]
            system = _system_prompt().format(
                guidance=guidance,
                bloom_level=target_bloom,
                history=history_text,
            )
            user = _USER_PROMPT.format(
                passages=grounding,
                entities=", ".join(entity_names[:10]),
            )
        else:
            system = _cross_doc_system().format(
                guidance=guidance,
                bloom_level=target_bloom,
                history=history_text,
            )
            user = (
                f"Passages from across the documents:\n{summary[:4000]}\n\n"
                f"Key entities: {', '.join(entity_names[:10])}\n\n"
                f"Write the 6 questions."
            )

        try:
            # Abandoned if the user ends up waiting on it. Suggestions are the
            # one LLM call here that is safe to lose: they are regenerable, and
            # an empty return already means "templates answer instead" at both
            # callers. Nothing is persisted until after this returns, so a
            # cancelled call leaves no half-written state.
            raw = await run_yielding_to_interactive(
                get_llm_service().complete(
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.7,
                    background=True,
                ),
                after_seconds=get_settings().LLM_BACKGROUND_YIELD_AFTER_SECONDS,
            )
        except YieldedToInteractive:
            logger.info(
                "suggestions: abandoned for doc=%s so a waiting question could have "
                "the slot; templates answer instead",
                document_id,
            )
            return []
        try:
            candidates = _parse_questions(raw)
            filtered = self.filter_near_duplicates(candidates, history)
            # An empty return falls back to templates at the caller. That fallback
            # was silent, so a model emitting unparseable JSON looked identical to
            # a document with nothing to ask about.
            if not filtered:
                logger.info(
                    "suggestions: no usable candidates for doc=%s "
                    "(parsed=%d, after_dedup=0, raw_chars=%d)",
                    document_id,
                    len(candidates),
                    len(raw or ""),
                )
            return filtered[:6]
        except LLMUnavailableError:
            logger.warning("LLM unavailable for suggestion generation; falling back to templates")
            raise


@lru_cache
def get_suggestion_service() -> SuggestionService:
    return SuggestionService()
