"""Make every table that points at a flashcard agree with the flashcards that exist.

Three defects produced drift that no user action could clear, and all three are
fixed at the source -- this repairs what they already left behind. Measured on a
real 949-card library: 228 rows in the search index named a card that had been
deleted, 71 rows in the two card-scoped tables named one too, and one card was
missing from the index entirely and could not be found by any query.

- Deleting a *document* removed its cards but never their index rows, because
  `flashcards_fts` carries no `document_id` to match on.
- `fill_gaps` and the teach-back correction card were inserted without indexing,
  so they existed and were unsearchable.
- Deleting a *card* left its misconceptions and teach-back results behind.

`review_events` is not repaired and must not be: an event with no card is the
record of a review that really happened. See `flashcard_repo._CARD_CHILD_TABLES`.
"""

from __future__ import annotations

import logging

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FlashcardModel
from app.repos.flashcard_repo import _CARD_CHILD_TABLES
from app.services.flashcard_search import _sync_flashcard_fts

logger = logging.getLogger(__name__)


async def repair_flashcard_tables(session: AsyncSession) -> dict[str, int]:
    """Drop rows naming a card that no longer exists; index cards that are missing.

    Deterministic and idempotent: a second run reports zeroes.
    """
    live_ids = set(
        (await session.execute(select(FlashcardModel.id))).scalars().all()
    )

    # c2 is `flashcard_id` -- the virtual table is fts5(question, answer,
    # flashcard_id UNINDEXED), and an UNINDEXED column cannot be filtered on the
    # virtual table itself (I-4), so the shadow content table supplies the rowid.
    indexed: dict[str, int] = {
        card_id: rowid
        for rowid, card_id in (
            await session.execute(text("SELECT rowid, c2 FROM flashcards_fts_content"))
        ).all()
    }

    stale_rowids = [rowid for card_id, rowid in indexed.items() if card_id not in live_ids]
    for rowid in stale_rowids:
        await session.execute(
            text("DELETE FROM flashcards_fts WHERE rowid = :rid"), {"rid": rowid}
        )

    missing = live_ids - set(indexed)
    if missing:
        cards = (
            (
                await session.execute(
                    select(FlashcardModel).where(FlashcardModel.id.in_(list(missing)))
                )
            )
            .scalars()
            .all()
        )
        for card in cards:
            await _sync_flashcard_fts(card, session)

    orphan_rows = 0
    for model in _CARD_CHILD_TABLES:
        result = await session.execute(
            delete(model).where(model.flashcard_id.notin_(select(FlashcardModel.id)))
        )
        orphan_rows += result.rowcount or 0

    await session.commit()
    report = {
        "index_rows_removed": len(stale_rowids),
        "cards_indexed": len(missing),
        "orphan_rows_removed": orphan_rows,
    }
    logger.info("flashcard repair: %s", report)
    return report
