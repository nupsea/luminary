"""Tech relationship extractor: pattern-match co-occurrence + verb patterns.

Pure functions only — no I/O, no database reads.

Extracts directed (name_a, name_b, relation_label) triples from chunk texts.
Only emits a triple when BOTH names are present in *known_names* (confirmed
by GLiNER), preventing false edges from purely textual pattern matches.

Supported relation types:
    IMPLEMENTS   -- 'X implements Y', 'X implements the Y interface'
    EXTENDS      -- 'X extends Y', 'class X extends Y'
    USES         -- 'import X', 'from X import', 'X uses Y'
    DEPENDS_ON   -- 'X requires Y', 'X depends on Y'
    REPLACES     -- 'X replaces Y', 'X is a replacement for Y'
"""

import re

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_IMPLEMENTS_RE = re.compile(r"\b(\w[\w.\-]*)\s+implements\s+([\w.\-]+)", re.I)
_EXTENDS_RE = re.compile(r"\b(\w[\w.\-]*)\s+extends\s+([\w.\-]+)", re.I)
_USES_RE = re.compile(r"\b(\w[\w.\-]*)\s+uses\s+([\w.\-]+)", re.I)
_DEPENDS_RE = re.compile(
    r"\b(\w[\w.\-]*)\s+requires\s+([\w.\-]+)"
    r"|\b(\w[\w.\-]*)\s+depends\s+on\s+([\w.\-]+)",
    re.I,
)
_REPLACES_RE = re.compile(
    r"\b(\w[\w.\-]*)\s+replaces\s+([\w.\-]+)"
    r"|\b(\w[\w.\-]*)\s+is\s+a\s+replacement\s+for\s+([\w.\-]+)",
    re.I,
)

# 'import X' or 'from X import ...' — signals X is a library used by the document.
# When a second known entity appears in the same chunk, we emit X USED_BY that entity
# (reversed: that entity USES X).
_IMPORT_RE = re.compile(r"\bimport\s+([\w.\-]+)|\bfrom\s+([\w.\-]+)\s+import\b", re.I)


def _match_known(name: str, known: set[str]) -> str | None:
    """Return *name* if it is in *known* (case-insensitive match)."""
    lower = name.lower()
    if lower in known:
        return lower
    return None


def extract_tech_relations(
    chunks: list[dict],
    known_names: set[str],
) -> list[tuple[str, str, str]]:
    """Return (name_a, name_b, relation_label) triples from chunk texts.

    Args:
        chunks: Chunk dicts with at least a ``text`` field.
        known_names: Set of canonical entity names (lowercase) confirmed by GLiNER.
            Only triples where BOTH names are in this set are returned.

    Returns:
        Deduplicated list of (name_a, name_b, relation_label) triples.
        relation_label is one of: IMPLEMENTS, EXTENDS, USES, REPLACES, DEPENDS_ON.
    """
    triples: set[tuple[str, str, str]] = set()

    for chunk in chunks:
        text = chunk.get("text", "")
        if not text:
            continue

        # IMPLEMENTS
        for m in _IMPLEMENTS_RE.finditer(text):
            a = _match_known(m.group(1), known_names)
            b = _match_known(m.group(2), known_names)
            if a and b and a != b:
                triples.add((a, b, "IMPLEMENTS"))

        # EXTENDS
        for m in _EXTENDS_RE.finditer(text):
            a = _match_known(m.group(1), known_names)
            b = _match_known(m.group(2), known_names)
            if a and b and a != b:
                triples.add((a, b, "EXTENDS"))

        # USES
        for m in _USES_RE.finditer(text):
            a = _match_known(m.group(1), known_names)
            b = _match_known(m.group(2), known_names)
            if a and b and a != b:
                triples.add((a, b, "USES"))

        # DEPENDS_ON — two sub-patterns (requires / depends on)
        for m in _DEPENDS_RE.finditer(text):
            # Group layout: (1,2) for 'requires', (3,4) for 'depends on'
            if m.group(1):
                a = _match_known(m.group(1), known_names)
                b = _match_known(m.group(2), known_names)
            else:
                a = _match_known(m.group(3), known_names)
                b = _match_known(m.group(4), known_names)
            if a and b and a != b:
                triples.add((a, b, "DEPENDS_ON"))

        # REPLACES — two sub-patterns
        for m in _REPLACES_RE.finditer(text):
            if m.group(1):
                a = _match_known(m.group(1), known_names)
                b = _match_known(m.group(2), known_names)
            else:
                a = _match_known(m.group(3), known_names)
                b = _match_known(m.group(4), known_names)
            if a and b and a != b:
                triples.add((a, b, "REPLACES"))

        # IMPORT patterns: 'import X' or 'from X import' — emit X USES other_entity
        # for each other known entity that also appears in this chunk.
        imported: list[str] = []
        for m in _IMPORT_RE.finditer(text):
            lib = m.group(1) or m.group(2)
            if lib:
                matched = _match_known(lib, known_names)
                if matched:
                    imported.append(matched)

        if imported:
            # Find other known entities mentioned in this chunk
            chunk_lower = text.lower()
            chunk_entities = [
                n for n in known_names
                if n in chunk_lower and n not in imported
            ]
            for lib in imported:
                for other in chunk_entities:
                    if other != lib:
                        # other entity USES the imported library
                        triples.add((other, lib, "USES"))

    return list(triples)
