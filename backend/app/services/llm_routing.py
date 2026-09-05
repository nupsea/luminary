"""Which engine serves each unit of work, derived from the code that decides it.

Luminary's claim is that a library stays on the machine and only a question ever
leaves. That is only checkable if something reports where each unit of work
actually runs, so this builds the report the Settings surface renders.

**Nothing here asserts an engine.** The routable roles resolve through
`model_router.resolve`, which is what `LLMService` itself calls, and the fixed
components report the id held by the module that loads them. `on_device` is then
read off that id against the provider set routing uses to build a model string
(`settings_service.cloud_provider_prefixes`), so a component that ever acquires a
hosted implementation flips this table without anyone editing it. A hand-written
column would state the claim rather than measure it, and would keep stating it
after a route moved -- which is the failure this module exists to make impossible.

`resolve` never raises, so a cloud route missing its key appears here as the local
model it will really use, carrying the reason. That case is the one worth seeing:
the mode says cloud and the machine is answering.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import get_settings
from app.services import settings_service
from app.services.embedder import MODEL_NAME as EMBEDDING_MODEL
from app.services.model_router import resolve


@dataclass(frozen=True)
class WorkRouting:
    id: str
    label: str
    # None only where no model is involved at all. A null model and an unresolved
    # one are different answers, so nothing substitutes a placeholder here.
    model: str | None
    on_device: bool
    # False where the mode cannot move this work at any setting. The distinction
    # is the point of the table: four rows are local by choice, five by
    # construction, and collapsing them would let a reader think the whole
    # pipeline follows the mode.
    routable: bool
    why: str
    # Set when resolution fell back -- a missing key, a host that cannot hold the
    # configured model. Reported, never swallowed.
    fallback_reason: str | None = None


@dataclass(frozen=True)
class RoutingReport:
    mode: str
    provider: str | None
    work: list[WorkRouting] = field(default_factory=list)

    @property
    def leaves_device(self) -> list[str]:
        return [w.id for w in self.work if not w.on_device]


def _on_device(model_id: str | None) -> bool:
    """Whether *model_id* names something that runs on this machine.

    Off-device is decided by the provider prefix routing itself prepends, not by
    a list kept here: `get_effective_routing` builds `"{provider}/{model}"` from
    the same set. A local id is either bare, an `ollama/` id, or a HuggingFace
    `org/name` -- none of which can collide with a provider, because a provider
    prefix is exactly what makes LiteLLM send the call somewhere.
    """
    if model_id is None:
        return True
    prefix, _, rest = model_id.partition("/")
    if not rest:
        return True
    return prefix not in settings_service.cloud_provider_prefixes()


def _routed(work_id: str, label: str, role: str, why: str) -> WorkRouting:
    choice = resolve(role)  # type: ignore[arg-type]
    return WorkRouting(
        id=work_id,
        label=label,
        model=choice.model,
        on_device=_on_device(choice.model),
        routable=True,
        why=why,
        fallback_reason=choice.fallback_reason,
    )


def _fixed(work_id: str, label: str, model: str | None, why: str) -> WorkRouting:
    return WorkRouting(
        id=work_id,
        label=label,
        model=model,
        on_device=_on_device(model),
        routable=False,
        why=why,
    )


def routing_report() -> RoutingReport:
    """Every unit of work, in pipeline order, with the engine that serves it.

    Answering sits last among the model rows because in hybrid mode it is the
    one that leaves, and a table read top to bottom should arrive there.
    """
    settings = get_settings()
    mode, provider = settings_service.active_routing()

    work = [
        _fixed(
            "indexing",
            "Indexing your library",
            EMBEDDING_MODEL,
            "One embedding space holds every stored vector, so this cannot be "
            "routed without regenerating all of them.",
        ),
        _fixed(
            "retrieval",
            "Finding the passage",
            settings.RERANK_MODEL,
            "Search runs against the local index; the cross-encoder re-scores what it returns.",
        ),
        _fixed(
            "transcription",
            "Transcribing audio and video",
            f"whisper-{settings.WHISPER_MODEL_SIZE}",
            "Whisper runs on this machine in every mode.",
        ),
        _fixed(
            "extraction",
            "Extracting topics and entities",
            settings.NER_MODEL,
            "The extractor is loaded in this process; there is no remote path.",
        ),
        _routed(
            "enrichment",
            "Summaries, tags and titles at ingest",
            "background",
            "Background work stays on the machine in hybrid mode, so ingesting a "
            "library never spends your quota.",
        ),
        _routed(
            "figures",
            "Reading figures",
            "vision",
            "The figure reader is an on-device model chosen for this host.",
        ),
        _routed(
            "study_material",
            "Writing cards and study material",
            "generation",
            "You asked for it, so it follows the interactive route.",
        ),
        _routed(
            "answering",
            "Answering your question",
            "chat",
            "Your question and the passages retrieved for it are what the "
            "answering model receives.",
        ),
        _fixed(
            "learner_record",
            "Your learner record",
            None,
            "Scheduling, mastery and calibration are computed from your own "
            "review events. No model is involved, so there is nothing to route.",
        ),
    ]

    return RoutingReport(mode=mode, provider=provider, work=work)
