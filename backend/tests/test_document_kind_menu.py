"""A kind chosen from a card: the facets it writes, and that ingestion keeps them (#223)."""

import itertools
import uuid
from typing import get_args

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import DocumentModel
from app.types import EditableKind, Form, document_kind, facets_for_kind
from app.workflows.ingestion import IngestionState, classify_node
from app.workflows.ingestion_nodes._shared import _persist_classification


@pytest.mark.parametrize(
    ("kind", "form", "domain"),
    list(
        itertools.product(
            get_args(EditableKind), [*get_args(Form), None], ["technical", "general", None]
        )
    ),
)
def test_the_facets_for_a_kind_derive_that_kind(kind, form, domain) -> None:
    facets = facets_for_kind(kind, form)
    assert document_kind("pdf", facets["form"], facets.get("domain", domain)) == kind


def test_a_book_or_technical_document_keeps_a_form_of_its_own() -> None:
    assert facets_for_kind("technical", "article") == {"form": "article", "domain": "technical"}
    assert facets_for_kind("book", "entries") == {"form": "prose", "domain": "general"}


async def _seed(factory, **fields) -> str:
    doc_id = str(uuid.uuid4())
    values = {
        "title": "DDIA",
        "format": "pdf",
        "content_type": "tech_book",
        "file_path": "/tmp/ddia.pdf",
        "stage": "complete",
        "form": "entries",
        "domain": "technical",
        "is_technical": True,
        **fields,
    }
    async with factory() as s:
        s.add(DocumentModel(id=doc_id, **values))
        await s.commit()
    return doc_id


async def _row(factory, doc_id) -> DocumentModel:
    async with factory() as s:
        return await s.get(DocumentModel, doc_id)


async def test_choosing_a_kind_writes_its_facets_as_the_readers(test_db) -> None:
    _engine, factory, _tmp = test_db
    doc_id = await _seed(factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(f"/documents/{doc_id}", json={"kind": "book"})

    assert r.status_code == 200 and r.json()["kind"] == "book"
    row = await _row(factory, doc_id)
    assert (row.form, row.domain, row.is_technical, row.facets_source) == (
        "prose",
        "general",
        False,
        "reader",
    )


async def test_a_recording_s_kind_cannot_be_changed(test_db) -> None:
    _engine, factory, _tmp = test_db
    doc_id = await _seed(factory, format="wav", content_type="audio", form="dialogue")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(f"/documents/{doc_id}", json={"kind": "book"})
    assert r.status_code == 400
    assert (await _row(factory, doc_id)).facets_source is None


async def test_a_measurement_does_not_overwrite_the_reader_s_facets(test_db) -> None:
    _engine, factory, _tmp = test_db
    chosen = await _seed(factory, form="reference", facets_source="reader")
    measured = await _seed(factory, form="reference")

    for doc_id in (chosen, measured):
        await _persist_classification(doc_id, "tech_book", False, "expository", "entries")

    kept = await _row(factory, chosen)
    assert (kept.form, kept.domain, kept.is_technical, kept.register) == (
        "reference",
        "technical",
        True,
        "expository",
    )
    remeasured = await _row(factory, measured)
    assert (remeasured.form, remeasured.domain) == ("entries", "general")


async def test_a_reprocess_chunks_by_the_reader_s_kind(test_db) -> None:
    _engine, factory, _tmp = test_db
    doc_id = await _seed(
        factory, format="txt", form="dialogue", domain=None, facets_source="reader"
    )
    # Text a measurement would call prose; the reader said conversation.
    state: IngestionState = {
        "document_id": doc_id,
        "file_path": "/tmp/notes.txt",
        "format": "txt",
        "parsed_document": {
            "title": "Notes",
            "format": "txt",
            "pages": 1,
            "word_count": 30,
            "sections": [],
            "raw_text": "A plain paragraph of prose about storage engines and indexes. " * 5,
        },
        "content_type": "notes",
        "chunks": None,
        "status": "classifying",
        "error": None,
    }

    result = await classify_node(state)

    assert result["status"] == "chunking"
    assert result["form"] == "dialogue"
    assert (await _row(factory, doc_id)).form == "dialogue"
