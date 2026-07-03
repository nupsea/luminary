"""retrieve_with_images must scope image search to the documents that actually
produced the answer's chunks — never the whole corpus. Regression for a
library-wide ("All documents") query attaching an unrelated document's image
(a tech diagram surfaced on an Odyssey answer)."""

import pytest

from app.services.retriever import HybridRetriever
from app.types import ScoredChunk


def _chunk(doc_id: str) -> ScoredChunk:
    return ScoredChunk(
        chunk_id=f"{doc_id}-c1",
        document_id=doc_id,
        text="Minerva visits Telemachus in Ithaca.",
        section_heading="Book I",
        page=1,
        score=0.9,
        source="vector",
    )


@pytest.mark.anyio
async def test_image_search_scoped_to_answer_documents(monkeypatch):
    r = HybridRetriever()

    async def fake_retrieve(query, document_ids, k):
        # A corpus-wide query (document_ids=None) whose chunks all come from odyssey.
        return [_chunk("odyssey"), _chunk("odyssey")]

    seen_scopes: dict[str, object] = {}

    def fake_vec(query_vector, document_ids, k=5, threshold=0.5):
        seen_scopes["vec"] = document_ids
        return ["img-from-odyssey"]

    async def fake_fts(query, document_ids, k=5):
        seen_scopes["fts"] = document_ids
        return []

    monkeypatch.setattr(r, "retrieve", fake_retrieve)
    monkeypatch.setattr(r, "_image_vector_search", fake_vec)
    monkeypatch.setattr(r, "_image_keyword_search", fake_fts)
    monkeypatch.setattr(
        "app.services.retriever._embedder_module.get_embedding_service",
        lambda: type("E", (), {"encode": staticmethod(lambda xs: [[0.0]])})(),
    )

    chunks, image_ids = await r.retrieve_with_images("Who is Minerva?", None, k=6)

    # Even though the caller passed document_ids=None, both image searches must
    # be scoped to the answer's documents ({"odyssey"}), never the whole corpus.
    assert seen_scopes["vec"] == ["odyssey"]
    assert seen_scopes["fts"] == ["odyssey"]
    assert image_ids == ["img-from-odyssey"]
    assert len(chunks) == 2


@pytest.mark.anyio
async def test_no_images_when_no_chunks(monkeypatch):
    """No retrieved chunks → no document scope → attach no images (never fall
    back to a corpus-wide search)."""
    r = HybridRetriever()

    async def fake_retrieve(query, document_ids, k):
        return []

    called = {"vec": False, "fts": False}

    def fake_vec(*a, **k):
        called["vec"] = True
        return ["should-not-appear"]

    async def fake_fts(*a, **k):
        called["fts"] = True
        return ["should-not-appear"]

    monkeypatch.setattr(r, "retrieve", fake_retrieve)
    monkeypatch.setattr(r, "_image_vector_search", fake_vec)
    monkeypatch.setattr(r, "_image_keyword_search", fake_fts)

    chunks, image_ids = await r.retrieve_with_images("anything", None, k=6)

    assert image_ids == []
    assert called == {"vec": False, "fts": False}
