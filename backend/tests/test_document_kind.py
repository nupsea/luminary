"""A document's kind, derived from its format and facets (#223).

The card label, the list filter and the facet counts must agree, so the Python
rule and its SQL form are checked against each other on a real database.
"""

import itertools
import uuid
from typing import get_args

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.main import app
from app.models import DocumentModel
from app.repos.document_kind_repo import DocumentKindRepo, kind_expr
from app.types import DocumentKind, Form, document_kind


@pytest.fixture
async def factory(memory_db, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    factory = async_sessionmaker(memory_db.engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", memory_db.engine)
    monkeypatch.setattr(db_module, "_session_factory", factory)
    return factory


async def _seed(factory, rows: list[tuple[str, str | None, str | None]]) -> list[str]:
    ids = []
    async with factory() as s:
        for fmt, form, domain in rows:
            doc_id = str(uuid.uuid4())
            ids.append(doc_id)
            s.add(
                DocumentModel(
                    id=doc_id,
                    title=f"{fmt}-{form}-{domain}",
                    content_type="book",
                    format=fmt,
                    form=form,
                    domain=domain,
                    file_path="/tmp/x",
                    stage="complete",
                )
            )
        await s.commit()
    return ids


def test_media_is_decided_by_format_before_form():
    assert document_kind("wav", "dialogue", "technical") == "audio"
    assert document_kind("mp4", "dialogue", None) == "video"
    assert document_kind("txt", "dialogue", None) == "conversation"


def test_the_domain_decides_only_the_forms_with_no_kind_of_their_own():
    assert document_kind("pdf", "reference", "technical") == "technical"
    assert document_kind("pdf", "article", "general") == "book"
    assert document_kind("pdf", "paper", "technical") == "paper"
    assert document_kind("txt", "entries", "technical") == "notes"


def test_an_unclassified_document_is_a_book_until_measured():
    assert document_kind("pdf", None, None) == "book"


async def test_sql_and_python_agree_on_every_combination(factory):
    formats = ["pdf", "txt", "wav", "flac", "mp4"]
    forms = [*get_args(Form), None]
    domains = ["technical", "general", None]
    grid = list(itertools.product(formats, forms, domains))
    ids = await _seed(factory, grid)

    async with factory() as s:
        sql = dict((await s.execute(select(DocumentModel.id, kind_expr()))).all())

    python = {doc_id: document_kind(*row) for doc_id, row in zip(ids, grid, strict=True)}
    assert sql == python
    assert set(python.values()) == set(get_args(DocumentKind))


async def test_the_list_filters_and_counts_by_kind(factory):
    technical, notes, _book = await _seed(
        factory,
        [("pdf", "reference", "technical"), ("txt", "entries", None), ("epub", "prose", None)],
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        page = (await c.get("/documents", params={"kind": "technical,notes"})).json()
        facets = (await c.get("/documents/facets")).json()
        detail = (await c.get(f"/documents/{technical}")).json()

    assert {(i["id"], i["kind"]) for i in page["items"]} == {
        (technical, "technical"),
        (notes, "notes"),
    }
    assert facets["kinds"] == {"technical": 1, "notes": 1, "book": 1}
    assert detail["kind"] == "technical"


async def test_search_resolves_kinds_to_documents(factory):
    notes, paper = await _seed(factory, [("txt", "entries", None), ("pdf", "paper", "technical")])
    async with factory() as s:
        repo = DocumentKindRepo(s)
        assert await repo.ids_of_kinds(["notes"]) == [notes]
        assert await repo.titles_and_kinds([notes, paper]) == {
            notes: ("txt-entries-None", "notes"),
            paper: ("pdf-paper-technical", "paper"),
        }
