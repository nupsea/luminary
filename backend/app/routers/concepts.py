"""Concept correction endpoints -- the "review what Lumen found" backend.

Each correction mutates the concept AND records an Override keyed by slug, so the
user's decision survives re-parse (I-22; docs/concepts.md). Thin handlers over
ConceptService.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ConceptModel, FlashcardModel, NoteModel
from app.services.concept_service import get_concept_service

_LEXICAL_SCAN_CAP = 500

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/concepts", tags=["concepts"])


class ConceptOut(BaseModel):
    id: str
    slug: str
    label: str
    kind: str
    status: str
    mastery: float


class RenameRequest(BaseModel):
    label: str


class ReclassifyRequest(BaseModel):
    kind: str  # concept | keyword


class MergeRequest(BaseModel):
    source_id: str
    target_id: str


def _out(row: ConceptModel) -> ConceptOut:
    return ConceptOut(
        id=row.id, slug=row.slug, label=row.label, kind=row.kind,
        status=row.status, mastery=row.mastery,
    )


@router.get("/{concept_id}", response_model=ConceptOut)
async def get_concept(concept_id: str, session: AsyncSession = Depends(get_db)) -> ConceptOut:
    row = await session.get(ConceptModel, concept_id)
    if row is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return _out(row)


@router.post("/{concept_id}/rename", response_model=ConceptOut)
async def rename_concept(
    concept_id: str, req: RenameRequest, session: AsyncSession = Depends(get_db)
) -> ConceptOut:
    label = req.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="label is required")
    row = await get_concept_service().rename_concept(session, concept_id, label)
    if row is None:
        raise HTTPException(status_code=404, detail="concept not found")
    await session.commit()
    return _out(row)


@router.post("/{concept_id}/reclassify", response_model=ConceptOut)
async def reclassify_concept(
    concept_id: str, req: ReclassifyRequest, session: AsyncSession = Depends(get_db)
) -> ConceptOut:
    try:
        row = await get_concept_service().reclassify_concept(session, concept_id, req.kind)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if row is None:
        raise HTTPException(status_code=404, detail="concept not found")
    await session.commit()
    return _out(row)


@router.post("/{concept_id}/confirm", status_code=204)
async def confirm_concept(concept_id: str, session: AsyncSession = Depends(get_db)) -> None:
    if await session.get(ConceptModel, concept_id) is None:
        raise HTTPException(status_code=404, detail="concept not found")
    await get_concept_service().confirm_concept(session, concept_id)
    await session.commit()


@router.post("/{concept_id}/reject", status_code=204)
async def reject_concept(concept_id: str, session: AsyncSession = Depends(get_db)) -> None:
    if await session.get(ConceptModel, concept_id) is None:
        raise HTTPException(status_code=404, detail="concept not found")
    await get_concept_service().reject_concept(session, concept_id)
    await session.commit()


@router.post("/merge", response_model=ConceptOut)
async def merge_concepts(
    req: MergeRequest, session: AsyncSession = Depends(get_db)
) -> ConceptOut:
    row = await get_concept_service().merge_concepts(session, req.source_id, req.target_id)
    if row is None:
        raise HTTPException(status_code=404, detail="source or target concept not found")
    await session.commit()
    return _out(row)


@router.post("/apply-overrides")
async def apply_overrides(session: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """Re-apply all stored overrides onto the current concepts (re-parse hook, I-22)."""
    applied = await get_concept_service().apply_overrides(session)
    await session.commit()
    return {"applied": applied}


class PurgeJunkResponse(BaseModel):
    dry_run: bool
    matched: int
    deleted: int
    labels: list[str]


@router.post("/purge-junk", response_model=PurgeJunkResponse)
async def purge_junk_concepts(
    dry_run: bool = True, session: AsyncSession = Depends(get_db)
) -> PurgeJunkResponse:
    """Delete concepts whose label is format-junk (code tokens, CLI flags, unicode garbage).

    Same predicate the extraction pipeline uses, applied retroactively so existing junk does
    not linger in study/scope. ``dry_run=True`` (default) previews the matches without deleting;
    pass ``dry_run=false`` to actually remove them from all three stores.
    """
    from app.workflows.concept_nodes._shared import is_junk_entity  # noqa: PLC0415

    rows = (await session.execute(select(ConceptModel.id, ConceptModel.label))).all()
    matches = [(cid, label) for cid, label in rows if is_junk_entity(label)]
    labels = sorted(label for _cid, label in matches)
    deleted = 0
    if not dry_run:
        svc = get_concept_service()
        for cid, _label in matches:
            await svc.delete_concept(session, cid)
            deleted += 1
        await session.commit()
    return PurgeJunkResponse(
        dry_run=dry_run, matched=len(matches), deleted=deleted, labels=labels
    )


# --- concept-layer rebuild (the UI's "make concepts") ---------------------------------
# A global wipe-and-rebuild from the entity graph. Runs IN-PROCESS as a background task so it
# shares the live Kuzu/SQLite/LanceDB connections (no offline lock fight). Single job at a time;
# status is polled. Heavy: entity clustering + per-batch LLM scoring -- minutes on a big library,
# needs Ollama. Resets the concept mastery rollup (card FSRS state survives); corrections re-apply.

_regen_state: dict = {
    "status": "idle",  # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "concepts": None,
    "error": None,
}
_regen_task: asyncio.Task | None = None


class RegenStatus(BaseModel):
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    concepts: int | None = None
    error: str | None = None


async def _run_regen() -> None:
    from app.workflows.concept_pipeline import run_pipeline  # noqa: PLC0415

    try:
        state = await run_pipeline(dry_run=False)
        persisted = state.get("diagnostics", {}).get("persist_concepts", {}).get("concepts", 0)
        _regen_state.update(
            status="done", finished_at=datetime.now(UTC).isoformat(),
            concepts=persisted, error=None,
        )
    except Exception as exc:  # noqa: BLE001 -- surface any failure to the poller
        logger.warning("concept rebuild failed", exc_info=True)
        _regen_state.update(
            status="error", finished_at=datetime.now(UTC).isoformat(), error=str(exc)
        )


@router.post("/regenerate", response_model=RegenStatus)
async def regenerate_concepts() -> RegenStatus:
    """Kick off a full concept-layer rebuild in the background. 409 if one is already running."""
    global _regen_task
    if _regen_state["status"] == "running":
        raise HTTPException(status_code=409, detail="a concept rebuild is already running")
    _regen_state.update(
        status="running", started_at=datetime.now(UTC).isoformat(),
        finished_at=None, concepts=None, error=None,
    )
    _regen_task = asyncio.create_task(_run_regen())  # keep a ref so it isn't GC'd mid-flight
    return RegenStatus(**_regen_state)


@router.get("/regenerate/status", response_model=RegenStatus)
async def regenerate_concepts_status() -> RegenStatus:
    """Poll the current/last rebuild's status."""
    return RegenStatus(**_regen_state)


@router.get("/for-note/{note_id}", response_model=list[ConceptOut])
async def concepts_for_note(
    note_id: str, session: AsyncSession = Depends(get_db)
) -> list[ConceptOut]:
    """Concepts a note touches (docs/03-notes-generation.md).

    Two signals, unioned: (1) engagement -- concepts the note's mapped cards point at;
    (2) lexical recall -- concepts whose label appears in the note's title/content. This
    is the always-on degraded path; the concept_linker full-mode feature enriches it later.
    """
    note = await session.get(NoteModel, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="note not found")

    mapped_ids = {
        cid
        for cid in (
            await session.execute(
                select(FlashcardModel.concept_id).where(
                    FlashcardModel.note_id == note_id,
                    FlashcardModel.concept_id.is_not(None),
                )
            )
        ).scalars().all()
        if cid
    }

    text = f"{note.title or ''}\n{note.content or ''}".lower()
    candidates = (
        await session.execute(select(ConceptModel).limit(_LEXICAL_SCAN_CAP))
    ).scalars().all()

    out: list[ConceptModel] = []
    seen: set[str] = set()
    for c in candidates:
        if c.id in mapped_ids or (c.label and c.label.lower() in text):
            if c.id not in seen:
                seen.add(c.id)
                out.append(c)
    # include mapped concepts that fell outside the lexical scan cap
    missing = mapped_ids - seen
    if missing:
        extra = (
            await session.execute(select(ConceptModel).where(ConceptModel.id.in_(missing)))
        ).scalars().all()
        out.extend(extra)

    out.sort(key=lambda c: c.mastery)  # weakest first
    return [_out(c) for c in out]


@router.get("")
async def list_concepts(
    status: str | None = None, session: AsyncSession = Depends(get_db)
) -> list[ConceptOut]:
    """List concepts, optionally filtered by status (e.g. ?status=proposed for review)."""
    stmt = select(ConceptModel)
    if status:
        stmt = stmt.where(ConceptModel.status == status)
    rows = (await session.execute(stmt.order_by(ConceptModel.mastery.asc()))).scalars().all()
    return [_out(r) for r in rows]
