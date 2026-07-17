"""Entity disambiguation: canonical name normalisation before Kuzu upsert.

Collapses surface-form variants (e.g. "Holmes", "Mr. Holmes", "Sherlock Holmes")
into a single canonical name, keeping the original surface form as an alias.

Merging is head-aware: an English noun phrase names its HEAD, so a shorter name
may only merge into a longer phrase when it overlaps the phrase's head zone --
the tokens after any possessor prefix ("ulysses' son" is a son, not ulysses)
and before any "of"-complement ("stream of egypt" is a stream, not egypt).
Within a merged cluster the canonical name is the most frequent surface form
(ties go to the longer form), so plain names beat one-off epithets.

Public API:
  _HONORIFICS          — frozenset of honorific tokens
  _strip_honorifics()  — lowercase + remove leading honorifics
  find_canonical()     — resolve one name against an existing pool (same type)
  canonicalize_batch() — process a batch of (name, type) pairs
"""

import logging
import re
from collections import Counter

logger = logging.getLogger(__name__)

# Matches a version qualifier at the end of a name: 'numpy 1.26', 'Python 3.13', 'React 18'.
# Group 1: text before the version  Group 2: major number  Group 3: rest of version (e.g. '.13.1')
# Using a separate group for the dotted tail avoids the repeated-group capture problem where
# only the last match of (?:\.(\d+))* is retained.
_VERSION_RE = re.compile(r"^(.*?)\s+(\d+)((?:\.\d+)+)?$")

# Trailing genitive marker on a token: "ulysses'", "jove's", curly-quote variants.
_GENITIVE_RE = re.compile(r"^(.+?)(?:'s|’s|'|’)$")

# Function words excluded from Rule C content-token comparison so that e.g.
# "king of ithaca" vs "queen of ithaca" share only {ithaca}, not {of, ithaca}.
_STOPWORDS: frozenset[str] = frozenset(
    {"the", "a", "an", "of", "and", "or", "in", "on", "at", "to", "for", "with", "by", "o"}
)

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


def _extract_version_qualifier(name: str) -> tuple[str, str | None]:
    """Split a versioned library name into (base_name, version_string | None).

    The base name retains the major version number only, so that patch versions
    ('Python 3.11', 'Python 3.13') are stored as separate nodes but both link
    to a shared major-version base ('Python 3').

    Examples:
        'Python 3.13' -> ('Python 3', '3.13')
        'numpy 1.26'  -> ('numpy 1', '1.26')
        'React 18'    -> ('React 18', None)   -- single-part: already canonical
        'numpy'       -> ('numpy', None)       -- no version
    """
    m = _VERSION_RE.match(name)
    if not m:
        return name, None
    base_text = m.group(1).strip()
    major = m.group(2)
    dotted_tail = m.group(3)  # e.g. '.13' for 'Python 3.13', '.13.1' for 'Python 3.13.1'
    if dotted_tail is None:
        # Single-component version (e.g. 'React 18') — already canonical, no split
        return name, None
    # Reconstruct the full version string: major + dotted tail
    full_version = major + dotted_tail  # e.g. '3.13' or '3.13.1'
    # Multi-component version: base = "name major"
    base_name = f"{base_text} {major}"
    return base_name, full_version


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


def _tokenize(stripped: str) -> list[tuple[str, bool]]:
    """Split a stripped name into (base_token, is_genitive) pairs.

    A genitive token carries a trailing possessive marker: "ulysses'" and
    "jove's" both yield (base, True), so possessor forms compare equal to the
    plain name while remaining detectable for head-zone computation.
    """
    tokens: list[tuple[str, bool]] = []
    for tok in stripped.split():
        m = _GENITIVE_RE.match(tok)
        if m:
            tokens.append((m.group(1), True))
        else:
            tokens.append((tok, False))
    return tokens


def _bases(tokens: list[tuple[str, bool]]) -> list[str]:
    return [base for base, _ in tokens]


def _head_zone(tokens: list[tuple[str, bool]]) -> tuple[int, int]:
    """Return the [start, end) token range holding the phrase's head.

    The head follows any possessor prefix ("ulysses' | son") and precedes any
    "of"-complement ("stream | of egypt").  A shorter name that matches only
    tokens outside this zone names a different entity than the phrase.
    """
    start = 0
    for i, (_, genitive) in enumerate(tokens[:-1]):
        if genitive:
            start = i + 1
    end = len(tokens)
    for i in range(start + 1, len(tokens)):
        if tokens[i][0] == "of":
            end = i
            break
    return start, end


def _match_exact(a: list[tuple[str, bool]], b: list[tuple[str, bool]]) -> bool:
    """Rule A: identical base-token sequences ("ulysses'" == "ulysses")."""
    return _bases(a) == _bases(b)


def _match_containment(a: list[tuple[str, bool]], b: list[tuple[str, bool]]) -> bool:
    """Rule B: the shorter name is a contiguous token slice of the longer one,
    and that slice overlaps the longer phrase's head zone.

    Token-level comparison prevents raw-substring accidents ("rome" / "romeo");
    the head-zone requirement blocks possessive and of-complement false merges
    ("ulysses" must not merge into "ulysses' son" or "house of ulysses").
    """
    if len(a) == len(b):
        return False
    short, long = (a, b) if len(a) < len(b) else (b, a)
    short_bases, long_bases = _bases(short), _bases(long)
    n = len(short_bases)
    span_start = -1
    for i in range(len(long_bases) - n + 1):
        if long_bases[i : i + n] == short_bases:
            span_start = i
            break
    if span_start == -1:
        return False
    zone_start, zone_end = _head_zone(long)
    return span_start < zone_end and span_start + n > zone_start


def _content_tokens(tokens: list[tuple[str, bool]]) -> set[str]:
    return {base for base, _ in tokens if base not in _STOPWORDS}


def _match_subset(a: list[tuple[str, bool]], b: list[tuple[str, bool]]) -> bool:
    """Rule C: one name's content tokens are a subset of the other's, with at
    least two shared, and the shared tokens reach the superset's head zone.

    Catches reordered variants ("ulysses' house" / "house of ulysses",
    "john watson" / "john h. watson") while refusing sibling-style overlaps
    ("george w bush" / "george h bush" share two tokens but neither contains
    the other) and possessive extensions ("king priam" / "king priam's son").
    """
    ca, cb = _content_tokens(a), _content_tokens(b)
    if len(ca & cb) < 2:
        return False
    if ca == cb:
        return True
    if ca < cb:
        subset, superset = ca, b
    elif cb < ca:
        subset, superset = cb, a
    else:
        return False
    zone_start, zone_end = _head_zone(superset)
    zone_bases = {base for base, _ in superset[zone_start:zone_end]}
    return bool(subset & zone_bases)


_RULES = (_match_exact, _match_containment, _match_subset)


def find_canonical(name: str, entity_type: str, existing_names: list[str]) -> str:
    """Resolve *name* against *existing_names*, returning the matching existing
    canonical or *name* unchanged when nothing matches.

    All comparisons are done in lowercase on honorific-stripped, genitive-aware
    tokens.  The function does NOT cross entity_type boundaries — callers must
    pass only names of the same type.  Rules are tried in order across the whole
    pool (exact, head-aware containment, head-aware content subset); the first
    match wins.  Existing pool names always win over the incoming surface form
    so already-stored canonicals stay stable.
    """
    tokens = _tokenize(_strip_honorifics(name))
    if not tokens:
        return name
    existing_tokens = [(e, _tokenize(_strip_honorifics(e))) for e in existing_names]
    for rule in _RULES:
        for existing, etokens in existing_tokens:
            if etokens and rule(tokens, etokens):
                return existing
    return name


class _Cluster:
    __slots__ = ("rep_tokens", "members", "pool_name")

    def __init__(self, rep_tokens: list[tuple[str, bool]], pool_name: str | None) -> None:
        self.rep_tokens = rep_tokens
        self.members: list[str] = []
        self.pool_name = pool_name


def canonicalize_batch(
    entities: list[tuple[str, str]],
    existing_by_type: dict[str, list[str]],
) -> list[tuple[str, str, str]]:
    """Resolve a batch of (name, entity_type) pairs to canonical forms.

    Args:
        entities: List of (name, entity_type) tuples as produced by the NER
            pipeline, one per mention (names are already lowercase).  Mention
            multiplicity is what makes frequency-based canonical naming work.
        existing_by_type: Dict mapping entity_type -> list of canonical names
            already stored in the Kuzu graph for this document.  A batch name
            that matches a stored canonical adopts it, so re-processing a
            document never splits an existing node.

    Returns:
        List of (canonical_name, entity_type, original_name) triples in the
        same order as *entities*.
        - canonical_name: resolved canonical form (may equal original_name)
        - entity_type:    unchanged
        - original_name:  surface form as given

    Names are clustered greedily in descending mention-frequency order: each
    unique name joins the first existing cluster whose representative it
    matches (rules tried in order across all clusters), else seeds a new one.
    A cluster's representative is its longest member so far, so a later, more
    specific form ("sherlock holmes") can still attract short aliases, while
    distinct specialisations ("python 3.11" vs "python 3.13") stay separate.
    Each cluster's canonical is the pool name when one seeded it, otherwise
    the member with the highest mention count (ties: longer form, then first
    seen).
    """
    freq: Counter[tuple[str, str]] = Counter(entities)
    first_seen: dict[tuple[str, str], int] = {}
    for idx, key in enumerate(entities):
        first_seen.setdefault(key, idx)

    clusters_by_type: dict[str, list[_Cluster]] = {}
    for etype, names in existing_by_type.items():
        pool_clusters = clusters_by_type.setdefault(etype, [])
        for pname in names:
            pool_clusters.append(_Cluster(_tokenize(_strip_honorifics(pname)), pname))

    ordered_unique = sorted(freq, key=lambda k: (-freq[k], first_seen[k]))

    assignment: dict[tuple[str, str], _Cluster] = {}
    for key in ordered_unique:
        name, etype = key
        tokens = _tokenize(_strip_honorifics(name))
        clusters = clusters_by_type.setdefault(etype, [])
        target: _Cluster | None = None
        if tokens:
            for rule in _RULES:
                for cluster in clusters:
                    if cluster.rep_tokens and rule(tokens, cluster.rep_tokens):
                        target = cluster
                        break
                if target is not None:
                    break
        if target is None:
            target = _Cluster(tokens, None)
            clusters.append(target)
        target.members.append(name)
        assignment[key] = target
        if len(tokens) > len(target.rep_tokens):
            target.rep_tokens = tokens

    def canonical_of(cluster: _Cluster, etype: str) -> str:
        if cluster.pool_name is not None:
            return cluster.pool_name
        return max(
            cluster.members,
            key=lambda n: (
                freq[(n, etype)],
                len(_strip_honorifics(n)),
                -first_seen[(n, etype)],
            ),
        )

    canonical_by_key = {
        key: canonical_of(assignment[key], key[1]) for key in freq
    }

    results = [
        (canonical_by_key[(name, etype)], etype, name) for name, etype in entities
    ]

    logger.debug(
        "canonicalize_batch: %d entities -> %d unique canonicals",
        len(entities),
        len({r[0] for r in results}),
    )
    return results
