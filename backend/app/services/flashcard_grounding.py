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

from app.exceptions import DependencyUnavailable
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


async def passage_for_card(card: FlashcardModel, session: AsyncSession) -> str:
    """The text this card was actually written from, when that is recoverable.

    Prefers `source_chunk_ids` -- the chunks whose text was in the prompt, in
    reading order. Falls back to the whole document, which is what every card
    created before that column existed has to be checked against; the fallback is
    strictly more permissive, since a quote from anywhere in the book passes.

    Never falls back to `chunk_id`: that column is the first chunk of the scope,
    and reading it as the card's passage is what made a retrospective measurement
    read 0.3333.
    """
    ids = card.source_chunk_ids
    if ids:
        rows = await session.execute(
            select(ChunkModel.id, ChunkModel.text).where(ChunkModel.id.in_(list(ids)))
        )
        by_id = {cid: txt or "" for cid, txt in rows.all()}
        # Reading order is the recorded order, not the query's.
        return "\n\n".join(by_id[cid] for cid in ids if cid in by_id)
    if card.document_id:
        return await _document_text(card.document_id, session)
    return ""


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
                # A recorded passage is the text the model actually saw, so the
                # quote has to be in *that*, not merely somewhere in the book.
                # Checking against the whole document lets a card quote page 400
                # of a passage that ended on page 12.
                own = await passage_for_card(card, session) if card.source_chunk_ids else text
                state = grounding_state(card.source_excerpt, own or text)
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


async def audit_factuality(
    session: AsyncSession, *, limit: int = 50, document_id: str | None = None
) -> dict[str, int]:
    """Check whether existing cards' answers follow from their recorded passage.

    Only cards with a recoverable passage are eligible. That is the whole reason
    `source_chunk_ids` exists: judged against a passage reconstructed from
    `chunk_id`, a sample of 60 live cards scored 0.3333 and the number was an
    artefact of the reconstruction -- the judge was shown text without the card's
    own quote in it 56 times. A card whose passage cannot be rebuilt is skipped
    and counted as skipped, never judged against an approximation.

    Bounded by *limit* and resumable: each call takes one model call per card, so
    a whole library is minutes of inference. `remaining` reports what is left.
    """
    from app.services.flashcard import get_llm_service  # noqa: PLC0415
    from app.services.flashcard_factuality import (  # noqa: PLC0415
        FACTUALITY_UNCHECKED,
        check_answer,
        effective_generation_model,
        factuality_model,
        is_self_judging,
    )

    checker = factuality_model()
    if not checker:
        raise DependencyUnavailable(
            "No factuality checker is configured. Set FLASHCARD_FACTUALITY_MODEL to a "
            "model that is not the generation model; there is deliberately no default, "
            "because the small local models measured for this pass ~90% of everything."
        )
    if is_self_judging(checker, effective_generation_model()):
        raise DependencyUnavailable(
            f"The factuality checker {checker} is also the generation model. A model "
            f"asked whether its own card follows from a passage agrees with itself."
        )

    stmt = select(FlashcardModel).where(
        FlashcardModel.factuality == FACTUALITY_UNCHECKED,
        FlashcardModel.source_chunk_ids.isnot(None),
    )
    if document_id is not None:
        stmt = stmt.where(FlashcardModel.document_id == document_id)
    remaining_stmt = stmt
    cards = list((await session.execute(stmt.limit(limit))).scalars().all())

    llm = get_llm_service()
    counts: Counter[str] = Counter()
    skipped = 0
    for card in cards:
        passage = await passage_for_card(card, session)
        if not passage:
            # A recorded-but-unrecoverable passage: the chunks are gone, most
            # likely re-ingested. Not judged, and not counted as a verdict.
            skipped += 1
            continue
        verdict = await check_answer(
            card.question, card.answer, passage, checker=checker, llm=llm
        )
        card.factuality = verdict
        counts[verdict] += 1

    if counts:
        await session.commit()
    left = len(
        (await session.execute(remaining_stmt)).scalars().all()
    )
    logger.info(
        "flashcard factuality audit: %d judged, %d skipped, %d left, %s",
        sum(counts.values()),
        skipped,
        left,
        dict(counts),
    )
    return {
        "judged": sum(counts.values()),
        "skipped_no_passage": skipped,
        "remaining": left,
        **counts,
    }
