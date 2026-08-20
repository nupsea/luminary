"""The Markdown serialiser. Every rule here comes from a measured failure.

Structure is what a boilerplate remover loses: on a custom-element page its pruned
tree carried zero headings, so the article extracted as one unbroken wall. These
tests pin the shape of the output that replaced it.
"""

from bs4 import BeautifulSoup

from app.services.html_to_markdown import to_markdown


def _md(html: str) -> str:
    return to_markdown(BeautifulSoup(f"<div>{html}</div>", "html.parser").div)


class TestHeadings:
    def test_levels_are_preserved(self):
        out = _md("<h1>One</h1><h2>Two</h2><h3>Three</h3>")
        assert "# One" in out
        assert "## Two" in out
        assert "### Three" in out

    def test_anchor_affordances_are_stripped(self):
        """Measured: all 21 headings of one article carried a deep-link anchor.

        `## Title[#](https://…)` is junk in a reading view, and the anchor is a
        navigation affordance rather than something the author wrote.
        """
        out = _md('<h2>Born for Translation<a href="#born">#</a></h2>')
        assert "## Born for Translation" in out
        assert "[#]" not in out

    def test_a_heading_keeps_a_real_link_inside_it(self):
        """The other bracket: only anchor-ONLY links go."""
        out = _md('<h2>See <a href="https://t.dev">the paper</a></h2>')
        assert "[the paper](https://t.dev)" in out


class TestInlineSpacing:
    def test_space_between_text_and_element_survives(self):
        """`is a <a>X</a> (or other` must not collapse to `is a[X](url)(or other`.

        Trimming each inline child independently destroys the only separator
        between the words. This shipped once and made every article read wrong.
        """
        out = _md(
            '<p>The encoder is a <a href="https://t.dev">bidirectional RNN</a> (or other).</p>'
        )
        assert "is a [bidirectional RNN](https://t.dev) (or other)" in out

    def test_emphasis_keeps_its_neighbours_apart(self):
        out = _md("<p>The <strong>seq2seq</strong> model was born.</p>")
        assert "The **seq2seq** model was born." in out


class TestLists:
    def test_ordered_and_unordered(self):
        out = _md("<ul><li>alpha</li><li>beta</li></ul><ol><li>first</li><li>second</li></ol>")
        assert "- alpha" in out and "- beta" in out
        assert "1. first" in out and "2. second" in out

    def test_nested_lists_are_indented(self):
        out = _md("<ul><li>outer<ul><li>inner</li></ul></li></ul>")
        assert "- outer" in out
        assert "  - inner" in out


class TestBlocks:
    def test_table_becomes_a_markdown_table(self):
        out = _md(
            "<table><tr><th>Model</th><th>Score</th></tr>"
            "<tr><td>A</td><td>0.91</td></tr></table>"
        )
        assert "| Model | Score |" in out
        assert "| A | 0.91 |" in out

    def test_blockquote_is_marked(self):
        out = _md("<blockquote><p>A quoted claim.</p></blockquote>")
        assert "> A quoted claim." in out

    def test_figure_keeps_image_and_caption(self):
        out = _md(
            '<figure><img src="/d.png" alt="Arch">'
            "<figcaption>Figure 1: pipeline</figcaption></figure>"
        )
        assert "![Arch](/d.png)" in out
        assert "Figure 1: pipeline" in out

    def test_details_content_is_not_swallowed(self):
        """A collapsed section is still the author's content."""
        out = _md("<details><summary>Show proof</summary><p>The proof body.</p></details>")
        assert "**Show proof**" in out
        assert "The proof body." in out

    def test_pre_keeps_its_lines(self):
        out = _md("<pre>line one\n    line two</pre>")
        assert "```" in out
        assert "    line two" in out

    def test_script_and_style_never_reach_the_reader(self):
        out = _md("<p>Real text.</p><script>var x=1</script><style>.a{color:red}</style>")
        assert "Real text." in out
        assert "var x" not in out and "color:red" not in out

    def test_a_heading_marked_as_a_caption_labels_a_figure_not_a_section(self):
        """13 of one article's 17 headings were the word "Original".

        Each was the label under a comparison image, and each became a section
        in the contents beside the real chapters. The text is content and is
        kept; only its promotion to a heading is wrong.
        """
        out = _md('<h3 class="caption">Original</h3><p>Body text.</p>')
        assert "Original" in out
        assert "### Original" not in out
        assert "Body text." in out

    def test_an_ordinary_heading_is_still_a_heading(self):
        """Brackets the rule above: only a caption class demotes a heading."""
        out = _md("<h3>Real Section</h3><p>Body text.</p>")
        assert "### Real Section" in out

    def test_a_heading_linked_to_its_own_id_keeps_only_its_text(self):
        """The anchor every docs generator emits is not a reference.

        Left as a link the heading reads "[Why Databases Exist](#why-databases-
        exist)" -- markdown syntax printed in the contents, and long enough to
        push a real heading past the length that decides whether it is treated
        as a heading at all.
        """
        out = _md('<h2 id="x"><a class="anchor" href="#x">Why Databases Exist</a></h2>')
        assert "## Why Databases Exist" in out
        assert "](#x)" not in out

    def test_a_heading_citing_another_page_keeps_its_link(self):
        """Brackets the rule above: only same-page fragments are affordances."""
        out = _md('<h2>See <a href="/chapter/ch-05">the next chapter</a></h2>')
        assert "[the next chapter](/chapter/ch-05)" in out
