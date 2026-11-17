import pytest

from app.services.parser import (
    DocumentParser,
    _heading_is_prose,
    _join_spans,
    _norm_ws,
    _sections_plausible,
)
from app.types import ParsedDocument, Section


@pytest.fixture(scope="session")
def parser():
    return DocumentParser()


@pytest.fixture(scope="session")
def tmp_fixtures(tmp_path_factory):
    return tmp_path_factory.mktemp("fixtures")


@pytest.fixture(scope="session")
def pdf_file(tmp_fixtures):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    path = tmp_fixtures / "sample.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("Introduction", styles["Heading1"]),
        Paragraph("This is the introduction text with some content.", styles["Normal"]),
        Paragraph("Methods", styles["Heading1"]),
        Paragraph("This describes the methods used in this study.", styles["Normal"]),
    ]
    doc.build(elements)
    return path


@pytest.fixture(scope="session")
def docx_file(tmp_fixtures):
    from docx import Document

    path = tmp_fixtures / "sample.docx"
    doc = Document()
    doc.add_heading("Chapter One", level=1)
    doc.add_paragraph("This is the content of chapter one.")
    doc.add_heading("Section 1.1", level=2)
    doc.add_paragraph("A subsection with more detail.")
    doc.add_heading("Chapter Two", level=1)
    doc.add_paragraph("Content for chapter two.")
    doc.save(str(path))
    return path


@pytest.fixture(scope="session")
def txt_file(tmp_fixtures):
    path = tmp_fixtures / "sample.txt"
    content = (
        "First paragraph with some text.\n\nSecond paragraph that follows.\n\nThird paragraph here."
    )
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def md_file(tmp_fixtures):
    path = tmp_fixtures / "sample.md"
    content = (
        "# Title\n\nIntroduction text.\n\n"
        "## Background\n\nBackground content.\n\n"
        "## Methods\n\nMethods content."
    )
    path.write_text(content, encoding="utf-8")
    return path


def test_pdf_parse_returns_sections(parser, pdf_file):
    result = parser.parse(pdf_file, "pdf")
    assert isinstance(result, ParsedDocument)
    assert result.format == "pdf"
    assert result.pages > 0
    assert result.word_count > 0
    assert len(result.sections) >= 1


def test_docx_parse_returns_heading_hierarchy(parser, docx_file):
    result = parser.parse(docx_file, "docx")
    assert isinstance(result, ParsedDocument)
    assert result.format == "docx"
    headings = [s.heading for s in result.sections]
    assert "Chapter One" in headings or len(headings) >= 1
    levels = [s.level for s in result.sections]
    assert any(lvl == 1 for lvl in levels)


def test_txt_parse_detects_encoding_and_sections(parser, txt_file):
    result = parser.parse(txt_file, "txt")
    assert isinstance(result, ParsedDocument)
    assert result.format == "txt"
    assert len(result.sections) >= 2
    assert result.word_count > 0


def test_unmarked_gutenberg_text_keeps_only_the_story(parser, tmp_path):
    """Usher has no chapter markers, so it reaches the paragraph split, licence and all (#357)."""
    path = tmp_path / "usher.txt"
    path.write_text(
        "The Project Gutenberg eBook of The Fall of the House of Usher\n\n"
        "This eBook is for the use of anyone anywhere in the United States.\n\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK THE FALL OF THE HOUSE OF USHER ***\n\n"
        "During the whole of a dull, dark, and soundless day.\n\n"
        "I know not how it was; but, with the first glimpse of the building.\n\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK THE FALL OF THE HOUSE OF USHER ***\n\n"
        "Updated editions will replace the previous one.\n\n"
        "START: FULL LICENSE\n\nTHE FULL PROJECT GUTENBERG LICENSE\n",
        encoding="utf-8",
    )
    result = parser.parse(path, "txt")
    assert [s.text for s in result.sections] == [
        "During the whole of a dull, dark, and soundless day.",
        "I know not how it was; but, with the first glimpse of the building.",
    ]
    assert "Gutenberg" not in result.raw_text
    assert result.word_count == 24


def test_md_parse_detects_headings(parser, md_file):
    result = parser.parse(md_file, "md")
    assert isinstance(result, ParsedDocument)
    assert result.format == "md"
    headings = [s.heading for s in result.sections]
    assert "Title" in headings or "Background" in headings or "Methods" in headings


@pytest.mark.parametrize(
    "heading,expected",
    [
        ("Chapter 5 describes the foundations of machine learning", True),
        ("Chapter 7 focuses on modern developments", True),
        ("Chapter 11 along with some of their fundamental properties", True),
        ("Part 3 are the same triangle", True),
        ("volume 22 of Carus Mathematical Monographs", True),
        ("Chapter 5. Machine Learning", False),
        ("Chapter 5: Optimization", False),
        ("Chapter 5 Machine Learning", False),
        ("Chapter 1 — The Beginning", False),
        ("CHAPTER I", False),
        ("Introduction", False),
        ("Methods", False),
    ],
)
def test_heading_is_prose(heading, expected):
    assert _heading_is_prose(heading) is expected


def test_sections_plausible_rejects_all_prose():
    secs = [
        Section(heading=h, level=1, text="x", page_start=1, page_end=1)
        for h in (
            "Chapter 5 describes the foundations",
            "Chapter 7 focuses on developments",
            "Part 3 are the same triangle",
        )
    ]
    assert _sections_plausible(secs) is False


def test_sections_plausible_accepts_real_headings():
    secs = [
        Section(heading=h, level=1, text="x", page_start=1, page_end=1)
        for h in ("Chapter 1 — The Beginning", "Chapter 2 — The Middle", "Chapter 3 — The End")
    ]
    assert _sections_plausible(secs) is True


def test_sections_plausible_empty():
    assert _sections_plausible([]) is False


@pytest.fixture(scope="session")
def prose_trap_pdf(tmp_fixtures):
    """A PDF whose preface enumerates its own chapters in body font — the exact
    trap that made chapter-regex matching produce prose-fragment headings."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate

    path = tmp_fixtures / "prose_trap.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("Preface", styles["Heading1"]),
        Paragraph(
            "Chapter 5 describes the foundations of machine learning, both algorithms "
            "for optimizing over given training examples and their analysis.",
            styles["Normal"],
        ),
        Paragraph(
            "Chapter 7 focuses on modern developments in understanding these methods.",
            styles["Normal"],
        ),
        Paragraph(
            "Part 3 discusses ranking and social choice as well as related problems.",
            styles["Normal"],
        ),
        Paragraph("Introduction", styles["Heading1"]),
        Paragraph(
            "The real introduction body with enough content to fill a section.",
            styles["Normal"],
        ),
        Paragraph("Methods", styles["Heading1"]),
        Paragraph(
            "This describes the actual methods used in this study in detail.",
            styles["Normal"],
        ),
    ]
    doc.build(elements)
    return path


def test_pdf_preface_prose_not_mistaken_for_headings(parser, prose_trap_pdf):
    result = parser.parse(prose_trap_pdf, "pdf")
    headings = [s.heading for s in result.sections]
    assert not any(_heading_is_prose(h) for h in headings), headings
    assert not any(h.lower().startswith("chapter 5 describes") for h in headings), headings
    # Headings carry no multi-space runs (PyMuPDF span-join artifact).
    assert not any("  " in h for h in headings), headings
    # The real font-based headings survive.
    joined = " ".join(headings).lower()
    assert any(k in joined for k in ("introduction", "methods", "preface")), headings


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("The   Law   of   Large   Numbers", "The Law of Large Numbers"),
        ("  Best Rank- k   Approximations ", "Best Rank- k Approximations"),
        ("Singular\tValue\nDecomposition", "Singular Value Decomposition"),
        ("Introduction", "Introduction"),
    ],
)
def test_norm_ws(raw, expected):
    assert _norm_ws(raw) == expected


def _span(text: str, x0: float, x1: float, size: float = 12.0) -> dict:
    return {"text": text, "bbox": (x0, 0.0, x1, size), "size": size}


class TestJoinSpans:
    def test_glyph_split_word_is_not_broken_by_spaces(self):
        """Type3 subsets split one word across many spans with no gap between
        them; joining on a space corrupted every word."""
        spans = [
            _span("The C", 27.750, 74.964, 16.5),
            _span("on", 74.980, 95.581, 16.5),
            _span("ce", 95.424, 113.169, 16.5),
            _span("ptu", 113.177, 141.037, 16.5),
            _span("al F", 141.045, 169.697, 16.5),
            _span("oun", 169.028, 200.460, 16.5),
            _span("da", 200.303, 220.153, 16.5),
            _span("t", 219.748, 226.282, 16.5),
            _span("i", 226.299, 231.562, 16.5),
            _span("ons", 231.570, 260.296, 16.5),
        ]
        assert _join_spans(spans) == "The Conceptual Foundations"

    def test_negative_kerning_does_not_insert_a_space(self):
        assert _join_spans([_span("Ke", 10.0, 20.0), _span("rn", 19.4, 30.0)]) == "Kern"

    def test_positional_word_gap_becomes_a_space(self):
        """Words separated by position rather than a space glyph must not weld."""
        spans = [_span("Hello", 10.0, 40.0), _span("world", 44.0, 74.0)]
        assert _join_spans(spans) == "Hello world"

    def test_existing_space_is_not_doubled(self):
        spans = [_span("Hello ", 10.0, 43.0), _span("world", 44.0, 74.0)]
        assert _join_spans(spans) == "Hello world"

    def test_leading_space_on_next_span_is_not_doubled(self):
        spans = [_span("Hello", 10.0, 40.0), _span(" world", 44.0, 78.0)]
        assert _join_spans(spans) == "Hello world"

    def test_empty_spans_are_skipped(self):
        assert _join_spans([_span("a", 10.0, 15.0), _span("", 15.0, 15.0)]) == "a"

    def test_no_spans(self):
        assert _join_spans([]) == ""

    def test_gap_threshold_scales_with_font_size(self):
        """A 3pt gap is a word break at 12pt but mere kerning at 24pt."""
        assert _join_spans([_span("a", 0.0, 10.0, 12.0), _span("b", 13.0, 20.0, 12.0)]) == "a b"
        assert _join_spans([_span("a", 0.0, 10.0, 24.0), _span("b", 13.0, 20.0, 24.0)]) == "ab"


class TestEpubDocumentSplitting:
    """A Gutenberg EPUB packs many chapters into a few XHTML files.

    One section per file gave Moby Dick 11 sections for 135 chapters, each
    headed by whichever chapter came first, and collapsing whitespace left every
    chapter a single run-on line.
    """

    def test_each_heading_starts_its_own_section(self):
        from app.services.parser import _split_epub_document

        html_doc = (
            "<html><body>"
            "<h2>CHAPTER 1. Loomings.</h2><p>Call me Ishmael.</p>"
            "<h2>CHAPTER 2. The Carpet-Bag.</h2><p>I stuffed a shirt or two.</p>"
            "<h2>CHAPTER 3. The Spouter-Inn.</h2><p>Entering that gable-ended inn.</p>"
            "</body></html>"
        )
        out = _split_epub_document(html_doc, "fallback")
        assert [h for h, _, _ in out] == [
            "CHAPTER 1. Loomings.",
            "CHAPTER 2. The Carpet-Bag.",
            "CHAPTER 3. The Spouter-Inn.",
        ]
        assert out[0][2] == "Call me Ishmael."

    def test_paragraph_breaks_survive(self):
        from app.services.parser import _epub_text

        text = _epub_text("<p>First paragraph.</p><p>Second paragraph.</p>")
        assert text == "First paragraph.\n\nSecond paragraph."

    def test_no_line_is_indented_into_a_markdown_code_block(self):
        from app.services.parser import _epub_text

        verse = "<blockquote><p>    Verse line one</p><p>    Verse line two</p></blockquote>"
        text = _epub_text(verse)
        assert not any(line.startswith("    ") for line in text.split("\n"))

    def test_front_matter_before_the_first_heading_is_kept(self):
        from app.services.parser import _split_epub_document

        doc = "<p>Front matter.</p><h1>Chapter One</h1><p>Body.</p>"
        out = _split_epub_document(doc, "Preface")
        assert out[0] == ("Preface", 1, "Front matter.")
        assert out[1] == ("Chapter One", 1, "Body.")

    def test_a_document_without_headings_yields_one_section(self):
        from app.services.parser import _split_epub_document

        out = _split_epub_document("<p>Only prose here.</p>", "Chapter File")
        assert out == [("Chapter File", 1, "Only prose here.")]

    def test_figure_caption_and_alt_text_survive(self):
        from app.services.parser import _epub_text

        raw = (
            "<p>Introduction.</p>"
            "<figure><img src='fig1.png' alt='Basic RAG Architecture' />"
            "<figcaption>Figure 1-1. Basic RAG Architecture</figcaption></figure>"
            "<p>Next paragraph.</p>"
        )
        text = _epub_text(raw)
        assert "[Figure: Basic RAG Architecture]" in text
        assert "Figure 1-1. Basic RAG Architecture" in text
        assert "Introduction." in text
        assert "Next paragraph." in text

    def test_a_blank_line_inside_alt_text_does_not_break_the_image(self):
        """An O'Reilly EPUB's auto-generated alt text carried a literal blank

        line ("A close up of a sign\\n\\nDescription automatically generated").
        CommonMark ends a paragraph at a blank line, so `![A close up of a
        sign` and `Description ... generated](url)` landed as two stray
        paragraphs of literal bracket text, with no image at all.
        """
        from app.services.parser import _epub_text

        raw = (
            "<figure><img src='fig.png' "
            "alt='A close up of a sign\n\nDescription automatically generated' />"
            "<figcaption>Figure 1-1. Tokenization example.</figcaption></figure>"
        )
        text = _epub_text(raw)
        assert "![A close up of a sign Description automatically generated](fig.png)" in text

    def test_a_blank_line_inside_a_bare_img_alt_does_not_break_the_image(self):
        """Brackets the figure case above: a plain `<img>` outside any <figure>."""
        from app.services.parser import _epub_text

        raw = "<p>See below.</p><img src='fig.png' alt='Line one\n\nLine two' />"
        text = _epub_text(raw)
        assert "![Line one Line two](fig.png)" in text


class TestEpubSectionLevels:
    """A book's section tree comes from its structure: before, every EPUB and bundle section was
    level 1, so Parts held nothing and a "Note" box became a section of its own."""

    HTMLBOOK = (
        '<section data-type="chapter"><h1>Chapter 2. Models</h1><p>Opening of the chapter.</p>'
        '<section data-type="sect1"><h1>Part 1: Basics</h1><p>What this part covers.</p>'
        '<section data-type="sect2"><h2>Tokens</h2><p>Text is cut into tokens first.</p>'
        '<div data-type="note"><h6>Note</h6><p>Tokens are not words.</p></div>'
        '<section data-type="sect3"><h3>Vocabulary</h3><p>The set of known tokens.</p>'
        "</section></section>"
        '<div class="sidebar"><h1>Helper Functions</h1><p>Code used throughout.</p></div>'
        "<aside><h2>Aside</h2><p>A side remark.</p></aside>"
        "<figure><h6>Figure 2-1. A token</h6></figure>"
        "</section></section>"
    )

    def test_structural_sections_nest_and_boxes_stay_in_their_section(self):
        from app.services.parser import _split_epub_document

        out = _split_epub_document(self.HTMLBOOK, "fallback")
        assert [(h, lv) for h, lv, _ in out] == [
            ("Chapter 2. Models", 1),
            ("Part 1: Basics", 2),
            ("Tokens", 3),
            ("Vocabulary", 4),
        ]
        tokens, vocabulary = out[2][2], out[3][2]
        assert "Tokens are not words." in tokens  # the note stays where it was written
        assert "Helper Functions" in vocabulary and "A side remark." in vocabulary

    def test_without_structural_sections_the_tags_decide(self):
        from app.services.parser import _split_epub_document

        out = _split_epub_document("<h2>Ch</h2><p>a</p><h3>Sub</h3><p>b</p>", "f")
        assert [(h, lv) for h, lv, _ in out] == [("Ch", 2), ("Sub", 3)]

    def test_an_epub_is_renumbered_as_one_book_not_per_file(self, tmp_path):
        """Moby Dick's first file has the title's <h1> over chapter <h2>s and every later file
        only <h2>s; renumbering each file put the same kind of heading on two levels."""
        from ebooklib import epub

        from app.services.parser import DocumentParser

        book = epub.EpubBook()
        book.set_title("Two Files")
        body = "<p>" + "Enough prose to keep this section. " * 3 + "</p>"
        first = epub.EpubHtml(title="a", file_name="a.xhtml")
        first.content = f"<h1>The Book</h1>{body}<h2>CHAPTER 1.</h2>{body}"
        second = epub.EpubHtml(title="b", file_name="b.xhtml")
        second.content = f"<h2>CHAPTER 2.</h2>{body}"
        for item in (first, second):
            book.add_item(item)
        book.spine = [first, second]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        path = tmp_path / "two.epub"
        epub.write_epub(str(path), book)

        parsed = DocumentParser().parse(path, "epub")
        levels = {s.heading: s.level for s in parsed.sections}
        assert levels["The Book"] == 1
        assert levels["CHAPTER 1."] == levels["CHAPTER 2."] == 2

    def test_a_bundle_page_nests_under_its_manifest_level_with_an_empty_title(self):
        """The Python tutorial's chapter pages open with an <h1> that has no text of its own;
        its subsections must still sit one level under the page, not take its place."""
        from app.services.parser import epub_chapter_sections

        page = "<h1>2. Using the Interpreter</h1><h2>2.1. Invoking</h2><p>" + "x " * 40 + "</p>"
        sections = epub_chapter_sections(page, "2. Using the Interpreter", top_level=1)
        assert [(s.heading, s.level) for s in sections] == [("2.1. Invoking", 2)]
