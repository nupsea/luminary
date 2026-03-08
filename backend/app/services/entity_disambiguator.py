"""Entity disambiguation: canonical name normalisation before Kuzu upsert.

Collapses surface-form variants (e.g. "Holmes", "Mr. Holmes", "Sherlock Holmes")
into a single canonical name, keeping the original surface form as an alias.

Public API:
  _HONORIFICS          — frozenset of honorific tokens
  _strip_honorifics()  — lowercase + remove leading honorifics
  find_canonical()     — resolve one name against an existing pool (same type)
  canonicalize_batch() — process a batch of (name, type) pairs
"""

import logging

logger = logging.getLogger(__name__)

# Honorifics that may appear at the FRONT of a name and should be stripped
# before matching.  "sr" is intentionally NOT included.
_HONORIFICS: frozenset[str] = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "sir",
        "miss",
        "lady",
        "lord",
        "prof",
        "professor",
        "rev",
        "captain",
        "capt",
        "col",
        "gen",
        "sgt",
        "lt",
    }
)


def _strip_honorifics(name: str) -> str:
    """Lowercase *name* and remove leading honorific tokens.

    Trailing punctuation (period, comma) is stripped from each token before
    the honorific check.  Only tokens at the FRONT are removed.

    Examples:
        "Mr. Sherlock Holmes" -> "sherlock holmes"
        "Dr. Watson"          -> "watson"
        "Sr. Holmes"          -> "sr. holmes"  (sr not an honorific)
        "Sherlock Holmes"     -> "sherlock holmes"
    """
    tokens = name.lower().strip().split()
    while tokens:
        stripped_first = tokens[0].rstrip(".,")
        if stripped_first in _HONORIFICS:
            tokens.pop(0)
        else:
            break
    return " ".join(tokens)


def find_canonical(name: str, entity_type: str, existing_names: list[str]) -> str:
    """Resolve *name* to a canonical form from *existing_names*.

    All comparisons are done in lowercase.  The function does NOT cross
    entity_type boundaries — callers must pass only names of the same type.

    Rules applied in order (first match wins):
      A. Exact stripped match:  _strip(name) == _strip(existing)
      B. Substring containment: one stripped form is a substring of the other;
         the longer stripped form wins.
      C. Token overlap >= 2:    at least two tokens shared; the longer
         stripped form wins.

    Returns *name* unchanged if no rule matches.
    """
    stripped_name = _strip_honorifics(name)

    for existing in existing_names:
        stripped_existing = _strip_honorifics(existing)

        # Rule A — exact match after honorific stripping
        if stripped_name == stripped_existing:
            return existing

    for existing in existing_names:
        stripped_existing = _strip_honorifics(existing)

        # Rule B — substring containment (longer wins)
        if stripped_name and stripped_existing:
            if stripped_name in stripped_existing or stripped_existing in stripped_name:
                # Return whichever (original form) corresponds to the longer stripped form
                if len(stripped_existing) >= len(stripped_name):
                    return existing
                else:
                    return name

    for existing in existing_names:
        stripped_existing = _strip_honorifics(existing)

        # Rule C — token overlap >= 2 (longer wins)
        tokens_name = set(stripped_name.split())
        tokens_existing = set(stripped_existing.split())
        if len(tokens_name & tokens_existing) >= 2:
            if len(stripped_existing) >= len(stripped_name):
                return existing
            else:
                return name

    # No match — this name becomes its own canonical entry
    return name


def canonicalize_batch(
    entities: list[tuple[str, str]],
    existing_by_type: dict[str, list[str]],
) -> list[tuple[str, str, str]]:
    """Resolve a batch of (name, entity_type) pairs to canonical forms.

    Args:
        entities: List of (name, entity_type) tuples as produced by the NER
            pipeline (names are already lowercase).
        existing_by_type: Dict mapping entity_type -> list of canonical names
            already stored in the Kuzu graph for this document.  Used as the
            initial lookup pool; new canonicals discovered within this batch
            are added to the pool so later entries benefit from earlier ones.

    Returns:
        List of (canonical_name, entity_type, original_name) triples in the
        same order as *entities*.
        - canonical_name: resolved canonical form (may equal original_name)
        - entity_type:    unchanged
        - original_name:  surface form as given
    """
    # Deep-copy so we can extend pool without mutating the caller's dict
    working: dict[str, list[str]] = {
        etype: list(names) for etype, names in existing_by_type.items()
    }

    # Pass 1 — build a stable pool: process every name and promote longer canonicals
    # so the pool converges to the best (longest) representative for each cluster
    # before we assign final results.  Without this pass, processing order determines
    # which canonical wins; a shorter name processed first stays in the pool and
    # causes later short-form aliases to match it via Rule A instead of the longer
    # canonical that was processed second.
    for name, entity_type in entities:
        pool = working.setdefault(entity_type, [])
        canonical = find_canonical(name, entity_type, pool)
        if canonical not in pool:
            # If this incoming name is longer than a pool entry it matched via
            # Rule B or C, evict that shorter entry so it cannot be matched
            # as a spurious canonical in subsequent iterations.
            stripped_canonical = _strip_honorifics(canonical)
            evict = [
                p for p in pool
                if _strip_honorifics(p) != stripped_canonical
                and (
                    (
                        stripped_canonical
                        and _strip_honorifics(p)
                        and (
                            _strip_honorifics(p) in stripped_canonical
                            or stripped_canonical in _strip_honorifics(p)
                        )
                        and len(stripped_canonical) > len(_strip_honorifics(p))
                    )
                    or (
                        len(
                            set(stripped_canonical.split())
                            & set(_strip_honorifics(p).split())
                        ) >= 2
                        and len(stripped_canonical) > len(_strip_honorifics(p))
                    )
                )
            ]
            for old in evict:
                pool.remove(old)
            pool.append(canonical)

    # Pass 2 — assign final results using the now-stable pool.
    results: list[tuple[str, str, str]] = []
    for name, entity_type in entities:
        pool = working.get(entity_type, [])
        canonical = find_canonical(name, entity_type, pool)
        results.append((canonical, entity_type, name))

    logger.debug(
        "canonicalize_batch: %d entities -> %d unique canonicals",
        len(entities),
        len({r[0] for r in results}),
    )
    return results
