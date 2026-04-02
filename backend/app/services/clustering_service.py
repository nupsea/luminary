"""ClusteringService: HDBSCAN-based semantic note clustering with LLM-generated names.

Reads all note embeddings from LanceDB note_vectors_v2, runs sklearn HDBSCAN
(min_cluster_size=3, min_samples=2, metric='cosine') to group notes, computes
per-cluster confidence scores, generates human-readable collection names via LiteLLM,
and persists each cluster as a ClusterSuggestionModel row.

Users then accept (creates NoteCollection + members) or reject each suggestion via the API.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from functools import lru_cache

import litellm
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ClusterSuggestionModel,
    NoteCollectionModel,
    NoteModel,
)
from app.services.naming import normalize_collection_name

logger = logging.getLogger(__name__)

RATE_LIMIT_HOURS = 1


class ClusteringService:
    async def cluster_notes(self, db: AsyncSession) -> int:
        """Run HDBSCAN over note_vectors_v2 and insert ClusterSuggestionModel rows.

        Returns:
            Number of new suggestions created.
            -1 if rate-limited (pending suggestion < RATE_LIMIT_HOURS old).
            0 if too few notes with vectors (< min_cluster_size=3).
        """
        # Rate-limit check: if any pending suggestion was created within the last hour, skip
        now = datetime.now(UTC)
        rate_limit_cutoff = datetime.fromtimestamp(
            now.timestamp() - RATE_LIMIT_HOURS * 3600, tz=UTC
        )
        result = await db.execute(
            select(ClusterSuggestionModel)
            .where(ClusterSuggestionModel.status == "pending")
            .where(ClusterSuggestionModel.created_at > rate_limit_cutoff)
            .limit(1)
        )
        if result.scalar_one_or_none() is not None:
            logger.info(
                "Clustering rate-limited: pending suggestion within last %dh",
                RATE_LIMIT_HOURS,
            )
            return -1

        # Fetch all note vectors from LanceDB
        from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

        svc = get_lancedb_service()
        df = await asyncio.to_thread(lambda: svc._get_or_create_note_table().to_pandas())

        if len(df) < 3:
            logger.info("Too few note vectors (%d) for HDBSCAN (need >= 3); skipping", len(df))
            return 0

        note_ids = df["note_id"].tolist()
        vectors = df["vector"].tolist()
        matrix = np.array(vectors, dtype=np.float32)

        # Run HDBSCAN in thread (CPU-bound sync work)
        from sklearn.cluster import HDBSCAN  # noqa: PLC0415
        from sklearn.metrics.pairwise import cosine_similarity  # noqa: PLC0415

        labels = await asyncio.to_thread(
            lambda: HDBSCAN(min_cluster_size=3, min_samples=2, metric="cosine").fit_predict(matrix)
        )

        unique_labels = [lbl for lbl in set(labels.tolist()) if lbl != -1]
        if not unique_labels:
            logger.info("HDBSCAN found no clusters (all noise); skipping")
            return 0

        created = 0

        for label in unique_labels:
            member_indices = [i for i, lbl in enumerate(labels.tolist()) if lbl == label]
            member_note_ids = [note_ids[i] for i in member_indices]
            member_matrix = matrix[member_indices]

            # Compute centroid and select up to 3 medoid note_ids (closest to centroid)
            centroid = member_matrix.mean(axis=0)
            centroid_norm = centroid / (np.linalg.norm(centroid) + 1e-10)
            member_matrix_norms = member_matrix / (
                np.linalg.norm(member_matrix, axis=1, keepdims=True) + 1e-10
            )
            cosine_dists = 1.0 - (member_matrix_norms @ centroid_norm)
            sorted_indices = np.argsort(cosine_dists)
            medoid_note_ids = [member_note_ids[i] for i in sorted_indices[:3]]

            # Confidence score: mean pairwise cosine similarity for cluster members
            if len(member_matrix) >= 2:
                sim_matrix = cosine_similarity(member_matrix)
                n = len(member_matrix)
                upper_triangle = [
                    sim_matrix[i, j] for i in range(n) for j in range(i + 1, n)
                ]
                confidence_score = float(np.mean(upper_triangle)) if upper_triangle else 0.0
            else:
                confidence_score = 1.0

            # Fetch note content excerpts for medoids to build LLM prompt
            note_rows = (
                await db.execute(
                    select(NoteModel.id, NoteModel.content).where(
                        NoteModel.id.in_(medoid_note_ids)
                    )
                )
            ).all()
            excerpts = [row[1][:150] for row in note_rows]

            # Generate collection name via LiteLLM
            suggested_name = await self._generate_cluster_name(excerpts)

            suggestion = ClusterSuggestionModel(
                id=str(uuid.uuid4()),
                suggested_name=suggested_name,
                note_ids=member_note_ids,
                confidence_score=round(confidence_score, 4),
                status="pending",
                created_at=datetime.now(UTC),
            )
            db.add(suggestion)
            created += 1

        if created > 0:
            await db.commit()

        logger.info("Clustering complete: %d suggestions created", created)
        return created

    async def _generate_cluster_name(self, excerpts: list[str]) -> str:
        """Generate a 2-4 word collection name from note excerpts via LiteLLM.

        Falls back to 'Notes Cluster' if LLM is unavailable.
        """
        from app.services.settings_service import get_litellm_kwargs  # noqa: PLC0415

        if not excerpts:
            return "Notes Cluster"
        excerpts_text = "\n---\n".join(excerpts)
        try:
            response = await litellm.acompletion(
                **get_litellm_kwargs(),
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Given these note excerpts, suggest a 2-4 word collection name "
                            "capturing their common theme. Reply with the name only. "
                            "No quotes, no punctuation, no explanation."
                        ),
                    },
                    {"role": "user", "content": excerpts_text},
                ],
                temperature=0.0,
            )
            raw = (response.choices[0].message.content or "").strip()
            # Sanitize: take first line, limit to 60 chars
            name = raw.split("\n")[0].strip()[:60]
            return name if name else "Notes Cluster"
        except Exception as exc:
            logger.warning("LLM cluster naming failed (non-fatal): %s", exc)
            return "Notes Cluster"

    async def get_pending_last_run(self, db: AsyncSession) -> datetime | None:
        """Return the created_at of the latest pending suggestion, or None."""
        result = await db.execute(
            select(ClusterSuggestionModel.created_at)
            .where(ClusterSuggestionModel.status == "pending")
            .order_by(ClusterSuggestionModel.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_pending_suggestions(self, db: AsyncSession) -> list[dict]:
        """Return pending ClusterSuggestionModel rows sorted by confidence_score DESC.

        Each row includes ALL note_ids with content excerpts (for Organization Plan dialog).
        """
        result = await db.execute(
            select(ClusterSuggestionModel)
            .where(ClusterSuggestionModel.status == "pending")
            .order_by(ClusterSuggestionModel.confidence_score.desc())
        )
        suggestions = list(result.scalars().all())

        if not suggestions:
            return []

        # Bulk-load note excerpts for ALL note_ids across all suggestions
        all_note_ids: list[str] = []
        for s in suggestions:
            all_note_ids.extend(s.note_ids or [])

        note_map: dict[str, str] = {}
        if all_note_ids:
            note_rows = (
                await db.execute(
                    select(NoteModel.id, NoteModel.content).where(
                        NoteModel.id.in_(all_note_ids)
                    )
                )
            ).all()
            note_map = {row[0]: row[1][:200] for row in note_rows}

        output = []
        for s in suggestions:
            nids = s.note_ids or []
            previews = [
                {"note_id": nid, "excerpt": note_map.get(nid, "")}
                for nid in nids
            ]
            output.append(
                {
                    "id": s.id,
                    "suggested_name": s.suggested_name,
                    "note_ids": nids,
                    "note_count": len(nids),
                    "confidence_score": s.confidence_score,
                    "status": s.status,
                    "created_at": s.created_at,
                    "previews": previews,
                }
            )
        return output

    async def accept_suggestion(
        self, suggestion_id: str, db: AsyncSession
    ) -> str | None:
        """Accept a cluster suggestion: create NoteCollection + members, mark accepted.

        Returns the new collection_id, or None if suggestion not found.
        """
        result = await db.execute(
            select(ClusterSuggestionModel).where(ClusterSuggestionModel.id == suggestion_id)
        )
        suggestion = result.scalar_one_or_none()
        if suggestion is None:
            return None

        # Create NoteCollection
        collection_id = str(uuid.uuid4())
        collection = NoteCollectionModel(
            id=collection_id,
            name=normalize_collection_name(suggestion.suggested_name),
            color="#6366F1",
            sort_order=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(collection)
        await db.flush()

        # Insert member rows using INSERT OR IGNORE (same pattern as collections router)
        from sqlalchemy import text as sa_text  # noqa: PLC0415

        for note_id in suggestion.note_ids or []:
            await db.execute(
                sa_text(
                    "INSERT OR IGNORE INTO note_collection_members"
                    " (id, note_id, collection_id, added_at)"
                    " VALUES (:id, :note_id, :collection_id, :added_at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "note_id": note_id,
                    "collection_id": collection_id,
                    "added_at": datetime.now(UTC).isoformat(),
                },
            )

        suggestion.status = "accepted"
        await db.commit()

        logger.info(
            "Accepted cluster suggestion %s -> collection %s (%d notes)",
            suggestion_id,
            collection_id,
            len(suggestion.note_ids or []),
        )
        return collection_id

    async def batch_accept_suggestions(
        self,
        items: list[dict],
        db: AsyncSession,
    ) -> list[str]:
        """Accept multiple cluster suggestions in a single transaction.

        Args:
            items: list of {"suggestion_id": str, "name_override": str | None,
                            "note_ids": list[str] | None}
            db: AsyncSession

        Returns:
            List of created collection IDs.
        """
        suggestion_ids = [it["suggestion_id"] for it in items]
        result = await db.execute(
            select(ClusterSuggestionModel).where(
                ClusterSuggestionModel.id.in_(suggestion_ids),
                ClusterSuggestionModel.status == "pending",
            )
        )
        suggestion_map = {s.id: s for s in result.scalars().all()}

        # Build override maps keyed by suggestion_id
        name_overrides = {
            it["suggestion_id"]: it["name_override"]
            for it in items
            if it.get("name_override")
        }
        note_ids_overrides = {
            it["suggestion_id"]: it["note_ids"]
            for it in items
            if it.get("note_ids") is not None
        }

        from sqlalchemy import text as sa_text  # noqa: PLC0415

        created_ids: list[str] = []

        for sid in suggestion_ids:
            suggestion = suggestion_map.get(sid)
            if suggestion is None:
                continue

            collection_id = str(uuid.uuid4())
            raw_name = name_overrides.get(sid) or suggestion.suggested_name
            name = normalize_collection_name(raw_name)
            collection = NoteCollectionModel(
                id=collection_id,
                name=name,
                color="#6366F1",
                sort_order=0,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            db.add(collection)
            await db.flush()

            # Use overridden note_ids if provided (drag-and-drop), else original
            effective_note_ids = note_ids_overrides.get(sid) or suggestion.note_ids or []

            for note_id in effective_note_ids:
                await db.execute(
                    sa_text(
                        "INSERT OR IGNORE INTO note_collection_members"
                        " (id, note_id, collection_id, added_at)"
                        " VALUES (:id, :note_id, :collection_id, :added_at)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "note_id": note_id,
                        "collection_id": collection_id,
                        "added_at": datetime.now(UTC).isoformat(),
                    },
                )

            suggestion.status = "accepted"
            created_ids.append(collection_id)

        if created_ids:
            await db.commit()

        logger.info("Batch accepted %d/%d cluster suggestions", len(created_ids), len(items))
        return created_ids

    async def reject_suggestion(self, suggestion_id: str, db: AsyncSession) -> bool:
        """Reject a cluster suggestion. Returns False if not found."""
        result = await db.execute(
            select(ClusterSuggestionModel).where(ClusterSuggestionModel.id == suggestion_id)
        )
        suggestion = result.scalar_one_or_none()
        if suggestion is None:
            return False
        suggestion.status = "rejected"
        await db.commit()
        return True


@lru_cache
def get_clustering_service() -> ClusteringService:
    return ClusteringService()
