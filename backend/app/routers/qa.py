"""POST /qa — SSE streaming grounded Q&A endpoint."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.intent import classify_intent_heuristic
from app.services.llm import get_llm_service
from app.services.okf_context import get_okf_context_service
from app.services.qa import get_qa_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qa", tags=["qa"])

_GROUNDED_SYSTEM = (
    "You are Lumen, a learning assistant. Answer the question using ONLY the grounding context "
    "below (the learner's own material). Cite concepts by name. If the context does not cover it, "
    "say so plainly rather than inventing an answer."
)


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class QARequest(BaseModel):
    question: str
    document_ids: list[str] | None = None
    scope: Literal["single", "all"] = "all"
    model: str | None = None
    messages: list[ConversationMessage] | None = None  # sliding-window history
    web_enabled: bool = False  # optional web augmentation
    socratic: bool = False  # when True, LLM asks a probing question before answering


class ClassifyOnlyResponse(BaseModel):
    chosen_route: Literal["summary", "graph", "comparative", "search"]
    intent: str
    confidence: float


def _normalize_classify_route(intent: str) -> Literal["summary", "graph", "comparative", "search"]:
    if intent == "summary":
        return "summary"
    if intent == "relational":
        return "graph"
    if intent == "comparative":
        return "comparative"
    return "search"


@router.post("")
async def ask_question(req: QARequest) -> StreamingResponse:
    svc = get_qa_service()
    history = [m.model_dump() for m in req.messages] if req.messages else []
    return StreamingResponse(
        svc.stream_answer(
            req.question,
            req.document_ids,
            req.scope,
            req.model,
            history,
            web_enabled=req.web_enabled,
            socratic=req.socratic,
        ),
        media_type="text/event-stream",
    )


@router.post("/classify-only", response_model=ClassifyOnlyResponse)
async def classify_only(req: QARequest) -> ClassifyOnlyResponse:
    """Classify the chat route without executing retrieval/LLM graph nodes."""
    intent, confidence = classify_intent_heuristic(req.question)
    return ClassifyOnlyResponse(
        chosen_route=_normalize_classify_route(intent),
        intent=intent,
        confidence=confidence,
    )


class GroundedRequest(BaseModel):
    question: str
    concept_id: str | None = None  # ground in this concept + its graph neighbourhood
    model: str | None = None


class GroundedConcept(BaseModel):
    id: str
    label: str


class GroundedResponse(BaseModel):
    answer: str
    grounded: bool
    concepts: list[GroundedConcept]


@router.post("/grounded", response_model=GroundedResponse)
async def ask_grounded(
    req: GroundedRequest, session: AsyncSession = Depends(get_db)
) -> GroundedResponse:
    """GraphRAG answer over the concept graph (docs/okf.md).

    Resolve scope -> concepts -> expand the graph + evidence -> one OKF grounding block -> LiteLLM.
    Self-contained (does not touch the streaming chat graph). Degrades: no concepts -> an honest
    "not in your library yet"; model down -> the grounding context is returned as the answer.
    """
    okf = get_okf_context_service()
    concept_ids = await okf.resolve_concepts(
        session,
        concept_id=req.concept_id,
        query=None if req.concept_id else req.question,
    )
    context = await okf.build_concept_context(session, concept_ids)
    from sqlalchemy import select  # noqa: PLC0415

    from app.models import ConceptModel  # noqa: PLC0415

    concepts: list[GroundedConcept] = []
    if concept_ids:
        rows = (
            await session.execute(
                select(ConceptModel.id, ConceptModel.label).where(ConceptModel.id.in_(concept_ids))
            )
        ).all()
        label_of = {cid: label for cid, label in rows}
        concepts = [
            GroundedConcept(id=cid, label=label_of[cid]) for cid in concept_ids if cid in label_of
        ]

    if not context:
        return GroundedResponse(
            answer="I don't have anything in your library covering that yet.",
            grounded=False,
            concepts=concepts,
        )

    user_msg = f"Grounding context:\n{context}\n\nQuestion: {req.question}"
    try:
        answer = await get_llm_service().complete(
            [
                {"role": "system", "content": _GROUNDED_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            model=req.model,
            temperature=0.2,
        )
    except Exception:
        logger.warning("grounded answer LLM call failed; returning context", exc_info=True)
        answer = context

    return GroundedResponse(answer=answer, grounded=True, concepts=concepts)
