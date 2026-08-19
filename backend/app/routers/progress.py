"""Progress router -- the Progress page's numbers, computed server-side.

The page previously assembled these in the browser from five other routers, one of
which (`monitoring`) is not even mounted in `public` mode, so its Documents count
read 0 in every shipped build. Everything the page needs is here, and every value
carries the definition it is computed from.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.progress import NotesTimelineResponse, ProgressSummaryResponse
from app.services.progress_service import ProgressService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/progress", tags=["progress"])

_TZ_OFFSET_DESC = (
    "Client's timezone offset from UTC in minutes, matching JS "
    "`Date.getTimezoneOffset()` (positive west of UTC; PDT=420). Buckets use the "
    "user's local date so a session at 11pm does not roll into tomorrow."
)


@router.get("/summary", response_model=ProgressSummaryResponse)
async def get_progress_summary(
    tz_offset_minutes: int = Query(default=0, description=_TZ_OFFSET_DESC),
    session: AsyncSession = Depends(get_db),
) -> ProgressSummaryResponse:
    """Every headline number on the Progress page, each with its definition.

    A metric that could not be computed returns `value=null` and says why; the
    client renders an em dash. Nothing defaults to zero.
    """
    return await ProgressService(session, tz_offset_minutes=tz_offset_minutes).summary()


@router.get("/notes-timeline", response_model=NotesTimelineResponse)
async def get_notes_timeline(
    months: int = Query(default=12, ge=1, le=60),
    tz_offset_minutes: int = Query(default=0, description=_TZ_OFFSET_DESC),
    session: AsyncSession = Depends(get_db),
) -> NotesTimelineResponse:
    """Notes created per month, grouped in SQL."""
    return await ProgressService(
        session, tz_offset_minutes=tz_offset_minutes
    ).notes_timeline(months=months)
