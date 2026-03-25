"""Admin endpoints for Luminary backend operations.

Routes: POST /admin/notes/reindex
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import NoteModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _check_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    """Dependency: verify X-Admin-Key header when ADMIN_KEY is configured."""
    settings = get_settings()
    if settings.ADMIN_KEY and x_admin_key != settings.ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Admin-Key header")


@router.post("/notes/reindex")
async def reindex_notes(
    _auth: None = Depends(_check_admin_key),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Queue a background reindex of all notes missing embeddings in LanceDB.

    Returns immediately with {queued: true, total_notes: int}.
    The reindex runs as asyncio.create_task (fire-and-forget).
    """
    from app.services.reindex_service import get_reindex_service  # noqa: PLC0415

    total_notes: int = (
        await session.execute(select(func.count()).select_from(NoteModel))
    ).scalar_one()

    reindex_svc = get_reindex_service()

    # Fire-and-forget: create a new session for the background task
    from app.database import get_session_factory  # noqa: PLC0415

    async def _run_reindex() -> None:
        try:
            async with get_session_factory()() as bg_session:
                report = await reindex_svc.reindex_notes(bg_session)
                logger.info("Background reindex complete: %s", report)
        except Exception as exc:
            logger.error("Background reindex failed: %s", exc)

    task = asyncio.create_task(_run_reindex())
    # Keep a reference to prevent GC
    task.add_done_callback(lambda t: None)

    logger.info("Reindex queued: total_notes=%d", total_notes)
    return {"queued": True, "total_notes": total_notes}
