"""Multi-granularity summarization service with map-reduce for large documents.

Summary generation is expensive (multiple sequential LLM calls for large docs).
To avoid re-running the LLM on every user request:

- `stream_summary`: cache-first — returns the stored summary instantly if one
  exists for this (document, mode) pair, streaming it word-by-word in the same
  SSE format so the frontend needs no changes.  Falls back to LLM + store only
  when no cached version exists.

- `pregenerate`: non-streaming version called during ingestion.  Generates and
  persists one_sentence + executive modes so they are ready when the user first
  opens a document.
"""

import json
import logging
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import delete, select

from app.database import get_session_factory
from app.models import ChunkModel, DocumentModel, LibrarySummaryModel, SummaryModel
from app.services.llm import get_llm_service

logger = logging.getLogger(__name__)

# Grounding prefix applied to every summarization prompt
GROUNDING_PREFIX = "Answer using only information present in the provided text."

_MARKDOWN_INSTRUCTION = (
    "Format your response using Markdown. "
    "Use ## headings, **bold**, bullet lists, and `code` spans where appropriate."
)

# Mode-specific instructions appended after the grounding prefix
MODE_INSTRUCTIONS: dict[str, str] = {
    "one_sentence": "Summarize in a single sentence of at most 30 words.",
    "executive": (
        f"List the 3 to 5 most important points as bullet points. {_MARKDOWN_INSTRUCTION}"
    ),
    "detailed": (
        "Summarize each section separately, preserving the heading structure. "
        f"{_MARKDOWN_INSTRUCTION}"
    ),
    "conversation": (
        'Output a JSON object with keys: "timeline" (list of strings), '
        '"decisions" (list of strings), '
        '"action_items" (list of objects with "owner" and "task" keys).'
    ),
}

# Token threshold above which map-reduce is applied
MAP_TOKEN_THRESHOLD = 8000

# Max tokens per map call — stays within mistral's 8K context with room for output
_MAP_BATCH_TOKENS = 3_000

# Modes pre-generated at ingestion time
PREGENERATE_MODES = ("one_sentence", "executive", "detailed")

# System prompts for library-level synthesis
LIBRARY_SYSTEM_PROMPTS: dict[str, str] = {
    "one_sentence": "Synthesize all documents in one sentence of at most 30 words.",
    "executive": (
        "List the 5-7 key themes across all documents as bullet points. "
        f"Note connections between them. {_MARKDOWN_INSTRUCTION}"
    ),
    "detailed": (
        "Write a structured overview: main themes, key documents, "
        f"and how they relate to each other. {_MARKDOWN_INSTRUCTION}"
    ),
}


def _build_system_prompt(mode: str) -> str:
    return f"{GROUNDING_PREFIX}\n\n{MODE_INSTRUCTIONS[mode]}"


class SummarizationService:
    """Summarize a document in multiple granularity modes."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_chunks(self, document_id: str) -> list[ChunkModel]:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(ChunkModel)
                .where(ChunkModel.document_id == document_id)
                .order_by(ChunkModel.chunk_index)
            )
            return list(result.scalars().all())

    async def _fetch_cached(self, document_id: str, mode: str) -> SummaryModel | None:
        """Return the most recent stored summary for this (document, mode), or None."""
        async with get_session_factory()() as session:
            result = await session.execute(
                select(SummaryModel)
                .where(SummaryModel.document_id == document_id)
                .where(SummaryModel.mode == mode)
                .order_by(SummaryModel.created_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def _store_summary(self, document_id: str, mode: str, content: str) -> str:
        summary_id = str(uuid.uuid4())
        async with get_session_factory()() as session:
            session.add(
                SummaryModel(
                    id=summary_id,
                    document_id=document_id,
                    mode=mode,
                    content=content,
                )
            )
            await session.commit()
        return summary_id

    def _chunk_into_batches(self, chunks: list[ChunkModel]) -> list[list[ChunkModel]]:
        """Split chunks into token-capped batches for map-reduce."""
        batches: list[list[ChunkModel]] = []
        current: list[ChunkModel] = []
        current_tokens = 0
        for chunk in chunks:
            t = chunk.token_count or len(chunk.text) // 4
            if current and current_tokens + t > _MAP_BATCH_TOKENS:
                batches.append(current)
                current = []
                current_tokens = 0
            current.append(chunk)
            current_tokens += t
        if current:
            batches.append(current)
        return batches

    async def _build_input_text(
        self, document_id: str, chunks: list[ChunkModel], model: str | None
    ) -> str:
        """Return reduced text ready for the final summarization call.

        For small documents: join all chunk texts directly.
        For large documents: run map-reduce (one LLM call per batch of chunks).
        The map-reduce result is stored as a '_map_reduce' pseudo-mode so that
        subsequent calls (e.g. on-demand detailed/conversation) skip the expensive
        map step entirely.
        """
        total_tokens = sum(c.token_count or len(c.text) // 4 for c in chunks)
        if total_tokens <= MAP_TOKEN_THRESHOLD:
            return "\n\n".join(c.text for c in chunks)

        # Return cached intermediate text if already computed for this document
        cached_map = await self._fetch_cached(document_id, "_map_reduce")
        if cached_map is not None:
            logger.debug(
                "Map-reduce: using cached intermediate text",
                extra={"document_id": document_id},
            )
            return cached_map.content

        # Build section groups; fall back to flat batches when unsectioned
        section_groups: dict[str, list[ChunkModel]] = {}
        for chunk in chunks:
            key = chunk.section_id or "default"
            section_groups.setdefault(key, []).append(chunk)

        if list(section_groups.keys()) == ["default"]:
            batches = self._chunk_into_batches(chunks)
        else:
            batches = []
            for group_chunks in section_groups.values():
                gt = sum(c.token_count or len(c.text) // 4 for c in group_chunks)
                if gt > _MAP_BATCH_TOKENS:
                    batches.extend(self._chunk_into_batches(group_chunks))
                else:
                    batches.append(group_chunks)

        llm = get_llm_service()
        section_system = f"{GROUNDING_PREFIX}\n\nSummarize this passage concisely in 2-3 sentences."
        section_summaries: list[str] = []
        for batch in batches:
            batch_text = "\n\n".join(c.text for c in batch)
            s = await llm.generate(batch_text, system=section_system, model=model)
            assert isinstance(s, str)
            section_summaries.append(s)

        result = "\n\n".join(section_summaries)
        logger.info(
            "Map-reduce: %d batches → %d section summaries",
            len(batches),
            len(section_summaries),
        )

        # Cache the intermediate text so future modes skip the map step
        await self._store_summary(document_id, "_map_reduce", result)
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def stream_summary(
        self,
        document_id: str,
        mode: str,
        model: str | None,
    ) -> AsyncGenerator[str]:
        """Async generator of SSE event strings.

        Cache-first: if a summary for this (document, mode) already exists in
        the database it is streamed word-by-word without calling the LLM.
        Only falls back to LLM generation when no cached version exists, then
        stores the result so subsequent calls are instant.

        Yields:
            ``data: {"token": "..."}\\n\\n``  — one word at a time
            ``data: {"done": true, "summary_id": "..."}\\n\\n``  — final event
            ``data: {"error": "llm_unavailable", ...}\\n\\n``  — on LLM failure
        """
        try:
            cached = await self._fetch_cached(document_id, mode)
            if cached is not None:
                logger.info(
                    "Serving cached summary",
                    extra={"document_id": document_id, "mode": mode},
                )
                # Send full content in a single event — no word-by-word drip
                yield f'data: {json.dumps({"token": cached.content})}\n\n'
                done_evt = {"done": True, "summary_id": cached.id, "cached": True}
                yield f"data: {json.dumps(done_evt)}\n\n"
                return

            # No cached version — run LLM generation
            chunks = await self._fetch_chunks(document_id)
            input_text = await self._build_input_text(document_id, chunks, model)

            llm = get_llm_service()
            system = _build_system_prompt(mode)
            token_stream = await llm.generate(input_text, system=system, model=model, stream=True)

            collected: list[str] = []
            async for token in token_stream:
                collected.append(token)
                yield f'data: {json.dumps({"token": token})}\n\n'

            summary_text = "".join(collected)
            summary_id = await self._store_summary(document_id, mode, summary_text)
            done_evt = {"done": True, "summary_id": summary_id, "cached": False}
            yield f"data: {json.dumps(done_evt)}\n\n"

        except Exception as exc:
            logger.warning(
                "stream_summary failed",
                extra={"document_id": document_id, "mode": mode},
                exc_info=exc,
            )
            err_evt = {
                "error": "llm_unavailable",
                "message": "Ollama is not running. Start it with: ollama serve",
                "done": True,
            }
            yield f"data: {json.dumps(err_evt)}\n\n"

    async def generate_all_summaries(self, document_id: str, model: str | None = None) -> None:
        """Public entry point for background summary generation.

        Generates one_sentence, executive, and detailed summaries sequentially.
        Delegates to pregenerate which handles caching and error isolation.
        """
        await self.pregenerate(document_id, model)

    async def pregenerate(self, document_id: str, model: str | None = None) -> None:
        """Pre-generate and store summaries for PREGENERATE_MODES.

        Called during ingestion so summaries are ready when the user first opens
        a document.  Skips any mode that already has a cached summary.
        Failures are logged and suppressed — a missing pre-generated summary is
        not a reason to fail ingestion.

        The map-reduce step (_build_input_text) is run once and shared across all
        modes so large documents don't pay the cost of multiple sequential map passes.
        """
        try:
            # Determine which modes still need generation
            modes_needed = []
            for mode in PREGENERATE_MODES:
                cached = await self._fetch_cached(document_id, mode)
                if cached is not None:
                    logger.debug(
                        "pregenerate: mode=%s already cached, skipping",
                        mode,
                        extra={"document_id": document_id},
                    )
                else:
                    modes_needed.append(mode)

            if not modes_needed:
                return

            chunks = await self._fetch_chunks(document_id)
            if not chunks:
                logger.warning(
                    "pregenerate: no chunks found",
                    extra={"document_id": document_id},
                )
                return

            # Build input text once — map-reduce is expensive (many LLM calls for
            # large documents); sharing it across modes avoids running it N times.
            input_text = await self._build_input_text(document_id, chunks, model)
            llm = get_llm_service()

            for mode in modes_needed:
                try:
                    system = _build_system_prompt(mode)
                    text = await llm.generate(input_text, system=system, model=model)
                    assert isinstance(text, str)
                    await self._store_summary(document_id, mode, text)
                    logger.info(
                        "pregenerate: stored mode=%s",
                        mode,
                        extra={"document_id": document_id},
                    )
                except Exception as exc:
                    logger.warning(
                        "pregenerate: mode=%s failed (non-fatal)",
                        mode,
                        extra={"document_id": document_id},
                        exc_info=exc,
                    )
        except Exception as exc:
            logger.warning(
                "pregenerate: setup failed (non-fatal)",
                extra={"document_id": document_id},
                exc_info=exc,
            )


    # ------------------------------------------------------------------
    # Library-level summary (cross-document synthesis)
    # ------------------------------------------------------------------

    async def _fetch_library_cached(self, mode: str) -> LibrarySummaryModel | None:
        """Return the most recent LibrarySummaryModel for this mode, or None."""
        async with get_session_factory()() as session:
            result = await session.execute(
                select(LibrarySummaryModel)
                .where(LibrarySummaryModel.mode == mode)
                .order_by(LibrarySummaryModel.created_at.desc())
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def _store_library_summary(self, mode: str, content: str) -> str:
        summary_id = str(uuid.uuid4())
        async with get_session_factory()() as session:
            session.add(
                LibrarySummaryModel(id=summary_id, mode=mode, content=content)
            )
            await session.commit()
        return summary_id

    async def _fetch_all_executive_summaries(self) -> dict[str, str]:
        """Return most-recent executive summary content keyed by document_id."""
        async with get_session_factory()() as session:
            rows = await session.execute(
                select(SummaryModel.document_id, SummaryModel.content, SummaryModel.created_at)
                .where(SummaryModel.mode == "executive")
                .order_by(SummaryModel.created_at.desc())
            )
            seen: set[str] = set()
            summaries: dict[str, str] = {}
            for row in rows:
                if row.document_id not in seen:
                    seen.add(row.document_id)
                    summaries[row.document_id] = row.content
        return summaries

    def _get_cross_doc_entities(self, min_docs: int = 3, limit: int = 20) -> list[str]:
        """Query Kuzu for entity names appearing in min_docs or more documents.

        Returns an empty list if Kuzu is unavailable or no entities qualify.
        """
        try:
            from app.services.graph import get_graph_service  # noqa: PLC0415

            conn = get_graph_service()._conn
            result = conn.execute(
                "MATCH (e:Entity)-[:MENTIONED_IN]->(d:Document)"
                " WITH e.name AS name, COUNT(DISTINCT d.id) AS doc_count"
                " WHERE doc_count >= $min"
                " RETURN name"
                " ORDER BY doc_count DESC"
                " LIMIT $lim",
                {"min": min_docs, "lim": limit},
            )
            names: list[str] = []
            while result.has_next():
                row = result.get_next()
                if row[0]:
                    names.append(row[0])
            return names
        except Exception:
            logger.warning("_get_cross_doc_entities: Kuzu query failed", exc_info=True)
            return []

    async def stream_library_summary(
        self,
        mode: str,
        model: str | None,
    ) -> AsyncGenerator[str]:
        """Synthesize a holistic summary across all ingested documents.

        Cache-first: if a LibrarySummaryModel for this mode already exists it is
        streamed as a single token event.  On cache miss, fetches executive summaries
        from all documents, queries Kuzu for cross-doc entities, builds input text,
        and generates via LLM.

        Yields:
            ``data: {"token": "..."}\\n\\n``  — one or more token events
            ``data: {"done": true, ...}\\n\\n``  — final event with cached flag
            ``data: {"error": "not_enough_summaries", ...}\\n\\n``  — when < 2 docs
        """
        try:
            # Cache-first
            cached = await self._fetch_library_cached(mode)
            if cached is not None:
                logger.info("Serving cached library summary", extra={"mode": mode})
                yield f'data: {json.dumps({"token": cached.content})}\n\n'
                done_evt = {"done": True, "summary_id": cached.id, "cached": True}
                yield f"data: {json.dumps(done_evt)}\n\n"
                return

            # Fetch executive summaries per document
            exec_summaries = await self._fetch_all_executive_summaries()

            if len(exec_summaries) < 2:
                yield (
                    'data: {"error": "not_enough_summaries", '
                    '"message": "Ingest at least 2 documents to generate a library overview.", '
                    '"done": true}\n\n'
                )
                return

            # Fetch document titles
            doc_ids = list(exec_summaries.keys())
            async with get_session_factory()() as session:
                rows = await session.execute(
                    select(DocumentModel.id, DocumentModel.title).where(
                        DocumentModel.id.in_(doc_ids)
                    )
                )
                titles = {row.id: row.title for row in rows}

            # Build input text ordered by title
            ordered = sorted(doc_ids, key=lambda did: titles.get(did, ""))
            parts = [
                f"## {titles.get(did, did)}\n{exec_summaries[did]}" for did in ordered
            ]

            # Cross-doc entities from Kuzu (non-fatal)
            entity_names = self._get_cross_doc_entities()
            if entity_names:
                parts.append(f"## Shared themes\n{', '.join(entity_names)}")

            input_text = "\n\n".join(parts)
            system = LIBRARY_SYSTEM_PROMPTS.get(mode, LIBRARY_SYSTEM_PROMPTS["executive"])

            llm = get_llm_service()
            token_stream = await llm.generate(input_text, system=system, model=model, stream=True)

            collected: list[str] = []
            async for token in token_stream:
                collected.append(token)
                yield f'data: {json.dumps({"token": token})}\n\n'

            summary_text = "".join(collected)
            summary_id = await self._store_library_summary(mode, summary_text)
            done_evt = {"done": True, "summary_id": summary_id, "cached": False}
            yield f"data: {json.dumps(done_evt)}\n\n"

        except Exception as exc:
            logger.warning("stream_library_summary failed", exc_info=exc)
            err_evt = {
                "error": "llm_unavailable",
                "message": "Ollama is not running. Start it with: ollama serve",
                "done": True,
            }
            yield f"data: {json.dumps(err_evt)}\n\n"

    async def invalidate_library_cache(self) -> None:
        """Delete all LibrarySummaryModel rows so the next call regenerates."""
        async with get_session_factory()() as session:
            await session.execute(delete(LibrarySummaryModel))
            await session.commit()
        logger.info("library summary cache invalidated")


_summarization_service: SummarizationService | None = None


def get_summarization_service() -> SummarizationService:
    global _summarization_service
    if _summarization_service is None:
        _summarization_service = SummarizationService()
    return _summarization_service
