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

Prompts live in `summary_prompts`, pure assembly in `summary_assembly`, queries in
`repos/summary_repo`, and the library-wide synthesis in `library_summary`.
"""

import json
import logging
from collections.abc import AsyncGenerator

from app.database import get_session_factory
from app.models import ChunkModel, SummaryModel
from app.repos.summary_repo import SummaryRepo
from app.services.llm import get_llm_service
from app.services.section_summarizer import _is_metadata_section
from app.services.summary_assembly import (
    CHARS_PER_TOKEN,
    MAP_BATCH_TOKENS,
    assemble_summary,
    chunk_into_batches,
    section_summary_input,
    split_for_detail,
)
from app.services.summary_prompts import MAP_SYSTEM_PROMPT, build_system_prompt
from app.types import DocumentProfile

logger = logging.getLogger(__name__)

# Tokens reserved inside the context window for the system prompt and the
# generated summary. num_ctx bounds prompt AND generation combined, and Ollama
# truncates the prompt from the FRONT — so an over-budget input silently drops
# the system message and the model free-associates on a tail slice of the text.
_SUMMARY_RESERVE_TOKENS = 2_000


def _summary_num_ctx(model: str | None = None) -> int:
    """The window the summary runs in, and the size of its input budget.

    Resolved from the model rather than from the global window (I-27): the same
    value both requests the window and sizes `_input_token_budget`, so pinning it
    to the global while the model's profile said something else would ask for one
    window, reload the runner, and then truncate the input against the wrong
    number. `None` means the caller let the router choose, which is the summary's
    own role resolution.
    """
    from app.model_registry import context_window_for  # noqa: PLC0415
    from app.services.model_router import resolve  # noqa: PLC0415

    return context_window_for(model or resolve("background").model)


def _input_token_budget() -> int:
    return max(_SUMMARY_RESERVE_TOKENS, _summary_num_ctx() - _SUMMARY_RESERVE_TOKENS)


def _truncate_to_budget(text: str) -> str:
    limit = _input_token_budget() * CHARS_PER_TOKEN
    return text if len(text) <= limit else text[:limit]


# Cap map-reduce at this many batches to bound total LLM call time.
# Large documents are sampled evenly rather than exhaustively processed.
_MAX_MAP_BATCHES = 8

# Per-call timeout (seconds) for map-reduce batch LLM calls.
# Keeps a stuck Ollama call from blocking pregenerate for 10 minutes.
_MAP_CALL_TIMEOUT = 300.0

# Modes pre-generated at ingestion time
PREGENERATE_MODES = ("one_sentence", "executive", "detailed")

# A background call sets the worst-case wait for an Ask that arrives while it is
# generating: Ollama cannot preempt, so the finest yield granularity is one
# completed call (I-31), and the admission gate cannot touch a call it has
# already admitted. In the 2026-08-17 latency pair the slowest Ask in *both*
# arms was waiting on this file's `detailed` call -- 107s and 179s on one
# 24-section document, against 6s and 21s for the two modes that state their own
# length. A generation cap fixes the wait by truncating the summary, which is
# not a trade this makes: the bound comes from call size instead.
_PREGENERATE_MAX_TOKENS = 1_200

# `detailed` asks for exactly what the section summarizer already wrote during
# ingestion -- one summary per section, under its heading, which is the shape
# `_build_section_summary_input` returns and the S82 metadata filter has already
# cleaned. Re-generating it spends the longest call in the pipeline to paraphrase
# text that is already a summary, and the two measured runs disagreed by 2.7x on
# length (1,840 vs 4,991 words) from identical input. Assembling costs nothing,
# drops nothing, and is the summarizer's own wording rather than a paraphrase of
# it.
_ASSEMBLED_MODES = frozenset({"detailed"})

_DETAILED_BATCH_MAX_TOKENS = 1_000


def llm_error_message(exc: Exception) -> str:
    """What to tell the user when a summary's LLM call failed."""
    from app.services.llm_errors import describe  # noqa: PLC0415

    return describe(exc)[1]


class SummarizationService:
    """Summarize a document in multiple granularity modes."""

    async def _fetch_profile(self, document_id: str) -> DocumentProfile | None:
        """What kind of document this is, for the prompt to adapt to.

        None when the row carries no form, and never raises: adapting the prompt
        improves a summary but is not a precondition for having one.
        """
        try:
            async with get_session_factory()() as session:
                row = await SummaryRepo(session).facets(document_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "summary profile lookup failed, using the neutral prompt: %s",
                type(exc).__name__,
                extra={"document_id": document_id},
            )
            return None
        return DocumentProfile.from_row(row)

    async def _fetch_chunks(self, document_id: str) -> list[ChunkModel]:
        async with get_session_factory()() as session:
            return await SummaryRepo(session).chunks(document_id)

    async def _fetch_cached(self, document_id: str, mode: str) -> SummaryModel | None:
        """Return the most recent stored summary for this (document, mode), or None."""
        async with get_session_factory()() as session:
            return await SummaryRepo(session).latest(document_id, mode)

    async def _store_summary(self, document_id: str, mode: str, content: str) -> str | None:
        """Store a summary, or nothing if the document was deleted while it was generated.

        Deleting a document cancels its background summaries, but a call already
        returning can still land here. Returns None when skipped.
        """
        async with get_session_factory()() as session:
            summary_id = await SummaryRepo(session).insert_if_document_exists(
                document_id, mode, content
            )
            await session.commit()
        if summary_id is None:
            logger.info(
                "summary not stored: document was deleted",
                extra={"document_id": document_id, "mode": mode},
            )
        return summary_id

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
        # Strip metadata/legal chunks (license preambles, copyright notices, etc.)
        # before any further processing so they never pollute the summary input.
        filtered = [c for c in chunks if not _is_metadata_section("", c.text)]
        if filtered:
            chunks = filtered

        total_tokens = sum(c.token_count or len(c.text) // CHARS_PER_TOKEN for c in chunks)
        if total_tokens <= _input_token_budget():
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
            batches = chunk_into_batches(chunks)
        else:
            batches = []
            for group_chunks in section_groups.values():
                gt = sum(c.token_count or len(c.text) // CHARS_PER_TOKEN for c in group_chunks)
                if gt > MAP_BATCH_TOKENS:
                    batches.extend(chunk_into_batches(group_chunks))
                else:
                    batches.append(group_chunks)

        # Sample evenly when the document produces too many batches to keep
        # total map-reduce time bounded (each batch call can take 30-90 s on Ollama).
        total_batches = len(batches)
        if total_batches > _MAX_MAP_BATCHES:
            step = total_batches / _MAX_MAP_BATCHES
            batches = [batches[int(i * step)] for i in range(_MAX_MAP_BATCHES)]
            logger.info(
                "Map-reduce: sampled %d/%d batches to stay within batch cap",
                len(batches),
                total_batches,
                extra={"document_id": document_id},
            )

        llm = get_llm_service()
        section_summaries: list[str] = []
        for batch in batches:
            batch_text = "\n\n".join(c.text for c in batch)
            s = await llm.generate(
                batch_text,
                system=MAP_SYSTEM_PROMPT,
                model=model,
                timeout=_MAP_CALL_TIMEOUT,
                background=True,
                num_ctx=_summary_num_ctx(model),
            )
            assert isinstance(s, str)  # noqa: S101
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

    async def _generate_detailed(
        self, input_text: str, model: str | None, profile: DocumentProfile | None = None
    ) -> str:
        """Generate the per-section summary as one bounded call per batch.

        Only reached when no section summaries exist. The batches are joined in
        document order, so the whole input is covered by exactly one call each.
        """
        llm = get_llm_service()
        system = build_system_prompt("detailed", profile)
        parts: list[str] = []
        for batch in split_for_detail(input_text):
            text = await llm.generate(
                batch,
                system=system,
                model=model,
                background=True,
                num_ctx=_summary_num_ctx(model),
                max_tokens=_DETAILED_BATCH_MAX_TOKENS,
            )
            assert isinstance(text, str)  # noqa: S101
            parts.append(text.strip())
        return "\n\n".join(p for p in parts if p)

    async def _build_section_summary_input(self, document_id: str) -> str | None:
        """Section summaries as the fast-path input, or None if too few units exist."""
        async with get_session_factory()() as session:
            rows = await SummaryRepo(session).section_summaries(document_id)
        return section_summary_input(rows)

    async def build_assembled_summary(self, document_id: str, mode: str) -> str | None:
        """`mode` assembled from stored section summaries without an LLM call, or None."""
        async with get_session_factory()() as session:
            rows = await SummaryRepo(session).section_summaries(document_id)
        return assemble_summary(rows, mode)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def stream_summary(
        self,
        document_id: str,
        mode: str,
        model: str | None,
        force_refresh: bool = False,
    ) -> AsyncGenerator[str]:
        """Async generator of SSE event strings.

        Cache-first: if a summary for this (document, mode) already exists in
        the database it is streamed word-by-word without calling the LLM.
        Only falls back to LLM generation when no cached version exists, then
        stores the result so subsequent calls are instant.

        force_refresh=True skips the cache lookup and overwrites the stored
        summary. `detailed` is still assembled from section summaries, so a
        refresh is not an LLM call; the done event's `source` says which it was.

        Yields:
            ``data: {"token": "..."}\\n\\n``  — one word at a time
            ``data: {"done": true, "summary_id": "...", "source": "..."}\\n\\n``  — final
            event; source is cached|assembled|generated, and `generated` names the `model`
            ``data: {"error": "llm_unavailable", ...}\\n\\n``  — on LLM failure
        """
        try:
            cached = None if force_refresh else await self._fetch_cached(document_id, mode)
            if cached is not None:
                logger.info(
                    "Serving cached summary",
                    extra={"document_id": document_id, "mode": mode},
                )
                # Send full content in a single event — no word-by-word drip
                yield f"data: {json.dumps({'token': cached.content})}\n\n"
                done_evt = {
                    "done": True,
                    "summary_id": cached.id,
                    "cached": True,
                    "source": "cached",
                }
                yield f"data: {json.dumps(done_evt)}\n\n"
                return

            # No cached version — prefer section summary fast path (metadata already
            # filtered by SectionSummarizerService).  Fall back to chunk map-reduce only
            # when section summaries are absent (old V1 documents, ingestion failures).
            section_input = await self._build_section_summary_input(document_id)
            if section_input is not None:
                input_text = section_input
                logger.info(
                    "stream_summary: using section summary fast path (%d chars)",
                    len(input_text),
                    extra={"document_id": document_id, "mode": mode},
                )
            else:
                chunks = await self._fetch_chunks(document_id)
                input_text = await self._build_input_text(document_id, chunks, model)

            if mode in _ASSEMBLED_MODES:
                # Same rule as pregenerate, so a refresh cannot replace the
                # assembled per-section text with a paraphrase of it. Neither
                # branch streams, so the summary is sent as one event exactly as
                # the cache path above does.
                assembled = await self.build_assembled_summary(document_id, mode)
                source = "assembled"
                if assembled is not None:
                    text = assembled
                elif section_input is not None:
                    text = section_input
                else:
                    text = await self._generate_detailed(
                        _truncate_to_budget(input_text),
                        model,
                        await self._fetch_profile(document_id),
                    )
                    source = "generated"
                summary_id = await self._store_summary(document_id, mode, text)
                yield f"data: {json.dumps({'token': text})}\n\n"
                done_evt = {
                    "done": True,
                    "summary_id": summary_id,
                    "cached": False,
                    "source": source,
                }
                yield f"data: {json.dumps(done_evt)}\n\n"
                return

            # A first request is answered from the section summaries; an explicit
            # refresh is the way to ask the LLM to synthesise instead.
            if mode == "executive" and section_input is not None and not force_refresh:
                assembled_exec = await self.build_assembled_summary(document_id, "executive")
                if assembled_exec is not None:
                    summary_id = await self._store_summary(document_id, mode, assembled_exec)
                    yield f"data: {json.dumps({'token': assembled_exec})}\n\n"
                    done_evt = {
                        "done": True,
                        "summary_id": summary_id,
                        "cached": False,
                        "source": "assembled",
                    }
                    yield f"data: {json.dumps(done_evt)}\n\n"
                    return

            llm = get_llm_service()
            system = build_system_prompt(mode, await self._fetch_profile(document_id))
            token_stream = await llm.generate(
                _truncate_to_budget(input_text),
                system=system,
                model=model,
                stream=True,
                num_ctx=_summary_num_ctx(model),
            )

            collected: list[str] = []
            async for token in token_stream:
                collected.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"

            summary_text = "".join(collected)
            summary_id = await self._store_summary(document_id, mode, summary_text)
            done_evt = {
                "done": True,
                "summary_id": summary_id,
                "cached": False,
                "source": "generated",
                # Read after the stream: an offline fallback changes who wrote it.
                "model": getattr(token_stream, "model", None),
            }
            yield f"data: {json.dumps(done_evt)}\n\n"

        except Exception as exc:
            logger.warning(
                "stream_summary failed",
                extra={"document_id": document_id, "mode": mode},
                exc_info=exc,
            )
            err_evt = {"error": "llm_unavailable", "message": llm_error_message(exc), "done": True}
            yield f"data: {json.dumps(err_evt)}\n\n"

    async def generate_all_summaries(
        self,
        document_id: str,
        model: str | None = None,
        modes: tuple[str, ...] | None = None,
    ) -> None:
        """Public entry point for background summary generation.

        Generates one_sentence, executive, and detailed summaries sequentially.
        Delegates to pregenerate which handles caching and error isolation.
        """
        await self.pregenerate(document_id, model, modes=modes)

    async def pregenerate(
        self,
        document_id: str,
        model: str | None = None,
        modes: tuple[str, ...] | None = None,
        *,
        refresh: bool = False,
    ) -> None:
        """Pre-generate and store summaries for PREGENERATE_MODES.

        Called during ingestion so summaries are ready when the user first opens
        a document.  Skips any mode that already has a cached summary, unless
        `refresh`: then a new version replaces it, as when more sections exist.
        Failures are logged and suppressed — a missing pre-generated summary is
        not a reason to fail ingestion.

        Fast path (V2): when >= 3 section summaries exist (written by S75), each
        mode is one LLM call on the concatenated section summaries.  Input is
        cached as mode='_section_reduce' for reuse across modes.

        Slow path (V1 / no section summaries): existing chunk-based map-reduce.
        The map-reduce result (_build_input_text) is run once and shared across
        all modes so large documents don't pay the cost of multiple sequential
        map passes.
        """
        try:
            # Fetched once: every mode in this call summarises the same document.
            profile = await self._fetch_profile(document_id)
            # Determine which modes still need generation
            target_modes = modes if modes is not None else PREGENERATE_MODES
            modes_needed = []
            for mode in target_modes:
                cached = None if refresh else await self._fetch_cached(document_id, mode)
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

            # Fast path: use section summaries when >= 3 units available
            section_input = await self._build_section_summary_input(document_id)

            if section_input is not None:
                # Cache the already-filtered section summaries as _section_reduce for
                # reuse across modes within this pregenerate() call.
                # NOTE: do NOT fall back to a previously cached _section_reduce row —
                # that row may pre-date the S82 metadata filter and could contain
                # Gutenberg/license content.  Always use the freshly filtered
                # section_input returned by _build_section_summary_input().
                cached_sr = await self._fetch_cached(document_id, "_section_reduce")
                if cached_sr is None:
                    await self._store_summary(document_id, "_section_reduce", section_input)
                    logger.info(
                        "pregenerate: stored _section_reduce",
                        extra={"document_id": document_id},
                    )
                # section_input is already the filtered value — do not overwrite it
                # with cached_sr.content, which could be a pre-filter cache entry.

                input_text = section_input
                logger.info(
                    "pregenerate: using section summary fast path (%d chars)",
                    len(input_text),
                    extra={"document_id": document_id},
                )
            else:
                # Slow path: chunk-based map-reduce
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
                logger.info(
                    "pregenerate: using chunk map-reduce slow path",
                    extra={"document_id": document_id},
                )

            llm = get_llm_service()

            for mode in modes_needed:
                try:
                    if mode in _ASSEMBLED_MODES and section_input is not None:
                        assembled = await self.build_assembled_summary(document_id, mode)
                        text = assembled if assembled is not None else section_input
                    elif mode in _ASSEMBLED_MODES:
                        text = await self._generate_detailed(
                            _truncate_to_budget(input_text), model, profile
                        )
                    else:
                        text = await llm.generate(
                            _truncate_to_budget(input_text),
                            system=build_system_prompt(mode, profile),
                            model=model,
                            background=True,
                            num_ctx=_summary_num_ctx(model),
                            max_tokens=_PREGENERATE_MAX_TOKENS,
                        )
                    assert isinstance(text, str)  # noqa: S101
                    if await self._store_summary(document_id, mode, text) is None:
                        return
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

    async def invalidate_section_reduce_cache(self, document_id: str) -> None:
        """Delete the '_section_reduce' summary row so pregenerate() recomputes it."""
        async with get_session_factory()() as session:
            await SummaryRepo(session).delete_mode(document_id, "_section_reduce")
            await session.commit()
        logger.info("_section_reduce cache invalidated", extra={"document_id": document_id})


_summarization_service: SummarizationService | None = None


def get_summarization_service() -> SummarizationService:
    global _summarization_service
    if _summarization_service is None:
        _summarization_service = SummarizationService()
    return _summarization_service
