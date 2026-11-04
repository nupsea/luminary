"""A book stored as a bundle reads as its EPUB twin does (#433): the parser, the book view's
table of contents, chapters, figures and cover, and the figures ingestion extracts."""

from __future__ import annotations

from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.main import app
from app.services.image_extractor import extract_images_epub
from app.services.parser import DocumentParser
from app.services.source_bundle import store_bundle
from tests.factories import make_document
from tests.oreilly_book import (
    BOOK_URL,
    COVER_URL,
    FixtureBookClient,
    write_book_bundle,
    write_book_epub,
)


def _image(fmt: str, size: tuple[int, int], colour: str) -> bytes:
    out = BytesIO()
    Image.new("RGB", size, colour).save(out, fmt)
    return out.getvalue()


class _RealImages(FixtureBookClient):
    """The fixture book with a decodable cover and figure, so both are extracted for real."""

    COVER = _image("JPEG", (400, 600), "navy")
    FIGURE = _image("PNG", (320, 200), "orange")

    def fetch_bytes(self, url: str) -> bytes:
        super().fetch_bytes(url)
        return self.COVER if url == COVER_URL else self.FIGURE


@pytest.fixture
def twins(tmp_path):
    """(EPUB path, stored bundle path) of the same book."""
    epub_path = write_book_epub(tmp_path / "book.epub", _RealImages())
    bundle = tmp_path / "raw" / "book.bundle"
    bundle.parent.mkdir()
    store_bundle(write_book_bundle(tmp_path / "out", _RealImages()), bundle)
    return epub_path, bundle


def test_a_bundle_book_parses_to_its_epub_twins_sections(twins):
    epub_path, bundle = twins
    from_epub = DocumentParser().parse(epub_path, "epub")
    from_bundle = DocumentParser().parse(bundle, "epub")
    assert [(s.heading, s.level, s.text) for s in from_bundle.sections] == [
        (s.heading, s.level, s.text) for s in from_epub.sections
    ]
    assert len(from_bundle.sections) >= 3


async def _book_view(client: AsyncClient, doc_id: str) -> dict:
    toc = (await client.get(f"/documents/{doc_id}/epub/toc")).json()["chapters"]
    chapters = []
    for entry in toc:
        resp = await client.get(f"/documents/{doc_id}/epub/chapter/{entry['chapter_index']}")
        assert resp.status_code == 200, resp.text
        chapter = {k: v for k, v in resp.json().items() if k != "section_ids"}
        # ebooklib's re-render drops the newline before the body's first element.
        chapters.append(chapter | {"html": chapter["html"].strip()})
    cover = await client.get(f"/documents/{doc_id}/cover")
    return {"toc": toc, "chapters": chapters, "cover": (cover.status_code, cover.content)}


async def test_the_book_view_reads_a_bundle_as_it_reads_the_epub(twins, test_db):
    _, factory, _ = test_db
    epub_path, bundle = twins
    async with factory() as session:
        for doc_id, path in (("epub-era", epub_path), ("bundle-era", bundle)):
            session.add(make_document(id=doc_id, title="Fixture Systems", format="epub",
                                      file_path=str(path), source_url=BOOK_URL))  # fmt: skip
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        from_epub = await _book_view(client, "epub-era")
        from_bundle = await _book_view(client, "bundle-era")
        figure = f"images/{next((bundle / 'assets' / 'images').iterdir()).name}"
        assets = [
            await client.get(f"/documents/{d}/asset/{figure}") for d in ("epub-era", "bundle-era")
        ]
        page = await client.get("/documents/bundle-era/asset/../manifest.json")
        (bundle / "assets" / "notes.html").write_text("<script>alert(1)</script>")
        script = await client.get("/documents/bundle-era/asset/notes.html")

    assert from_bundle == from_epub
    assert [c["title"] for c in from_bundle["toc"]] == ["Preface", "1. Storage", "2. Replication"]
    # The figure is inlined from the book itself, not linked to the network.
    assert "data:image/png;base64," in from_bundle["chapters"][1]["html"]
    assert from_bundle["cover"][0] == 200 and from_bundle["cover"][1][:4] == b"RIFF"
    assert [(a.status_code, a.content) for a in assets] == [(200, _RealImages.FIGURE)] * 2
    assert (page.status_code, script.status_code) == (404, 404), "only images are served"


def test_ingestion_extracts_the_same_figures_from_a_bundle(twins, tmp_path):
    epub_path, bundle = twins
    from_epub = extract_images_epub(epub_path, tmp_path / "images-epub", "doc")
    from_bundle = extract_images_epub(bundle, tmp_path / "images-bundle", "doc")

    def _seen(images):
        return [(i.abs_path.name, i.content_hash, i.abs_path.read_bytes()) for i in images]

    assert len(from_bundle) == 1, "the cover is not a figure"
    assert _seen(from_bundle) == _seen(from_epub)


def test_a_bundle_is_sampled_as_ingestion_reads_it(twins):
    """The eval golden generator samples through `read_document_text`: a bundle read as bytes
    would ask questions about its manifest."""
    from app.services.universal_parser import read_document_text

    _, bundle = twins
    text = read_document_text(bundle)
    assert text == DocumentParser().parse(bundle, "epub").raw_text
    assert "append-only sequence of records" in text


async def test_a_bundles_labels_become_the_documents_tags(test_db, tmp_path):
    """The built-in O'Reilly import tags a book `oreilly` and `tech-book`; a bundle-era book
    carries the same tags in the library and its tag index."""
    from sqlalchemy import select

    from app.models import DocumentModel, DocumentTagIndexModel
    from app.workflows.bundle_ingestion import store_document_bundle

    _, factory, _ = test_db
    async with factory() as session:
        session.add(make_document(id="book", title="x", format="epub", file_path="", tags=[]))
        await session.commit()
    await store_document_bundle("book", write_book_bundle(tmp_path / "out", _RealImages()))

    async with factory() as session:
        doc = await session.get(DocumentModel, "book")
        indexed = await session.scalars(
            select(DocumentTagIndexModel.tag_full).where(
                DocumentTagIndexModel.document_id == "book"
            )
        )
        assert doc.tags == ["oreilly", "tech-book"]
        assert sorted(indexed) == ["oreilly", "tech-book"]


def test_an_epub_era_book_keeps_its_section_tree(tmp_path):
    """Books imported before connectors keep their EPUB and read as they did (#467)."""
    from ebooklib import epub

    path = write_book_epub(tmp_path / "book.epub", FixtureBookClient())
    parsed = DocumentParser().parse(path, "epub")

    names = {item.get_name() for item in epub.read_epub(str(path)).get_items()}
    figure = next(name for name in names if name.endswith("-f1.png"))
    assert [(s.heading, s.level, s.text) for s in parsed.sections] == [
        ("Preface", 1, "This preface says who the book is for and what each chapter covers."),
        ("1. Storage", 1, "A log is an append-only sequence of records on disk."),
        (
            "Indexes",
            1,
            "An index is extra structure derived from the primary data.\n\n"
            f"![An LSM tree]({figure})\n*[Figure: An LSM tree]*",
        ),
        (
            "2. Replication",
            1,
            "Replication keeps a copy of the same data on several machines, building on logs.",
        ),
        ("Leaders and Followers", 1, "Every write goes to the leader, which streams it on."),
    ]
    assert parsed.title == "Fixture Systems"
