class TestChapterSplitting:
    """A Gutenberg EPUB packs many chapters into one XHTML file.

    A unit per spine document listed 11 chapters for Moby Dick's 135 and made
    Prev/Next jump twelve chapters at a time.
    """

    def test_each_heading_becomes_its_own_chapter(self):
        from bs4 import BeautifulSoup

        from app.services.epub_service import _split_soup_on_headings

        soup = BeautifulSoup(
            "<body><h2>CHAPTER 1. Loomings.</h2><p>Call me Ishmael.</p>"
            "<h2>CHAPTER 2. The Carpet-Bag.</h2><p>I stuffed a shirt.</p></body>",
            "html.parser",
        )
        units = _split_soup_on_headings(soup)
        assert [u["title"] for u in units] == ["CHAPTER 1. Loomings.", "CHAPTER 2. The Carpet-Bag."]
        assert "Call me Ishmael." in units[0]["html"]
        assert "Call me Ishmael." not in units[1]["html"]

    def test_a_nested_heading_is_not_a_chapter_break(self):
        """Headings inside an extracts block are sub-headings of it.

        Requiring every heading to share one parent left Moby Dick's first file,
        and with it chapters 1 to 8, as a single lump.
        """
        from bs4 import BeautifulSoup

        from app.services.epub_service import _split_soup_on_headings

        soup = BeautifulSoup(
            "<body><h2>EXTRACTS.</h2><div class='extracts'><h3>Sub</h3><p>Quote.</p></div>"
            "<h2>CHAPTER 1.</h2><p>Body.</p>"
            "<h2>CHAPTER 2.</h2><p>More.</p></body>",
            "html.parser",
        )
        units = _split_soup_on_headings(soup)
        assert [u["title"] for u in units] == ["EXTRACTS.", "CHAPTER 1.", "CHAPTER 2."]
        assert "Quote." in units[0]["html"]

    def test_front_matter_before_the_first_heading_is_kept(self):
        from bs4 import BeautifulSoup

        from app.services.epub_service import _split_soup_on_headings

        soup = BeautifulSoup("<body><p>Front.</p><h1>One</h1><p>Body.</p></body>", "html.parser")
        units = _split_soup_on_headings(soup)
        assert units[0]["title"] == ""
        assert "Front." in units[0]["html"]
        assert units[1]["title"] == "One"

    def test_a_document_without_headings_stays_whole(self):
        from bs4 import BeautifulSoup

        from app.services.epub_service import _split_soup_on_headings

        soup = BeautifulSoup("<body><p>Just prose, no headings.</p></body>", "html.parser")
        assert len(_split_soup_on_headings(soup)) == 1

    def test_the_books_toc_decides_what_a_chapter_is(self, tmp_path):
        """A file the TOC lists once is one chapter; a file it points into twice is split.

        Heading levels alone cannot tell a technical chapter (<h1> over <h2>
        sections) from a Gutenberg file (<h1> title over <h2> chapters).
        """
        from ebooklib import epub

        from app.services.epub_service import EpubService

        book = epub.EpubBook()
        book.set_identifier("toc-test")
        book.set_title("TOC test")
        tech = epub.EpubHtml(title="Intro", file_name="ch01.xhtml")
        tech.content = (
            "<html><body><h1>Chapter 1. Introduction</h1><p>Intro text here.</p>"
            "<h2>1.1 Background</h2><p>Background text.</p>"
            "<h2>1.2 Architecture</h2><p>Arch text.</p></body></html>"
        )
        packed = epub.EpubHtml(title="Stories", file_name="stories.xhtml")
        packed.content = (
            "<html><body><h1>STORIES</h1>"
            '<h2 id="s1">CHAPTER 2. One.</h2><p>First story.</p>'
            '<h2 id="s2">CHAPTER 3. Two.</h2><p>Second story.</p></body></html>'
        )
        for item in (tech, packed):
            book.add_item(item)
        book.toc = (
            epub.Link("ch01.xhtml", "Chapter 1", "c1"),
            epub.Link("stories.xhtml#s1", "Chapter 2", "c2"),
            epub.Link("stories.xhtml#s2", "Chapter 3", "c3"),
        )
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", tech, packed]
        path = tmp_path / "toc.epub"
        epub.write_epub(str(path), book)

        titles = [c["title"] for c in EpubService().get_toc(str(path))]

        assert titles.count("Intro") + titles.count("Chapter 1. Introduction") == 1
        assert "1.1 Background" not in titles
        assert "CHAPTER 2. One." in titles
        assert "CHAPTER 3. Two." in titles

    def test_sanitize_html_preserves_images_figures_and_callouts(self):
        from app.services.epub_service import EpubService

        raw_html = (
            '<div data-type="note"><p>Important note</p></div>'
            '<figure id="fig1">'
            '<img src="data:image/png;base64,iVBORw0KGgoA" alt="Diagram" />'
            "<figcaption>Figure 1. Diagram</figcaption>"
            "</figure>"
            '<script>alert("bad")</script>'
        )

        cleaned = EpubService.sanitize_html(raw_html)
        assert "data:image/png;base64" in cleaned
        assert "<figure" in cleaned
        assert "<figcaption>Figure 1. Diagram</figcaption>" in cleaned
        assert 'data-type="note"' in cleaned
        assert "<script>" not in cleaned

    def test_a_heading_wrapped_in_a_header_does_not_drop_the_body(self):
        from bs4 import BeautifulSoup

        from app.services.epub_service import _split_soup_on_headings

        soup = BeautifulSoup(
            "<body><section><header><h1>Chapter 3</h1></header>"
            "<p>The whole chapter body.</p><h2>Part</h2><p>More body.</p></section></body>",
            "html.parser",
        )
        html = "".join(u["html"] for u in _split_soup_on_headings(soup))
        assert "The whole chapter body." in html
        assert "More body." in html


class TestBookMarkupSurvivesSanitizing:
    """An O'Reilly chapter lost 85 footnote markers, 19 equations and 7 table captions."""

    def test_footnotes_subscripts_definitions_and_captions_are_kept(self):
        from app.services.epub_service import EpubService

        cleaned = EpubService.sanitize_html(
            '<p>logits<sup><a href="#n1" id="n1-marker">1</a></sup> of H<sub>2</sub>O '
            "in <i>Moby-Dick</i></p>"
            "<dl><dt>Token</dt><dd>A unit of text.</dd></dl>"
            "<table><caption>Table 2-1. Sizes</caption><tr><td>7B</td></tr></table>"
        )
        assert '<sup><a href="#n1" id="n1-marker">1</a></sup>' in cleaned
        assert "H<sub>2</sub>O" in cleaned
        assert "<i>Moby-Dick</i>" in cleaned
        assert "<dt>Token</dt><dd>A unit of text.</dd>" in cleaned
        assert "<caption>Table 2-1. Sizes</caption>" in cleaned

    def test_mathml_is_kept_and_cannot_carry_html_or_handlers(self):
        from app.services.epub_service import EpubService

        cleaned = EpubService.sanitize_html(
            '<math display="block" alttext="x sub 1"><msub><mi onclick="evil()">x</mi>'
            "<mn>1</mn></msub>"
            '<annotation-xml encoding="text/html"><img src="x" onerror="evil()"></annotation-xml>'
            "</math>"
        )
        assert '<math alttext="x sub 1" display="block">' in cleaned
        assert "<msub><mi>x</mi><mn>1</mn></msub>" in cleaned
        assert "annotation-xml" not in cleaned
        assert "onclick" not in cleaned
        assert "onerror" not in cleaned
        assert 'src="x"' not in cleaned

    def test_a_title_keeps_the_space_between_its_label_and_name(self):
        from bs4 import BeautifulSoup

        from app.services.epub_service import _extract_chapter_title

        soup = BeautifulSoup(
            '<h1><span class="label">Chapter 1. </span>Introduction</h1>', "html.parser"
        )
        assert _extract_chapter_title(soup) == "Chapter 1. Introduction"
        soup = BeautifulSoup("<h1>Praise for <em>AI Engineering</em></h1>", "html.parser")
        assert _extract_chapter_title(soup) == "Praise for AI Engineering"


def test_a_link_into_another_chapter_names_the_chapter_that_holds_it(tmp_path):
    """The book links `ch02.html#x` while the reader shows one chapter at a time."""
    from ebooklib import epub

    from app.services.epub_service import EpubService

    book = epub.EpubBook()
    book.set_identifier("links-test")
    book.set_title("Links")
    one = epub.EpubHtml(title="One", file_name="ch01.xhtml")
    one.content = (
        "<html><body><h1>Chapter 1</h1>"
        '<p>See <a href="ch02.html#tokens">Tokens</a>, <a href="ch02.html">Chapter 2</a>, '
        '<a href="#here">here</a>, <a href="https://example.com/">out</a>.</p>'
        '<p id="here">Here.</p></body></html>'
    )
    two = epub.EpubHtml(title="Two", file_name="ch02.xhtml")
    two.content = '<html><body><h1>Chapter 2</h1><p id="tokens">Tokens.</p></body></html>'
    for item in (one, two):
        book.add_item(item)
    book.toc = (epub.Link("ch01.xhtml", "One", "c1"), epub.Link("ch02.xhtml", "Two", "c2"))
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", one, two]
    path = tmp_path / "links.epub"
    epub.write_epub(str(path), book)

    html = EpubService().get_chapter(str(path), 0)["html"]

    assert '<a data-chapter="1" href="#tokens">Tokens</a>' in html
    assert '<a data-chapter="1" href="#">Chapter 2</a>' in html
    assert '<a href="#here">here</a>' in html
    assert '<a href="https://example.com/">out</a>' in html
