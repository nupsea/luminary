"""Library-wide summary: one synthesis across every ingested document."""

import json
import logging
from collections.abc import AsyncGenerator

from app.database import get_session_factory
from app.models import LibrarySummaryModel
from app.repos.summary_repo import SummaryRepo
from app.services.llm import LLMAuthenticationError, get_llm_service
from app.services.summarizer import _input_token_budget, _summary_num_ctx, _truncate_to_budget
from app.services.summary_assembly import section_summary_input
from app.services.summary_prompts import LIBRARY_SYSTEM_PROMPTS

logger = logging.getLogger(__name__)

# Floor on each document's contribution to the library synthesis, so a large
# library degrades to shallower per-document coverage rather than dropping docs.
_MIN_LIBRARY_WORDS_PER_DOC = 60
_WORDS_PER_TOKEN = 0.75


class LibrarySummaryService:
    async def _fetch_library_cached(self, mode: str) -> LibrarySummaryModel | None:
        """Return the most recent LibrarySummaryModel for this mode, or None."""
        async with get_session_factory()() as session:
            return await SummaryRepo(session).latest_library(mode)

    async def _store_library_summary(
        self, mode: str, content: str, source_ids: list[str]
    ) -> str | None:
        """Store a library summary, or nothing if any source document was deleted meanwhile.

        Deleting a document drops the cached library summary, so one generated
        from it must not be written back afterwards. Returns None when skipped.
        """
        async with get_session_factory()() as session:
            summary_id = await SummaryRepo(session).insert_library_if_sources_exist(
                mode, content, source_ids
            )
            await session.commit()
        if summary_id is None:
            logger.info("library summary not stored: a source document was deleted")
        return summary_id

    async def _fetch_all_executive_summaries(self) -> dict[str, str]:
        """Best-available summary content keyed by document_id."""
        async with get_session_factory()() as session:
            return await SummaryRepo(session).best_document_summaries()

    async def _get_cross_doc_entities(self, min_docs: int = 3, limit: int = 20) -> list[str]:
        """Entity names found in `min_docs` or more documents; [] if the graph fails."""
        try:
            from app.services.graph import get_graph_service  # noqa: PLC0415

            return await get_graph_service().get_cross_document_entities(
                limit=limit, min_documents=min_docs, topics_only=False
            )
        except Exception:
            logger.warning("_get_cross_doc_entities: graph query failed", exc_info=True)
            return []

    async def _document_part(self, document_id: str, fallback: str, max_words: int) -> str:
        """One document's contribution: its section summaries, already stripped of
        metadata and legal sections, else its stored summary; capped at max_words."""
        async with get_session_factory()() as session:
            rows = await SummaryRepo(session).section_summaries(document_id)
        raw_text = section_summary_input(rows) or fallback
        words = raw_text.split()
        return " ".join(words[:max_words]) if len(words) > max_words else raw_text

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
        from all documents, queries the graph for cross-doc entities, builds input text,
        and generates via LLM.

        force_refresh=True skips the cache and regenerates.

        Yields:
            ``data: {"token": "..."}\\n\\n``  — one or more token events
            ``data: {"done": true, ...}\\n\\n``  — final event with cached flag
            ``data: {"error": "not_enough_summaries", ...}\\n\\n``  — when < 2 docs
        """
        try:
            cached = None if force_refresh else await self._fetch_library_cached(mode)
            if cached is not None:
                logger.info("Serving cached library summary", extra={"mode": mode})
                yield f"data: {json.dumps({'token': cached.content})}\n\n"
                done_evt = {"done": True, "summary_id": cached.id, "cached": True}
                yield f"data: {json.dumps(done_evt)}\n\n"
                return

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
                summary_id = await self._store_library_summary(mode, content, [doc_id])
                yield f"data: {json.dumps({'token': content})}\n\n"
                yield f"data: {
                    json.dumps({'done': True, 'summary_id': summary_id, 'cached': False})
                }\n\n"
                return

            doc_ids = list(exec_summaries.keys())
            async with get_session_factory()() as session:
                titles = await SummaryRepo(session).titles(doc_ids)

            # Cap each document's contribution so the TOTAL input stays inside the
            # context window: a fixed per-document cap silently blows the budget once
            # the library is large, and Ollama then truncates away the system prompt.
            max_words_per_doc = max(
                _MIN_LIBRARY_WORDS_PER_DOC,
                int(_input_token_budget() * _WORDS_PER_TOKEN) // max(len(doc_ids), 1),
            )
            parts: list[str] = []
            for did in sorted(doc_ids, key=lambda d: titles.get(d, "")):
                doc_text = await self._document_part(
                    did, exec_summaries.get(did, ""), max_words_per_doc
                )
                parts.append(f"## {titles.get(did, did)}\n{doc_text}")

            entity_names = await self._get_cross_doc_entities()
            if entity_names:
                parts.append(f"## Shared themes\n{', '.join(entity_names)}")

            input_text = _truncate_to_budget("\n\n".join(parts))
            system = LIBRARY_SYSTEM_PROMPTS.get(mode, LIBRARY_SYSTEM_PROMPTS["executive"])

            token_stream = await get_llm_service().generate(
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
            summary_id = await self._store_library_summary(mode, summary_text, doc_ids)
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
        from app.services.llm_routing import refusal  # noqa: PLC0415

        if refusal("background") is not None:
            logger.info("library summary refresh: not run, this host refuses the background model")
            return
        try:
            async for _ in self.stream_library_summary(
                mode="executive", model=None, force_refresh=True, background=True
            ):
                pass
        except Exception as exc:
            logger.warning("library summary refresh failed (non-fatal): %s", exc)


_library_summary_service: LibrarySummaryService | None = None


def get_library_summary_service() -> LibrarySummaryService:
    global _library_summary_service
    if _library_summary_service is None:
        _library_summary_service = LibrarySummaryService()
    return _library_summary_service
