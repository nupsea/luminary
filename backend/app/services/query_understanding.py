"""Extract structured retrieval filters (content-type, date range) from a query.

"Generate a story from my daily thoughts notes this month" ->
    content_types = ["notes"], date_from = 2026-07-01, date_to = 2026-07-31
so retrieval can route to the right kind of document and the right time window
instead of running semantic search over the raw phrase. Local-first: pure
regex/keyword rules, no LLM call. Dates resolve relative to `now`.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})

# query keyword -> corpus content_type string(s)
_CONTENT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "notes": ["notes", "note", "thought", "thoughts", "journal", "diary", "jottings"],
    "conversation": ["transcript", "meeting", "conversation", "standup", "sync", "call log"],
    "book": ["book", "novel", "chapter"],
    "paper": ["paper", "papers"],
    "tech_article": ["article", "articles", "blog post"],
    "audio": ["podcast", "audio", "recording", "lecture", "talk"],
    "code": ["source code", "codebase", "the code"],
}

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_MONTH_WORD = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b", re.I)
_PAST_N = re.compile(r"\b(?:past|last|previous)\s+(\d+)\s+(day|week|month|year)s?\b", re.I)


@dataclass
class QueryFilters:
    content_types: list[str] = field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    matched: list[str] = field(default_factory=list)

    @property
    def has_filter(self) -> bool:
        return bool(self.content_types) or self.date_from is not None or self.date_to is not None


def _month_range(y: int, m: int) -> tuple[date, date]:
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _week_range(d: date) -> tuple[date, date]:
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def _resolve_dates(q: str, now: date) -> tuple[date | None, date | None, str | None]:
    ql = q.lower()
    if "yesterday" in ql:
        d = now - timedelta(days=1)
        return d, d, "yesterday"
    if "today" in ql:
        return now, now, "today"
    if "this week" in ql:
        return (*_week_range(now), "this week")
    if "last week" in ql:
        return (*_week_range(now - timedelta(days=7)), "last week")
    if "this month" in ql:
        return (*_month_range(now.year, now.month), "this month")
    if "last month" in ql:
        pm = date(now.year, now.month, 1) - timedelta(days=1)
        return (*_month_range(pm.year, pm.month), "last month")
    if "this year" in ql:
        return date(now.year, 1, 1), date(now.year, 12, 31), "this year"
    if "last year" in ql:
        return date(now.year - 1, 1, 1), date(now.year - 1, 12, 31), "last year"
    m = _PAST_N.search(ql)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"day": timedelta(days=n), "week": timedelta(weeks=n),
                 "month": timedelta(days=30 * n), "year": timedelta(days=365 * n)}[unit]
        return now - delta, now, m.group(0)
    # "<month> <year>" or bare "<month>" (this year) or bare "<year>"
    mw = _MONTH_WORD.search(ql)
    yr = _YEAR.search(ql)
    if mw:
        mnum = _MONTHS[mw.group(1).lower()]
        year = int(yr.group(0)) if yr else now.year
        return (*_month_range(year, mnum), mw.group(0))
    if yr:
        y = int(yr.group(0))
        return date(y, 1, 1), date(y, 12, 31), yr.group(0)
    return None, None, None


def parse_query_filters(query: str, now: date | None = None) -> QueryFilters:
    now = now or datetime.now().date()
    f = QueryFilters()
    ql = query.lower()
    for ctype, kws in _CONTENT_TYPE_KEYWORDS.items():
        for kw in kws:
            if re.search(rf"\b{re.escape(kw)}\b", ql):
                f.content_types.append(ctype)
                f.matched.append(kw)
                break
    df, dt, phrase = _resolve_dates(query, now)
    f.date_from, f.date_to = df, dt
    if phrase:
        f.matched.append(phrase)
    return f
