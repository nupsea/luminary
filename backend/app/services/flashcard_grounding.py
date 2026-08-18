"""Whether the cards already in a deck can prove where they came from.

The generation gate stops an ungrounded card from being created. It says nothing
about the cards created before it existed, and a deck is not regenerated -- it is
reviewed for years. Measured on a real library of 949 cards: 26% of the cards that
quoted anything quoted text that is not in their document, and every one of them
was being shown to the reviewer under a heading that reads "Source".

This recomputes the verdict from the document's own chunks. No model is involved:
the question "is this span in that text" is decided by looking.

The audit never downgrades a verdict it cannot re-derive. A note-sourced card has
no document to check against, and its verdict was decided at generation while the
note text was in hand; overwriting that with `unverifiable` would destroy a real
measurement and replace it with an absence of one.
"""

from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, FlashcardModel
from app.services.flashcard_parsers import (
    GROUNDING_UNCHECKED,
    GROUNDING_UNVERIFIABLE,
    grounding_state,
)

logger = logging.getLogger(__name__)

# A card from these sources never claimed to quote a passage: `source_excerpt`
# holds the knowledge gap the card was written from, not a span of any document.
# Auditing it would report a label as a fabricated quote, which is a worse lie
# than the one this module exists to catch.
_PASSAGE_LESS_SOURCES = frozenset({"gap"})


async def _document_text(document_id: str, session: AsyncSession) -> str:
    """A document's chunks, in reading order.

    Order matters: a quote that spans a chunk boundary is real, and joining the
    chunks in whatever order the database returns them would report it as invented.
    """
    rows = await session.execute(
        select(ChunkModel.text)
        .where(ChunkModel.document_id == document_id)
        .order_by(ChunkModel.chunk_index)
    )
    return "\n".join(t for t in rows.scalars().all() if t)


async def audit_grounding(
    session: AsyncSession, document_id: str | None = None
) -> dict[str, int]:
    """Recompute and persist the grounding verdict for a deck.

    *document_id* limits the audit to one document; omitting it audits the library.
    Returns the resulting state counts plus how many verdicts changed.
    """
    stmt = select(FlashcardModel)
    if document_id is not None:
        stmt = stmt.where(FlashcardModel.document_id == document_id)
    cards = list((await session.execute(stmt)).scalars().all())

    by_document: dict[str | None, list[FlashcardModel]] = {}
    for card in cards:
        by_document.setdefault(card.document_id, []).append(card)

    counts: Counter[str] = Counter()
    changed = 0
    for doc_id, doc_cards in by_document.items():
        # One document's text at a time: a technical manual runs to millions of
        # words, and holding every document's chunks at once turns an audit into
        # an out-of-memory failure on the machine this app is meant to run on.
        text = await _document_text(doc_id, session) if doc_id else ""
        for card in doc_cards:
            if card.source in _PASSAGE_LESS_SOURCES:
                # We looked and there is nothing to check: say so, rather than
                # leaving the card reading "nobody has looked" forever.
                if card.grounding == GROUNDING_UNCHECKED:
                    card.grounding = GROUNDING_UNVERIFIABLE
                    changed += 1
                counts[card.grounding] += 1
                continue
            if not text:
                # Nothing to check against. Record that we looked, but never
                # overwrite a verdict reached when the source text still existed.
                state = (
                    GROUNDING_UNVERIFIABLE
                    if card.grounding == GROUNDING_UNCHECKED
                    else card.grounding
                )
            else:
                state = grounding_state(card.source_excerpt, text)
            if state != card.grounding:
                card.grounding = state
                changed += 1
            counts[state] += 1

    if changed:
        await session.commit()
    logger.info(
        "flashcard grounding audit: %d cards, %d verdicts changed, %s",
        len(cards),
        changed,
        dict(counts),
    )
    return {"scanned": len(cards), "changed": changed, **counts}
