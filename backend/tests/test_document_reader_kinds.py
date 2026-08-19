"""`read_document_text` must return reading text for every kind ingestion accepts.

The rule it exists to enforce -- read the corpus the way ingestion reads it --
fails silently for container formats. A zip decoded as bytes yields `PK\x03\x04`,
which a golden generator turns into questions about the container and an
integrity check reports as every hint unresolved. It happened once with PDF; the
same hole was open for EPUB and DOCX.
"""

import zipfile
from pathlib import Path

from app.services.universal_parser import read_document_text

_CHAPTER = (
    "<html><body><h1>Chapter One</h1>"
    "<p>The measurement came back at three tenths of a percent.</p>"
    "<p>That reading was the reader, not the corpus.</p>"
    "</body></html>"
)


def _minimal_epub(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr(
            "content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="3.0" unique-identifier="id"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">x</dc:identifier>'
            "<dc:title>Kinds</dc:title><dc:language>en</dc:language></metadata>"
            '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
            "</manifest><spine><itemref idref=\"c1\"/></spine></package>",
        )
        z.writestr("c1.xhtml", _CHAPTER)
    return path


def test_epub_reads_as_prose_not_as_a_zip(tmp_path):
    path = _minimal_epub(tmp_path / "kinds.epub")

    text = read_document_text(path)

    assert not text.startswith("PK"), "epub was decoded as bytes"
    assert "measurement came back" in text
    assert "application/epub+zip" not in text


def test_a_text_file_is_unaffected(tmp_path):
    path = tmp_path / "plain.txt"
    path.write_text("plain reading text\n")

    assert read_document_text(path).strip() == "plain reading text"
