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
import unicodedata
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


# Irregular plurals worth knowing without a dictionary. Deliberately tiny and
# technical-noun-heavy; "data" is NOT mapped to "datum" because in this domain
# "data" is its own word.
_IRREGULAR_PLURALS: dict[str, str] = {
    "indices": "index",
    "matrices": "matrix",
    "vertices": "vertex",
    "criteria": "criterion",
    "phenomena": "phenomenon",
    "schemata": "schema",
    "children": "child",
}


def _fold_ascii(s: str) -> str:
    """Strip diacritics for comparison ('josé' == 'jose'). Key-only."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)
    )


def _singular_key(base: str) -> str:
    """Collapse regular English plurals to a comparison key ('databases' ==
    'database', 'libraries' == 'library') without a dictionary.

    Keys are used only for token equality -- canonical display names are
    chosen from real surface forms -- so the rule can be crude, but it must
    stay conservative: endings where stripping commonly changes the word
    ('ss', 'us', 'is', short tokens) are left alone, because a missed merge
    is a smaller node while a false merge corrupts two entities.
    """
    base = _IRREGULAR_PLURALS.get(base, base)
    if len(base) <= 3:
        return base
    if not base.endswith("s"):
        # 'caches' (-ches) strips to 'cach', so the singular of a mute-e word
        # must key the same way ('cache' -> 'cach'); ditto -she/-xe/-ze.
        if base.endswith(("che", "she", "xe", "ze")):
            return base[:-1]
        return base
    if base.endswith(("ss", "us", "is")):
        return base
    if base.endswith("ies") and len(base) > 4:
        return base[:-3] + "y"
    if base.endswith(("ches", "shes", "xes", "zes", "oes")):
        return base[:-2]
    return base[:-1]


def _tokenize(stripped: str) -> list[tuple[str, bool]]:
    """Split a stripped name into (base_token, is_genitive) pairs.

    A genitive token carries a trailing possessive marker: "ulysses'" and
    "jove's" both yield (base, True), so possessor forms compare equal to the
    plain name while remaining detectable for head-zone computation. Bases are
    diacritic-folded, hyphen-split ("batch-job" == "batch job"), and
    plural-normalized via _singular_key so regular surface variants compare
    equal ("database" / "databases").
    """
    tokens: list[tuple[str, bool]] = []
    for tok in stripped.split():
        m = _GENITIVE_RE.match(tok)
        genitive = m is not None
        raw = _fold_ascii(m.group(1) if m else tok)
        parts = [p for p in raw.split("-") if p] or [raw]
        for i, part in enumerate(parts):
            tokens.append((_singular_key(part), genitive and i == len(parts) - 1))
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
    __slots__ = ("rep_tokens", "members", "pool_name", "etype")

    def __init__(
        self,
        rep_tokens: list[tuple[str, bool]],
        etype: str,
        pool_name: str | None = None,
    ) -> None:
        self.rep_tokens = rep_tokens
        self.etype = etype
        self.members: list[tuple[str, str]] = []  # (name, original etype) keys
        self.pool_name = pool_name


# Cross-type fold threshold: a name-identical cluster in another type is
# treated as extraction noise only when the dominant side has at least this
# many times the minority's mentions. Balanced counts are what a genuine
# homonym pair (a person and a place sharing a name) looks like -- kept apart.
_TYPE_FOLD_DOMINANCE = 3


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
        List of (canonical_name, canonical_type, original_name) triples in the
        same order as *entities*.
        - canonical_name: resolved canonical form (may equal original_name)
        - canonical_type: usually the input type; differs when a lopsided
          cross-type variant was folded into its dominant twin (see below)
        - original_name:  surface form as given

    Stage 1 clusters names within each type, greedily in descending
    mention-frequency order: each unique name joins the first existing cluster
    whose representative it matches (rules tried in order across all
    clusters), else seeds a new one.  A cluster's representative is its
    longest member so far, so a later, more specific form ("sherlock holmes")
    can still attract short aliases, while distinct specialisations
    ("python 3.11" vs "python 3.13") stay separate.

    Stage 2 reconciles across types: NER often tags surface variants of one
    entity with different types ("node" PERSON / "nodes" DATA_STRUCTURE),
    which per-type clustering can never repair.  Clusters whose representative
    key sequences are identical across types are folded into the
    mention-dominant one when the ratio is lopsided (>= _TYPE_FOLD_DOMINANCE);
    balanced counts stay separate, preserving genuine homonyms.

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
            pool_clusters.append(
                _Cluster(_tokenize(_strip_honorifics(pname)), etype, pool_name=pname)
            )

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
            target = _Cluster(tokens, etype)
            clusters.append(target)
        target.members.append(key)
        assignment[key] = target
        if len(tokens) > len(target.rep_tokens):
            target.rep_tokens = tokens

    # Stage 2 -- cross-type reconciliation (pool clusters stay untouched:
    # their canonical and type are already committed in the graph).
    def batch_mentions(cluster: _Cluster) -> int:
        return sum(freq[m] for m in cluster.members)

    by_rep_key: dict[tuple[str, ...], list[_Cluster]] = {}
    for clusters in clusters_by_type.values():
        for cluster in clusters:
            if cluster.pool_name is not None or not cluster.members:
                continue
            by_rep_key.setdefault(tuple(_bases(cluster.rep_tokens)), []).append(cluster)
    for group in by_rep_key.values():
        if len(group) < 2:
            continue
        sized = sorted(((batch_mentions(c), c) for c in group), key=lambda t: -t[0])
        dominant_count, dominant = sized[0]
        for count, cluster in sized[1:]:
            if dominant_count >= _TYPE_FOLD_DOMINANCE * max(count, 1):
                dominant.members.extend(cluster.members)
                for member in cluster.members:
                    assignment[member] = dominant
                cluster.members = []

    def canonical_of(cluster: _Cluster) -> str:
        if cluster.pool_name is not None:
            return cluster.pool_name
        return max(
            cluster.members,
            key=lambda m: (freq[m], len(_strip_honorifics(m[0])), -first_seen[m]),
        )[0]

    canonical_cache: dict[int, str] = {}
    results: list[tuple[str, str, str]] = []
    for name, etype in entities:
        cluster = assignment[(name, etype)]
        canonical = canonical_cache.get(id(cluster))
        if canonical is None:
            canonical = canonical_of(cluster)
            canonical_cache[id(cluster)] = canonical
        results.append((canonical, cluster.etype, name))

    logger.debug(
        "canonicalize_batch: %d entities -> %d unique canonicals",
        len(entities),
        len({r[0] for r in results}),
    )
    return results
