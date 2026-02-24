"""Multi-granularity summarization service with map-reduce for large documents."""

import json
import logging
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import select

from app.database import get_session_factory
from app.models import ChunkModel, SummaryModel
from app.services.llm import get_llm_service

logger = logging.getLogger(__name__)

# Grounding prefix applied to every summarization prompt
GROUNDING_PREFIX = (
    "Answer using only information present in the provided text. "
    "Do not introduce any facts, names, or claims not explicitly stated."
)

# Mode-specific instructions appended after the grounding prefix
MODE_INSTRUCTIONS: dict[str, str] = {
    "one_sentence": "Summarize in a single sentence of at most 30 words.",
    "executive": "List the 3 to 5 most important points as bullet points.",
    "detailed": "Summarize each section separately, preserving the heading structure.",
    "conversation": (
        "Output a JSON object with keys: timeline (list of strings), "
        "decisions (list of strings), "
        "action_items (list of objects each with 'owner' and 'task' keys). "
        "Return only valid JSON, no prose."
    ),
}

# Token threshold above which map-reduce is applied
MAP_TOKEN_THRESHOLD = 8000


def _build_system_prompt(mode: str) -> str:
    return f"{GROUNDING_PREFIX}\n\n{MODE_INSTRUCTIONS[mode]}"


class SummarizationService:
    """Summarize a document in multiple granularity modes.

    Call `stream_summary` to get an async generator of SSE-formatted strings::

        async for event in svc.stream_summary(doc_id, "executive", None):
            # event looks like: 'data: {"token": "..."}\n\n'
            ...
    """

    async def _fetch_chunks(self, document_id: str) -> list[ChunkModel]:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(ChunkModel)
                .where(ChunkModel.document_id == document_id)
                .order_by(ChunkModel.chunk_index)
            )
            return list(result.scalars().all())

    async def _store_summary(self, document_id: str, mode: str, content: str) -> str:
        summary_id = str(uuid.uuid4())
        async with get_session_factory()() as session:
            summary = SummaryModel(
                id=summary_id,
                document_id=document_id,
                mode=mode,
                content=content,
            )
            session.add(summary)
            await session.commit()
        return summary_id

    async def _map_sections(
        self,
        chunks: list[ChunkModel],
        model: str | None,
    ) -> str:
        """Map phase: summarize each section independently (non-streaming).

        Groups chunks by section_id, generates a concise section summary for
        each group, then concatenates them as input for the final reduce pass.
        """
        section_groups: dict[str, list[ChunkModel]] = {}
        for chunk in chunks:
            key = chunk.section_id or "default"
            section_groups.setdefault(key, []).append(chunk)

        llm = get_llm_service()
        section_summaries: list[str] = []
        section_system = (
            f"{GROUNDING_PREFIX}\n\n"
            "Summarize this section concisely in 2-3 sentences."
        )
        for section_chunks in section_groups.values():
            section_text = "\n\n".join(c.text for c in section_chunks)
            summary = await llm.generate(section_text, system=section_system, model=model)
            assert isinstance(summary, str)
            section_summaries.append(summary)

        return "\n\n".join(section_summaries)

    async def stream_summary(
        self,
        document_id: str,
        mode: str,
        model: str | None,
    ) -> AsyncGenerator[str]:
        """Async generator of SSE event strings for the given document and mode.

        Yields token events: ``data: {"token": "..."}\n\n``
        Yields final event: ``data: {"done": true, "summary_id": "..."}\n\n``
        """
        chunks = await self._fetch_chunks(document_id)

        total_tokens = sum(c.token_count for c in chunks)
        if total_tokens > MAP_TOKEN_THRESHOLD:
            input_text = await self._map_sections(chunks, model)
        else:
            input_text = "\n\n".join(c.text for c in chunks)

        llm = get_llm_service()
        system = _build_system_prompt(mode)
        token_stream = await llm.generate(input_text, system=system, model=model, stream=True)

        collected: list[str] = []
        async for token in token_stream:
            collected.append(token)
            yield f'data: {json.dumps({"token": token})}\n\n'

        summary_text = "".join(collected)
        summary_id = await self._store_summary(document_id, mode, summary_text)
        yield f'data: {json.dumps({"done": True, "summary_id": summary_id})}\n\n'
