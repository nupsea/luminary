"""A web page's title and its `<main>`, as HTML a bundle section can hold.

For a page whose content sits in `<main>`. A site that needs more (chrome inside the content, a
contents list) parses its own pages, as the html-book connector does.
"""

from __future__ import annotations

from html.parser import HTMLParser

_VOID = frozenset({"area", "br", "col", "embed", "hr", "img", "input", "source", "track", "wbr"})


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.title = ""
        self.main: list[str] = []
        self._in_title = False
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        self._in_title = tag == "title"
        if self._depth and tag in _VOID:
            self.main.append(self.get_starttag_text() or "")
        elif tag == "main" or self._depth:
            self._depth += 1
            if self._depth > 1:
                self.main.append(self.get_starttag_text() or "")

    def handle_startendtag(self, tag, attrs):
        if self._depth:
            self.main.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag):
        self._in_title = False
        if self._depth:
            self._depth -= 1
            if self._depth:
                self.main.append(f"</{tag}>")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._depth:
            self.main.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def main_html(page: str) -> tuple[str, str]:
    """(the page's `<title>`, whitespace collapsed; the inside of its `<main>`). Either is ""
    when the page has none."""
    parser = _Page()
    parser.feed(page)
    return " ".join(parser.title.split()), "".join(parser.main)
