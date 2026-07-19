"""Entity disambiguation: canonical name normalisation before Kuzu upsert.

Collapses surface-form variants of one entity into a single canonical name,
keeping the original surface form as an alias.

Merging is head-aware: an English noun phrase names its HEAD, so a shorter name
may only merge into a longer phrase when it overlaps the phrase's head zone --
the tokens after any possessor prefix (a possessive phrase names the possessed,
not the possessor) and before any "of"-complement (an of-phrase names its
subject, not its complement).
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

# Matches a trailing version qualifier: name text, major number, optional dotted
# tail. A separate group for the dotted tail avoids the repeated-group capture
# problem where only the last match of (?:\.(\d+))* is retained.
_VERSION_RE = re.compile(r"^(.*?)\s+(\d+)((?:\.\d+)+)?$")

# Trailing genitive marker on a token: straight or curly apostrophe, with or
# without a following s.
_GENITIVE_RE = re.compile(r"^(.+?)(?:'s|’s|'|’)$")

# Function words excluded from Rule C content-token comparison so shared
# function words never count as evidence that two names co-refer.
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

    The base name retains the major version number only, so that different
    patch versions are stored as separate nodes but all link to a shared
    major-version base. Names with a single-component version or no version
    are returned unchanged with no version string.
    """
    m = _VERSION_RE.match(name)
    if not m:
        return name, None
    base_text = m.group(1).strip()
    major = m.group(2)
    dotted_tail = m.group(3)
    if dotted_tail is None:
        return name, None
    full_version = major + dotted_tail
    base_name = f"{base_text} {major}"
    return base_name, full_version


def _strip_honorifics(name: str) -> str:
    """Lowercase *name* and remove leading honorific tokens.

    Trailing punctuation (period, comma) is stripped from each token before
    the honorific check.  Only tokens at the FRONT are removed.
    """
    tokens = name.lower().strip().split()
    while tokens:
        stripped_first = tokens[0].rstrip(".,")
        if stripped_first in _HONORIFICS:
            tokens.pop(0)
        else:
            break
    return " ".join(tokens)


# Irregular plurals worth knowing without a dictionary. Deliberately tiny;
# formally-plural mass nouns are excluded because their Latin singular is a
# different word in practice.
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
    """Strip diacritics for comparison keys; never alters the stored name."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)
    )


def _singular_key(base: str) -> str:
    """Collapse regular English plurals to a comparison key without a
    dictionary.

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
        # An -es plural on a sibilant stem keys with its -es stripped, so a
        # mute-e singular on the same stem must drop its final -e to key
        # identically.
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

    A genitive token yields (base, True), so possessor forms compare equal to
    the plain name while remaining detectable for head-zone computation.
    Bases are diacritic-folded and plural-normalized via _singular_key so
    regular surface variants compare equal. A hyphenated compound stays ONE
    token (each part singularized in place) -- the containment rules must
    never see inside it, because a hyphenated compound names a different
    entity than its bare head noun; hyphen-vs-space equivalence lives solely
    in _exact_key.
    """
    tokens: list[tuple[str, bool]] = []
    for tok in stripped.split():
        m = _GENITIVE_RE.match(tok)
        genitive = m is not None
        raw = _fold_ascii(m.group(1) if m else tok)
        parts = [_singular_key(p) for p in raw.split("-") if p]
        tokens.append(("-".join(parts) if parts else raw, genitive))
    return tokens


def _bases(tokens: list[tuple[str, bool]]) -> list[str]:
    return [base for base, _ in tokens]


def _exact_key(tokens: list[tuple[str, bool]]) -> tuple[str, ...]:
    """Whole-name comparison key: hyphens flatten to word boundaries, so
    hyphenated, spaced, and line-break-split spellings of one compound
    compare equal. Safe ONLY for full-sequence equality; partial matching
    over this key would merge a compound's bare head noun into the compound.
    """
    return tuple(part for base, _ in tokens for part in base.split("-"))


def _head_zone(tokens: list[tuple[str, bool]]) -> tuple[int, int]:
    """Return the [start, end) token range holding the phrase's head.

    The head follows any possessor prefix and precedes any "of"-complement.
    A shorter name that matches only tokens outside this zone names a
    different entity than the phrase.
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
    """Rule A: identical whole-name keys (genitive-, plural-, and
    hyphen-insensitive)."""
    return _exact_key(a) == _exact_key(b)


def _match_containment(a: list[tuple[str, bool]], b: list[tuple[str, bool]]) -> bool:
    """Rule B: the shorter name is a contiguous token slice of the longer one,
    and that slice overlaps the longer phrase's head zone.

    Token-level comparison prevents raw-substring accidents between unrelated
    words that share a prefix; the head-zone requirement blocks possessive and
    of-complement false merges, where the shorter name is the possessor or
    complement rather than the phrase's referent.
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

    Catches reordered and initialed variants of one name while refusing
    sibling-style overlaps (two names sharing modifier tokens but with
    neither's content a subset of the other's) and possessive extensions
    (a name versus a longer phrase possessed by it).
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
    longest member so far, so a later, more specific form can still attract
    short aliases, while distinct specialisations stay separate.

    Stage 2 reconciles across types: NER often tags surface variants of one
    entity with different types, which per-type clustering can never repair.
    Clusters whose canonical-name keys are identical across types are folded
    into the mention-dominant one when the ratio is lopsided
    (>= _TYPE_FOLD_DOMINANCE); balanced counts stay separate, preserving
    genuine homonyms.

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

    def batch_mentions(cluster: _Cluster) -> int:
        return sum(freq[m] for m in cluster.members)

    def canonical_of(cluster: _Cluster) -> str:
        if cluster.pool_name is not None:
            return cluster.pool_name
        return max(
            cluster.members,
            key=lambda m: (freq[m], len(_strip_honorifics(m[0])), -first_seen[m]),
        )[0]

    canonical_cache: dict[int, str] = {}

    def cached_canonical(cluster: _Cluster) -> str:
        got = canonical_cache.get(id(cluster))
        if got is None:
            got = canonical_of(cluster)
            canonical_cache[id(cluster)] = got
        return got

    # Stage 2 -- cross-type reconciliation (pool clusters stay untouched:
    # their canonical and type are already committed in the graph). Folding
    # keys on each cluster's CANONICAL name, never its longest-member
    # representative: the rep drifts as more specific phrases join, so
    # rep-keyed folding both misses true twins and fuses unrelated clusters
    # that merely share a drifted rep. Caching canonicals BEFORE folding also
    # pins the dominant cluster's name against a high-frequency minority
    # member changing it after the merge.
    by_name_key: dict[tuple[str, ...], list[_Cluster]] = {}
    for clusters in clusters_by_type.values():
        for cluster in clusters:
            if cluster.pool_name is not None or not cluster.members:
                continue
            key = _exact_key(_tokenize(_strip_honorifics(cached_canonical(cluster))))
            by_name_key.setdefault(key, []).append(cluster)
    for group in by_name_key.values():
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

    results: list[tuple[str, str, str]] = []
    for name, etype in entities:
        cluster = assignment[(name, etype)]
        results.append((cached_canonical(cluster), cluster.etype, name))

    logger.debug(
        "canonicalize_batch: %d entities -> %d unique canonicals",
        len(entities),
        len({r[0] for r in results}),
    )
    return results
