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
