"""The source bundle (#432): its one schema, the importer's refusals, and parity with EPUB."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import get_args
from unittest.mock import AsyncMock, patch

import pytest

from app.models import DocumentModel
from app.schemas.source_bundle import BUNDLE_VERSION, BundleManifest
from app.services import source_bundle
from app.services.documents_service import delete_raw_file
from app.services.parser import DocumentParser
from app.services.source_bundle import BundleRefused, read_manifest, store_bundle
from app.workflows.bundle_ingestion import ingest_bundle
from tests.factories import make_document
from tests.oreilly_book import (
    BOOK_ID,
    CHAPTERS,
    FixtureBookClient,
    process_chapter_html,
    write_book_epub,
)
from tools.dump_bundle_schema import SCHEMA_PATH, render


def test_the_published_schema_is_the_model():
    assert SCHEMA_PATH.read_text(encoding="utf-8") == render(), (
        "BundleManifest changed: run `uv run python -m tools.dump_bundle_schema` from backend/"
    )
    assert get_args(BundleManifest.model_fields["bundle_version"].annotation) == (BUNDLE_VERSION,)


def _manifest(**overrides) -> dict:
    manifest = {
        "bundle_version": 1,
        "connector": {"name": "fixture", "version": "0.1.0"},
        "title": "Fixture Systems",
        "authors": ["Ada Author"],
        "source_url": "https://learning.oreilly.com/library/view/fixture-systems/9781098100001/",
        "locator": BOOK_ID,
        "media": {"kind": "text"},
        "terms": {
            "statement": "Members may download titles for personal offline reading.",
            "url": "https://www.oreilly.com/terms/",
        },
        "tags": ["oreilly"],
        "sections": [],
    }
    return manifest | overrides


def _write_bundle(root: Path, manifest: dict, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _fixture_book_bundle(root: Path) -> Path:
    """The fixture book as a connector would hand it over: one HTML file a chapter."""
    client = FixtureBookClient()
    sections, files = [], {}
    for ch in CHAPTERS:
        url = ch["content_url"]
        cleaned, _ = process_chapter_html(client.fetch_chapter_html(url), BOOK_ID, url)
        name = ch["filename"].removesuffix(".html")
        files[f"sections/{name}.html"] = cleaned.encode()
        sections.append(
            {"id": name, "heading": ch["title"], "level": 1, "file": f"sections/{name}.html"}
        )
    return _write_bundle(root, _manifest(sections=sections), files)


def _text_bundle(root: Path, text: bytes = b"<h1>One</h1><p>" + b"word " * 20 + b"</p>") -> Path:
    section = {"id": "one", "heading": "One", "level": 1, "file": "sections/one.html"}
    return _write_bundle(root, _manifest(sections=[section]), {"sections/one.html": text})


def test_a_bundle_parses_to_the_sections_its_epub_twin_does(tmp_path: Path):
    epub_path = write_book_epub(tmp_path / "book.epub", FixtureBookClient())
    from_epub = DocumentParser().parse(epub_path, "epub")
    stored = tmp_path / "raw" / "doc.bundle"
    store_bundle(_fixture_book_bundle(tmp_path / "out"), stored)
    # The document keeps the format a reader shows it in; storage decides how it is read.
    from_bundle = DocumentParser().parse(stored, "epub")

    def shape(doc):
        return [(s.heading, s.level, s.text) for s in doc.sections]

    assert shape(from_bundle) == shape(from_epub)
    assert len(from_epub.sections) == 5
    assert (from_bundle.title, from_bundle.raw_text, from_bundle.word_count) == (
        from_epub.title,
        from_epub.raw_text,
        from_epub.word_count,
    )


async def test_a_bundle_chunks_as_its_epub_twin_does(test_db, tmp_path: Path):
    from app.workflows.ingestion_nodes.chunk import _chunk_tech_book
    from app.workflows.ingestion_nodes.parse import parse_node

    _, factory, _ = test_db
    epub_path = write_book_epub(tmp_path / "book.epub", FixtureBookClient())
    stored = tmp_path / "raw" / "twin.bundle"
    store_bundle(_fixture_book_bundle(tmp_path / "out"), stored)

    chunked = []
    for doc_id, path in (("epub-twin", epub_path), ("bundle-twin", stored)):
        async with factory() as session:
            session.add(make_document(id=doc_id, title="Fixture Systems", format="epub"))
            await session.commit()
        state = {"document_id": doc_id, "file_path": str(path), "format": "epub"}
        parsed = await parse_node(state)
        state = {**parsed, "form": "reference", "domain": "technical", "chunks": None}
        with patch("app.services.vector_store.get_lancedb_service"):
            result = await _chunk_tech_book(state, parsed["parsed_document"], doc_id)
        chunked.append([c["text"] for c in result["chunks"]])

    assert chunked[0] == chunked[1]
    assert len(chunked[0]) >= 5


def test_a_stored_bundle_is_a_checked_copy(tmp_path: Path):
    source = _fixture_book_bundle(tmp_path / "out")
    (source / "assets").mkdir()
    (source / "assets" / "cover.jpg").write_bytes(b"\xff\xd8cover")
    dest = tmp_path / "raw" / "doc.bundle"
    dest.parent.mkdir()

    manifest = store_bundle(source, dest)

    assert manifest.title == "Fixture Systems"
    assert [s.id for s in manifest.sections] == ["preface01", "ch01", "ch02"]
    assert (dest / "assets" / "cover.jpg").read_bytes() == b"\xff\xd8cover"
    assert sorted(p.name for p in dest.parent.iterdir()) == ["doc.bundle"]


def _refused(source: Path, tmp_path: Path, media: frozenset[str] = frozenset({"text"})) -> str:
    dest = tmp_path / "raw" / "doc.bundle"
    dest.parent.mkdir(exist_ok=True)
    with pytest.raises(BundleRefused) as refused:
        store_bundle(source, dest, media=media)
    # A refused bundle leaves nothing behind, partial copy included.
    assert list(dest.parent.iterdir()) == []
    return refused.value.detail


def test_a_path_that_leaves_the_bundle_is_refused(tmp_path: Path):
    (tmp_path / "secret.html").write_text("<p>" + "s" * 60 + "</p>")
    section = {"id": "x", "heading": "X", "level": 1, "file": "sections/../../secret.html"}
    source = _write_bundle(tmp_path / "out", _manifest(sections=[section]), {})
    assert _refused(source, tmp_path) == "sections/../../secret.html leaves the bundle"


def test_an_absolute_path_is_refused(tmp_path: Path):
    section = {"id": "x", "heading": "X", "level": 1, "file": "/etc/passwd"}
    source = _write_bundle(tmp_path / "out", _manifest(sections=[section]), {})
    assert _refused(source, tmp_path).startswith(
        "manifest.json: sections.0.file: String should match pattern"
    )


def _symlink(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link)
    except OSError as exc:  # Windows without the privilege to create one
        pytest.skip(f"cannot create a symbolic link here: {exc}")


@pytest.mark.parametrize("what", ["file", "directory"])
def test_a_symbolic_link_is_refused(tmp_path: Path, what: str):
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "key.html").write_text("<p>" + "s" * 60 + "</p>")
    source = _text_bundle(tmp_path / "out")
    if what == "file":
        (source / "sections" / "one.html").unlink()
        _symlink(source / "sections" / "one.html", secret / "key.html")
        expected = "sections/one.html is a symbolic link"
    else:
        _symlink(source / "assets", secret)
        expected = "assets is a symbolic link"
    assert _refused(source, tmp_path) == expected


@pytest.mark.skipif(sys.platform == "win32", reason="no named pipes in the filesystem")
def test_a_special_file_is_refused(tmp_path: Path):
    source = _text_bundle(tmp_path / "out")
    (source / "assets").mkdir()
    os.mkfifo(source / "assets" / "pipe")
    assert _refused(source, tmp_path) == "assets/pipe is not a regular file"


def test_an_entry_outside_the_layout_is_refused(tmp_path: Path):
    source = _text_bundle(tmp_path / "out")
    (source / "run.sh").write_text("echo hi")
    assert _refused(source, tmp_path) == "run.sh is not part of a bundle"


def test_an_oversize_section_file_is_refused(tmp_path: Path):
    big = b"<p>" + b"x" * source_bundle.MAX_SECTION_FILE_BYTES + b"</p>"
    source = _text_bundle(tmp_path / "out", big)
    assert _refused(source, tmp_path) == "sections/one.html is larger than 4 MiB"


def test_an_oversize_asset_is_refused(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(source_bundle, "MAX_BUNDLE_BYTES", 2 * 1024**2)
    source = _text_bundle(tmp_path / "out")
    (source / "assets").mkdir()
    (source / "assets" / "talk.flac").write_bytes(b"\x00" * (3 * 1024**2))
    assert _refused(source, tmp_path) == "the bundle is larger than 2 MiB"


def _three_section_bundle(root: Path) -> Path:
    files, sections = {}, []
    for i in range(3):
        files[f"sections/{i}.html"] = b"<p>" + b"w " * 30 + b"</p>"
        sections.append(
            {"id": f"s{i}", "heading": f"S{i}", "level": 1, "file": f"sections/{i}.html"}
        )
    return _write_bundle(root, _manifest(sections=sections), files)


def test_too_many_sections_are_refused(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(source_bundle, "MAX_SECTIONS", 2)
    source = _three_section_bundle(tmp_path / "out")
    assert _refused(source, tmp_path) == "the bundle has more than 2 sections"


def test_too_many_files_are_refused(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(source_bundle, "MAX_FILES", 3)
    source = _three_section_bundle(tmp_path / "out")
    assert _refused(source, tmp_path) == "the bundle holds more than 3 files"


def test_too_much_section_text_is_refused(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(source_bundle, "MAX_SECTION_TEXT_BYTES", 2 * 1024**2)
    files, sections = {}, []
    for i in range(3):
        files[f"sections/{i}.html"] = b"<p>" + b"w" * 1024**2 + b"</p>"
        sections.append(
            {"id": f"s{i}", "heading": f"S{i}", "level": 1, "file": f"sections/{i}.html"}
        )
    source = _write_bundle(tmp_path / "out", _manifest(sections=sections), files)
    assert _refused(source, tmp_path) == "the bundle's sections are larger than 2 MiB"


def test_a_missing_bundle_is_refused(tmp_path: Path):
    assert _refused(tmp_path / "never-written", tmp_path) == "never-written is not a directory"


@pytest.mark.parametrize("version", [2, 0, "1", True, None])
def test_an_unknown_bundle_version_is_refused(tmp_path: Path, version):
    source = _text_bundle(tmp_path / "out")
    manifest = json.loads((source / "manifest.json").read_text())
    (source / "manifest.json").write_text(json.dumps({**manifest, "bundle_version": version}))
    assert _refused(source, tmp_path) == (
        f"bundle_version {version!r} is not supported; this Luminary reads 1"
    )


def test_a_missing_section_file_is_refused(tmp_path: Path):
    source = _text_bundle(tmp_path / "out")
    (source / "sections" / "one.html").unlink()
    assert _refused(source, tmp_path) == (
        "sections/one.html is named in manifest.json but the bundle does not contain it"
    )


def test_a_missing_cover_is_refused(tmp_path: Path):
    source = _text_bundle(tmp_path / "out")
    manifest = json.loads((source / "manifest.json").read_text())
    (source / "manifest.json").write_text(json.dumps({**manifest, "cover": "assets/cover.jpg"}))
    assert _refused(source, tmp_path) == (
        "assets/cover.jpg is named in manifest.json but the bundle does not contain it"
    )


def test_text_that_is_not_utf8_is_refused(tmp_path: Path):
    source = _text_bundle(tmp_path / "out", "<p>Abbé Faria</p>".encode("cp1252"))
    assert _refused(source, tmp_path) == "sections/one.html is not UTF-8 (byte 6)"


def test_a_utf8_byte_order_mark_is_not_text(tmp_path: Path):
    """I-68: valid UTF-8 is UTF-8, and a BOM does not reach the text."""
    body = "<h1>Abbé</h1><p>" + "Faria " * 12 + "</p>"
    stored = tmp_path / "raw" / "doc.bundle"
    store_bundle(_text_bundle(tmp_path / "out", b"\xef\xbb\xbf" + body.encode()), stored)
    (section,) = DocumentParser().parse(stored, "epub").sections
    assert section.heading == "Abbé"
    assert section.text.startswith("Faria")


def test_a_manifest_the_model_rejects_names_the_field(tmp_path: Path):
    source = _text_bundle(tmp_path / "out")
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["sections"][0]["level"] = 9
    manifest["terms"] = {}
    (source / "manifest.json").write_text(json.dumps(manifest))
    assert _refused(source, tmp_path) == (
        "manifest.json: terms.statement: Field required (and 2 more)"
    )


def test_a_duplicate_section_id_is_refused(tmp_path: Path):
    source = _text_bundle(tmp_path / "out")
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["sections"] *= 2
    (source / "manifest.json").write_text(json.dumps(manifest))
    assert _refused(source, tmp_path) == "section id 'one' appears twice"


def test_an_audio_bundle_is_not_ingested_yet(tmp_path: Path):
    source = _write_bundle(
        tmp_path / "out",
        _manifest(media={"kind": "audio", "audio": "assets/talk.flac"}),
        {"assets/talk.flac": b"fLaC"},
    )
    assert _refused(source, tmp_path) == "audio bundles cannot be ingested yet"


@pytest.mark.parametrize(
    ("audio", "captions", "message"),
    [
        ("assets/talk.ogg", None, "assets/talk.ogg is not one of mp3, m4a, wav, flac"),
        ("assets/talk.flac", "assets/talk.srt", "assets/talk.srt is not a WebVTT caption track"),
    ],
)
def test_audio_the_transcriber_and_player_cannot_take_is_refused(
    tmp_path, audio, captions, message
):
    media = {"kind": "youtube", "url": "https://www.youtube.com/watch?v=t1", "audio": audio}
    files = {audio: b"fLaC"}
    if captions:
        media["captions"] = captions
        files[captions] = b"1\n00:00:01,000 --> 00:00:02,000\nhi\n"
    source = _write_bundle(tmp_path / "out", _manifest(media=media), files)
    assert _refused(source, tmp_path, frozenset({"youtube"})) == message


def test_markdown_sections_keep_their_declared_heading(tmp_path: Path):
    body = b"Replication keeps a copy of the same data on several machines."
    section = {"id": "r", "heading": "Replication", "level": 2, "file": "sections/r.md"}
    source = _write_bundle(tmp_path / "out", _manifest(sections=[section]), {"sections/r.md": body})
    stored = tmp_path / "raw" / "doc.bundle"
    store_bundle(source, stored)
    (parsed,) = DocumentParser().parse(stored, "md").sections
    assert (parsed.heading, parsed.text) == ("Replication", body.decode())


def test_a_bundle_without_a_section_of_text_fails_to_parse(tmp_path: Path):
    stored = tmp_path / "raw" / "doc.bundle"
    store_bundle(_text_bundle(tmp_path / "out", b"<h1>Contents</h1>"), stored)
    with pytest.raises(BundleRefused, match="no section of the bundle has 50 characters"):
        DocumentParser().parse(stored, "epub")


def test_deleting_a_document_removes_its_stored_bundle_only(test_db):
    _, _, tmp_path = test_db
    raw = tmp_path / "raw"
    raw.mkdir()
    store_bundle(_text_bundle(tmp_path / "out"), raw / "doc-a.bundle")
    store_bundle(_text_bundle(tmp_path / "out2"), raw / "doc-b.bundle")
    (raw / "doc-a.epub").write_bytes(b"PK")

    delete_raw_file("doc-a")

    assert sorted(p.name for p in raw.iterdir()) == ["doc-b.bundle"]


async def test_ingest_bundle_stores_it_as_the_documents_source(test_db, monkeypatch):
    _, factory, tmp_path = test_db
    async with factory() as session:
        session.add(make_document(id="doc-1", title="Fixture Systems", format="epub"))
        await session.commit()
    ingested = AsyncMock()
    monkeypatch.setattr("app.workflows.bundle_ingestion.run_ingestion", ingested)

    await ingest_bundle("doc-1", _fixture_book_bundle(tmp_path / "out"))

    stored = tmp_path / "raw" / "doc-1.bundle"
    ingested.assert_awaited_once_with("doc-1", str(stored), "epub")
    assert read_manifest(stored).locator == BOOK_ID
    async with factory() as session:
        assert (await session.get(DocumentModel, "doc-1")).file_path == str(stored)


async def test_ingest_bundle_refuses_before_storing_anything(test_db, monkeypatch):
    _, factory, tmp_path = test_db
    async with factory() as session:
        session.add(make_document(id="doc-1", title="Talk", format="epub", file_path="/x"))
        await session.commit()
    ingested = AsyncMock()
    monkeypatch.setattr("app.workflows.bundle_ingestion.run_ingestion", ingested)
    source = _text_bundle(tmp_path / "out")
    (source / "sections" / "one.html").unlink()

    with pytest.raises(BundleRefused):
        await ingest_bundle("doc-1", source)

    ingested.assert_not_called()
    assert list((tmp_path / "raw").iterdir()) == []
    async with factory() as session:
        assert (await session.get(DocumentModel, "doc-1")).file_path == "/x"
