"""Furniture removal for text captured by scraping a site.

Concrete shapes live here, not in the module: the detector is structural, so
naming a site in it would only recognise the sites someone already looked at.

Every case states its input and its whole expected output literally. The
interesting behaviour is which lines survive and in what order, and an assertion
that rebuilds the expectation by the same rule as the input cannot see a wrong
rule.
"""

import pytest

from app.services.book_parser import BookParser
from app.services.parser import DocumentParser
from app.services.source_text import decode, normalise
from app.services.universal_parser import UniversalParser


def test_a_repeating_navigation_block_collapses_to_its_first_instance():
    source = "\n".join(
        [
            "Prev",
            "Up",
            "Next",
            "Chapter 1. Origins",
            "The first chapter opens here.",
            "Prev",
            "Up",
            "Next",
            "Chapter 2. Growth",
            "The second chapter opens here.",
            "Prev",
            "Up",
            "Next",
            "Chapter 3. Decline",
            "The third chapter opens here.",
        ]
    )

    assert normalise(source) == "\n".join(
        [
            "Prev",
            "Up",
            "Next",
            "Chapter 1. Origins",
            "The first chapter opens here.",
            "Chapter 2. Growth",
            "The second chapter opens here.",
            "Chapter 3. Decline",
            "The third chapter opens here.",
        ]
    )


def test_a_heading_buried_in_furniture_survives_even_when_it_recurs_most():
    """I-30: a heading is a label the source authored, so nothing may delete it.

    Here the heading recurs six times and the pager three. That profile defeats
    any "delete what recurs often" threshold, which is why there is none: a line
    is dropped only where the document still holds it elsewhere.
    """
    source = "\n".join(
        [
            "Prev",
            "Up",
            "Chapter 4. Modularity",
            "Chapter 4. Modularity",
            "Prev",
            "Up",
            "Chapter 4. Modularity",
            "Chapter 4. Modularity",
            "Prev",
            "Up",
            "Chapter 4. Modularity",
            "Chapter 4. Modularity",
            "Body text appears once.",
        ]
    )

    assert normalise(source) == "\n".join(
        [
            "Prev",
            "Up",
            "Chapter 4. Modularity",
            "Body text appears once.",
        ]
    )


def test_an_error_page_the_crawl_walked_into_is_collapsed_with_the_rest():
    """Its body is ordinary prose, so only the repetition marks it as furniture."""
    source = "\n".join(
        [
            "Page not found",
            "Home to one of the largest free archives online.",
            "About | Contact",
            "Real content about compilers.",
            "Page not found",
            "Home to one of the largest free archives online.",
            "About | Contact",
            "Real content about linkers.",
            "Page not found",
            "Home to one of the largest free archives online.",
            "About | Contact",
            "Real content about loaders.",
        ]
    )

    assert normalise(source) == "\n".join(
        [
            "Page not found",
            "Home to one of the largest free archives online.",
            "About | Contact",
            "Real content about compilers.",
            "Real content about linkers.",
            "Real content about loaders.",
        ]
    )


def test_two_recurring_lines_are_not_enough_to_be_a_template():
    """A pair of repeated lines is a refrain; three consecutive is a template.

    Without this floor, any prose with a repeated short line would be eaten.
    """
    source = "\n".join(
        [
            "Alas",
            "Poor Yorick",
            "I knew him well.",
            "Alas",
            "Poor Yorick",
            "He hath borne me on his back.",
            "Alas",
            "Poor Yorick",
            "Where be your gibes now?",
        ]
    )

    assert normalise(source) == source


def test_a_block_seen_only_twice_is_not_yet_a_template():
    """Twice is coincidence. A scrape's furniture recurs on every page.

    Three consecutive lines here each appear exactly twice, so nothing is
    template enough to touch.
    """
    source = "\n".join(
        [
            "To be, or not to be",
            "that is the question",
            "Whether tis nobler",
            "A speech that follows once.",
            "To be, or not to be",
            "that is the question",
            "Whether tis nobler",
            "A different speech that follows once.",
        ]
    )

    assert normalise(source) == source


def test_a_blank_line_between_furniture_lines_stops_the_collapse():
    """A run must be literally consecutive. This is the deliberate boundary.

    Treating blank lines as neutral -- so they neither break a run nor count
    toward it -- catches double-spaced scrapes, and was measured against the 14
    corpora in DATA. It eats real documents: Hamlet loses 25 lines (`GHOST.` /
    `[_Beneath._] Swear.` / `HAMLET.`, the second and third exchanges deleted),
    the Federalist Papers 8 (the byline block each paper authors), and Alice 7
    (the asterisk scene breaks). Each is content at that position that happens
    to recur, which is the one thing the collapse rule cannot tell apart.

    So a scrape that double-spaces its navigation is not collapsed, and its
    furniture reaches the corpus. That is the price of never touching verse.
    """
    source = "\n".join(
        [
            "Prev",
            "",
            "Up",
            "",
            "Next",
            "Chapter 1. Origins",
            "Prev",
            "",
            "Up",
            "",
            "Next",
            "Chapter 2. Growth",
            "Prev",
            "",
            "Up",
            "",
            "Next",
            "Chapter 3. Decline",
        ]
    )

    assert normalise(source) == source


def test_prose_that_never_repeats_is_returned_unchanged():
    source = "\n".join(
        [
            "The first sentence stands alone.",
            "The second sentence differs from it.",
            "The third resembles neither.",
        ]
    )

    assert normalise(source) == source


def test_html_entities_and_non_breaking_spaces_are_normalised():
    """`&nbsp;` unescapes to U+00A0, which would split phrases for any matcher."""
    assert normalise("He said &#8220;hi&#8221; &#8212; then&nbsp;left.") == (
        "He said “hi” — then left."
    )


def test_decode_replaces_an_undecodable_byte_rather_than_raising():
    assert decode("café".encode()) == "café"
    assert "hello" in decode(b"hello \xff world")


# Every text-reading parser goes through it. Three did their own chardet decode
# before this module existed, and a fourth that reintroduced one would silently
# ingest furniture -- so the parsers are tested, not just the module.

_SCRAPED = "\n\n".join(
    "\n".join(["Prev", "Up", "Next"]) + f"\n\nChapter {n}. {title}\n\n{body}"
    for n, title, body in [
        (1, "Origins", "Unix began on a spare machine and grew from there."),
        (2, "Growth", "The toolkit philosophy spread with the source tapes."),
        (3, "Decline", "Vendors forked the system and interoperability suffered."),
    ]
)


@pytest.fixture
def scraped_file(tmp_path):
    path = tmp_path / "scraped.txt"
    path.write_text(_SCRAPED, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "parser",
    [DocumentParser(), BookParser(), UniversalParser()],
    ids=["DocumentParser", "BookParser", "UniversalParser"],
)
def test_every_text_parser_reads_through_source_text(parser, scraped_file):
    """The navigation reaches the document once, not once per chapter."""
    parsed = parser.parse(scraped_file, "txt")

    for nav_line in ("Prev", "Up", "Next"):
        assert parsed.raw_text.count(nav_line) == 1


@pytest.mark.parametrize(
    "parser",
    [DocumentParser(), BookParser(), UniversalParser()],
    ids=["DocumentParser", "BookParser", "UniversalParser"],
)
def test_no_section_body_carries_navigation(parser, scraped_file):
    """What survives the collapse lands ahead of chapter 1, outside every body.

    A section body is what becomes a chunk, so this is the assertion retrieval
    depends on: 118 of 248 chunks carried furniture on the one scraped corpus.
    """
    parsed = parser.parse(scraped_file, "txt")

    assert [s.text for s in parsed.sections if "Prev" in s.text] == []


def test_a_chapter_heading_a_scrape_repeated_is_still_authored(scraped_file):
    """I-30 through the parser: the collapse must not cost a heading.

    `UniversalParser` is the general text path -- `BookParser` recognises this
    fixture as a book and applies its own chapter-count heuristics on top.
    """
    parsed = UniversalParser().parse(scraped_file, "txt")

    assert [s.heading for s in parsed.sections] == [
        "Chapter 1. Origins",
        "Chapter 2. Growth",
        "Chapter 3. Decline",
    ]


# Furniture collapse must not eat repeated content


def test_a_repeated_indented_idiom_survives_intact():
    """The reported failure: three functions sharing a `try/except` idiom. The
    idiom repeats at exactly the threshold, so collapsing it deleted the bodies
    of the second and third functions -- retrieval over them could never return
    their error handling again."""
    body = "    try:\n        return parse(x)\n    except ValueError:\n        return None\n"
    source = "".join(f"def {name}(x):\n{body}\n" for name in ("a", "b", "c"))

    out = normalise(source)

    # Every function keeps its own body: the idiom appears three times, not once.
    assert out.count("return parse(x)") == 3
    assert out.count("except ValueError:") == 3
    # `normalise` joins the kept lines, so a trailing blank line is not
    # reproduced; every other line is, in order.
    assert out.splitlines() == source.splitlines()[: len(out.splitlines())]
    assert len(out.splitlines()) >= len(source.splitlines()) - 1


def test_flush_left_scrape_chrome_still_collapses():
    """The case the collapse exists for: a nav block repeated on every page."""
    chrome = "Prev\nNext\nUp\n"
    source = "".join(f"{chrome}Section {i} says something distinct.\n" for i in range(4))

    out = normalise(source)

    assert out.count("Prev") == 1
    assert all(f"Section {i}" in out for i in range(4))


def test_indentation_beats_frequency():
    """A margin, not a threshold. An indented block repeated far more often than
    any chrome still survives, because no number can tell chrome from content and
    the left margin can."""
    block = "    logger.debug('step')\n    validate(x)\n    commit(x)\n"
    source = "".join(f"def f{i}(x):\n{block}\n" for i in range(12))

    assert normalise(source).count("validate(x)") == 12
