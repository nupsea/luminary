"""prerequisite_detector: scan chunk text for prerequisite linguistic markers.

Pure function module — no I/O, no DB, no ML.  Called from entity_extract_node
in the ingestion workflow

Detected pairs are only returned when BOTH entity names appear in the
GLiNER-confirmed entity_names set for the document, preventing false positives
from incidental regex matches in prose.
"""

import re

# ---------------------------------------------------------------------------
# Marker patterns
# Each entry: (compiled pattern, confidence_score)
# Patterns use named groups (?P<dep>...) and (?P<prereq>...) to capture the
# dependent concept and its prerequisite.
# ---------------------------------------------------------------------------

_ENTITY_FRAG = r"[A-Za-z][A-Za-z\s'\-]{1,45}"

_MARKERS: list[tuple[re.Pattern, float]] = [
    # "X requires understanding of Y"  /  "X requires Y"
    (
        re.compile(
            rf"(?P<dep>{_ENTITY_FRAG}?)\s+requires?\s+(?:understanding\s+of\s+)?(?P<prereq>{_ENTITY_FRAG})",
            re.IGNORECASE,
        ),
        0.9,
    ),
    # "X is a subclass of Y"
    (
        re.compile(
            rf"(?P<dep>{_ENTITY_FRAG}?)\s+is\s+a\s+subclass\s+of\s+(?P<prereq>{_ENTITY_FRAG})",
            re.IGNORECASE,
        ),
        0.9,
    ),
    # "X builds on Y"  /  "X build on Y"
    (
        re.compile(
            rf"(?P<dep>{_ENTITY_FRAG}?)\s+builds?\s+on\s+(?P<prereq>{_ENTITY_FRAG})",
            re.IGNORECASE,
        ),
        0.7,
    ),
    # "X depends on Y"  /  "X depend on Y"
    (
        re.compile(
            rf"(?P<dep>{_ENTITY_FRAG}?)\s+depends?\s+on\s+(?P<prereq>{_ENTITY_FRAG})",
            re.IGNORECASE,
        ),
        0.7,
    ),
    # "X defined as a type of Y"  /  "X is defined as a type of Y"
    (
        re.compile(
            rf"(?P<dep>{_ENTITY_FRAG}?)\s+(?:is\s+)?defined\s+as\s+a\s+type\s+of\s+(?P<prereq>{_ENTITY_FRAG})",
            re.IGNORECASE,
        ),
        0.7,
    ),
    # "X first introduced as Y"  /  "X was first introduced as Y"
    (
        re.compile(
            rf"(?P<dep>{_ENTITY_FRAG}?)\s+(?:was\s+)?first\s+introduced\s+as\s+(?P<prereq>{_ENTITY_FRAG})",
            re.IGNORECASE,
        ),
        0.5,
    ),
]

# Trailing noise words that commonly bleed into the captured prerequisite group.
_TRAILING_NOISE = re.compile(
    r"\s+(?:and|or|but|which|where|that|with|for|in|on|at|to|of|the|a|an|is|are|was|were)\b.*$",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    """Strip trailing noise words and normalise whitespace."""
    text = _TRAILING_NOISE.sub("", text).strip()
    return re.sub(r"\s+", " ", text).lower()


def detect_prerequisites(
    chunks: list[dict],
    entity_names: set[str],
) -> list[tuple[str, str, float]]:
    """Scan chunk texts for prerequisite linguistic markers.

    Args:
        chunks:       Chunk dicts with at least a 'text' field.
        entity_names: Lowercase canonical entity names confirmed by GLiNER for
                      this document.  Only pairs where BOTH names appear in this
                      set are returned, preventing regex over-matching.

    Returns:
        Deduplicated list of (dependent_name, prerequisite_name, confidence)
        triples.  All names are lowercased.  If the same pair is detected
        multiple times, the highest confidence is kept.
    """
    if not chunks or not entity_names:
        return []

    # Normalise entity_names to lowercase for lookup
    known: set[str] = {n.lower() for n in entity_names}

    # best[(dep, prereq)] = highest confidence seen
    best: dict[tuple[str, str], float] = {}

    for chunk in chunks:
        text: str = chunk.get("text", "")
        if not text:
            continue

        for pattern, base_confidence in _MARKERS:
            for m in pattern.finditer(text):
                dep_raw = m.group("dep")
                pre_raw = m.group("prereq")
                if not dep_raw or not pre_raw:
                    continue

                dep = _clean(dep_raw)
                pre = _clean(pre_raw)

                if not dep or not pre or dep == pre:
                    continue

                # Entity guard: both names must be in the confirmed entity set
                if dep not in known or pre not in known:
                    continue

                key = (dep, pre)
                if key not in best or base_confidence > best[key]:
                    best[key] = base_confidence

    return [(dep, pre, conf) for (dep, pre), conf in best.items()]
