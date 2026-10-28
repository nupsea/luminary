"""A document whose enrichment is still queued at quit is not failed by the next launch.

The startup reconcile (I-10) fails every document not 'complete' or 'error'. Queued
enrichment is safe only because ingestion leaves the document 'complete' before any
job runs; a document left 'enriching' while its jobs wait would be failed at launch.
"""

import uuid

from sqlalchemy import select

import app.workflows.ingestion_nodes.finalize as fin
from app.models import DocumentModel, EnrichmentJobModel
from app.runtime.library_work import _fail_interrupted_ingestions
from tests.test_pdf_page_number import _make_doc, _make_pdf_sections, _make_state


async def test_a_document_with_queued_enrichment_survives_the_startup_reconcile(
    test_db, monkeypatch
):
    _, factory, _ = test_db
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(_make_doc(doc_id))
        await session.commit()

    async def _noop(*_a, **_k):
        return None

    class _NoWorker:
        async def _dispatch_pending(self):
            return None

    # Quit before the worker takes a job: nothing dispatches, nothing follows up.
    monkeypatch.setattr(fin, "_run_pregenerate", _noop)
    monkeypatch.setattr(fin, "enrich_document_tags", _noop)
    monkeypatch.setattr(fin, "get_enrichment_worker", lambda: _NoWorker())
    await fin.enrichment_enqueue_node(_make_state(doc_id, _make_pdf_sections(3), format="pdf"))

    await _fail_interrupted_ingestions()

    async with factory() as session:
        doc = await session.get(DocumentModel, doc_id)
        queued = (
            (
                await session.execute(
                    select(EnrichmentJobModel.job_type).where(
                        EnrichmentJobModel.document_id == doc_id,
                        EnrichmentJobModel.status == "pending",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert sorted(queued) == ["chapter_cards", "concept_link", "image_extract"]
    assert (doc.stage, doc.error_message) == ("complete", None)
