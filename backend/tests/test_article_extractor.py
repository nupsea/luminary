import pytest

trafilatura = pytest.importorskip("trafilatura")

from app.services.article_extractor import ArticleExtractor  # noqa: E402

PAD = "padding sentence for extractor density. " * 20


def _extract(html: str) -> str:
    """The real pipeline: prepare, extract, then restore protected blocks."""
    extractor = ArticleExtractor()
    prepared, protected = extractor._prepare_html(html, "testdoc")
    markdown = trafilatura.extract(
        prepared,
        output_format="markdown",
        include_links=True,
        include_images=True,
        include_formatting=True,
    )
    return extractor._restore_protected(markdown or "", protected)


def _prepared(html: str) -> str:
    return ArticleExtractor()._prepare_html(html, "testdoc")[0]


def _wrap(body: str) -> str:
    return (
        f"<html><body><article><h1>Title</h1><p>{PAD}</p>{body}<p>{PAD}</p></article></body></html>"
    )


class TestLazyImageHydration:
    def test_picture_source_srcset_is_hydrated(self):
        html = _wrap(
            "<figure><picture>"
            '<source srcset="https://cdn.test/small.png 640w, https://cdn.test/large.png 1400w">'
            '<img role="presentation" width="700">'
            "</picture></figure>"
        )
        assert "![](https://cdn.test/large.png)" in _extract(html)

    def test_data_src_is_hydrated(self):
        html = _wrap('<figure><img data-src="https://cdn.test/diagram.png"></figure>')
        assert "https://cdn.test/diagram.png" in _extract(html)

    def test_figcaption_becomes_alt_text(self):
        html = _wrap(
            '<figure><img data-src="https://cdn.test/d.png">'
            "<figcaption>Figure 1: system schematic</figcaption></figure>"
        )
        assert "![Figure 1: system schematic](https://cdn.test/d.png)" in _extract(html)

    def test_existing_src_is_not_overwritten(self):
        html = _wrap(
            '<figure><picture><source srcset="https://cdn.test/other.png 1400w">'
            '<img src="https://cdn.test/original.png"></picture></figure>'
        )
        assert "https://cdn.test/original.png" in _extract(html)


class TestListStructure:
    def test_bold_prefixed_items_keep_bullets_and_spacing(self):
        html = _wrap(
            "<ul>"
            "<li><strong>Positive Signals:</strong> capturing engagement.</li>"
            "<li><strong>Negative Signals:</strong> capturing fatigue.</li>"
            "</ul>"
        )
        lines = _extract(html).splitlines()
        assert "- **Positive Signals:** capturing engagement." in lines
        assert "- **Negative Signals:** capturing fatigue." in lines

    def test_link_leading_item_is_not_dropped(self):
        html = _wrap('<ul><li><a href="https://test.dev">Planner</a> writes intent.</li></ul>')
        assert "- [Planner](https://test.dev) writes intent." in _extract(html).splitlines()

    def test_plain_items_are_unaffected(self):
        html = _wrap("<ul><li>first item</li><li>second item</li></ul>")
        lines = _extract(html).splitlines()
        assert "- first item" in lines
        assert "- second item" in lines


class TestAnchorFlatteningScope:
    def test_anchors_in_prose_stay_real_links(self):
        """Flattened anchors are invisible to trafilatura's link-density heuristic."""
        html = _wrap('<p>See <a href="https://test.dev">the docs</a> for detail.</p>')
        prepared = _prepared(html)
        assert '<a href="https://test.dev">the docs</a>' in prepared

    def test_anchors_in_navigation_lists_are_untouched(self):
        html = _wrap('<nav><ul><li><a href="/home">Home</a></li></ul></nav>')
        prepared = _prepared(html)
        assert '<a href="/home">Home</a>' in prepared

    def test_anchors_in_content_list_items_are_flattened(self):
        html = _wrap('<ul><li><a href="https://test.dev">Planner</a> writes intent.</li></ul>')
        prepared = _prepared(html)
        assert "[Planner](https://test.dev)" in prepared


class TestInlineFormatting:
    def test_inter_element_spacing_is_preserved(self):
        html = _wrap(
            "<p>Uses <strong>fast</strong> <em>slow</em> "
            '<a href="https://t.dev">policy</a> here.</p>'
        )
        assert "Uses **fast** *slow* [policy](https://t.dev) here." in _extract(html)

    def test_a_pre_block_becomes_a_fence_not_inline_code(self):
        """A code block is a block. Collapsing it to inline code was the defect."""
        html = _wrap("<pre><code>value = compute(1)</code></pre>")
        extracted = _extract(html)
        assert "```" in extracted
        assert "value = compute(1)" in extracted


class TestUncapturedVisualDetection:
    PROSE = "word " * 300  # comfortably above the article-length floor

    def _detect(self, html: str, markdown: str) -> list[str]:
        extractor = ArticleExtractor()
        return extractor._detect_uncaptured_visuals(html, markdown, len(markdown.split()))

    def test_js_app_with_prose_but_no_images_warns(self):
        html = "<html><body><script>self.__next_f.push([])</script></body></html>"
        assert self._detect(html, self.PROSE)

    def test_dehydrated_streaming_app_warns(self):
        html = "<html><body>...dehydratedQueryClient...stream-barrier...</body></html>"
        assert self._detect(html, self.PROSE)

    def test_static_text_only_article_does_not_warn(self):
        html = "<html><body><article><p>plain server-rendered prose</p></article></body></html>"
        assert self._detect(html, self.PROSE) == []

    def test_js_app_that_yielded_an_image_does_not_warn(self):
        html = "<html><body><script>self.__next_f.push([])</script></body></html>"
        md = self.PROSE + "\n\n![](__LUMINARY_IMG__/doc/a.png)"
        assert self._detect(html, md) == []

    def test_short_page_does_not_warn(self):
        html = "<html><body><script>self.__next_f.push([])</script></body></html>"
        assert self._detect(html, "too short to be an article") == []


class TestBestSrcsetUrl:
    @pytest.mark.parametrize(
        ("srcset", "expected"),
        [
            ("https://cdn.test/a.png 640w, https://cdn.test/b.png 1400w", "https://cdn.test/b.png"),
            ("https://cdn.test/only.png", "https://cdn.test/only.png"),
            ("https://cdn.test/a.png bad, https://cdn.test/b.png 800w", "https://cdn.test/b.png"),
            ("", None),
            (None, None),
        ],
    )
    def test_picks_highest_width(self, srcset, expected):
        assert ArticleExtractor._best_srcset_url(srcset) == expected


class TestImportFidelity:
    """Each case below was a measured, silent loss before these passes existed.

    trafilatura is a boilerplate remover, not a fidelity-preserving converter: it
    normalises the text it keeps. Everything here is content a technical article
    carries its meaning in, so losing it quietly is worse than failing loudly.
    """

    def test_code_keeps_its_indentation(self):
        """Python without indentation is not ugly, it is a different program."""
        html = _wrap(
            '<pre><code class="language-python">class Value:\n'
            "    def __init__(self, data):\n"
            "        self.data = data\n"
            "</code></pre>"
        )
        extracted = _extract(html)
        assert "    def __init__(self, data):" in extracted
        assert "        self.data = data" in extracted

    def test_code_carries_its_language(self):
        html = _wrap('<pre><code class="language-python">x = 1</code></pre>')
        assert "```python" in _extract(html)

    def test_inline_math_keeps_the_sentence_around_it(self):
        """The formula mattered; the words after it mattered more.

        A rendered KaTeX span used to take the rest of its text node with it, so
        `Loss <math> here.` extracted as `Loss`.
        """
        html = _wrap(
            '<p>Loss <span class="katex"><span class="katex-mathml"><math><semantics>'
            '<annotation encoding="application/x-tex">L=\\sum_i y_i</annotation>'
            "</semantics></math></span></span> here.</p>"
        )
        extracted = _extract(html)
        assert "$L=\\sum_i y_i$" in extracted
        assert "here." in extracted

    def test_figure_caption_survives(self):
        html = _wrap(
            '<figure><img src="/d.png" alt="Arch">'
            "<figcaption>Figure 1: The pipeline</figcaption></figure>"
        )
        extracted = _extract(html)
        assert "Figure 1: The pipeline" in extracted
        assert "![Arch](/d.png)" in extracted

    def test_inline_svg_diagram_is_mirrored_and_referenced(self, tmp_path, monkeypatch):
        """An inline <svg> used to extract as nothing at all -- no graphic, no mark."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from app.config import get_settings

        get_settings.cache_clear()
        svg = '<svg width="600" height="400" aria-label="Architecture">' + (
            '<rect x="1" y="2" width="30" height="40"/>' * 20
        ) + "</svg>"
        extracted = _extract(_wrap(f"<figure>{svg}<figcaption>Figure 2</figcaption></figure>"))
        get_settings.cache_clear()
        assert "__LUMINARY_IMG__/testdoc/" in extracted
        assert ".svg)" in extracted
        assert "Figure 2" in extracted
        assert list((tmp_path / "images" / "testdoc").glob("*.svg"))

    def test_a_large_svg_in_page_furniture_is_still_chrome(self, tmp_path, monkeypatch):
        """Position decides, not size. This is the case that set the rule.

        On a real article the site logo inside <a> is 2,425 characters and a nav
        button icon 631, so a size floor alone reported nine pieces of chrome as
        lost diagrams -- a warning that cries wolf is worse than none.
        """
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from app.config import get_settings

        get_settings.cache_clear()
        big = '<svg width="40" height="40">' + ('<path d="M0 0L1 1"/>' * 120) + "</svg>"
        html = _wrap(f'<footer><ul><li><a href="/x">{big}</a></li></ul></footer>')
        extracted = _extract(html)
        get_settings.cache_clear()
        assert len(big) > 400, "the guard must be tested above the size floor"
        assert "__LUMINARY_IMG__" not in extracted
        assert not (tmp_path / "images" / "testdoc").exists()

    def test_a_small_svg_icon_is_left_as_chrome(self, tmp_path, monkeypatch):
        """The other bracket: a glyph in prose is below the size floor."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        from app.config import get_settings

        get_settings.cache_clear()
        html = _wrap('<p>Next <svg width="8" height="8"><path d="M0 0"/></svg> item.</p>')
        extracted = _extract(html)
        get_settings.cache_clear()
        assert "__LUMINARY_IMG__" not in extracted
        assert not (tmp_path / "images" / "testdoc").exists()

    def test_tables_still_survive(self):
        """Guarding what already worked, so a future pass cannot quietly break it."""
        html = _wrap(
            "<table><thead><tr><th>Model</th><th>Score</th></tr></thead>"
            "<tbody><tr><td>A</td><td>0.91</td></tr></tbody></table>"
        )
        extracted = _extract(html)
        assert "| Model | Score |" in extracted
        assert "| A | 0.91 |" in extracted


class TestExtractionReport:
    """The report is a measurement, and a measurement that cannot be wrong is not one.

    The first version of `_extraction_report` ran after restoration, when every
    token has already been replaced by its content -- so it found no tokens and
    called a perfectly clean import a total loss. Both directions are pinned here.
    """

    def test_a_clean_import_reports_nothing_dropped(self):
        extractor = ArticleExtractor()
        markdown = "Prose LUMINARYPROTECTEDBLOCK0000ENDPROTECTED more prose."
        protected = {"LUMINARYPROTECTEDBLOCK0000ENDPROTECTED": "```py\nx = 1\n```"}
        dropped = extractor._dropped_blocks(markdown, protected)
        report = extractor._extraction_report(markdown, dropped, [])
        assert report["dropped"] == {}
        assert report["complete"] is True

    def test_a_token_that_never_arrived_is_reported(self):
        extractor = ArticleExtractor()
        markdown = "Prose with no tokens at all."
        protected = {
            "LUMINARYPROTECTEDBLOCK0000ENDPROTECTED": "```py\nx = 1\n```",
            "LUMINARYPROTECTEDBLOCK0001ENDPROTECTED": "![Diagram](__LUMINARY_IMG__/d/a.svg)",
        }
        dropped = extractor._dropped_blocks(markdown, protected)
        report = extractor._extraction_report(markdown, dropped, [])
        assert report["dropped"] == {"code block": 1, "diagram": 1}
        assert report["complete"] is False

    def test_notes_alone_make_an_import_incomplete(self):
        extractor = ArticleExtractor()
        report = extractor._extraction_report("Prose.", [], ["figures drawn by JavaScript"])
        assert report["dropped"] == {}
        assert report["complete"] is False


class TestVisualWarningScope:
    """The "figures may be missing" note reasons about the static path only."""

    def _extractor(self):
        from app.services.article_extractor import ArticleExtractor

        return ArticleExtractor()

    def test_a_static_js_page_with_no_images_is_still_warned_about(self):
        """The original inference: scripts never ran, so figures may be absent."""
        html = '<html><body><script>self.__next_f=[]</script><p>x</p></body></html>'
        warnings = self._extractor()._detect_uncaptured_visuals(
            html, "prose only", 500, "static"
        )
        assert warnings, "a static hydrated page with no images must still warn"

    def test_a_rendered_page_with_no_canvas_is_not_warned_about(self):
        """After rendering, "no images" means the page has none.

        Inferring anyway told a reader content was missing from a chapter of
        prose and code that had no figures at all, and a warning that fires when
        nothing is wrong is one the reader learns to scroll past.
        """
        html = '<html><body><script>self.__next_f=[]</script><p>x</p></body></html>'
        warnings = self._extractor()._detect_uncaptured_visuals(
            html, "prose only", 500, "webview"
        )
        assert warnings == []

    def test_a_rendered_page_with_a_canvas_is_warned_about(self):
        """Brackets the rule: canvas pixels need a screenshot, not a DOM capture."""
        html = "<html><body><canvas id='chart'></canvas><p>x</p></body></html>"
        warnings = self._extractor()._detect_uncaptured_visuals(
            html, "prose only", 500, "webview"
        )
        assert warnings, "a rendered canvas is a real, uncapturable figure"


class TestPageSpecificTitle:
    """A site that gives every page one og:title makes a library of identical rows."""

    def _refine(self, title, html):
        from app.services.article_extractor import _title_specific_to_this_page

        return _title_specific_to_this_page(title, html)

    def test_a_site_name_as_metadata_title_is_replaced_by_the_page_title(self):
        html = (
            "<html><head><title>Chapter 4: Databases &#x2014; Where Data Lives "
            "&#x2014; The Builder&#x27;s Gita</title></head><body></body></html>"
        )
        assert (
            self._refine("The Builder's Gita", html)
            == "Chapter 4: Databases — Where Data Lives"
        )

    def test_a_correct_metadata_title_is_left_alone(self):
        """The bracketing case: here the metadata is a prefix, not a suffix.

        Taking the remainder would rename a correct title to the site's name.
        """
        html = "<html><head><title>Attention? Attention! | Lil&#39;Log</title></head></html>"
        assert self._refine("Attention? Attention!", html) == "Attention? Attention!"

    def test_a_title_matching_the_metadata_exactly_is_left_alone(self):
        html = "<html><head><title>Understanding LSTM Networks</title></head></html>"
        assert self._refine("Understanding LSTM Networks", html) == "Understanding LSTM Networks"

    def test_a_remainder_too_short_to_be_a_title_is_refused(self):
        """"Ch 4" is a fragment, and the metadata title is the safer answer."""
        html = "<html><head><title>Ch 4 - The Builder&#x27;s Gita</title></head></html>"
        assert self._refine("The Builder's Gita", html) == "The Builder's Gita"

    def test_a_page_with_no_title_tag_keeps_its_metadata(self):
        assert self._refine("Some Article", "<html><body>x</body></html>") == "Some Article"
