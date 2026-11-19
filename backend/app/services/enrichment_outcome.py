"""Why a document was left without its summaries or cards, kept on the document.

Summaries, tags and cards each treat a failed model call as non-fatal, so a provider
that refused every call left a document `complete` with none of them and nothing on
screen saying why (#514). Ingestion and enrichment jobs run under `for_document`; a
call that finally fails there records its reason in the document's `extraction_report`,
and the reader is told only while the work it names is still missing.
"""

import contextlib
import logging
from collections.abc import Iterator
from contextvars import ContextVar
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session_factory
from app.models import DocumentModel
from app.repos.document_repo import DocumentRepo
from app.repos.enrichment_repo import EnrichmentRepo
from app.repos.summary_repo import SummaryRepo

logger = logging.getLogger(__name__)

REPORT_KEY = "enrichment_failure"

_document: ContextVar[str | None] = ContextVar("enrichment_document", default=None)
# Document -> the reason last written by this process: every failing section would
# otherwise write the same row.
_written: dict[str, str] = {}


@contextlib.contextmanager
def for_document(document_id: str) -> Iterator[None]:
    """Model calls in this block, and tasks it starts, are made for *document_id*."""
    token = _document.set(document_id)
    try:
        yield
    finally:
        _document.reset(token)


async def record_failure(reason: str) -> None:
    """Keep *reason* on the document this call was made for, if any."""
    document_id = _document.get()
    if document_id is None or _written.get(document_id) == reason:
        return
    _written[document_id] = reason
    try:
        async with get_session_factory()() as session:
            repo = DocumentRepo(session)
            doc = await repo.get(document_id)
            if doc is None:
                return
            report = dict(doc.extraction_report or {})
            report[REPORT_KEY] = {"reason": reason, "at": datetime.now(UTC).isoformat()}
            await repo.update_fields(document_id, extraction_report=report)
            await session.commit()
    except Exception:
        logger.warning("could not record why %s went unenriched", document_id, exc_info=True)


async def notice(session: AsyncSession, doc: DocumentModel) -> str | None:
    """What the reader is told about missing summaries or cards, or None."""
    failure = (doc.extraction_report or {}).get(REPORT_KEY)
    if not failure or doc.stage != "complete":
        return None
    missing = await _missing(session, doc.id)
    if not missing:
        return None
    text = f"No {' or '.join(missing)} were written for this document: {failure['reason']}."
    if "summaries" in missing:
        text += " Generate one from the Summary panel once the provider accepts calls again."
    if "chapter cards" in missing:
        text += " Chapter cards are tried again when Luminary next starts."
    return text


async def _missing(session: AsyncSession, document_id: str) -> list[str]:
    summaries = SummaryRepo(session)
    missing = []
    has_summary = any(not m.startswith("_") for m in await summaries.modes(document_id))
    if not has_summary and not await summaries.section_summaries(document_id):
        missing.append("summaries")
    if await EnrichmentRepo(session).latest_status(document_id, "chapter_cards") == "failed":
        missing.append("chapter cards")
    return missing
