"""POST /explain (SSE streaming), glossary CRUD endpoints."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.services.explain import GlossaryParseError, get_explain_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/explain", tags=["explain"])


class ExplainRequest(BaseModel):
    text: str
    document_id: str
    mode: Literal["plain", "eli5", "analogy", "formal"] = "plain"


@router.post("")
async def explain_text(req: ExplainRequest) -> StreamingResponse:
    """Stream an explanation of the selected text using surrounding document context."""
    logger.info(
        "Explain request",
        extra={"document_id": req.document_id, "mode": req.mode, "text_len": len(req.text)},
    )
    svc = get_explain_service()
    return StreamingResponse(
        svc.stream_explain(req.text, req.document_id, req.mode),
        media_type="text/event-stream",
    )


# NOTE: /glossary/{document_id}/cached MUST be registered BEFORE /glossary/{document_id}
# to prevent FastAPI from matching "cached" as a document_id wildcard.
# However here document_id is the second path segment so there is no ambiguity.
# The static sub-path /terms/{term_id} under /{document_id} also has no conflict.

@router.get("/glossary/{document_id}/cached")
async def get_cached_glossary(document_id: str) -> list[dict]:
    """Return persisted glossary terms without LLM call. Empty list if none generated."""
    svc = get_explain_service()
    return await svc.get_cached_glossary(document_id)


@router.post("/glossary/{document_id}")
async def extract_glossary(document_id: str) -> list[dict]:
    """Extract domain-specific terms from a document via LLM, persist, and return."""
    svc = get_explain_service()
    try:
        result = await svc.extract_glossary(document_id)
    except GlossaryParseError:
        raise HTTPException(status_code=422, detail="Glossary generation failed -- try again")
    except Exception as exc:
        # LLM unavailable (e.g. Ollama down)
        err_name = type(exc).__name__
        if "ServiceUnavailable" in err_name or "Connection" in err_name:
            raise HTTPException(
                status_code=503,
                detail="Ollama unavailable -- start it to generate glossary",
            )
        raise
    logger.info("Glossary extracted", extra={"document_id": document_id, "count": len(result)})
    return result


@router.delete("/glossary/{document_id}/terms/{term_id}", status_code=204)
async def delete_glossary_term(document_id: str, term_id: str) -> None:
    """Delete a single glossary term."""
    svc = get_explain_service()
    deleted = await svc.delete_term(term_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Term not found")
