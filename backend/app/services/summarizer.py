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
from app.models import (
    ChunkModel,
    DocumentModel,
    LibrarySummaryModel,
    SectionSummaryModel,
    SummaryModel,
)
from app.services.llm import LLMAuthenticationError, get_llm_service
from app.services.section_summarizer import _is_metadata_section
from app.types import DocumentProfile

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
        "Identify the 3 to 5 most important ideas that run through the entire work. "
        "Write each as a concise bullet point. "
        "Do NOT list individual chapter or passage summaries — synthesise across them. "
        "Ignore copyright notices, licensing terms, and distribution metadata. "
        f"{_MARKDOWN_INSTRUCTION}"
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
    # A recorded talk has no decisions and no owners. Asking for them returns
    # empty lists, which is why this mode was hidden from anything but a
    # meeting rather than adapted (#104).
    "conversation_talk": (
        'Output a JSON object with keys: "timeline" (list of strings), '
        '"points" (list of strings: the techniques, tools and claims covered), '
        '"references" (list of strings: anything named that a listener would '
        "look up afterwards)."
    ),
}

# Tokens reserved inside the context window for the system prompt and the
# generated summary. num_ctx bounds prompt AND generation combined, and Ollama
# truncates the prompt from the FRONT — so an over-budget input silently drops
# the system message and the model free-associates on a tail slice of the text.
_SUMMARY_RESERVE_TOKENS = 2_000

# Rough token estimate used throughout; matches the chunker's own heuristic.
_CHARS_PER_TOKEN = 4


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
    limit = _input_token_budget() * _CHARS_PER_TOKEN
    return text if len(text) <= limit else text[:limit]


# Max tokens per map call — stays within the generation window with room for output
_MAP_BATCH_TOKENS = 3_000

# Floor on each document's contribution to the library synthesis, so a large
# library degrades to shallower per-document coverage rather than dropping docs.
_MIN_LIBRARY_WORDS_PER_DOC = 60
_WORDS_PER_TOKEN = 0.75

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

# Slow path only, where no section summaries exist and `detailed` must be
# generated. Per-section output is the one mode that splits without changing
# meaning -- a synthesis would lose the cross-section view; this does not. Every
# batch is summarised and none is dropped, so the bound is on how long one call
# runs, never on how much of the document is covered.
_DETAILED_BATCH_TOKENS = 1_500
_DETAILED_BATCH_MAX_TOKENS = 1_000

_METADATA_IGNORE = (
    "Ignore any copyright notices, licensing terms, distribution metadata, "
    "publisher boilerplate, or digitisation project information. "
    "Focus only on the intellectual and narrative content of the works."
)

# System prompts for library-level synthesis
LIBRARY_SYSTEM_PROMPTS: dict[str, str] = {
    "one_sentence": (
        f"Synthesize all documents in one sentence of at most 30 words. {_METADATA_IGNORE}"
    ),
    "executive": (
        "List the 5-7 key themes across all documents as bullet points. "
        "Focus on intellectual content, ideas, arguments, and narratives. "
        f"Note connections between them. {_METADATA_IGNORE} {_MARKDOWN_INSTRUCTION}"
    ),
    "detailed": (
        "Write a structured overview: main themes, key documents, "
        f"and how they relate to each other. {_METADATA_IGNORE} {_MARKDOWN_INSTRUCTION}"
    ),
}


def _split_for_detail(text: str, budget_tokens: int = _DETAILED_BATCH_TOKENS) -> list[str]:
    """Split on blank lines into batches of at most `budget_tokens`.

    Splits between paragraphs so a section is summarised as a whole. A single
    paragraph over the budget is its own batch rather than being cut: the point
    of batching is to bound one call, never to drop text.
    """
    batches: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for para in text.split("\n\n"):
        if not para.strip():
            continue
        tokens = len(para) // _CHARS_PER_TOKEN
        if current and current_tokens + tokens > budget_tokens:
            batches.append("\n\n".join(current))
            current = []
            current_tokens = 0
        current.append(para)
        current_tokens += tokens
    if current:
        batches.append("\n\n".join(current))
    return batches


# What to say about each kind of document, appended to the mode instruction.
# One instruction for all of them asked a conference talk for "character arcs"
# and lost every tool it named (#105). Keyed on the facets, not content_type:
# a manual and a novel are both "book".
_FORM_GUIDANCE: dict[str, str] = {
    "prose": (
        "Focus on what the work argues or recounts, and name the people, places "
        "and specific subjects it is about."
    ),
    "article": "Focus on the claim being made and the specific things it is about.",
    "reference": (
        "Name the specific rules, components, commands and parameters the work "
        "defines. A reader uses this to decide what to look up, so a named thing "
        "is worth more than a description of it."
    ),
    "paper": (
        "Name what was measured, the method, the finding, and the limitation the "
        "work states. Keep figures and named methods exactly as written."
    ),
    "dialogue": (
        "Name the specific systems, tools and decisions discussed, and who owns "
        "them. Anything that will go stale -- a version, a date, a number -- "
        "carries its date."
    ),
    "entries": "Name the recurring subjects across entries rather than retelling each one.",
    "script": "Focus on what happens and what the characters want.",
    "source_code": "Name the functions, types and responsibilities the file defines.",
}

_NARRATIVE_GUIDANCE = (
    "Focus on what happens, what the characters want, and what their choices "
    "cost. Name the people and places that carry the story."
)

# The specific failure was abstraction: "configuration files" for `agents.md`.
_TECHNICAL_GUIDANCE = (
    "Preserve exact names: files, commands, libraries, parameters, metrics and "
    "tools. Never replace a named thing with the category it belongs to."
)


def _kind_guidance(profile: "DocumentProfile | None") -> str:
    """The sentence that tells the model what this kind of document is for."""
    if profile is None:
        return ""
    if profile.form in ("prose", "article") and profile.register == "narrative":
        parts = [_NARRATIVE_GUIDANCE]
    else:
        parts = [_FORM_GUIDANCE.get(profile.form, "")]
    if profile.is_technical:
        parts.append(_TECHNICAL_GUIDANCE)
    return " ".join(p for p in parts if p)


def _build_system_prompt(mode: str, profile: "DocumentProfile | None" = None) -> str:
    """The grounding prefix, the mode instruction, and what this kind wants.

    `conversation` asks for a JSON object; prose guidance would invite
    commentary around it.
    """
    if mode == "conversation" and profile is not None and profile.is_technical:
        mode = "conversation_talk"
    prompt = f"{GROUNDING_PREFIX}\n\n{MODE_INSTRUCTIONS[mode]}"
    if mode.startswith("conversation"):
        return prompt
    guidance = _kind_guidance(profile)
    return f"{prompt} {guidance}" if guidance else prompt


class SummarizationService:
    """Summarize a document in multiple granularity modes."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_profile(self, document_id: str) -> "DocumentProfile | None":
        """What kind of document this is, for the prompt to adapt to.

        None when the row carries no form, and never raises: adapting the prompt
        improves a summary but is not a precondition for having one.
        """
        try:
            async with get_session_factory()() as session:
                row = (
                    await session.execute(
                        select(
                            DocumentModel.form, DocumentModel.domain, DocumentModel.register
                        ).where(DocumentModel.id == document_id)
                    )
                ).first()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "summary profile lookup failed, using the neutral prompt: %s",
                type(exc).__name__,
                extra={"document_id": document_id},
            )
            return None
        if row is None or not row.form:
            return None
        return DocumentProfile(
            form=row.form,  # type: ignore[arg-type]
            domain=row.domain,  # type: ignore[arg-type]
            register=row.register,  # type: ignore[arg-type]
        )

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
        # Strip metadata/legal chunks (license preambles, copyright notices, etc.)
        # before any further processing so they never pollute the summary input.
        filtered = [c for c in chunks if not _is_metadata_section("", c.text)]
        if filtered:
            chunks = filtered

        total_tokens = sum(c.token_count or len(c.text) // _CHARS_PER_TOKEN for c in chunks)
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
            batches = self._chunk_into_batches(chunks)
        else:
            batches = []
            for group_chunks in section_groups.values():
                gt = sum(c.token_count or len(c.text) // 4 for c in group_chunks)
                if gt > _MAP_BATCH_TOKENS:
                    batches.extend(self._chunk_into_batches(group_chunks))
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
        section_system = f"{GROUNDING_PREFIX}\n\nSummarize this passage concisely in 2-3 sentences."
        section_summaries: list[str] = []
        for batch in batches:
            batch_text = "\n\n".join(c.text for c in batch)
            s = await llm.generate(
                batch_text,
                system=section_system,
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
        self, input_text: str, model: str | None, profile: "DocumentProfile | None" = None
    ) -> str:
        """Generate the per-section summary as one bounded call per batch.

        Only reached when no section summaries exist. The batches are joined in
        document order, so the whole input is covered by exactly one call each.
        """
        llm = get_llm_service()
        system = _build_system_prompt("detailed", profile)
        parts: list[str] = []
        for batch in _split_for_detail(input_text):
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
        """Return a markdown string built from section summaries, or None if < 3 units exist.

        When >= 3 section summary units are available, this string is used as the
        direct input to all summarization modes (fast path), bypassing chunk map-reduce.
        """
        async with get_session_factory()() as session:
            result = await session.execute(
                select(SectionSummaryModel)
                .where(SectionSummaryModel.document_id == document_id)
                .order_by(SectionSummaryModel.unit_index)
            )
            rows = list(result.scalars().all())

        # Filter out metadata/legal section summary rows
        qualifying = [row for row in rows if not _is_metadata_section(row.heading, row.content)]

        if len(qualifying) < 3:
            return None

        parts = [f"## {row.heading}\n{row.content}" for row in qualifying]
        return "\n\n".join(parts)

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

        force_refresh=True skips the cache lookup and re-generates via LLM,
        overwriting the stored summary.

        Yields:
            ``data: {"token": "..."}\\n\\n``  — one word at a time
            ``data: {"done": true, "summary_id": "..."}\\n\\n``  — final event
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
                done_evt = {"done": True, "summary_id": cached.id, "cached": True}
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
                text = (
                    section_input
                    if section_input is not None
                    else await self._generate_detailed(
                        _truncate_to_budget(input_text),
                        model,
                        await self._fetch_profile(document_id),
                    )
                )
                summary_id = await self._store_summary(document_id, mode, text)
                yield f"data: {json.dumps({'token': text})}\n\n"
                done_evt = {"done": True, "summary_id": summary_id, "cached": False}
                yield f"data: {json.dumps(done_evt)}\n\n"
                return

            llm = get_llm_service()
            system = _build_system_prompt(mode, await self._fetch_profile(document_id))
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
            done_evt = {"done": True, "summary_id": summary_id, "cached": False}
            yield f"data: {json.dumps(done_evt)}\n\n"

        except Exception as exc:
            logger.warning(
                "stream_summary failed",
                extra={"document_id": document_id, "mode": mode},
                exc_info=exc,
            )
            if isinstance(exc, ValueError):
                msg = "LLM provider not configured. Add your API key in Settings."
            elif isinstance(exc, LLMAuthenticationError):
                msg = "LLM API key is invalid. Check your key in Settings."
            else:
                msg = "LLM service unavailable. If using Ollama, run: ollama serve"
            err_evt = {"error": "llm_unavailable", "message": msg, "done": True}
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
                        text = section_input
                    elif mode in _ASSEMBLED_MODES:
                        text = await self._generate_detailed(
                            _truncate_to_budget(input_text), model, profile
                        )
                    else:
                        text = await llm.generate(
                            _truncate_to_budget(input_text),
                            system=_build_system_prompt(mode, profile),
                            model=model,
                            background=True,
                            num_ctx=_summary_num_ctx(model),
                            max_tokens=_PREGENERATE_MAX_TOKENS,
                        )
                    assert isinstance(text, str)  # noqa: S101
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

    async def invalidate_section_reduce_cache(self, document_id: str) -> None:
        """Delete the '_section_reduce' summary row so pregenerate() recomputes it."""
        async with get_session_factory()() as session:
            await session.execute(
                delete(SummaryModel)
                .where(SummaryModel.document_id == document_id)
                .where(SummaryModel.mode == "_section_reduce")
            )
            await session.commit()
        logger.info("_section_reduce cache invalidated", extra={"document_id": document_id})

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
            session.add(LibrarySummaryModel(id=summary_id, mode=mode, content=content))
            await session.commit()
        return summary_id

    async def _fetch_all_executive_summaries(self) -> dict[str, str]:
        """Return best-available summary content keyed by document_id.

        Priority: executive > detailed > one_sentence > conversation.
        Documents with no summary of any kind are excluded.
        """
        _MODE_PRIORITY = {"executive": 0, "detailed": 1, "one_sentence": 2, "conversation": 3}
        async with get_session_factory()() as session:
            rows = await session.execute(
                select(
                    SummaryModel.document_id,
                    SummaryModel.mode,
                    SummaryModel.content,
                    SummaryModel.created_at,
                ).order_by(SummaryModel.created_at.desc())
            )
            # best[doc_id] = (priority, content)
            best: dict[str, tuple[int, str]] = {}
            for row in rows:
                prio = _MODE_PRIORITY.get(row.mode, 99)
                if row.document_id not in best or prio < best[row.document_id][0]:
                    best[row.document_id] = (prio, row.content)
        return {doc_id: content for doc_id, (_, content) in best.items()}

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
        force_refresh: bool = False,
        background: bool = False,
    ) -> AsyncGenerator[str]:
        """Synthesize a holistic summary across all ingested documents.

        Cache-first: if a LibrarySummaryModel for this mode already exists it is
        streamed as a single token event.  On cache miss, fetches executive summaries
        from all documents, queries Kuzu for cross-doc entities, builds input text,
        and generates via LLM.

        force_refresh=True skips the cache and regenerates.

        Yields:
            ``data: {"token": "..."}\\n\\n``  — one or more token events
            ``data: {"done": true, ...}\\n\\n``  — final event with cached flag
            ``data: {"error": "not_enough_summaries", ...}\\n\\n``  — when < 2 docs
        """
        try:
            # Cache-first (skipped when force_refresh=True)
            cached = None if force_refresh else await self._fetch_library_cached(mode)
            if cached is not None:
                logger.info("Serving cached library summary", extra={"mode": mode})
                yield f"data: {json.dumps({'token': cached.content})}\n\n"
                done_evt = {"done": True, "summary_id": cached.id, "cached": True}
                yield f"data: {json.dumps(done_evt)}\n\n"
                return

            # Fetch executive summaries per document
            exec_summaries = await self._fetch_all_executive_summaries()

            if len(exec_summaries) == 0:
                yield (
                    'data: {"error": "not_enough_summaries", '
                    '"message": "Ingest at least one document to generate a library overview.", '
                    '"done": true}\n\n'
                )
                return

            if len(exec_summaries) == 1:
                # Single-document library: serve that document's executive summary directly
                doc_id, content = next(iter(exec_summaries.items()))
                summary_id = await self._store_library_summary(mode, content)
                yield f"data: {json.dumps({'token': content})}\n\n"
                yield f"data: {
                    json.dumps({'done': True, 'summary_id': summary_id, 'cached': False})
                }\n\n"
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

            # Build input text ordered by title.
            # Per-document source priority:
            #   1. _build_section_summary_input() — section summaries already have
            #      metadata/legal sections filtered out; use this as the primary source.
            #   2. Cached executive summary — fallback for pre-V2 docs without section
            #      summaries.
            # Cap each document's contribution so the TOTAL input stays inside the
            # context window: a fixed per-document cap silently blows the budget once
            # the library is large, and Ollama then truncates away the system prompt.
            max_words_per_doc = max(
                _MIN_LIBRARY_WORDS_PER_DOC,
                int(_input_token_budget() * _WORDS_PER_TOKEN) // max(len(doc_ids), 1),
            )
            ordered = sorted(doc_ids, key=lambda did: titles.get(did, ""))
            parts: list[str] = []
            for did in ordered:
                section_input = await self._build_section_summary_input(did)
                raw_text = section_input or exec_summaries.get(did, "")
                words = raw_text.split()
                doc_text = (
                    " ".join(words[:max_words_per_doc])
                    if len(words) > max_words_per_doc
                    else raw_text
                )
                parts.append(f"## {titles.get(did, did)}\n{doc_text}")

            # Cross-doc entities from Kuzu (non-fatal)
            entity_names = self._get_cross_doc_entities()
            if entity_names:
                parts.append(f"## Shared themes\n{', '.join(entity_names)}")

            input_text = _truncate_to_budget("\n\n".join(parts))
            system = LIBRARY_SYSTEM_PROMPTS.get(mode, LIBRARY_SYSTEM_PROMPTS["executive"])

            llm = get_llm_service()
            token_stream = await llm.generate(
                input_text,
                system=system,
                model=model,
                stream=True,
                background=background,
                num_ctx=_summary_num_ctx(model),
            )

            collected: list[str] = []
            async for token in token_stream:
                collected.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"

            summary_text = "".join(collected)
            summary_id = await self._store_library_summary(mode, summary_text)
            done_evt = {"done": True, "summary_id": summary_id, "cached": False}
            yield f"data: {json.dumps(done_evt)}\n\n"

        except Exception as exc:
            logger.warning("stream_library_summary failed", exc_info=exc)
            if isinstance(exc, ValueError):
                msg = "LLM provider not configured. Add your API key in Settings."
            elif isinstance(exc, LLMAuthenticationError):
                msg = "LLM API key is invalid. Check your key in Settings."
            else:
                msg = "LLM service unavailable. If using Ollama, run: ollama serve"
            err_evt = {"error": "llm_unavailable", "message": msg, "done": True}
            yield f"data: {json.dumps(err_evt)}\n\n"

    async def refresh_library_summary(self) -> None:
        """Regenerate the library summary in place, keeping the old one readable.

        This used to delete every row, which left the library with no summary at
        all until something regenerated it -- and that something was the next
        question. `summary_node` found nothing, fired the generation itself, and
        then queued behind it on the one serving slot: measured 2026-08-17 at 54.5s
        to first token against a 13.5s median for the same question. That Ask also
        took the retrieval route rather than the summary route, so it differed in
        kind and not only in latency.

        Regenerating here puts the work in ingestion, where the admission gate can
        defer it, and readers keep serving the previous summary until the
        replacement is stored -- both readers order by `created_at`, so the new row
        wins the moment it exists and never before. A summary one document out of
        date is worth more than no summary at all.
        """
        try:
            async for _ in self.stream_library_summary(
                mode="executive", model=None, force_refresh=True, background=True
            ):
                pass
        except Exception as exc:
            logger.warning("library summary refresh failed (non-fatal): %s", exc)


_summarization_service: SummarizationService | None = None


def get_summarization_service() -> SummarizationService:
    global _summarization_service
    if _summarization_service is None:
        _summarization_service = SummarizationService()
    return _summarization_service
