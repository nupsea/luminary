"""Pure functions for tech section detection: admonitions, numbered hierarchy.

All functions are stateless (no I/O, no DB access) and can be unit-tested
without any fixtures.  Orchestration lives in _chunk_tech_book (ingestion.py).
"""

import re

# Admonition detection

_ADMONITION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^NOTE\s*:", re.M), "note"),
    (re.compile(r"^note\s*:", re.M), "note"),
    (re.compile(r"^WARNING\s*:", re.M), "warning"),
    (re.compile(r"^warning\s*:", re.M), "warning"),
    (re.compile(r"^TIP\s*:", re.M), "tip"),
    (re.compile(r"^tip\s*:", re.M), "tip"),
    (re.compile(r"^CAUTION\s*:", re.M), "caution"),
    (re.compile(r"^caution\s*:", re.M), "caution"),
    (re.compile(r"^IMPORTANT\s*:", re.M), "important"),
    (re.compile(r"^important\s*:", re.M), "important"),
    # GitHub-flavored Markdown blockquote admonitions: > **Note**, > **Warning**, etc.
    (re.compile(r"^>\s+\*\*(?:Note|NOTE)\*\*", re.M), "note"),
    (re.compile(r"^>\s+\*\*(?:Warning|WARNING)\*\*", re.M), "warning"),
    (re.compile(r"^>\s+\*\*(?:Tip|TIP)\*\*", re.M), "tip"),
    (re.compile(r"^>\s+\*\*(?:Caution|CAUTION)\*\*", re.M), "caution"),
    (re.compile(r"^>\s+\*\*(?:Important|IMPORTANT)\*\*", re.M), "important"),
]


def detect_admonition(text: str) -> str | None:
    """Return the admonition type if text begins with an admonition marker, else None.

    Checks only the first 500 characters to avoid false positives deeper in content.
    Returns one of 'note', 'warning', 'tip', 'caution', 'important', or None.
    """
    snippet = text[:500]
    for pattern, admonition_type in _ADMONITION_PATTERNS:
        if pattern.search(snippet):
            return admonition_type
    return None


# Numbered hierarchy classification

_RE_PART = re.compile(r"^Part\s+[IVXLCDM\d]+\b", re.I)
_RE_CHAPTER = re.compile(r"^Chapter\s+\d+\b", re.I)
_RE_SECTION_NMP = re.compile(r"^\d+\.\d+\.\d+\s")  # "1.1.1 Detail"
_RE_SECTION_NM = re.compile(r"^\d+\.\d+\s")  # "1.1 Overview"
_RE_SECTION_N = re.compile(r"^\d+\.\s")  # "1. Introduction"


def classify_section_level(heading: str) -> int | None:
    """Return 1=Part, 2=Chapter, 3=Section (N.M), 4=Subsection (N.M.P), None if unnumbered."""
    if _RE_PART.match(heading):
        return 1
    if _RE_CHAPTER.match(heading):
        return 2
    if _RE_SECTION_NMP.match(heading):
        return 4
    if _RE_SECTION_NM.match(heading):
        return 3
    if _RE_SECTION_N.match(heading):
        return 2
    return None


def assign_parent_headings_dicts(sections: list[dict]) -> list[dict]:
    """Set each section dict's 'level', 'parent_heading' and 'parent_index' in place.

    A numbered heading's mark decides its level; an unnumbered one keeps the level the
    parser read from the source (default 2). Overwriting that with 2 flattened every
    markdown book into one level, so its topics were all 241 headings (#307).
    The parent is the most recent section one level up, else None.
    """
    stack: dict[int, int] = {}  # level -> index of the most recent section at it

    for i, s in enumerate(sections):
        level = classify_section_level(s.get("heading", "")) or s.get("level") or 2
        s["level"] = level

        parent = stack.get(level - 1)
        s["parent_index"] = parent
        s["parent_heading"] = sections[parent].get("heading", "") if parent is not None else None

        stack[level] = i
        for deeper in [lv for lv in stack if lv > level]:
            del stack[deeper]

    return sections


# Learning objective candidate detection

_OBJECTIVE_PHRASES: list[str] = [
    "you will",
    "you will be able to",
    "after this chapter",
    "in this chapter we cover",
    "by the end of",
    "goals",
    "objectives",
    "learning objectives",
    "chapter goals",
    "what you will learn",
]


def is_objective_candidate(text: str) -> bool:
    """Return True if the first 300 chars of text match objective-section patterns."""
    snippet = text[:300].lower()
    return any(phrase in snippet for phrase in _OBJECTIVE_PHRASES)
