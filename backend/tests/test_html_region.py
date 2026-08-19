"""Content-region selection: which subtree of a page is the article."""

from app.services.html_region import region_is_plausible, select_region

# Comfortably over the region floor: a fixture below it exercises the fallback,
# not the selection rule under test.
PROSE = "<p>" + ("Real article prose that reads like a written paragraph. " * 20) + "</p>"


def _page(body: str) -> str:
    return f"<html><body>{body}</body></html>"


class TestRegionSelection:
    def test_article_is_preferred_over_body(self):
        region = select_region(_page(f"<div>chrome text</div><article>{PROSE}</article>"))
        assert region.name == "article"

    def test_furniture_tags_are_removed(self):
        region = select_region(
            _page(
                f"<article><nav>Home About</nav>{PROSE}"
                "<footer>All rights reserved</footer></article>"
            )
        )
        text = region.get_text()
        assert "Home About" not in text
        assert "All rights reserved" not in text

    def test_furniture_class_names_are_removed(self):
        region = select_region(
            _page(f'<article>{PROSE}<div class="post-share-buttons">Share this</div></article>')
        )
        assert "Share this" not in region.get_text()

    def test_the_largest_article_wins(self):
        """Teaser cards are <article> too; size is what separates them."""
        small = "<article><p>Teaser blurb.</p></article>"
        big = f"<article>{PROSE}</article>"
        region = select_region(_page(small + big))
        assert "Real article prose" in region.get_text()
        assert "Teaser blurb." not in region.get_text()

    def test_a_thin_container_falls_back_to_the_page(self):
        """Bracketing the floor: a 3-word <main> is a mis-pick, not an article."""
        region = select_region(_page(f"<main><p>Just a heading area.</p></main><div>{PROSE}</div>"))
        assert "Real article prose" in region.get_text()

    def test_a_furniture_hint_on_the_region_itself_does_not_delete_it(self):
        """`<article class="post-header-wrapper">` must not erase the article."""
        region = select_region(_page(f'<article class="page-header-main">{PROSE}</article>'))
        assert "Real article prose" in region.get_text()


class TestInteractiveFurniture:
    """Widgets that live *inside* the article, where tag stripping cannot reach."""

    def test_an_interactive_figures_controls_are_not_prose(self):
        """An explorable explainer read its own sliders out as sentences.

        The panel sits inside the article, so `<button>` stripping removes the
        play control and leaves "Points Per Side 20 Perplexity 10" behind as
        body text.
        """
        widget = (
            '<div id="demo-controls">'
            '<div id="steps-display">Step<span>1</span></div>'
            '<span class="slider-label-Points">Points Per Side</span>'
            '<span class="slider-value-Points">20</span>'
            "</div>"
        )
        region = select_region(_page(f"<article>{widget}{PROSE}</article>"))
        text = region.get_text()
        assert "Real article prose" in text
        for control in ("Points Per Side", "20", "Step"):
            assert control not in text

    def test_a_byline_block_is_not_prose(self):
        """Custom-element pages wrap the byline in a plain div inside a tag no
        tag list can anticipate, so the class is the only handle."""
        byline = (
            "<dt-byline><div class=\"byline\">"
            '<div class="author"><a class="name">A Writer</a>'
            '<a class="affiliation">Some Lab</a></div>'
            '<div class="date">Oct. 13</div>'
            "</div></dt-byline>"
        )
        region = select_region(_page(f"<article>{byline}{PROSE}</article>"))
        text = region.get_text()
        assert "Real article prose" in text
        for meta in ("A Writer", "Some Lab", "Oct. 13"):
            assert meta not in text

    def test_prose_that_merely_mentions_a_control_survives(self):
        """The rule reads class and id, never the words on the page."""
        region = select_region(
            _page(f"<article><p>The slider controls the perplexity.</p>{PROSE}</article>")
        )
        assert "The slider controls the perplexity." in region.get_text()


class TestPlausibility:
    def test_a_region_matching_the_reference_is_trusted(self):
        region = select_region(_page(f"<article>{PROSE}</article>"))
        assert region_is_plausible(region, region.get_text())

    def test_a_region_far_short_of_the_reference_is_rejected(self):
        """Four well-structured articles are not evidence about a messy one."""
        region = select_region(_page(f"<article>{PROSE}</article>"))
        assert not region_is_plausible(region, "word " * 5000)

    def test_no_region_is_never_plausible(self):
        assert not region_is_plausible(None, "anything")
