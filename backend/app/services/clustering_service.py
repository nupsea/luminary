"""ClusteringService: HDBSCAN-based semantic note clustering with LLM-generated names.

Reads all note embeddings from LanceDB note_vectors_v2, runs sklearn HDBSCAN
(min_cluster_size=3, min_samples=2, metric='cosine') to group notes, computes
per-cluster confidence scores, generates human-readable collection names via LiteLLM,
and persists each cluster as a ClusterSuggestionModel row.

Users then accept (creates Collection + members) or reject each suggestion via the API.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from functools import lru_cache

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CanonicalTagModel, ClusterSuggestionModel, TagAliasModel
from app.repos.cluster_repo import ClusterRepo
from app.repos.collection_repo import CollectionRepo
from app.repos.note_repo import NoteRepo
from app.repos.tag_repo import TagRepo
from app.services import (
    vector_store as _vector_store_module,  # indirect: get_lancedb_service is patched
)
from app.services.llm import get_llm_service
from app.services.naming import normalize_collection_name, normalize_tag_slug

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
        if await ClusterRepo(db).has_pending_since(rate_limit_cutoff):
            logger.info(
                "Clustering rate-limited: pending suggestion within last %dh",
                RATE_LIMIT_HOURS,
            )
            return -1

        # Fetch all note vectors from LanceDB

        svc = _vector_store_module.get_lancedb_service()
        df = await asyncio.to_thread(lambda: svc._get_or_create_note_table().to_pandas())

        if len(df) < 3:
            logger.info("Too few note vectors (%d) for HDBSCAN (need >= 3); skipping", len(df))
            return 0

        note_ids = df["note_id"].tolist()
        vectors = df["vector"].tolist()
        matrix = np.array(vectors, dtype=np.float32)

        # Run HDBSCAN in thread (CPU-bound sync work). sklearn imports stay
        # lazy: they're heavy, and tests patch `sklearn.cluster.HDBSCAN`
        # directly, which only works when this module looks the name up at
        # call time rather than caching a top-level binding.
        from sklearn.cluster import HDBSCAN  # noqa: PLC0415

        labels = await asyncio.to_thread(
            lambda: HDBSCAN(min_cluster_size=3, min_samples=2, metric="cosine").fit_predict(matrix)
        )

        unique_labels = [lbl for lbl in set(labels.tolist()) if lbl != -1]
        if not unique_labels:
            logger.info("HDBSCAN found no clusters (all noise); skipping")
            return 0

        created = 0
        suggestions: list[ClusterSuggestionModel] = []

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
                from sklearn.metrics.pairwise import cosine_similarity  # noqa: PLC0415

                sim_matrix = cosine_similarity(member_matrix)
                n = len(member_matrix)
                upper_triangle = [sim_matrix[i, j] for i in range(n) for j in range(i + 1, n)]
                confidence_score = float(np.mean(upper_triangle)) if upper_triangle else 0.0
            else:
                confidence_score = 1.0

            # Fetch note content excerpts for medoids to build LLM prompt
            excerpts = [
                snippet for _id, snippet, _n in await NoteRepo(db).snippets(medoid_note_ids, 150)
            ]

            # Generate collection name via LiteLLM
            suggested_name = await self._generate_cluster_name(excerpts)

            suggestions.append(
                ClusterSuggestionModel(
                    id=str(uuid.uuid4()),
                    suggested_name=suggested_name,
                    note_ids=member_note_ids,
                    confidence_score=round(confidence_score, 4),
                    status="pending",
                    created_at=datetime.now(UTC),
                )
            )
            created += 1

        # Added only once the naming calls are done, never inside the loop.
        #
        # `db.add` inside the loop left a row pending, and the next iteration's
        # note read autoflushed it -- which takes SQLite's single write
        # lock. The loop then `await`ed an LLM call per cluster while holding it.
        # Measured on a real library: 11.2s before commit, against a 5.0s
        # busy_timeout, so every concurrent writer failed with "database is locked"
        # -- notes, web references, collections and the enrichment queue alike (#88).
        # Nothing is dirty during the naming calls now, so the autoflush is a no-op
        # and the write lock is taken once, here, for the length of one insert.
        if suggestions:
            db.add_all(suggestions)
            await db.commit()

        logger.info("Clustering complete: %d suggestions created", created)
        return created

    async def _generate_cluster_name(self, excerpts: list[str]) -> str:
        """Generate a 2-4 word collection name from note excerpts via LiteLLM.

        Falls back to 'Notes Cluster' if LLM is unavailable.
        """
        if not excerpts:
            return "Notes Cluster"
        excerpts_text = "\n---\n".join(excerpts)
        try:
            raw = await get_llm_service().complete(
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
                background=True,
            )
            name = raw.strip().split("\n")[0].strip()[:60]
            return name if name else "Notes Cluster"
        except Exception as exc:
            logger.warning("LLM cluster naming failed (non-fatal): %s", exc)
            return "Notes Cluster"

    async def get_pending_last_run(self, db: AsyncSession) -> datetime | None:
        """Return the created_at of the latest pending suggestion, or None."""
        return await ClusterRepo(db).latest_pending_at()

    async def get_pending_suggestions(self, db: AsyncSession) -> list[dict]:
        """Return pending ClusterSuggestionModel rows sorted by confidence_score DESC.

        Each row includes ALL note_ids with content excerpts (for Organization Plan dialog).
        """
        suggestions = await ClusterRepo(db).pending_by_confidence()

        if not suggestions:
            return []

        # Bulk-load note excerpts for ALL note_ids across all suggestions
        all_note_ids: list[str] = []
        for s in suggestions:
            all_note_ids.extend(s.note_ids or [])

        note_map = {
            nid: snippet for nid, snippet, _n in await NoteRepo(db).snippets(all_note_ids, 200)
        }

        output = []
        for s in suggestions:
            nids = s.note_ids or []
            previews = [{"note_id": nid, "excerpt": note_map.get(nid, "")} for nid in nids]
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

    async def accept_suggestion(self, suggestion_id: str, db: AsyncSession) -> str | None:
        """Accept a cluster suggestion: create Collection + members, mark accepted.

        Returns the new collection_id, or None if suggestion not found.
        """
        suggestion = await ClusterRepo(db).find(suggestion_id)
        if suggestion is None:
            return None

        collections = CollectionRepo(db)
        collection = await collections.stage_new(
            normalize_collection_name(suggestion.suggested_name)
        )
        collection_id = collection.id
        await collections.stage_members(
            collection_id, list(suggestion.note_ids or []), member_type="note"
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
        suggestion_map = await ClusterRepo(db).pending_among(suggestion_ids)
        collections = CollectionRepo(db)

        # Build override maps keyed by suggestion_id
        name_overrides = {
            it["suggestion_id"]: it["name_override"] for it in items if it.get("name_override")
        }
        note_ids_overrides = {
            it["suggestion_id"]: it["note_ids"] for it in items if it.get("note_ids") is not None
        }

        created_ids: list[str] = []

        for sid in suggestion_ids:
            suggestion = suggestion_map.get(sid)
            if suggestion is None:
                continue

            raw_name = name_overrides.get(sid) or suggestion.suggested_name
            collection = await collections.stage_new(normalize_collection_name(raw_name))
            collection_id = collection.id

            # Use overridden note_ids if provided (drag-and-drop), else original
            effective_note_ids = note_ids_overrides.get(sid) or suggestion.note_ids or []
            await collections.stage_members(
                collection_id, list(effective_note_ids), member_type="note"
            )

            suggestion.status = "accepted"
            created_ids.append(collection_id)

        if created_ids:
            await db.commit()

        logger.info("Batch accepted %d/%d cluster suggestions", len(created_ids), len(items))
        return created_ids

    async def reject_suggestion(self, suggestion_id: str, db: AsyncSession) -> bool:
        """Reject a cluster suggestion. Returns False if not found."""
        suggestion = await ClusterRepo(db).find(suggestion_id)
        if suggestion is None:
            return False
        suggestion.status = "rejected"
        await db.commit()
        return True

    async def detect_naming_violations(self, db: AsyncSession) -> list[dict]:
        """Scan canonical tags and collections for naming convention violations.

        Returns a list of dicts:
          {"type": "tag"|"collection", "id": str, "current_name": str,
           "suggested_name": str, "action": "rename"|"merge",
           "merge_target_id": str | None}
        """

        violations: list[dict] = []

        # --- Tags ---
        tag_rows = await TagRepo(db).all_in_storage_order()

        # Build normalized-slug -> list of (id, original) for duplicate detection
        tag_norm_map: dict[str, list[str]] = {}
        for tag in tag_rows:
            normalized = normalize_tag_slug(tag.id)
            if not normalized:
                continue
            tag_norm_map.setdefault(normalized, []).append(tag.id)

        # Detect renames and merges
        for normalized, originals in tag_norm_map.items():
            if len(originals) == 1:
                # Simple rename if different
                original = originals[0]
                if original != normalized:
                    violations.append(
                        {
                            "type": "tag",
                            "id": original,
                            "current_name": original,
                            "suggested_name": normalized,
                            "action": "rename",
                            "merge_target_id": None,
                        }
                    )
            else:
                # Multiple originals map to the same slug -> merge
                # Keep the one that is already normalized, or the first one
                primary = normalized if normalized in originals else originals[0]
                for orig in originals:
                    if orig == primary and orig == normalized:
                        continue  # already correct
                    if orig == primary and orig != normalized:
                        # Primary needs rename too
                        violations.append(
                            {
                                "type": "tag",
                                "id": orig,
                                "current_name": orig,
                                "suggested_name": normalized,
                                "action": "rename",
                                "merge_target_id": None,
                            }
                        )
                    else:
                        violations.append(
                            {
                                "type": "tag",
                                "id": orig,
                                "current_name": orig,
                                "suggested_name": normalized,
                                "action": "merge",
                                "merge_target_id": primary if primary == normalized else normalized,
                            }
                        )

        # --- Collections ---
        coll_rows = await CollectionRepo(db).all_in_storage_order()

        for coll in coll_rows:
            normalized = normalize_collection_name(coll.name)
            if normalized and coll.name != normalized:
                violations.append(
                    {
                        "type": "collection",
                        "id": coll.id,
                        "current_name": coll.name,
                        "suggested_name": normalized,
                        "action": "rename",
                        "merge_target_id": None,
                    }
                )

        return violations

    async def apply_naming_fixes(
        self,
        fixes: list[dict],
        db: AsyncSession,
    ) -> dict:
        """Apply naming fixes transactionally.

        Each fix: {"type": "tag"|"collection", "id": str,
                   "current_name": str, "suggested_name": str,
                   "action": "rename"|"merge"}

        Returns {"tags_renamed": int, "collections_renamed": int, "tags_merged": int}
        """

        tags_renamed = 0
        tags_merged = 0
        collections_renamed = 0
        tag_repo = TagRepo(db)

        for fix in fixes:
            if fix["type"] == "tag":
                old_slug = fix["id"]
                new_slug = fix["suggested_name"]
                action = fix.get("action", "rename")

                if action == "merge":
                    # Repoint both shadow indexes from old_slug -> new_slug.
                    # NOTE: NoteModel.tags / DocumentModel.tags JSON columns are
                    # NOT rewritten here -- the shadow indexes now diverge from
                    # those columns until the next per-row write. The proper
                    # cross-content rewrite lives in TagMergeService; this
                    # bulk-clustering path should be migrated to call it.
                    await tag_repo.retarget_index_rows(old_slug, new_slug)
                    old_tag = await tag_repo.find_by_id(old_slug)
                    if old_tag:
                        await db.delete(old_tag)

                    target_tag = await tag_repo.find_by_id(new_slug)
                    new_usage = await tag_repo.index_usage(new_slug)
                    if target_tag:
                        target_tag.usage_count = new_usage
                    else:
                        db.add(
                            CanonicalTagModel(
                                id=new_slug,
                                display_name=new_slug.split("/")[-1],
                                parent_tag=new_slug.split("/")[0] if "/" in new_slug else None,
                                usage_count=new_usage,
                                created_at=datetime.now(UTC),
                            )
                        )

                    existing_alias = await tag_repo.find_alias(old_slug)
                    if not existing_alias:
                        db.add(TagAliasModel(alias=old_slug, canonical_tag_id=new_slug))

                    tags_merged += 1
                else:
                    # Rename: re-key the canonical tag PK and repoint both
                    # shadow indexes from old_slug to new_slug.
                    old_tag = await tag_repo.find_by_id(old_slug)

                    if old_tag:
                        prev_usage_count = old_tag.usage_count
                        display_name = new_slug.split("/")[-1]
                        parent_tag_id = (
                            "/".join(new_slug.split("/")[:-1]) if "/" in new_slug else None
                        )
                        await db.delete(old_tag)
                        await db.flush()
                        db.add(
                            CanonicalTagModel(
                                id=new_slug,
                                display_name=display_name,
                                parent_tag=parent_tag_id,
                                usage_count=prev_usage_count,
                                created_at=datetime.now(UTC),
                            )
                        )

                    await tag_repo.retarget_index_rows(old_slug, new_slug)

                    # Create tag alias

                    existing_alias = await tag_repo.find_alias(old_slug)
                    if not existing_alias:
                        db.add(TagAliasModel(alias=old_slug, canonical_tag_id=new_slug))

                    tags_renamed += 1

            elif fix["type"] == "collection":
                coll_id = fix["id"]
                new_name = fix["suggested_name"]
                coll = await CollectionRepo(db).find(coll_id)
                if coll:
                    coll.name = new_name
                    collections_renamed += 1

        await db.commit()
        return {
            "tags_renamed": tags_renamed,
            "collections_renamed": collections_renamed,
            "tags_merged": tags_merged,
        }


@lru_cache
def get_clustering_service() -> ClusteringService:
    return ClusteringService()
