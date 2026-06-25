"""okf_context -- the model-agnostic grounding assembler (docs/knowledge-model.md §9, okf.md).

GraphRAG for Lumen: resolve a scope (a concept, a goal, or a free-text query) to concept ids,
EXPAND the concept graph (RELATED_TO neighbours), pull each concept's evidence passages, and project
it all as one portable OKF text block. The same block grounds a local Ollama model and a cloud model
identically -- OKF is the payload, LiteLLM is the wire (okf.md). Strictly local assembly.

This is the reusable core; callers (grounded QA now, the study assembler / live chat graph later)
decide what to do with the string. Community-summary caching for global questions is a follow-up.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, ConceptModel
from app.services.graph import get_graph_service

logger = logging.getLogger(__name__)


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


class OkfContextService:
    async def resolve_concepts(
        self,
        session: AsyncSession,
        *,
        concept_id: str | None = None,
        query: str | None = None,
        limit: int = 6,
    ) -> list[str]:
        """Scope -> concept ids. A concept expands to itself + neighbours; a free-text query
        matches concept labels lexically (a vector match is the planned enhancement -- concept
        centroids live in 384 chunk space, not the 1024 query space)."""
        if concept_id:
            from app.services.scope_resolver import resolve_concept  # noqa: PLC0415

            return await resolve_concept(session, concept_id)
        if query:
            qt = _tokens(query)
            if not qt:
                return []
            rows = (
                await session.execute(
                    select(ConceptModel.id, ConceptModel.label).where(
                        ConceptModel.status != "candidate"
                    )
                )
            ).all()
            scored = []
            for cid, label in rows:
                ct = _tokens(label)
                inter = len(qt & ct)
                if inter:
                    scored.append((inter / len(ct), cid))
            scored.sort(reverse=True)
            return [cid for _s, cid in scored[:limit]]
        return []

    async def build_concept_context(
        self,
        session: AsyncSession,
        concept_ids: list[str],
        *,
        max_quotes: int = 2,
        quote_chars: int = 280,
        budget_chars: int = 4000,
    ) -> str:
        """Assemble an OKF grounding block: per concept, its evidence quotes + related concepts."""
        if not concept_ids:
            return ""
        concepts = list(
            (
                await session.execute(
                    select(ConceptModel).where(ConceptModel.id.in_(concept_ids))
                )
            )
            .scalars()
            .all()
        )
        if not concepts:
            return ""
        # keep the caller's order (resolve puts the focal concept first)
        order = {cid: i for i, cid in enumerate(concept_ids)}
        concepts.sort(key=lambda c: order.get(c.id, 1_000))

        wanted_chunks: set[str] = set()
        for c in concepts:
            for ev in c.evidence_json or []:
                wanted_chunks.update((ev.get("chunk_ids") or [])[:max_quotes])
        chunk_text: dict[str, str] = {}
        if wanted_chunks:
            for cid, text in (
                await session.execute(
                    select(ChunkModel.id, ChunkModel.text).where(ChunkModel.id.in_(wanted_chunks))
                )
            ).all():
                chunk_text[cid] = text

        graph = get_graph_service()
        neighbours: dict[str, list[str]] = {}
        needed_labels: set[str] = set()
        for c in concepts:
            try:
                nbrs = graph.get_concept_neighbors(c.id, limit=5)
            except Exception:
                nbrs = []
            neighbours[c.id] = nbrs
            needed_labels.update(nbrs)
        label_of = {c.id: c.label for c in concepts}
        missing = [i for i in needed_labels if i not in label_of]
        if missing:
            for cid, label in (
                await session.execute(
                    select(ConceptModel.id, ConceptModel.label).where(ConceptModel.id.in_(missing))
                )
            ).all():
                label_of[cid] = label

        blocks: list[str] = []
        for c in concepts:
            lines = [f"## {c.label}"]
            quotes: list[str] = []
            for ev in c.evidence_json or []:
                for ch in ev.get("chunk_ids") or []:
                    t = chunk_text.get(ch)
                    if t:
                        quotes.append(re.sub(r"\s+", " ", t).strip()[:quote_chars])
                    if len(quotes) >= max_quotes:
                        break
                if len(quotes) >= max_quotes:
                    break
            for q in quotes:
                lines.append(f"- evidence: {q}")
            rel = [label_of[n] for n in neighbours.get(c.id, []) if n in label_of]
            if rel:
                lines.append(f"- related: {', '.join(rel[:5])}")
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks)[:budget_chars]


_service: OkfContextService | None = None


def get_okf_context_service() -> OkfContextService:
    global _service
    if _service is None:
        _service = OkfContextService()
    return _service
