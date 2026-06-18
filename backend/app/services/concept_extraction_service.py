"""concept_extraction_service: derive a small set of higher-level Concepts from the
Entity graph (docs/concepts.md). This is the real concept model -- NOT a 1:1 entity
rename.

A Concept is a synthesized theme over many entities ("Data Systems"), not a NER
mention. The pipeline mirrors a human's "too granular -> group up" reduction:

    L0  entities (GLiNER)                 -- filter to salient, dedupe
    L1  embed each (bge-small name vec)   -- 384-dim, chunk space
    L2  per-document agglomerative cluster -> sub-concepts (level 1, doc-attributed)
    L3  cluster sub-concept centroids globally (n_clusters=target) -> themes (level 0)
    L4  name themes via LLM (top entities -> "Data Systems"); central-entity fallback;
        sub-concepts named by their most-central entity (no LLM -- resource cap)
    L5  lateral theme<->theme edges from shared documents; hierarchy via parent_id

Resource-bounded (constitution 9 / user req): embeddings + clustering run in
asyncio.to_thread (never the event loop); LLM is used ONLY for the ~target theme names,
behind a small semaphore. The heavy run is meant for an offline/idle batch (see
regenerate orchestration), never the live request path.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.embedder import get_embedding_service
from app.services.graph import get_graph_service
from app.services.llm import get_llm_service

logger = logging.getLogger(__name__)

# tunables
_TARGET_THEMES = 25          # ~level-0 stars in the Universe
_MIN_ENTITY_LEN = 3
_SUBCONCEPT_COSINE_THRESHOLD = 0.45   # per-doc agglomerative cut (cosine distance)
_MIN_DOC_ENTITIES = 3        # below this, a doc's entities form one sub-concept
_NAME_CONCURRENCY = 3        # cap concurrent LLM naming calls
_MAX_LABEL_LEN = 60


@dataclass
class ProtoConcept:
    label: str
    level: int                              # 0 = theme, 1 = sub-concept
    entities: list[str]
    document_ids: list[str]
    centroid: list[float]
    salience: float = 0.0
    parent_idx: int | None = None           # index into the themes list (for level-1)
    idx: int = -1                           # filled in after assembly


@dataclass
class ExtractionResult:
    themes: list[ProtoConcept] = field(default_factory=list)       # level 0
    subconcepts: list[ProtoConcept] = field(default_factory=list)  # level 1
    theme_edges: list[tuple[int, int]] = field(default_factory=list)  # (themeIdx, themeIdx)


def _norm(name: str) -> str:
    return name.strip()


async def _gather_entities_per_doc() -> dict[str, list[str]]:
    """document_id -> deduped, filtered entity names (sync graph reads off the loop)."""
    graph = get_graph_service()

    def _read() -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for doc_id in graph.get_all_document_ids():
            names: set[str] = set()
            by_type = graph.get_entities_by_type_for_document(doc_id)
            for type_names in by_type.values():
                for raw_name in type_names:
                    n = _norm(raw_name)
                    if len(n) >= _MIN_ENTITY_LEN:
                        names.add(n)
            if names:
                out[doc_id] = sorted(names)
        return out

    return await asyncio.to_thread(_read)


def _agglomerative(vectors: list[list[float]], n_clusters=None, threshold=None) -> list[int]:
    """Cosine agglomerative labels. Either n_clusters or threshold. Pure/sync."""
    import numpy as np  # noqa: PLC0415
    from sklearn.cluster import AgglomerativeClustering  # noqa: PLC0415

    n = len(vectors)
    if n == 0:
        return []
    if n == 1:
        return [0]
    kwargs: dict = {"metric": "cosine", "linkage": "average"}
    if n_clusters is not None:
        kwargs["n_clusters"] = max(1, min(n_clusters, n))
    else:
        kwargs["n_clusters"] = None
        kwargs["distance_threshold"] = threshold
    labels = AgglomerativeClustering(**kwargs).fit_predict(np.array(vectors, dtype="float32"))
    return [int(x) for x in labels]


def _centroid(vectors: list[list[float]]) -> list[float]:
    import numpy as np  # noqa: PLC0415

    return np.mean(np.array(vectors, dtype="float32"), axis=0).astype("float32").tolist()


def _most_central(entities: list[str], vectors: list[list[float]]) -> str:
    """Medoid label: the entity closest to the cluster centroid."""
    if not entities:
        return "concept"
    if len(entities) == 1:
        return entities[0]
    import numpy as np  # noqa: PLC0415

    arr = np.array(vectors, dtype="float32")
    c = arr.mean(axis=0)
    cn = c / (np.linalg.norm(c) + 1e-9)
    sims = (arr / (np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9)) @ cn
    return entities[int(np.argmax(sims))]


class ConceptExtractionService:
    def __init__(self) -> None:
        self._embedder = get_embedding_service()

    async def extract(self, target_themes: int = _TARGET_THEMES) -> ExtractionResult:
        per_doc = await _gather_entities_per_doc()
        if not per_doc:
            return ExtractionResult()

        # L1: embed every unique entity once (bge-small, 384-dim), off the loop
        vocab = sorted({n for names in per_doc.values() for n in names})
        vectors = await asyncio.to_thread(self._embedder.encode, vocab)
        vec_of = dict(zip(vocab, vectors, strict=True))

        # L2: per-document sub-concepts
        subs: list[ProtoConcept] = []
        for doc_id, names in per_doc.items():
            doc_vecs = [vec_of[n] for n in names]
            if len(names) < _MIN_DOC_ENTITIES:
                groups = {0: list(range(len(names)))}
            else:
                labels = await asyncio.to_thread(
                    _agglomerative, doc_vecs, None, _SUBCONCEPT_COSINE_THRESHOLD
                )
                groups = {}
                for i, lab in enumerate(labels):
                    groups.setdefault(lab, []).append(i)
            for members in groups.values():
                ents = [names[i] for i in members]
                mvecs = [doc_vecs[i] for i in members]
                subs.append(
                    ProtoConcept(
                        label=_most_central(ents, mvecs),
                        level=1,
                        entities=ents,
                        document_ids=[doc_id],
                        centroid=_centroid(mvecs),
                        salience=float(len(ents)),
                    )
                )
        if not subs:
            return ExtractionResult()

        # L3: roll sub-concept centroids up into ~target themes
        sub_centroids = [s.centroid for s in subs]
        theme_labels = await asyncio.to_thread(
            _agglomerative, sub_centroids, target_themes, None
        )
        theme_members: dict[int, list[int]] = {}
        for si, lab in enumerate(theme_labels):
            theme_members.setdefault(lab, []).append(si)

        themes: list[ProtoConcept] = []
        for tlab, sub_idxs in theme_members.items():
            ents: list[str] = []
            docs: set[str] = set()
            for si in sub_idxs:
                ents.extend(subs[si].entities)
                docs.update(subs[si].document_ids)
            tvecs = [subs[si].centroid for si in sub_idxs]
            theme = ProtoConcept(
                label="",  # named below
                level=0,
                entities=sorted(set(ents)),
                document_ids=sorted(docs),
                centroid=_centroid(tvecs),
                # salience: coverage (distinct docs) x breadth (entities)
                salience=float(len(docs)) * float(len(set(ents))),
            )
            theme.idx = len(themes)
            for si in sub_idxs:
                subs[si].parent_idx = theme.idx
            themes.append(theme)

        # prioritize: keep the top-salience themes (already ~target, but cap hard)
        themes.sort(key=lambda t: t.salience, reverse=True)
        themes = themes[:target_themes]
        kept = {t.idx for t in themes}
        # reindex themes 0..n and remap parents
        remap = {t.idx: i for i, t in enumerate(themes)}
        for t in themes:
            t.idx = remap[t.idx]
        subs = [s for s in subs if s.parent_idx in kept]
        for s in subs:
            s.parent_idx = remap[s.parent_idx]

        # L4: name themes via LLM (bounded); sub-concepts already have central-entity labels
        await self._name_themes(themes)

        # L5: lateral theme edges from shared documents
        edges: list[tuple[int, int]] = []
        for i in range(len(themes)):
            for j in range(i + 1, len(themes)):
                if set(themes[i].document_ids) & set(themes[j].document_ids):
                    edges.append((i, j))

        return ExtractionResult(themes=themes, subconcepts=subs, theme_edges=edges)

    async def _name_themes(self, themes: list[ProtoConcept]) -> None:
        sem = asyncio.Semaphore(_NAME_CONCURRENCY)
        llm = get_llm_service()

        async def _name(theme: ProtoConcept) -> None:
            fallback = theme.entities[0] if theme.entities else "Theme"
            top = theme.entities[:12]
            async with sem:
                try:
                    raw = await llm.complete(
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are given key terms from a body of study material. "
                                    "Reply with a 2-4 word higher-level topic name that captures "
                                    "their common theme (e.g. 'Data Systems', 'Transformers'). "
                                    "Name only -- no quotes, punctuation, or explanation."
                                ),
                            },
                            {"role": "user", "content": ", ".join(top)},
                        ],
                        temperature=0.0,
                    )
                    name = raw.strip().split("\n")[0].strip().strip('"')[:_MAX_LABEL_LEN]
                    theme.label = name or fallback
                except Exception:
                    logger.debug("theme naming failed; using fallback", exc_info=True)
                    theme.label = fallback

        await asyncio.gather(*[_name(t) for t in themes])


async def regenerate(session: AsyncSession, target_themes: int = _TARGET_THEMES) -> dict[str, int]:
    """Wipe the concept layer and rebuild it from the entity graph (docs/concepts.md).

    Replaces the naive 1:1 entity promotion. Persists themes (level 0) + sub-concepts
    (level 1, parent_id) across SQLite + Kuzu + LanceDB, draws lateral theme edges, then
    re-applies user overrides by slug. Heavy -- run offline/idle (never the live loop).
    """
    import uuid  # noqa: PLC0415

    from sqlalchemy import delete, update  # noqa: PLC0415

    from app.models import ConceptModel, FlashcardModel  # noqa: PLC0415
    from app.services.concept_service import get_concept_service, slugify  # noqa: PLC0415
    from app.services.vector_store import get_lancedb_service  # noqa: PLC0415

    graph = get_graph_service()
    lance = get_lancedb_service()

    result = await get_concept_extraction_service().extract(target_themes=target_themes)

    # --- wipe the old concept layer (additive data like flashcards is preserved) ---
    await session.execute(
        update(FlashcardModel)
        .where(FlashcardModel.concept_id.is_not(None))
        .values(concept_id=None, mapping_status="unmapped")
    )
    await session.execute(delete(ConceptModel))
    graph.delete_all_concepts()
    await asyncio.to_thread(lance.clear_concept_vectors)

    used_slugs: set[str] = set()

    def _slug(label: str) -> str:
        base = slugify(label)
        slug, n = base, 2
        while slug in used_slugs:
            slug, n = f"{base}-{n}", n + 1
        used_slugs.add(slug)
        return slug

    async def _persist(proto: ProtoConcept, parent_id: str | None) -> str:
        cid = uuid.uuid4().hex
        slug = _slug(proto.label)
        session.add(
            ConceptModel(
                id=cid, slug=slug, label=proto.label, kind="concept",
                origin="document", status="proposed", level=proto.level,
                parent_id=parent_id, salience=proto.salience, evidence_json=[],
            )
        )
        try:
            graph.upsert_concept_node(cid, slug, proto.label, "concept", "proposed")
            for did in proto.document_ids:
                graph.add_extracted_from(cid, did)
        except Exception:
            logger.debug("regenerate: Kuzu write failed for %s", slug, exc_info=True)
        if proto.centroid:
            await asyncio.to_thread(lance.upsert_concept_vector, cid, proto.centroid)
        return cid

    theme_ids: list[str] = [await _persist(t, None) for t in result.themes]
    for sub in result.subconcepts:
        parent = theme_ids[sub.parent_idx] if sub.parent_idx is not None else None
        await _persist(sub, parent)

    for a, b in result.theme_edges:
        try:
            graph.add_concept_relation(theme_ids[a], theme_ids[b], 0.5, "proposed")
        except Exception:
            logger.debug("regenerate: edge %s-%s failed", a, b, exc_info=True)

    await session.commit()

    # re-apply user corrections (rename/reject/merge) by stable slug
    try:
        await get_concept_service().apply_overrides(session)
        await session.commit()
    except Exception:
        logger.warning("regenerate: apply_overrides failed (non-fatal)", exc_info=True)

    stats = {
        "themes": len(result.themes),
        "subconcepts": len(result.subconcepts),
        "theme_edges": len(result.theme_edges),
    }
    logger.info("concept regenerate complete: %s", stats)
    return stats


_extraction_service: ConceptExtractionService | None = None


def get_concept_extraction_service() -> ConceptExtractionService:
    global _extraction_service
    if _extraction_service is None:
        _extraction_service = ConceptExtractionService()
    return _extraction_service
