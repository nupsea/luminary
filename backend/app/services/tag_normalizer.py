"""SmartTagNormalizerService: embedding-based tag similarity scan and merge suggestions.

Scans all canonical tag display_names, embeds them via EmbeddingService (bge-small-en-v1.5),
computes pairwise cosine similarity, and stores pairs above 0.85 threshold as
TagMergeSuggestionModel rows (skipping pairs already linked via TagAliasModel).

Users then accept or reject each suggestion via the API. Accepting reuses the same
note-rewrite + alias-creation + canonical-tag-deletion logic as POST /tags/merge.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CanonicalTagModel,
    TagAliasModel,
    TagMergeSuggestionModel,
)

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.85


@dataclass
class TagSuggestionDetail:
    id: str
    tag_a_id: str
    tag_a_display_name: str
    tag_a_usage_count: int
    tag_b_id: str
    tag_b_display_name: str
    tag_b_usage_count: int
    similarity: float
    suggested_canonical_id: str
    status: str
    created_at: datetime


class SmartTagNormalizerService:
    async def scan(self, session: AsyncSession) -> int:
        """Embed all canonical tag display_names and find similar pairs.

        Returns the count of new TagMergeSuggestionModel rows created.
        Skips pairs already linked in TagAliasModel (in either direction).
        """
        # Load all canonical tags
        result = await session.execute(select(CanonicalTagModel).order_by(CanonicalTagModel.id))
        tags = list(result.scalars().all())

        if len(tags) < 2:
            logger.info("Not enough canonical tags to scan (%d); skipping", len(tags))
            return 0

        # Build set of existing aliases (both directions) for fast skip
        alias_result = await session.execute(select(TagAliasModel))
        aliases = alias_result.scalars().all()
        linked_pairs: set[frozenset[str]] = {
            frozenset([a.alias, a.canonical_tag_id]) for a in aliases
        }

        # Every existing suggestion, read once, in both orientations.
        #
        # This was a SELECT per candidate pair, and that is what made the scan
        # hold the write lock: autoflush is on, so the first `session.add` below
        # was flushed by the next iteration's SELECT, and the write transaction
        # then stayed open for the rest of an O(n^2) loop. Measured on synthetic
        # tag sets -- 300 tags held it 2.17s, 600 held it 13.9s, 900 held it
        # 48.5s, against a 5s busy_timeout -- which is why an ordinary
        # `POST /notes` failed with "database is locked" whenever a scan was
        # running (#88). Both orientations are reachable: (a-mouse, mouse) and
        # (mouse, a-mouse) were both present in a real library.
        suggestion_rows = await session.execute(
            select(TagMergeSuggestionModel.tag_a_id, TagMergeSuggestionModel.tag_b_id)
        )
        suggested_pairs: set[frozenset[str]] = {
            frozenset([a, b]) for a, b in suggestion_rows.all()
        }

        # Embed display_names using the synchronous EmbeddingService in a thread
        from app.services.embedder import get_embedding_service  # noqa: PLC0415

        display_names = [t.display_name for t in tags]
        raw_embeddings = await asyncio.to_thread(get_embedding_service().encode, display_names)
        # EmbeddingService returns L2-normalized embeddings (normalize_embeddings=True)
        # so cosine similarity = dot product
        embeddings = np.array(raw_embeddings, dtype=np.float32)  # (N, D)

        # Pairwise similarity matrix: sims[i][j] = cosine(tags[i], tags[j])
        sims = embeddings @ embeddings.T  # (N, N)

        n = len(tags)
        pending: list[TagMergeSuggestionModel] = []

        for i in range(n):
            for j in range(i + 1, n):
                sim = float(sims[i, j])
                if sim <= SIMILARITY_THRESHOLD:
                    continue

                tag_a = tags[i]
                tag_b = tags[j]

                # Skip same slug
                if tag_a.id == tag_b.id:
                    continue

                # Skip if already linked as aliases
                if frozenset([tag_a.id, tag_b.id]) in linked_pairs:
                    logger.debug("Skipping already-aliased pair (%s, %s)", tag_a.id, tag_b.id)
                    continue

                # Skip if a suggestion already exists for this pair (any status).
                if frozenset([tag_a.id, tag_b.id]) in suggested_pairs:
                    continue

                # Suggested canonical = whichever has higher usage_count
                suggested_canonical_id = (
                    tag_a.id if tag_a.usage_count >= tag_b.usage_count else tag_b.id
                )

                pending.append(
                    TagMergeSuggestionModel(
                        id=str(uuid.uuid4()),
                        tag_a_id=tag_a.id,
                        tag_b_id=tag_b.id,
                        similarity=round(sim, 4),
                        suggested_canonical_id=suggested_canonical_id,
                        status="pending",
                        created_at=datetime.now(UTC),
                    )
                )

        # Held until the loop is done on purpose. Adding inside it puts the
        # write in the same transaction as the remaining iterations, and the
        # writer then owns the SQLite write lock for the whole scan (#88).
        created = len(pending)
        if created > 0:
            session.add_all(pending)
            await session.commit()

        logger.info("Tag normalization scan complete: %d new suggestions", created)
        return created

    async def get_pending_suggestions(self, session: AsyncSession) -> list[TagSuggestionDetail]:
        """Return all pending suggestions with expanded tag_a and tag_b info."""
        result = await session.execute(
            select(TagMergeSuggestionModel)
            .where(TagMergeSuggestionModel.status == "pending")
            .order_by(TagMergeSuggestionModel.similarity.desc())
        )
        suggestions = result.scalars().all()
        if not suggestions:
            return []

        # Collect all tag IDs we need to look up
        tag_ids = set()
        for s in suggestions:
            tag_ids.add(s.tag_a_id)
            tag_ids.add(s.tag_b_id)

        tags_result = await session.execute(
            select(CanonicalTagModel).where(CanonicalTagModel.id.in_(tag_ids))
        )
        tag_by_id: dict[str, CanonicalTagModel] = {t.id: t for t in tags_result.scalars().all()}

        details: list[TagSuggestionDetail] = []
        for s in suggestions:
            tag_a = tag_by_id.get(s.tag_a_id)
            tag_b = tag_by_id.get(s.tag_b_id)
            if tag_a is None or tag_b is None:
                # Orphaned suggestion (tag deleted) -- skip
                continue
            details.append(
                TagSuggestionDetail(
                    id=s.id,
                    tag_a_id=s.tag_a_id,
                    tag_a_display_name=tag_a.display_name,
                    tag_a_usage_count=tag_a.usage_count,
                    tag_b_id=s.tag_b_id,
                    tag_b_display_name=tag_b.display_name,
                    tag_b_usage_count=tag_b.usage_count,
                    similarity=s.similarity,
                    suggested_canonical_id=s.suggested_canonical_id,
                    status=s.status,
                    created_at=s.created_at,
                )
            )
        return details

    async def get_suggestion_for_accept(
        self, suggestion_id: str, session: AsyncSession
    ) -> tuple[TagMergeSuggestionModel, str, str]:
        """Validate and return (suggestion, source_id, target_id) for the accept flow.

        Raises ValueError if not found or already resolved.
        The actual merge (note rewrites, alias creation, tag deletion) is performed
        by the router layer so it can call _sync_tag_index without violating the
        six-layer import rule (Service must not import from Router/API layer).
        """
        suggestion = (
            await session.execute(
                select(TagMergeSuggestionModel).where(TagMergeSuggestionModel.id == suggestion_id)
            )
        ).scalar_one_or_none()
        if suggestion is None:
            raise ValueError(f"Suggestion {suggestion_id!r} not found")
        if suggestion.status != "pending":
            raise ValueError(f"Suggestion {suggestion_id!r} is already {suggestion.status}")

        target_id = suggestion.suggested_canonical_id
        source_id = suggestion.tag_a_id if suggestion.tag_b_id == target_id else suggestion.tag_b_id
        return suggestion, source_id, target_id

    async def reject_suggestion(self, suggestion_id: str, session: AsyncSession) -> None:
        """Set suggestion status to rejected."""
        suggestion = (
            await session.execute(
                select(TagMergeSuggestionModel).where(TagMergeSuggestionModel.id == suggestion_id)
            )
        ).scalar_one_or_none()
        if suggestion is None:
            raise ValueError(f"Suggestion {suggestion_id!r} not found")

        suggestion.status = "rejected"
        session.add(suggestion)
        await session.commit()
        logger.info("Rejected tag merge suggestion %s", suggestion_id)


_service: SmartTagNormalizerService | None = None


def get_tag_normalizer_service() -> SmartTagNormalizerService:
    global _service
    if _service is None:
        _service = SmartTagNormalizerService()
    return _service
