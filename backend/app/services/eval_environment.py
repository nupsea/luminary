"""What produced an eval number, as the running backend resolves it.

An eval run records its metrics but nothing about the system that produced
them, so two numbers from different builds, models or library states read as
comparable when they are not. Re-ingesting one document has moved an untouched
document's MRR by 0.0125 -- the same magnitude as a model change measured at
the time -- so the corpus fingerprint is as load-bearing here as the model ids.

Resolved, never configured: a model chosen in Settings lives in the settings
service, not in `config.py`, and reading the config default would record a model
the run did not use.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.paths import app_version
from app.repos.document_repo import DocumentRepo
from app.services import settings_service
from app.services.embedder import MODEL_NAME as EMBEDDING_MODEL
from app.services.vector_store import TABLE_NAME as CHUNK_VECTOR_TABLE

# I-9: the corpus is embedded at this width and the stored vectors carry it.
# Recorded per run because a run against a re-embedded corpus is a different
# measurement, not a later one.
EMBEDDING_DIM = 384


def _routed(*, background: bool) -> str:
    """The model this backend would actually call, or why it could not answer."""
    try:
        model, _ = settings_service.get_effective_routing(background=background)
    except ValueError as exc:
        return f"unresolved: {exc}"
    return model


async def collect_environment(db: AsyncSession) -> dict[str, Any]:
    """The build, models and corpus a run is about to measure."""
    settings = get_settings()
    llm = await settings_service.get_llm_settings(db)
    documents, chunks = await DocumentRepo(db).corpus_counts()

    from app.services.model_router import resolve  # noqa: PLC0415

    generation_model = resolve("generation").model

    # Both arms, because `hybrid` resolves them to different models: interactive
    # goes to the cloud while background stays local. A run that records one
    # model for a mode with two describes a system that does not exist.
    interactive_model = _routed(background=False)
    background_model = _routed(background=True)

    return {
        "backend_version": app_version(),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": EMBEDDING_DIM,
        "chunk_vector_table": CHUNK_VECTOR_TABLE,
        "rerank_model": settings.RERANK_MODEL,
        "rerank_depth": settings.RERANK_DEPTH,
        "rerank_blend_alpha": settings.RERANK_BLEND_ALPHA,
        "query_spell_correct": settings.QUERY_SPELL_CORRECT,
        "llm_mode": llm["mode"],
        "chat_model": interactive_model,
        "background_model": background_model,
        "local_chat_model": llm["local_chat_model"],
        "generation_model": generation_model,
        "vision_model": llm["vision_model"],
        "library": {"documents": documents, "chunks": chunks},
    }
