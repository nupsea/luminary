"""embed_entities node -- vectorize concept seeds by CONTEXT (docs/concept-model-design.md §3).

An entity's vector = the centroid of the chunk vectors where it actually occurs. This
captures *how the term is used*, not just its surface string -- so "bloom filter"
(indexing/storage contexts) separates from Spark "dataframe" (processing contexts), which
bare-name embeddings conflate. Entities with no locatable chunk fall back to a name
embedding. Also stores the entity->chunk index (lineage needs it later).

Swappable; the `method` mix (context vs name fallback) is logged per run.
"""

from __future__ import annotations

import asyncio

import numpy as np
from sqlalchemy import select

from app.database import get_session_factory
from app.models import ChunkModel
from app.services.embedder import get_embedding_service
from app.services.vector_store import get_lancedb_service
from app.workflows.concept_nodes._shared import ConceptPipelineState, record

_MAX_CHUNKS_PER_ENTITY = 60  # cap context chunks per entity (bounds the centroid)


def _match_entities_to_chunks(
    entities: list[dict], chunk_rows: list[tuple[str, str, str]]
) -> dict[str, list[str]]:
    """name -> chunk_ids it occurs in, scoped to its own docs. Pure CPU.

    Matches against each chunk's `entities_text` (the short canonical entity tail), NOT the
    full chunk text -- 10-50x cheaper, so this never blows up on a large library.
    """
    by_doc: dict[str, list[tuple[str, str]]] = {}
    for cid, did, etext in chunk_rows:
        by_doc.setdefault(did, []).append((cid, etext))
    out: dict[str, list[str]] = {}
    for e in entities:
        nl = e["name"].lower()
        hits: list[str] = []
        for did in e.get("document_ids", []):
            for cid, etext in by_doc.get(did, []):
                if nl in etext:
                    hits.append(cid)
                    if len(hits) >= _MAX_CHUNKS_PER_ENTITY:
                        break
            if len(hits) >= _MAX_CHUNKS_PER_ENTITY:
                break
        if hits:
            out[e["name"]] = list(dict.fromkeys(hits))
    return out


async def embed_entities(state: ConceptPipelineState) -> ConceptPipelineState:
    entities = state.get("entities", [])
    if not entities:
        state["vectors"] = {}
        record(state, "embed_entities", {"embedded": 0, "method": "none"})
        return state

    doc_ids = sorted({d for e in entities for d in e.get("document_ids", [])})

    # 1. load chunk texts for the relevant docs (on this loop), then match off the loop.
    # Degrades to a pure name-embedding pass if chunks/DB are unavailable.
    chunk_rows: list[tuple[str, str, str]] = []
    if doc_ids:
        try:
            async with get_session_factory()() as session:
                rows = (
                    await session.execute(
                        select(
                            ChunkModel.id, ChunkModel.document_id, ChunkModel.entities_text
                        ).where(ChunkModel.document_id.in_(doc_ids))
                    )
                ).all()
            # match against the short canonical entity tail; fall back to text only if a
            # chunk has no entities_text (older rows).
            chunk_rows = [(cid, did, (etext or "").lower()) for cid, did, etext in rows]
        except Exception:
            chunk_rows = []
    name_to_chunks = await asyncio.to_thread(_match_entities_to_chunks, entities, chunk_rows)
    state["entity_chunks"] = name_to_chunks

    # 2. bulk-load every needed chunk vector once
    all_chunk_ids = sorted({c for cids in name_to_chunks.values() for c in cids})
    chunk_vecs = await asyncio.to_thread(get_lancedb_service().fetch_chunk_vectors, all_chunk_ids)

    # 3. context-centroid per entity; name-embedding fallback when no chunk vectors
    vectors: dict[str, list[float]] = {}
    fallback: list[str] = []
    for e in entities:
        name = e["name"]
        vs = [chunk_vecs[c] for c in name_to_chunks.get(name, []) if c in chunk_vecs]
        if vs:
            mean = np.mean(np.array(vs, dtype="float32"), axis=0)
            vectors[name] = mean.astype("float32").tolist()
        else:
            fallback.append(name)
    if fallback:
        fb_vecs = await asyncio.to_thread(get_embedding_service().encode, fallback)
        vectors.update(dict(zip(fallback, fb_vecs, strict=True)))

    state["vectors"] = vectors
    record(
        state,
        "embed_entities",
        {
            "embedded": len(vectors),
            "method": "context_centroid",
            "by_context": len(vectors) - len(fallback),
            "by_name_fallback": len(fallback),
            "chunk_vectors_loaded": len(chunk_vecs),
        },
    )
    return state
