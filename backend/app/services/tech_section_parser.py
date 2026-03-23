"""Pure functions for tech section detection: admonitions, numbered hierarchy.

All functions are stateless (no I/O, no DB access) and can be unit-tested
without any fixtures.  Orchestration lives in _chunk_tech_book (ingestion.py).
"""

import re

# ---------------------------------------------------------------------------
# Admonition detection
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Numbered hierarchy classification
# ---------------------------------------------------------------------------

_RE_PART = re.compile(r"^Part\s+[IVXLCDM\d]+\b", re.I)
_RE_CHAPTER = re.compile(r"^Chapter\s+\d+\b", re.I)
_RE_SECTION_NMP = re.compile(r"^\d+\.\d+\.\d+\s")   # "1.1.1 Detail"
_RE_SECTION_NM = re.compile(r"^\d+\.\d+\s")          # "1.1 Overview"
_RE_SECTION_N = re.compile(r"^\d+\.\s")              # "1. Introduction"


def classify_section_level(heading: str) -> int:
    """Return 1=Part, 2=Chapter, 3=Section (N.M), 4=Subsection (N.M.P).

    Defaults to level 2 (chapter) if none of the patterns match.
    """
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
    return 2


def assign_parent_headings_dicts(sections: list[dict]) -> list[dict]:
    """Enrich section dicts with 'level' and 'parent_heading' based on hierarchy.

    Modifies each dict in-place (also returns the list for convenience).

    Rules:
    - level=1 (Part): no parent
    - level=2 (Chapter or N.): parent is the most recent level=1 section
    - level=3 (N.M section): parent is the most recent level=2 section
    - level=4 (N.M.P subsection): parent is the most recent level=3 section
    If no ancestor exists at the required level, parent_heading stays None.
    """
    # Track most recent heading seen at each level
    level_stack: dict[int, str | None] = {1: None, 2: None, 3: None, 4: None}

    for s in sections:
        heading = s.get("heading", "")
        level = classify_section_level(heading)
        s["level"] = level

        # Determine parent: look one level up
        parent_level = level - 1
        parent_heading = level_stack.get(parent_level) if parent_level >= 1 else None
        s["parent_heading"] = parent_heading

        # Update the stack at this level; invalidate deeper levels
        level_stack[level] = heading
        for deeper in range(level + 1, 5):
            level_stack[deeper] = None

    return sections


# ---------------------------------------------------------------------------
# Learning objective candidate detection
# ---------------------------------------------------------------------------

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
