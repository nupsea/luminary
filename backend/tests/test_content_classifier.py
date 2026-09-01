"""Content-type classification, measured against a labelled corpus.

The rules this replaces scored 4 of 13 here. That is the point of the file: a
classifier is not testable by asserting the branches it happens to have, because
every wrong version of it also passes those. It is testable against documents
somebody labelled.

`DATA/` is not in a fresh checkout, so the corpus test skips rather than fails
when the files are absent. The unit tests below do not depend on it and always
run -- they cover the specific defects that produced the 4/13, so a regression
is caught even where the corpus is unavailable.
"""

import json
from pathlib import Path

import pytest

from app.services.content_classifier import (
    _speaker_stats,
    classify_content,
    count_numbered_sections,
    sample_body,
    strip_boilerplate,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LABELS = Path(__file__).parent / "fixtures" / "content_type_labels.json"

_FAMILIES = {
    "book": "prose",
    "paper": "prose",
    "tech_book": "technical",
    "tech_article": "technical",
    "conversation": "conversation",
    "notes": "notes",
}


def _cases() -> list[dict]:
    return json.loads(_LABELS.read_text())["cases"]


def _classify_path(path: Path) -> str:
    from app.services.parser import DocumentParser  # noqa: PLC0415

    fmt = path.suffix.lstrip(".")
    parsed = DocumentParser().parse(path, fmt)
    return classify_content(
        parsed.raw_text,
        [s.__dict__ for s in parsed.sections],
        parsed.word_count,
        fmt,
        path.name,
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda c: Path(c["path"]).name)
def test_labelled_corpus_family(case: dict) -> None:
    """The coarse call must be right. This is the one that changes behaviour.

    A technical document chunked and prompted as a novel is a real failure;
    tech_book vs tech_article only changes chunk sizing, so family is asserted
    separately from the exact type and is the stricter gate of the two.
    """
    path = _REPO_ROOT / case["path"]
    if not path.exists():
        pytest.skip(f"{case['path']} not in this checkout")
    got = _classify_path(path)
    assert _FAMILIES[got] == case["family"], (
        f"{case['path']}: got {got} (family {_FAMILIES[got]}), "
        f"expected family {case['family']} -- {case['why']}"
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda c: Path(c["path"]).name)
def test_labelled_corpus_exact(case: dict) -> None:
    path = _REPO_ROOT / case["path"]
    if not path.exists():
        pytest.skip(f"{case['path']} not in this checkout")
    got = _classify_path(path)
    assert got in case["expected"], (
        f"{case['path']}: got {got}, expected one of {case['expected']} -- {case['why']}"
    )


def test_gutenberg_licence_is_not_the_document() -> None:
    """The original defect: every literary text was classified on its licence."""
    body = "The Time Traveller sat by the fire and spoke of the fourth dimension. " * 40
    raw = (
        "The Project Gutenberg eBook of Something\n"
        "This ebook is for the use of anyone anywhere at no cost.\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK SOMETHING ***\n"
        f"{body}\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK SOMETHING ***\n"
        "Updated editions will replace the previous one.\n"
    )
    stripped = strip_boilerplate(raw)
    assert "Project Gutenberg eBook of" not in stripped
    assert "Updated editions" not in stripped
    assert stripped.startswith("The Time Traveller")


def test_strip_boilerplate_leaves_a_plain_document_alone() -> None:
    raw = "A document with no licence around it at all."
    assert strip_boilerplate(raw) == raw


def test_sample_body_reads_past_the_opening() -> None:
    """An opening is the least representative part of a document."""
    raw = ("front matter " * 500) + ("the actual body " * 4000)
    assert "the actual body" in sample_body(raw)


def test_a_label_is_not_a_speaker() -> None:
    """`\\b[A-Z][a-zA-Z]+:\\s` made "Chapter 1: " a conversation.

    A speaker recurs. A name seen once is a field label, which is why the stats
    count only names appearing at least twice.
    """
    labelled = "Date: 2026-01-01\nAuthor: Someone\nChapter 1: The Beginning\nNote: read this\n"
    distinct, lines, _ = _speaker_stats(labelled)
    assert (distinct, lines) == (0, 0)

    dialogue = (
        "Ana: we should ship it\nBen: not yet\nCleo: agreed\n"
        "Ana: why not\nBen: the gate\nCleo: after the gate\n"
    )
    distinct, lines, _ = _speaker_stats(dialogue)
    assert distinct == 3
    assert lines == 6


def test_extension_decides_media_and_code() -> None:
    for ext, expected in (
        ("mp3", "audio"),
        ("wav", "audio"),
        ("mp4", "video"),
        ("py", "code"),
        ("rs", "code"),
        ("epub", "book"),
    ):
        assert classify_content("anything at all", [], 100, ext) == expected


def test_kindle_needs_its_own_header_not_just_a_rule() -> None:
    """`^==========` alone made a design-review document Kindle clippings."""
    divider_only = "Project Atlas\n==========\nA design document with a divider in it.\n" * 5
    assert classify_content(divider_only, [], 300, "txt") != "kindle_clippings"

    real = "Some Book (Author)\n- Your Highlight on page 12\n\nthe highlighted text\n==========\n"
    assert classify_content(real, [], 300, "txt") == "kindle_clippings"


def test_short_documents_are_notes() -> None:
    assert classify_content("a few quick thoughts about today", [], 40, "txt") == "notes"


def test_plot_ticks_are_not_numbered_sections() -> None:
    """A PDF extracts bare numbers onto their own lines, sections and data alike.

    Measured on the stored papers: "Attention Is All You Need" produced 199
    matches, whose most common distinct values were 0.0, 0.1, 0.2, 0.3 -- axis
    ticks, not sections. A section number never starts with zero, and that is
    the only thing separating the two by pattern.
    """
    ticks = "\n".join(f"0.{n}" for n in range(10))
    assert count_numbered_sections(ticks) == 0

    real = "3.1\nAttention\n3.2\nMulti-Head\n3.2.1\nScaled Dot-Product\n"
    assert count_numbered_sections(real) == 3

    # A measurement cannot pose as a section number.
    assert count_numbered_sections("2931529.5\n1234.56\n") == 0


def test_duplicated_extraction_does_not_multiply_the_section_count() -> None:
    """The parser can repeat a section body (issue #97).

    Counting raw matches let one skeleton of 3 sections read as 9 and cross the
    >= 8 threshold that awards the technical score its largest structural bonus.
    """
    skeleton = "3.1\nOne\n3.2\nTwo\n3.3\nThree\n"
    assert count_numbered_sections(skeleton) == 3
    assert count_numbered_sections(skeleton * 3) == 3


def test_chapter_headings_do_not_decide_prose() -> None:
    """Chapter headings look like the obvious prose signal and are not one.

    A technical book is divided into chapters exactly like a novel, so awarding
    prose for them only ever fired on both -- it is what made `art_of_unix.txt`
    a book despite its correctly-detected technical vocabulary.
    """
    sections = [{"heading": f"Chapter {i}"} for i in range(1, 9)]
    technical = (
        "The kernel exposes a system call interface; each function takes parameters "
        "and returns an integer. A process reads from stdin and writes to stdout, and "
        "the protocol between client and server is specified as a sequence of packets. "
    ) * 200
    assert _FAMILIES[classify_content(technical, sections, 30000, "txt")] == "technical"
