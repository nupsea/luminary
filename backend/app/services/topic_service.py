"""topic_service -- turn a document into a clean list of study TOPICS.

Topics come from the document's authored structure (SectionModel headings), NOT from concept
clustering. Two paths:
  - clean docs: the top-level headings, with front/back-matter + metadata filtered out
    (index, contents, copyright, ISBN, publisher, newsletter, blank headings, ...).
  - messy docs (heading detection over/under-fired): an LLM outline grounded in the doc's
    headings + opening text.

Honest by design: a topic must be real study content, never an INDEX page or publisher boilerplate.
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocumentModel, SectionModel
from app.services.llm import get_llm_service

logger = logging.getLogger(__name__)

# front/back-matter + metadata headings that are navigation/boilerplate, never study topics
_EXACT_JUNK = frozenset(
    {
        "index", "contents", "table of contents", "copyright", "copyright page",
        "dedication", "acknowledgments", "acknowledgements", "about the author",
        "about the authors", "about the publisher", "about this book", "bibliography",
        "references", "glossary", "colophon", "title page", "imprint", "credits",
        "list of figures", "list of tables", "list of illustrations", "frontmatter",
        "front matter", "back matter", "endnotes", "footnotes", "permissions",
    }
)
# substrings that mark boilerplate wherever they appear
_CONTAINS_JUNK = (
    "copyright", "all rights reserved", "isbn", "newsletter", "subscribe",
    "©", "oreilly.com", "o'reilly media", "first edition", "printed in",
)

# a "good" topic level has chapter-like granularity; fewer is too coarse (DDIA's 3 Parts),
# more is over-detected noise. If no level qualifies, we outline instead.
_GOOD_MIN = 5
_GOOD_MAX = 40
_SMALL_DOC = 12  # for a small doc, its few top headings ARE its chapters


def _norm(heading: str) -> str:
    h = re.sub(r"[^a-z0-9 ]", " ", (heading or "").lower())
    return re.sub(r"\s+", " ", h).strip()


def _clean_title(heading: str) -> str:
    """Strip markdown markers + a trailing colon + collapse whitespace for display."""
    t = re.sub(r"\s+", " ", re.sub(r"^#+\s*", "", (heading or "").strip())).strip()
    return t.rstrip(":; ").strip() or t


# a real topic title is a few words: not a bare list-marker, not a whole paragraph
_MAX_TOPIC_WORDS = 14


# explicit chapter markers -- a clean book labels its chapters even when the level field is flat
_CHAPTER_RE = re.compile(r"^(chapter|ch|part|lesson|module|unit)\s+(\d+|[ivxlcdm]+)\b", re.I)


def _chapter_sections(content: list) -> list | None:
    """The 'Chapter N' / 'Part N' headings, when a clean book buries them in a flattened level
    (DDIA: 12 'Chapter N.' headings among 200 level-2 subsections). Deterministic -- no LLM. Prefers
    chapters over parts (parts are groupings)."""
    matches = [s for s in content if _CHAPTER_RE.match(_clean_title(s.heading))]
    if len(matches) < 5:
        return None
    non_part = [s for s in matches if not re.match(r"^part\b", _clean_title(s.heading), re.I)]
    pick = non_part if len(non_part) >= 5 else matches
    return pick if 5 <= len(pick) <= 60 else None


def _pick_topic_sections(content: list) -> list | None:
    """Pick the level that IS the topic list, judged by STRUCTURE not raw count:

    - Single substantive content level -> that level is the topics, whatever the count: a flat
      book of 211 small topics (SysDesign), 36 chapters (Gita), or 10 (Attention) are all valid.
    - Explicit "Chapter N" headings -> the chapters are the topics, even when buried in a flattened
      level (DDIA). Deterministic, no LLM.
    - Genuinely hierarchical (>=2 substantive levels) -> prefer a chapter-like level (5-40).
    - Tiny doc -> its few top headings. Only a truly structureless doc falls through to the outline.
    """
    by_level: dict[int, list] = {}
    for s in content:
        by_level.setdefault(s.level, []).append(s)

    # explicit "Chapter N" headings win first -- a clean book buries its chapters in a flattened
    # level among subsections (DDIA); pull just the chapters, deterministically, no LLM.
    chapters = _chapter_sections(content)
    if chapters:
        return chapters

    substantive = [lvl for lvl, ss in by_level.items() if len(ss) >= 2]
    if len(substantive) == 1:
        flat = by_level[substantive[0]]
        if len(flat) >= 3:
            return flat

    for level in sorted(by_level):
        if _GOOD_MIN <= len(by_level[level]) <= _GOOD_MAX:
            return by_level[level]

    shallow = min(by_level)
    if len(by_level[shallow]) >= 3 and len(content) <= _SMALL_DOC:
        return by_level[shallow]
    return None


def is_junk_heading(heading: str) -> bool:
    """True for blank/boilerplate/metadata headings that must never become a study topic."""
    raw = (heading or "").strip()
    if not raw or not any(c.isalnum() for c in raw):
        return True
    n = _norm(heading)
    if not n or n in _EXACT_JUNK:
        return True
    # bare list-markers ("1", "18", single letter) -- numbering, not a topic
    if re.fullmatch(r"\d{1,3}|[a-z]", n):
        return True
    # a paragraph misdetected as a heading (an intro sentence) -- too long to be a topic title
    if len(n.split()) > _MAX_TOPIC_WORDS:
        return True
    return any(sub in n for sub in _CONTAINS_JUNK)


class TopicService:
    async def document_topics(self, session: AsyncSession, document_id: str) -> dict | None:
        doc = await session.get(DocumentModel, document_id)
        if doc is None:
            return None

        sections = list(
            (
                await session.execute(
                    select(SectionModel)
                    .where(SectionModel.document_id == document_id)
                    .order_by(SectionModel.section_order)
                )
            )
            .scalars()
            .all()
        )
        content = [s for s in sections if not is_junk_heading(s.heading)]
        tops = _pick_topic_sections(content) if content else None
        if tops:
            return {
                "document_id": document_id,
                "title": doc.title,
                "source": "sections",
                "topics": [
                    {
                        "title": _clean_title(s.heading),
                        "level": s.level,
                        "section_id": s.id,
                        "page_start": s.page_start,
                    }
                    for s in tops
                ],
            }

        # truly structureless doc (no chapters, no clean level) -> LLM outline from the headings
        outline = await self._llm_outline(session, doc, content or sections)
        return {
            "document_id": document_id,
            "title": doc.title,
            "source": "outline",
            "topics": outline,
        }

    async def document_sections(
        self, session: AsyncSession, document_id: str, *, q: str | None = None, limit: int = 200
    ) -> list[dict]:
        """All real sub-sections of a document (junk filtered, searchable) for drill-down study,
        e.g. search 'Hardware Faults' under DDIA's Chapter 1. Distinct from the chapter list."""
        rows = list(
            (
                await session.execute(
                    select(SectionModel)
                    .where(SectionModel.document_id == document_id)
                    .order_by(SectionModel.section_order)
                )
            )
            .scalars()
            .all()
        )
        needle = (q or "").strip().lower()
        out = []
        for s in rows:
            if is_junk_heading(s.heading):
                continue
            title = _clean_title(s.heading)
            if needle and needle not in title.lower():
                continue
            out.append(
                {
                    "title": title,
                    "level": s.level,
                    "section_id": s.id,
                    "page_start": s.page_start,
                }
            )
            if len(out) >= limit:
                break
        return out

    async def _llm_outline(
        self, session: AsyncSession, doc: DocumentModel, sections: list[SectionModel]
    ) -> list[dict]:
        headings = [
            _clean_title(s.heading) for s in sections if not is_junk_heading(s.heading)
        ]
        # span the WHOLE document so later chapters aren't cut off (DDIA's ch.6-12 live past the
        # first 80 headings). Even-sample only if there are too many to fit context.
        cap = 250
        if len(headings) > cap:
            step = len(headings) / cap
            headings = [headings[int(i * step)] for i in range(cap)]
        context = "All headings, first to last:\n" + "\n".join(headings)
        system = (
            "You outline a document's main study TOPICS / chapters from its complete heading list. "
            "Cover the ENTIRE document, first heading to last (a book usually has 8-15 chapters); "
            "list ALL of them in reading order, do NOT stop after the first few. Collapse "
            "fine-grained sub-headings under their parent chapter. Use ONLY real subject-matter "
            "content; NEVER include index, table of contents, copyright, dedication, "
            "acknowledgements, about-the-author, preface, bibliography, or publisher boilerplate. "
            'Return ONLY JSON: {"topics": ["...", "..."]}.'
        )
        try:
            raw = await get_llm_service().complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Document: {doc.title}\n\n{context}"},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
                background=True,
            )
            data = json.loads(re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", raw.strip()))
            items = data.get("topics") if isinstance(data, dict) else None
            out = []
            for t in (items or [])[:20]:
                title = (t if isinstance(t, str) else t.get("title", "")).strip()
                if title and not is_junk_heading(title):
                    out.append(
                        {"title": title, "level": 1, "section_id": None, "page_start": None}
                    )
            return out
        except Exception:
            logger.warning("LLM outline failed for doc %s", doc.id, exc_info=True)
            return []


_service: TopicService | None = None


def get_topic_service() -> TopicService:
    global _service
    if _service is None:
        _service = TopicService()
    return _service
