import pytest

trafilatura = pytest.importorskip("trafilatura")

from app.services.article_extractor import ArticleExtractor  # noqa: E402

PAD = "padding sentence for extractor density. " * 20


def _extract(html: str) -> str:
    extractor = ArticleExtractor()
    return trafilatura.extract(
        extractor._prepare_html(html),
        output_format="markdown",
        include_links=True,
        include_images=True,
        include_formatting=True,
    )


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
        prepared = ArticleExtractor()._prepare_html(html)
        assert '<a href="https://test.dev">the docs</a>' in prepared

    def test_anchors_in_navigation_lists_are_untouched(self):
        html = _wrap('<nav><ul><li><a href="/home">Home</a></li></ul></nav>')
        prepared = ArticleExtractor()._prepare_html(html)
        assert '<a href="/home">Home</a>' in prepared

    def test_anchors_in_content_list_items_are_flattened(self):
        html = _wrap('<ul><li><a href="https://test.dev">Planner</a> writes intent.</li></ul>')
        prepared = ArticleExtractor()._prepare_html(html)
        assert "[Planner](https://test.dev)" in prepared


class TestInlineFormatting:
    def test_inter_element_spacing_is_preserved(self):
        html = _wrap(
            "<p>Uses <strong>fast</strong> <em>slow</em> "
            '<a href="https://t.dev">policy</a> here.</p>'
        )
        assert "Uses **fast** *slow* [policy](https://t.dev) here." in _extract(html)

    def test_code_inside_pre_is_not_double_wrapped(self):
        html = _wrap("<pre><code>value = compute(1)</code></pre>")
        extracted = _extract(html)
        assert "`value = compute(1)`" in extracted
        assert "``" not in extracted


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
