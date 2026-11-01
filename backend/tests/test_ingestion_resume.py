"""An ingestion the process lost resumes after the stages whose rows are stored."""

import uuid

import pytest
from sqlalchemy import select

import app.workflows.ingestion_nodes.finalize as fin
from app.models import ChunkModel, DocumentModel, EnrichmentJobModel, GraphEntityModel, SectionModel
from app.services.document_deletion_service import DocumentDeletionService
from app.workflows import ingestion
from app.workflows.ingestion_nodes import entity_extract
from tests.factories import make_chunk, make_document, make_section
from tests.test_ingestion_error_routing import _stub_graph
from tests.test_pdf_page_number import _make_pdf_sections, _make_state


@pytest.fixture
def launched(monkeypatch):
    """What the startup resume launches, by document id: (function, its arguments). Never run."""
    work: dict[str, tuple[str, dict]] = {}

    class _Jobs:
        def launch(self, doc_id, coro):
            work[doc_id] = (coro.__qualname__, dict(coro.cr_frame.f_locals))
            coro.close()

    monkeypatch.setattr(ingestion, "get_ingestion_jobs", lambda: _Jobs())
    return work


@pytest.fixture
def vectors_dropped(monkeypatch):
    dropped: list[str] = []
    monkeypatch.setattr(
        DocumentDeletionService,
        "delete_lancedb_vectors",
        lambda self, doc_id: dropped.append(doc_id),
    )
    return dropped


async def _document(factory, tmp_path, stage, *, resumes=0, on_disk=True) -> str:
    doc_id = str(uuid.uuid4())
    path = tmp_path / f"{doc_id}.md"
    if on_disk:
        path.write_text("# Title\n\nBody text.\n")
    async with factory() as session:
        session.add(
            make_document(
                id=doc_id, format="md", file_path=str(path), stage=stage, ingest_resumes=resumes
            )
        )
        await session.commit()
    return doc_id


async def _row(factory, doc_id) -> DocumentModel:
    async with factory() as session:
        return await session.get(DocumentModel, doc_id)


@pytest.mark.parametrize(
    "stage, resume_from",
    [
        ("embedding", "embed"),
        ("indexing", "section_summarize"),
        ("summarizing", "section_summarize"),
    ],
)
async def test_a_lost_ingestion_resumes_after_its_stored_stages(
    test_db, launched, vectors_dropped, stage, resume_from
):
    _, factory, tmp_path = test_db
    doc_id = await _document(factory, tmp_path, stage)

    assert await ingestion.resume_interrupted_ingestions() == (1, 0)

    assert launched[doc_id][0] == "resume_ingestion"
    assert launched[doc_id][1]["resume_from"] == resume_from
    doc = await _row(factory, doc_id)
    assert (doc.stage, doc.ingest_resumes) == (stage, 1)
    assert vectors_dropped == []


@pytest.mark.parametrize("stage", ["parsing", "transcribing", "chunking", "entity_extract"])
async def test_a_partial_parse_is_cleared_and_ingested_again(
    test_db, launched, vectors_dropped, stage
):
    _, factory, tmp_path = test_db
    doc_id = await _document(factory, tmp_path, stage)
    async with factory() as session:
        section = make_section(document_id=doc_id)
        session.add(section)
        await session.flush()
        session.add(make_chunk(document_id=doc_id, section_id=section.id))
        await session.commit()

    assert await ingestion.resume_interrupted_ingestions() == (1, 0)

    assert launched[doc_id][0] == "run_ingestion"
    assert vectors_dropped == [doc_id]
    async with factory() as session:
        for model in (SectionModel, ChunkModel):
            rows = await session.execute(select(model).where(model.document_id == doc_id))
            assert rows.first() is None, model.__name__


@pytest.mark.parametrize(
    "stage, resumes, on_disk, message",
    [
        ("downloading", 0, True, "interrupted before it finished"),
        ("embedding", 0, False, "interrupted before it finished"),
        ("embedding", 1, True, "interrupted again after resuming"),
    ],
)
async def test_what_cannot_resume_fails_with_a_reason(
    test_db, launched, vectors_dropped, stage, resumes, on_disk, message
):
    _, factory, tmp_path = test_db
    doc_id = await _document(factory, tmp_path, stage, resumes=resumes, on_disk=on_disk)

    assert await ingestion.resume_interrupted_ingestions() == (0, 1)

    assert launched == {}
    doc = await _row(factory, doc_id)
    assert doc.stage == "error"
    assert message in doc.error_message
    assert doc.ingest_resumes == 0


async def test_finished_documents_are_left_alone(test_db, launched):
    _, factory, tmp_path = test_db
    for stage in ("complete", "error"):
        await _document(factory, tmp_path, stage)

    assert await ingestion.resume_interrupted_ingestions() == (0, 0)
    assert launched == {}


async def test_a_resume_enters_at_embed_with_the_stored_chunks(test_db, monkeypatch):
    _, factory, tmp_path = test_db
    doc_id = await _document(factory, tmp_path, "embedding")
    async with factory() as session:
        for i in range(2):
            session.add(
                make_chunk(
                    id=f"{doc_id}-{i}",
                    document_id=doc_id,
                    text=f"chunk {i}",
                    chunk_index=i,
                    entities_text="[Entities: X]",
                )
            )
        await session.commit()

    seen: list[dict] = []
    graph, visited = _stub_graph(monkeypatch, {})
    monkeypatch.setattr(ingestion, "ingestion_graph", graph)
    real_invoke = graph.ainvoke

    async def _invoke(state, *a, **k):
        seen.append(state)
        return await real_invoke(state, *a, **k)

    monkeypatch.setattr(graph, "ainvoke", _invoke)

    await ingestion.resume_ingestion(doc_id, "embed")

    assert visited == [
        "embed",
        "keyword_index",
        "section_summarize",
        "summarize",
        "enrichment_enqueue",
    ]
    assert seen[0]["chunks"] == [
        {
            "id": f"{doc_id}-{i}",
            "document_id": doc_id,
            "text": f"chunk {i}",
            "index": i,
            "entities_text": "[Entities: X]",
        }
        for i in range(2)
    ]


async def test_reaching_enqueue_twice_queues_each_job_once(test_db, monkeypatch):
    _, factory, tmp_path = test_db
    doc_id = await _document(factory, tmp_path, "indexing", resumes=1)

    async def _noop(*_a, **_k):
        return None

    class _NoWorker:
        async def _dispatch_pending(self):
            return None

    monkeypatch.setattr(fin, "_run_pregenerate", _noop)
    monkeypatch.setattr(fin, "enrich_document_tags", _noop)
    monkeypatch.setattr(fin, "get_enrichment_worker", lambda: _NoWorker())
    state = _make_state(doc_id, _make_pdf_sections(2), format="pdf")
    await fin.enrichment_enqueue_node(state)
    await fin.enrichment_enqueue_node(state)

    async with factory() as session:
        jobs = (
            (
                await session.execute(
                    select(EnrichmentJobModel.job_type).where(
                        EnrichmentJobModel.document_id == doc_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert sorted(jobs) == ["chapter_cards", "concept_link", "image_extract"]
    doc = await _row(factory, doc_id)
    assert (doc.stage, doc.ingest_resumes) == ("complete", 0)


async def test_extracting_entities_twice_does_not_double_their_counts(test_db, monkeypatch):
    _, factory, tmp_path = test_db
    doc_id = await _document(factory, tmp_path, "entity_extract")
    chunk_id = f"{doc_id}-0"
    async with factory() as session:
        session.add(make_chunk(id=chunk_id, document_id=doc_id, text="Ada met Babbage."))
        await session.commit()

    class _TwoNames:
        def extract(self, chunks, is_technical=False):
            return [
                {"name": name, "type": "PERSON", "chunk_id": chunk_id, "document_id": doc_id}
                for name in ("Ada Lovelace", "Charles Babbage")
            ]

    monkeypatch.setattr(entity_extract._ner_module, "get_entity_extractor", lambda: _TwoNames())
    state = {
        "document_id": doc_id,
        "format": "md",
        "form": "prose",
        "chunks": [{"id": chunk_id, "document_id": doc_id, "text": "Ada met Babbage.", "index": 0}],
    }

    async def _frequencies():
        async with factory() as session:
            rows = await session.execute(
                select(GraphEntityModel.name, GraphEntityModel.frequency).where(
                    GraphEntityModel.document_id == doc_id
                )
            )
            return sorted(rows.all())

    await entity_extract.entity_extract_node(state)
    once = await _frequencies()
    await entity_extract.entity_extract_node(state)

    assert len(once) == 2
    assert await _frequencies() == once
