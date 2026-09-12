"""Shared constants + helpers for chat-graph nodes.

System prompt strings, the intent->prompt selector, the chunk shape
helper, the round-robin interleaver, and the module-level background
task registry. Imported by `chat_graph.py` and (in later phases) by
the per-node modules in this package.
"""

from __future__ import annotations

import logging

from app.database import get_session_factory
from app.services.background import task_registry
from app.services.qa import (
    CITATION_RULE,
    NOT_FOUND_SENTINEL,
    QA_FACTUAL_SYSTEM_PROMPT,
    QA_SYSTEM_PROMPT,
)
from app.services.settings_service import get_rerank_enabled
from app.types import ScoredChunk

# Strong references for fire-and-forget background tasks (asyncio holds weak refs only).
# Shared across all chat-graph nodes that spawn background work.

_background_tasks = task_registry(__name__)


async def _read_rerank_enabled(logger: logging.Logger, node_name: str) -> bool:
    """DB-backed rerank toggle, failing soft to off.

    Every retrieval call inside the chat graph must match search_node's rerank
    setting (I-55) -- a stale or unread toggle silently weakens grounding on
    exactly the supplemental/retry paths meant to strengthen it.
    """
    try:
        async with get_session_factory()() as session:
            return await get_rerank_enabled(session)
    except Exception as exc:
        logger.warning("%s: could not read rerank setting, defaulting off: %s", node_name, exc)
        return False


# Intent-specific system prompts (used by synthesize_node)

_SUMMARY_SYSTEM = (
    "You are a knowledge assistant. Answer using the provided document summary. "
    "Be concise and well-structured. Use Markdown headings and bullet points. "
    f"If the answer is not present, respond exactly: {NOT_FOUND_SENTINEL}."
)

_RELATIONAL_SYSTEM = (
    "You are a knowledge assistant. Answer using the knowledge graph connections "
    "and the supporting passages provided. Name the entities clearly. "
    "Use Markdown to show relationships between entities. "
    f"If the answer is not present, respond exactly: {NOT_FOUND_SENTINEL}. "
    "Do not speculate. "
    "Write your answer as Markdown prose. "
    "Then on a new line write this JSON: "
    '{"citations":[{"source":"S1"}],"confidence":"high|medium|low"}\n'
    f"{CITATION_RULE}"
)

_COMPARATIVE_SYSTEM = (
    "You are a knowledge assistant. Compare the two subjects using the provided passages. "
    "Structure your answer as: **Subject A:** ... **Subject B:** ... "
    f"If the answer is not present, respond exactly: {NOT_FOUND_SENTINEL}. "
    "Do not speculate. "
    "Write your answer as Markdown prose. "
    "Then on a new line write this JSON: "
    '{"citations":[{"source":"S1"}],"confidence":"high|medium|low"}\n'
    f"{CITATION_RULE}"
)


def _get_system_prompt(intent: str | None) -> str:
    """Return intent-appropriate system prompt for the LLM call."""
    if intent == "summary":
        return _SUMMARY_SYSTEM
    if intent == "relational":
        return _RELATIONAL_SYSTEM
    if intent == "comparative":
        return _COMPARATIVE_SYSTEM
    if intent == "factual":
        return QA_FACTUAL_SYSTEM_PROMPT
    return QA_SYSTEM_PROMPT


def _chunk_to_dict(c: ScoredChunk) -> dict:
    return {
        "chunk_id": c.chunk_id,
        "document_id": c.document_id,
        "text": c.text,
        "section_heading": c.section_heading,
        "page": c.page,
        "score": c.score,
        "source": c.source,
    }


def _round_robin(lists: list[list]) -> list:
    """Round-robin interleave N lists: [l0[0], l1[0], l2[0], l0[1], l1[1], ...]."""
    result: list = []
    iters = [iter(lst) for lst in lists]
    while True:
        advanced = False
        for it in iters:
            try:
                result.append(next(it))
                advanced = True
            except StopIteration:
                pass
        if not advanced:
            break
    return result
