"""Document auto-tagging service + enrichment runner.

The service is a thin LLM caller that returns up to 5 short, lowercase tag
suggestions for a document's content. The runner is the non-blocking task
scheduled from ingestion's finalize node (and from the manual retag
endpoint) -- it owns slug normalization, provenance writes, and the
DocumentModel.tags + shadow-index update.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import func, select

from app.config import get_settings
from app.database import get_session_factory
from app.models import (
    ChunkModel,
    DocumentModel,
    DocumentTagIndexModel,
    DocumentTagProvenanceModel,
    SummaryModel,
)
from app.services import graph as _graph_module  # indirect: get_graph_service is patched in tests
from app.services.llm_json import parse_llm_json_array
from app.services.naming import normalize_tag_slug
from app.services.notes_service import sync_document_tag_index

logger = logging.getLogger(__name__)

LLM_TAGGER_VERSION = "doc-1"
ENTITY_TAGGER_VERSION = "entity-1"

# Entity-tag budget scales with the log of chunk count: K = BASE + SLOPE*log2,
# clamped to [MIN, AUTO_TAG_ENTITY_CAP_MAX]. Calibrated so ~18 chunks -> ~12
# tags, ~5k chunks -> ~29, with the cap holding the top.
_ENTITY_TAG_BUDGET_BASE = 4.0
_ENTITY_TAG_BUDGET_SLOPE = 2.0
_ENTITY_TAG_BUDGET_MIN = 5


def _entity_tag_budget(num_chunks: int, cap_max: int) -> int:
    raw = _ENTITY_TAG_BUDGET_BASE + _ENTITY_TAG_BUDGET_SLOPE * math.log2(max(num_chunks, 2))
    return max(_ENTITY_TAG_BUDGET_MIN, min(round(raw), cap_max))


async def _count_chunks(doc_id: str) -> int:
    async with get_session_factory()() as session:
        return (
            await session.execute(
                select(func.count(ChunkModel.id)).where(ChunkModel.document_id == doc_id)
            )
        ).scalar_one() or 0

# Content-type aware entity-type selection. Tech writing rarely benefits from
# PERSON / PLACE entities surfacing as tags (they're author cites, example
# characters, stack locations); narrative content benefits from exactly those
# (characters and settings ARE the topics). Mention-frequency threshold +
# stoplist still apply in both buckets.
_TECH_CONTENT_TYPES: frozenset[str] = frozenset(
    {"tech_book", "tech_article", "paper", "code", "conversation"}
)


def _allowed_entity_types_for(content_type: str | None) -> tuple[str, ...]:
    """Return the entity-type tuple to pass to the graph query for this doc."""
    if (content_type or "").lower() in _TECH_CONTENT_TYPES:
        return ("CONCEPT",)
    # Narrative-leaning content (book, epub, kindle_clippings, audio, notes,
    # plus anything unknown) gets characters and settings too.
    return ("PERSON", "PLACE", "CONCEPT")

# Tag-side stoplist: slugs that survive normalization but would be noise as
# browseable tags. Three buckets:
#   - Generic role / placeholder nouns from technical writing examples.
#   - Cryptography-style example names ("alice and bob").
#   - NER extraction artifacts we observed in the wild.
# Kept small and obvious -- tuning toward false negatives (let through) over
# false positives (silently drop a real concept). The mention threshold and
# CONCEPT-only entity filter do most of the heavy lifting.
TAG_STOPLIST: frozenset[str] = frozenset(
    {
        # Generic roles
        "user", "users", "admin", "admins", "admin-user", "end-user", "end-users",
        "viewer", "worker", "workers", "member", "members", "person", "people",
        "friend", "friends", "partner", "partners", "target", "crowd",
        "author", "authors", "reader", "readers", "writer", "writers",
        "employee", "employees", "customer", "customers", "client", "clients",
        "invoker", "individual", "individuals",
        # Numbered placeholder variants (catches user1..user9 etc.)
        *(f"user{i}" for i in range(1, 10)),
        # Crypto/example names
        "alice", "bob", "carol", "charlie", "dave", "eve", "mallory", "oscar",
        "trent", "wendy", "peggy", "victor",
        # NER artifacts / template fragments observed in the wild. The deeper
        # fix is to upgrade entity extraction itself; these are the specific
        # NER residues we've actually seen leak through.
        "mention", "mentions", "name", "names", "role", "roles",
        "thing", "things", "stuff", "item", "items", "example",
        "r-name", "ne-role", "persons-name", "your-name", "your-role",
        # Generic ambient concepts observed as noise in tech docs.
        # Intentionally NOT included: 'knowledge', 'idea', 'concept' --
        # they have legitimate topical uses in philosophy/epistemology.
        "planning", "dream", "love", "mind", "thought", "thoughts", "meaning",
    }
)

_SYSTEM = (
    "You are a tagging assistant. Given a document, suggest up to 5 short, "
    "lowercase tags that best describe its topics. Tags should be 1-3 words, "
    "no punctuation. Output ONLY a JSON array of strings, e.g. "
    '["machine learning", "python"]. Write no explanation, preamble, or '
    "markdown fences."
)

_USER_TMPL = (
    "Title:\n{title}\n\nSummary:\n{summary}\n\nExcerpt:\n{excerpt}\n\n"
    "Tags (JSON array, at most 5):"
)


def _parse_tag_list(raw: str) -> list[str]:
    """Parse LLM output into a list of at most 5 tags. Never raises."""
    if not raw:
        return []
    result = parse_llm_json_array(raw)
    return [str(t).strip().lower() for t in result if str(t).strip()][:5]


class DocumentTaggerService:
    """Suggest tags for a document's title + summary + excerpt."""

    async def suggest_tags(self, title: str, summary: str, excerpt: str) -> list[str]:
        """Return up to 5 suggested tags. Returns [] on any failure."""
        if not (title or summary or excerpt):
            return []
        from app.services.llm import get_llm_service  # noqa: PLC0415

        prompt = _USER_TMPL.format(
            title=title[:300],
            summary=(summary or "")[:600],
            excerpt=(excerpt or "")[:2000],
        )
        try:
            raw = await get_llm_service().complete(
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
            )
            return _parse_tag_list(raw)
        except Exception as exc:
            # 2D.1.b: any failure logs and returns []. Never propagates so the
            # caller (background task) survives LLM outages, parse drift, etc.
            logger.warning("document tagger failed (non-fatal): %s", exc)
            return []


@lru_cache
def get_document_tagger() -> DocumentTaggerService:
    return DocumentTaggerService()


async def _fetch_doc_excerpt(doc_id: str) -> tuple[str, str, str] | None:
    """Title, one-sentence summary (if present), and a short excerpt.

    Returns None if the document row is missing.
    """
    async with get_session_factory()() as session:
        doc = (
            await session.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
        ).scalar_one_or_none()
        if doc is None:
            return None
        summary = (
            await session.execute(
                select(SummaryModel.content).where(
                    SummaryModel.document_id == doc_id,
                    SummaryModel.mode == "one_sentence",
                )
            )
        ).scalar_one_or_none() or ""
        # Use the first few chunks as an excerpt to keep the prompt budget
        # tight. Falls back to empty if no chunks have been written yet.
        excerpt_rows = (
            await session.execute(
                select(ChunkModel.text)
                .where(ChunkModel.document_id == doc_id)
                .order_by(ChunkModel.chunk_index)
                .limit(5)
            )
        ).all()
        excerpt = "\n".join((r[0] or "") for r in excerpt_rows)[:2000]
    return doc.title, summary, excerpt


def _fetch_entity_tags(
    doc_id: str,
    min_mentions: int,
    allowed_types: tuple[str, ...] = ("CONCEPT",),
    limit: int | None = None,
) -> list[str]:
    """Pull the top-`limit` entity names (by MENTIONED_IN count, descending)
    with at least `min_mentions` edges among `allowed_types`.

    Score-ranked, so slicing to `limit` keeps the most-mentioned entities --
    the cap acts as a dynamic threshold: a long book keeps its central
    concepts, a short doc keeps all of its (low-count) ones. Returns [] on any
    Kuzu error.
    """
    try:
        svc = _graph_module.get_graph_service()
        pairs = (
            svc.get_entities_with_counts(
                doc_id, min_mentions=min_mentions, allowed_types=allowed_types
            )
            or []
        )
        names = [name for name, _count in pairs]
        return names[:limit] if limit is not None else names
    except Exception as exc:
        logger.warning("entity tag fetch failed (non-fatal): %s", exc)
        return []


def is_acceptable_auto_tag(slug: str, min_length: int) -> bool:
    """Quality gate for auto-suggested tag slugs.

    Rejects: blanks, slugs shorter than `min_length`, all-digit slugs (NER
    artifacts like '9083' from port numbers), and stoplisted generic words.
    Hierarchical slugs are checked against the leaf segment -- 'science/users'
    would be accepted because 'science' anchors it, but bare 'users' fails.
    """
    if not slug:
        return False
    leaf = slug.rsplit("/", 1)[-1]
    if len(slug) < min_length:
        return False
    if leaf.isdigit():
        return False
    if leaf in TAG_STOPLIST:
        return False
    return True


def _normalize_dedupe(
    raw_tags: list[str],
    already_seen: set[str],
    *,
    min_length: int,
    apply_quality_gate: bool,
) -> list[str]:
    """Slugify each candidate, drop blanks, drop duplicates, and -- for the
    entity-source path -- drop tags that fail is_acceptable_auto_tag.

    The LLM-source path passes `apply_quality_gate=False`: the model already
    returns prompt-shaped topics and the stoplist would chew them up. The
    entity path passes True to filter raw NER output.
    """
    out: list[str] = []
    seen = set(already_seen)
    for raw in raw_tags:
        slug = normalize_tag_slug(raw)
        if not slug or slug in seen:
            continue
        if apply_quality_gate and not is_acceptable_auto_tag(slug, min_length):
            continue
        seen.add(slug)
        out.append(slug)
    return out


async def enrich_document_tags(doc_id: str) -> int:
    """Run LLM + entity tag enrichment for a document.

    Each source is normalized + deduped independently and tagged with its own
    `tagger_version` in provenance so cleanup can tell them apart later. The
    LLM source is a small handful of prompt-shaped topics; the entity source
    is score-ranked by MENTIONED_IN.count (no fixed cap, threshold-driven) so
    a long technical book naturally yields more tags than a short article.

    Returns the total number of NEW tags added across both sources. Always
    non-fatal -- any failure is logged and swallowed so the background task
    cannot bubble into the ingestion path.
    """
    try:
        fetched = await _fetch_doc_excerpt(doc_id)
        if fetched is None:
            return 0
        title, summary, excerpt = fetched

        settings = get_settings()

        llm_raw = await get_document_tagger().suggest_tags(title, summary, excerpt)

        # Look up the doc's content_type so the entity query knows whether to
        # include PERSON/PLACE. Cheaper than threading it through _fetch_doc_excerpt.
        async with get_session_factory()() as ct_session:
            content_type = (
                await ct_session.execute(
                    select(DocumentModel.content_type).where(DocumentModel.id == doc_id)
                )
            ).scalar_one_or_none()

        allowed_types = _allowed_entity_types_for(content_type)
        budget = _entity_tag_budget(await _count_chunks(doc_id), settings.AUTO_TAG_ENTITY_CAP_MAX)
        entity_raw: list[str] = (
            _fetch_entity_tags(
                doc_id,
                settings.AUTO_TAG_ENTITY_MIN_MENTIONS,
                allowed_types=allowed_types,
                limit=budget,
            )
            if settings.AUTO_TAG_USE_ENTITIES
            else []
        )

        if not llm_raw and not entity_raw:
            return 0

        async with get_session_factory()() as session:
            doc = (
                await session.execute(select(DocumentModel).where(DocumentModel.id == doc_id))
            ).scalar_one_or_none()
            if doc is None:
                return 0

            existing: list[str] = list(doc.tags or [])
            existing_set: set[str] = {normalize_tag_slug(t) for t in existing}

            min_len = settings.AUTO_TAG_MIN_SLUG_LENGTH
            # LLM tags first so their slugs reserve seats; entity tags then
            # add what's left. Both sources share dedupe state. Only the
            # entity pipeline runs through the quality gate -- the LLM is
            # already steered by its prompt and the stoplist would chew up
            # legitimate prompt-shaped topics.
            new_llm = _normalize_dedupe(
                list(llm_raw),
                existing_set,
                min_length=min_len,
                apply_quality_gate=False,
            )
            existing_set.update(new_llm)
            new_entity = _normalize_dedupe(
                list(entity_raw),
                existing_set,
                min_length=min_len,
                apply_quality_gate=True,
            )

            if not new_llm and not new_entity:
                return 0

            doc.tags = existing + new_llm + new_entity
            await sync_document_tag_index(doc_id, doc.tags, session)

            now = datetime.now(UTC)
            for slug in new_llm:
                session.add(
                    DocumentTagProvenanceModel(
                        document_id=doc_id,
                        tag_full=slug,
                        source="auto",
                        tagger_version=LLM_TAGGER_VERSION,
                        created_at=now,
                    )
                )
            for slug in new_entity:
                session.add(
                    DocumentTagProvenanceModel(
                        document_id=doc_id,
                        tag_full=slug,
                        source="auto",
                        tagger_version=ENTITY_TAGGER_VERSION,
                        created_at=now,
                    )
                )
            await session.commit()

        added = len(new_llm) + len(new_entity)
        logger.info(
            "auto-tag: doc=%s added=%d (llm=%d entity=%d)",
            doc_id,
            added,
            len(new_llm),
            len(new_entity),
        )
        return added
    except Exception as exc:
        logger.warning("enrich_document_tags failed (non-fatal): %s", exc, exc_info=exc)
        return 0


async def prune_auto_entity_tags() -> dict[str, int]:
    """Remove auto-tags that wouldn't be generated by the current pipeline.

    Walks every row in `document_tag_index`. For each:
      - If a `source='manual'` provenance row exists -> SKIP. Manual tags
        belong to the user, even if they would fail the gate.
      - Otherwise apply two gates in order:
          1. `is_acceptable_auto_tag` (stoplist / slug shape / min-length).
          2. For entity-1 rows: re-query the graph with the *current* rules
             (content-type-aware allowed_types + threshold) and drop any
             tag not in the fresh result set. This catches legacy rows from
             before PERSON-was-dropped, before the threshold was bumped,
             etc. -- the prune semantic becomes "wouldn't be generated now".
        Failures are removed via the standard sync path so canonical_tags
        .usage_count, the shadow index, the JSON column, and provenance
        all stay aligned.

    Idempotent: a second call with no rule change returns pruned=0.
    """
    from sqlalchemy import and_, delete  # local: avoid touching the top imports

    settings = get_settings()
    min_len = settings.AUTO_TAG_MIN_SLUG_LENGTH

    pruned_total = 0
    docs_touched: set[str] = set()

    async with get_session_factory()() as session:
        # Pull every (doc, tag) shadow-index row.
        idx_rows = (
            await session.execute(
                select(
                    DocumentTagIndexModel.document_id,
                    DocumentTagIndexModel.tag_full,
                )
            )
        ).all()

        # Build fast lookups of provenance source + version per (doc, tag) so
        # the gate loop can decide protection / re-check semantics without an
        # n-query pattern.
        prov_full_rows = (
            await session.execute(
                select(
                    DocumentTagProvenanceModel.document_id,
                    DocumentTagProvenanceModel.tag_full,
                    DocumentTagProvenanceModel.source,
                    DocumentTagProvenanceModel.tagger_version,
                )
            )
        ).all()
        manual_keys: set[tuple[str, str]] = set()
        llm_keys: set[tuple[str, str]] = set()
        entity_keys: set[tuple[str, str]] = set()
        for d, t, src, ver in prov_full_rows:
            if src == "manual":
                manual_keys.add((d, t))
            elif src == "auto" and ver == LLM_TAGGER_VERSION:
                llm_keys.add((d, t))
            elif src == "auto" and ver == ENTITY_TAGGER_VERSION:
                entity_keys.add((d, t))

        # Re-query the graph for every doc that has at least one non-manual
        # index row -- includes entity-1 rows AND orphan rows (no provenance
        # at all, typically from legacy state pre-provenance-tracking). The
        # orphan rows can't be reliably labeled, but treating them as
        # candidate-auto and running them through gate 2 catches the bulk of
        # legacy noise.
        all_doc_ids: set[str] = {d for d, _t in idx_rows}
        docs_with_entity_rows: set[str] = {
            d for d, _t in idx_rows if (d, _t) not in manual_keys
        } & all_doc_ids
        # Fetch content_type per doc to choose allowed entity types.
        ct_rows = (
            await session.execute(
                select(DocumentModel.id, DocumentModel.content_type).where(
                    DocumentModel.id.in_(docs_with_entity_rows)
                    if docs_with_entity_rows
                    else DocumentModel.id.is_(None)  # empty-set guard
                )
            )
        ).all()
        content_type_by_doc: dict[str, str] = {d: ct or "" for d, ct in ct_rows}

        # Chunk counts per doc so the fresh set uses the SAME budget as
        # enrich_document_tags -- otherwise prune would flag the newly-allowed
        # tags as stale and strip them right back out.
        chunk_count_by_doc: dict[str, int] = {}
        if docs_with_entity_rows:
            chunk_count_by_doc = {
                d: n
                for d, n in (
                    await session.execute(
                        select(ChunkModel.document_id, func.count(ChunkModel.id))
                        .where(ChunkModel.document_id.in_(docs_with_entity_rows))
                        .group_by(ChunkModel.document_id)
                    )
                ).all()
            }

        # Per-doc set of slugs the CURRENT entity query would produce. Any
        # entity-1 index row for a slug NOT in this set is now stale.
        fresh_entity_by_doc: dict[str, set[str]] = {}
        for d in docs_with_entity_rows:
            allowed_types = _allowed_entity_types_for(content_type_by_doc.get(d))
            budget = _entity_tag_budget(
                chunk_count_by_doc.get(d, 0), settings.AUTO_TAG_ENTITY_CAP_MAX
            )
            fresh_names = _fetch_entity_tags(
                d,
                settings.AUTO_TAG_ENTITY_MIN_MENTIONS,
                allowed_types=allowed_types,
                limit=budget,
            )
            fresh_entity_by_doc[d] = {
                normalize_tag_slug(n) for n in fresh_names if normalize_tag_slug(n)
            }

        # Group rejections by doc so we re-sync each doc once.
        by_doc: dict[str, set[str]] = {}
        for doc_id, tag_full in idx_rows:
            if (doc_id, tag_full) in manual_keys:
                continue
            # Gate 1: stoplist / slug shape / min-length.
            if not is_acceptable_auto_tag(tag_full, min_len):
                by_doc.setdefault(doc_id, set()).add(tag_full)
                continue
            # Gate 2: for any non-manual / non-LLM row (entity-1 OR orphan)
            # where the fresh graph query returned something for this doc,
            # drop tags the current rules wouldn't generate. LLM-sourced
            # (doc-1) rows are exempt -- they come from a different pipeline.
            # Defensive: if the graph re-query is empty for this doc (Kuzu
            # unavailable, or no entities indexed), skip gate 2 entirely.
            if (doc_id, tag_full) in llm_keys:
                continue
            fresh = fresh_entity_by_doc.get(doc_id, set())
            if fresh and tag_full not in fresh:
                by_doc.setdefault(doc_id, set()).add(tag_full)

        if not by_doc:
            return {"pruned": 0, "docs_touched": 0}

        for doc_id, to_drop in by_doc.items():
            doc = (
                await session.execute(
                    select(DocumentModel).where(DocumentModel.id == doc_id)
                )
            ).scalar_one_or_none()
            if doc is None:
                # Stale index row for a deleted doc -- clean up the orphan.
                await session.execute(
                    delete(DocumentTagIndexModel).where(
                        and_(
                            DocumentTagIndexModel.document_id == doc_id,
                            DocumentTagIndexModel.tag_full.in_(to_drop),
                        )
                    )
                )
                await session.execute(
                    delete(DocumentTagProvenanceModel).where(
                        and_(
                            DocumentTagProvenanceModel.document_id == doc_id,
                            DocumentTagProvenanceModel.tag_full.in_(to_drop),
                        )
                    )
                )
                pruned_total += len(to_drop)
                docs_touched.add(doc_id)
                continue
            current = list(doc.tags or [])
            kept = [t for t in current if normalize_tag_slug(t) not in to_drop]
            if len(kept) == len(current):
                # Index row exists but the JSON column doesn't reference it
                # (legacy divergence). Clean index + provenance directly.
                await session.execute(
                    delete(DocumentTagIndexModel).where(
                        and_(
                            DocumentTagIndexModel.document_id == doc_id,
                            DocumentTagIndexModel.tag_full.in_(to_drop),
                        )
                    )
                )
                await session.execute(
                    delete(DocumentTagProvenanceModel).where(
                        and_(
                            DocumentTagProvenanceModel.document_id == doc_id,
                            DocumentTagProvenanceModel.tag_full.in_(to_drop),
                        )
                    )
                )
                pruned_total += len(to_drop)
                docs_touched.add(doc_id)
                continue
            doc.tags = kept
            await sync_document_tag_index(doc_id, kept, session)
            pruned_total += len(to_drop)
            docs_touched.add(doc_id)

        await session.commit()

    logger.info(
        "auto-tag prune: removed=%d touched=%d", pruned_total, len(docs_touched)
    )
    return {"pruned": pruned_total, "docs_touched": len(docs_touched)}
