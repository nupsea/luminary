

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
