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
from tests.factories import make_document


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
        "file_path": "/tmp/ddia.pdf",
        "form": "entries",
        "domain": "technical",
        **fields,
    }
    async with factory() as s:
        s.add(make_document(id=doc_id, **values))
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
    assert (row.form, row.domain, row.facets_source) == ("prose", "general", "reader")


async def test_a_recording_s_kind_cannot_be_changed(test_db) -> None:
    _engine, factory, _tmp = test_db
    doc_id = await _seed(factory, format="wav", form="dialogue")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.patch(f"/documents/{doc_id}", json={"kind": "book"})
    assert r.status_code == 400
    assert (await _row(factory, doc_id)).facets_source is None


async def test_a_measurement_does_not_overwrite_the_reader_s_facets(test_db) -> None:
    _engine, factory, _tmp = test_db
    chosen = await _seed(factory, form="reference", facets_source="reader")
    measured = await _seed(factory, form="reference")

    for doc_id in (chosen, measured):
        await _persist_classification(doc_id, "entries", "general", "expository")

    kept = await _row(factory, chosen)
    assert (kept.form, kept.domain, kept.register) == ("reference", "technical", "expository")
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
        "form": "entries",
        "chunks": None,
        "status": "classifying",
        "error": None,
    }

    result = await classify_node(state)

    assert result["status"] == "chunking"
    assert result["form"] == "dialogue"
    assert (await _row(factory, doc_id)).form == "dialogue"


def _record_ingestion(monkeypatch) -> list[str | None]:
    """The kind each upload hands the job; the job itself never runs."""
    import app.routers.documents as documents_module

    calls: list[str | None] = []

    async def _noop() -> None:
        return None

    def _run(document_id, file_path, format, parsed_document=None, kind=None):
        calls.append(kind)
        return _noop()

    monkeypatch.setattr(documents_module, "run_ingestion", _run)
    monkeypatch.setattr(
        documents_module.get_ingestion_jobs(), "launch", lambda doc_id, coro: coro.close()
    )
    return calls


async def _upload(name: str, body: bytes, **data):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.post("/documents/ingest", files={"file": (name, body)}, data=data)


async def test_an_upload_s_kind_reaches_ingestion(test_db, monkeypatch):
    _engine, factory, _tmp = test_db
    calls = _record_ingestion(monkeypatch)
    r = await _upload("talk-notes.txt", b"Two people discuss storage engines.", kind="paper")
    assert r.status_code == 200, r.text
    assert calls == ["paper"]
    # Laid over the measured shape in classify_node, not guessed at upload.
    assert (await _row(factory, r.json()["document_id"])).form is None


async def test_a_recording_cannot_be_uploaded_as_another_kind(test_db, monkeypatch):
    calls = _record_ingestion(monkeypatch)
    r = await _upload("talk.mp3", b"\x00\x01", kind="book")
    assert r.status_code == 400
    assert calls == []


async def test_an_upload_s_kind_is_laid_over_the_measured_shape(test_db) -> None:
    _engine, factory, _tmp = test_db
    doc_id = await _seed(factory, format="txt", form=None, domain=None)
    # Dated entries measure as `entries` (notes); the reader said technical.
    journal = "".join(
        f"2026-03-{d:02d}\nRead about storage engines and write-ahead logs today.\n\n"
        for d in range(1, 29)
    )
    state: IngestionState = {
        "document_id": doc_id,
        "file_path": "/tmp/journal.txt",
        "format": "txt",
        "parsed_document": {
            "title": "Journal",
            "format": "txt",
            "pages": 1,
            "word_count": len(journal.split()),
            "sections": [],
            "raw_text": journal,
        },
        "kind": "technical",
        "chunks": None,
        "status": "classifying",
        "error": None,
    }

    result = await classify_node(state)

    row = await _row(factory, doc_id)
    assert document_kind(row.format, row.form, row.domain) == "technical"
    assert (row.form, row.domain, row.facets_source) == ("reference", "technical", "reader")
    assert result["form"] == "reference"
    assert result["domain"] == "technical"
