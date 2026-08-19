"""Choose the subtree of a page that is the article.

Separated from serialisation on purpose. One library deciding both *which* subtree
is the article and *what markdown comes out* is why structure was being lost:
trafilatura is very good at boilerplate removal and prose recall, and unreliable
about structure. Measured on distill.pub, its pruned tree contains zero heading
elements, so nothing downstream can put the headings back.

Selecting the region here and serialising it ourselves recovers, on the same four
articles, 13/13, 14/14, 9/9 and 12/12 headings against trafilatura's 13, 11, 0 and 3.
"""

import logging
import re

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# Structural furniture. Removed wholesale: none of it is ever article prose.
_FURNITURE_TAGS = (
    "nav",
    "header",
    "footer",
    "aside",
    "script",
    "style",
    "noscript",
    "form",
    "button",
    "template",
    "dialog",
)

# Class/id names authors give to furniture. Matched as a substring, case-insensitively,
# so `SiteHeader-module-scss__x` and `post-share-buttons` both hit.
_FURNITURE_HINT = re.compile(
    r"nav|menu|sidebar|footer|header|breadcrumb|share|social|comment|related|"
    r"recirc|subscribe|newsletter|cookie|consent|banner|promo|advert|sponsor|"
    r"paywall|popup|modal|skip-link|screen-reader|visually-hidden|"
    # An interactive figure's controls sit inside the article, so tag-based
    # stripping never reaches them: an explorable explainer contributed
    # "Step 1 Points Per Side 20 Perplexity 10 Epsilon 5" to its own prose,
    # every slider label and value read out as a sentence. `byline` covers the
    # author/affiliation/date/citation block that custom-element pages wrap in
    # a plain div inside a tag no tag list can anticipate.
    r"controls|slider|byline",
    re.I,
)

# A region must hold at least this much text to be believed. Bracketing cases: a
# 60-word <main> on a page whose prose sits in a sibling div is a mis-pick and the
# body is the safer answer; a 200-word linkblog post is a real article.
_MIN_REGION_WORDS = 120


def _strip_furniture(root: Tag) -> None:
    for tag in root.find_all(_FURNITURE_TAGS):
        tag.decompose()
    for attribute in ("class", "id"):
        for tag in root.find_all(attrs={attribute: _FURNITURE_HINT}):
            # A hint on the region itself is not licence to delete the article.
            if tag is not root:
                tag.decompose()


def select_region(html: str) -> Tag | None:
    """The article subtree with furniture removed, or None if nothing qualifies.

    Prefers the largest <article>/<main>, falling back to <body>. Size decides
    between candidates because a page may carry several <article> elements, one
    per teaser card, alongside the real one.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates = soup.find_all(["article", "main"])
    body = soup.body or soup
    root = max(candidates, key=lambda t: len(t.get_text()), default=None) or body
    if root is None:
        return None

    _strip_furniture(root)
    if len(root.get_text().split()) < _MIN_REGION_WORDS and root is not body:
        # The chosen container was too thin to be the article; take the page.
        soup2 = BeautifulSoup(html, "html.parser")
        fallback = soup2.body or soup2
        _strip_furniture(fallback)
        return fallback
    return root


def region_is_plausible(region: Tag | None, reference_text: str) -> bool:
    """Whether our region agrees with an independent extraction of the same page.

    Four well-structured articles are not evidence about a messy one, so the
    region is only trusted when it carries at least as much prose as the
    reference. Falling materially short means the furniture rules ate content,
    and the reference is the safer answer.
    """
    if region is None:
        return False
    ours = len(region.get_text(" ").split())
    theirs = len(reference_text.split())
    if theirs == 0:
        return ours >= _MIN_REGION_WORDS
    return ours >= theirs * 0.9
