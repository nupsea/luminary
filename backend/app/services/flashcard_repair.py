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

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChunkModel, FlashcardModel
from app.repos.document_repo import DocumentRepo
from app.repos.flashcard_repo import FlashcardRepo
from app.services.flashcard_grounding import card_quote, quote_home

logger = logging.getLogger(__name__)

# Bound on one IN (...) list: SQLite's variable limit is far above it on every build we ship.
_ID_BATCH = 500


async def repair_flashcard_tables(session: AsyncSession) -> dict[str, int]:
    """Drop rows naming a card that no longer exists; index cards that are missing.

    Deterministic and idempotent: a second run reports zeroes.
    """
    repo = FlashcardRepo(session)
    live_ids = await repo.all_ids()
    indexed = await repo.fts_index()

    stale_rowids = [rowid for card_id, rowid in indexed.items() if card_id not in live_ids]
    for rowid in stale_rowids:
        await repo.delete_fts_row(rowid)

    missing = live_ids - set(indexed)
    for card in (await repo.get_many(list(missing))).values():
        await repo.sync_fts(card)

    orphan_rows = await repo.delete_orphan_children()
    refiled = await refile_cards(session)

    await session.commit()
    report = {
        "index_rows_removed": len(stale_rowids),
        "cards_indexed": len(missing),
        "orphan_rows_removed": orphan_rows,
        "cards_refiled": refiled,
    }
    logger.info("flashcard repair: %s", report)
    return report


async def refile_cards(session: AsyncSession) -> int:
    """File each card under the section its quote is in (I-35). Returns how many moved.

    Only a card whose quote is in exactly one window of its passage moves. Caller commits.
    """
    from app.services.flashcard import (  # noqa: PLC0415
        _get_section_context_for_chunks,
        _resolve_section_heading,
    )

    cards = [
        c
        for c in await FlashcardRepo(session).all_for(None)
        if c.source_chunk_ids and card_quote(c)
    ]
    chunks = await _chunks_named_by(cards, session)
    moves = [(card, home) for card in cards if (home := _misfiled_home(card, chunks))]
    if not moves:
        return 0

    section_ctx = await _get_section_context_for_chunks([home for _card, home in moves], session)
    for card, home in moves:
        card.chunk_id = home.id
        card.section_heading = _resolve_section_heading(home, section_ctx)
    logger.info("flashcard repair: %d card(s) moved to the section of their quote", len(moves))
    return len(moves)


async def _chunks_named_by(
    cards: list[FlashcardModel], session: AsyncSession
) -> dict[str, ChunkModel]:
    wanted = sorted(
        {cid for c in cards for cid in c.source_chunk_ids or [] if isinstance(cid, str)}
        | {c.chunk_id for c in cards if c.chunk_id}
    )
    docs = DocumentRepo(session)
    chunks: dict[str, ChunkModel] = {}
    for i in range(0, len(wanted), _ID_BATCH):
        chunks.update({c.id: c for c in await docs.chunks_by_ids(wanted[i : i + _ID_BATCH])})
    return chunks


def _misfiled_home(card: FlashcardModel, chunks: dict[str, ChunkModel]) -> ChunkModel | None:
    """The chunk holding the card's quote, when that is in another section than `chunk_id`."""
    home = quote_home(card, chunks)
    stored = chunks.get(card.chunk_id or "")
    if home is None or (stored is not None and stored.section_id == home.section_id):
        return None
    return home
