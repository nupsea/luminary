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
from app.services import model_keepwarm, settings_service
from app.services.context_packer import resolve_context_budget
from app.services.embedder import MODEL_NAME as EMBEDDING_MODEL
from app.services.prompt_spec import withheld
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

    # Which prompt the models were given. A `bare` run measures the contract
    # without its accommodations, so its numbers are a different measurement
    # from a shipped run's rather than a newer one.
    bare, dropped = withheld()

    from app.memory_profile import (  # noqa: PLC0415
        active_profile,
        host_ram_gb,
        max_resident_models,
        profile_is_explicit,
    )
    from app.services.model_router import resident_models  # noqa: PLC0415

    profile = active_profile()

    return {
        "backend_version": app_version(),
        "embedding_model": EMBEDDING_MODEL,
        "embedding_dim": EMBEDDING_DIM,
        "chunk_vector_table": CHUNK_VECTOR_TABLE,
        "rerank_model": settings.RERANK_MODEL,
        "rerank_depth": settings.RERANK_DEPTH,
        "rerank_blend_alpha": settings.RERANK_BLEND_ALPHA,
        # Whether the reranker actually runs, not merely which one is configured.
        # `/search` defaults `rerank=false` while the chat path resolves this
        # setting, so an eval arm querying `/search` measured a funnel the app
        # does not ship -- and the block still named a reranker, which read as
        # proof it had been used. Recorded so the two can be compared.
        "rerank_enabled": await settings_service.get_rerank_enabled(db),
        # The slow-host profile, readable without log access. "Still slow" has
        # several independent causes -- wrong build, no start-up probe recorded,
        # profile engaged but prefill still dominant -- and separating them from
        # outside the process previously needed the container's logs.
        "startup_probe_seconds": model_keepwarm.measured_probe_seconds(),
        "local_inference_slow": model_keepwarm.local_inference_is_slow(),
        "qa_context_token_budget": resolve_context_budget()[0],
        "qa_context_budget_reason": resolve_context_budget()[1],
        "query_spell_correct": settings.QUERY_SPELL_CORRECT,
        "llm_mode": llm["mode"],
        "chat_model": interactive_model,
        "background_model": background_model,
        "local_chat_model": llm["local_chat_model"],
        "generation_model": generation_model,
        # Resolved, not configured. On a single-resident profile the vision role
        # falls back to the model already answering another role, so reporting the
        # configured id would name a model the run never loaded -- the exact class
        # of defect E5 exists to prevent, in the block that exists to prevent it.
        "vision_model": resolve("vision").model,
        "prompt_arm": "bare" if bare else "shipped",
        "prompt_accommodations_dropped": sorted(dropped),
        # Which machine class produced the run. Stage 6's exit gate is "all three
        # gates on all three profiles", and without this a run on the low profile
        # is indistinguishable in the history from a run on a 32GB desktop -- the
        # same defect E5 fixed for models, on the axis that decides which models
        # are even resolvable. `max_resident` is the constraint that makes a
        # single-model role map necessary rather than merely tidy.
        "memory_profile": profile,
        "memory_profile_explicit": profile_is_explicit(),
        "max_resident_models": max_resident_models(profile),
        "host_ram_gb": host_ram_gb(),
        "resident_models": sorted(resident_models()),
        "library": {"documents": documents, "chunks": chunks},
    }
