"""Per-chunk content-date extraction for temporal retrieval filtering.

"My daily thoughts this month" needs the date the content was WRITTEN, not when
it was ingested (created_at) -- a month of daily notes bulk-imported today all
share one created_at. So each chunk gets an ``entry_date`` parsed from its own
text, forward-filled through the document: a chunk without a date inherits the
most recent dated chunk above it (the "Date: 2026-01-15" header of its entry).
"""

import re
from datetime import date

from dateutil import parser as _du
from sqlalchemy import text

_MONTHS = r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
# Explicit "Date:"/"Dated:" line -> capture the value.
_DATE_LINE = re.compile(r"(?im)^\s*(?:date|dated|entry)\s*[:\-]\s*(.+?)\s*$")
# ISO 8601 anywhere near the top.
_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
# "July 3, 2026" / "3 July 2026" -- a DAY is required. A bare "March 2017"
# (ubiquitous in references) is deliberately NOT a content date.
_MONTH_DMY = re.compile(
    rf"\b((?:{_MONTHS})[a-z]*\.?\s+\d{{1,2}},?\s+\d{{4}}"
    rf"|\d{{1,2}}\s+(?:{_MONTHS})[a-z]*\.?\s+\d{{4}})\b",
    re.I,
)


def extract_date(chunk_text: str) -> date | None:
    """Return the content date at the head of a chunk, or None. Conservative:
    only fires on an explicit date line or an unambiguous date near the top."""
    head = chunk_text[:400]
    for rx in (_DATE_LINE, _ISO, _MONTH_DMY):
        m = rx.search(head)
        if not m:
            continue
        raw = m.group(1) if m.lastindex else m.group(0)
        try:
            parsed = _du.parse(raw, fuzzy=False, default=_du.parse("2000-01-01"))
            return parsed.date()
        except (ValueError, OverflowError):
            continue
    return None


# A document earns date forward-filling only if it has genuine dated-entry
# structure: enough directly-dated chunks (absolute + relative) and several
# distinct dates. This is what separates a journal/transcript log from a book
# whose one stray reference date would otherwise smear over every chunk.
_MIN_DATED_CHUNKS = 3
_MIN_DATED_FRACTION = 0.05
_MIN_DISTINCT_DATES = 2


async def assign_entry_dates(session, document_id: str) -> int:
    """Forward-fill content dates over a document's chunks (in order) and persist
    to chunks.entry_date -- but ONLY for documents that look like dated-entry
    logs. Returns the number of chunks dated (0 if the doc doesn't qualify)."""
    rows = (
        await session.execute(
            text("SELECT id, text FROM chunks WHERE document_id=:d ORDER BY chunk_index"),
            {"d": document_id},
        )
    ).fetchall()
    if not rows:
        return 0
    direct = [(cid, extract_date(body or "")) for cid, body in rows]
    hits = [d for _, d in direct if d is not None]
    if (
        len(hits) < _MIN_DATED_CHUNKS
        or len(hits) < _MIN_DATED_FRACTION * len(rows)
        or len({d for d in hits}) < _MIN_DISTINCT_DATES
    ):
        return 0

    current: date | None = None
    dated = 0
    for cid, found in direct:
        if found is not None:
            current = found
        if current is not None:
            await session.execute(
                text("UPDATE chunks SET entry_date=:e WHERE id=:i"),
                {"e": current.isoformat(), "i": cid},
            )
            dated += 1
    return dated
