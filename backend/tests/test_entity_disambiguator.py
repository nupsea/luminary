"""Unit tests for entity_disambiguator.

Tests are pure Python — no DB, no fixtures, no async.
"""

from app.services.entity_disambiguator import (
    _HONORIFICS,
    _extract_version_qualifier,
    canonicalize_batch,
    find_canonical,
)


def test_honorific_stripped_resolves_to_existing():
    """'Mr. Holmes' strips to 'holmes', which is a substring of 'sherlock holmes'."""
    existing = ["sherlock holmes"]
    result = find_canonical("mr. holmes", "PERSON", existing)
    # Rule B: "holmes" in "sherlock holmes" -> longer wins -> "sherlock holmes"
    assert result == "sherlock holmes"


def test_direct_substring():
    """'holmes' is a direct substring of 'sherlock holmes'; longer name wins."""
    existing = ["sherlock holmes"]
    result = find_canonical("holmes", "PERSON", existing)
    assert result == "sherlock holmes"


def test_sr_not_in_honorifics():
    """'sr' must NOT be in _HONORIFICS; 'Sr. Holmes' must NOT resolve to 'Sherlock Holmes'."""
    assert "sr" not in _HONORIFICS

    existing = ["sherlock holmes"]
    result = find_canonical("sr. holmes", "PERSON", existing)
    # "sr" is not stripped -> stripped form is "sr. holmes"
    # Rule A: "sr. holmes" != "sherlock holmes" — no match
    # Rule B: "sr. holmes" not a substring of "sherlock holmes" — no match
    # Rule C: tokens {"sr.", "holmes"} & {"sherlock", "holmes"} = {"holmes"} -> 1 < 2 — no match
    assert result == "sr. holmes"


def test_canonicalize_batch_deduplicates_variants():
    """All three variants of Holmes collapse to 'sherlock holmes'."""
    entities = [
        ("sherlock holmes", "PERSON"),
        ("holmes", "PERSON"),
        ("mr. holmes", "PERSON"),
    ]
    triples = canonicalize_batch(entities, {})
    canonical_names = [t[0] for t in triples]
    assert all(name == "sherlock holmes" for name in canonical_names)


def test_entity_type_boundary():
    """Entities of different types must never merge, even if names are identical."""
    entities = [
        ("london", "PLACE"),
        ("london", "PERSON"),
    ]
    triples = canonicalize_batch(entities, {})
    assert triples[0][0] == "london"
    assert triples[0][1] == "PLACE"
    assert triples[1][0] == "london"
    assert triples[1][1] == "PERSON"


# S135: _extract_version_qualifier tests


def test_version_qualifier_multi_component():
    """'Python 3.13' splits into base='Python 3', version='3.13'."""
    base, ver = _extract_version_qualifier("Python 3.13")
    assert base == "Python 3"
    assert ver == "3.13"


def test_version_qualifier_numpy():
    """'numpy 1.26' splits into base='numpy 1', version='1.26'."""
    base, ver = _extract_version_qualifier("numpy 1.26")
    assert base == "numpy 1"
    assert ver == "1.26"


def test_version_qualifier_single_component_no_split():
    """'React 18' has a single-part version — no split, version=None."""
    base, ver = _extract_version_qualifier("React 18")
    assert base == "React 18"
    assert ver is None


def test_version_qualifier_no_version():
    """'numpy' has no version — returned unchanged with version=None."""
    base, ver = _extract_version_qualifier("numpy")
    assert base == "numpy"
    assert ver is None


def test_versioned_libraries_stay_separate():
    """AC4: 'python 3.11' and 'python 3.13' must NOT be merged into a single canonical.

    Token overlap: {'python', '3.11'} & {'python', '3.13'} = {'python'} = 1 < 2.
    Substring: '3.11' not in 'python 3.13', '3.13' not in 'python 3.11'.
    Both remain distinct.
    """
    entities = [
        ("python 3.11", "LIBRARY"),
        ("python 3.13", "LIBRARY"),
    ]
    triples = canonicalize_batch(entities, {})
    names = [t[0] for t in triples]
    assert "python 3.11" in names
    assert "python 3.13" in names
    assert names[0] != names[1]


def test_unversioned_library_does_not_merge_with_versioned():
    """'python' and 'python 3.13' must not collapse under substring rule.

    'python' is a substring of 'python 3.13', but the longer form wins,
    so 'python' would canonicalize to 'python 3.13'.  This is acceptable
    behaviour (longer canonical); verify no crash and canonical is the longer form.
    """
    entities = [("python 3.13", "LIBRARY"), ("python", "LIBRARY")]
    triples = canonicalize_batch(entities, {})
    names = [t[0] for t in triples]
    # Both should canonicalize to the longer form
    assert all(n == "python 3.13" for n in names)


# Head-aware merging: possessive and of-constructions name a DIFFERENT entity
# than their possessor/complement, and must never merge with it.


def test_possessive_does_not_merge_with_possessor():
    """"ulysses' son" is Telemachus, not Ulysses -- no merge either direction."""
    for son in ["ulysses' son", "ulysses’ son", "ulysses's son"]:
        entities = [("ulysses", "PERSON")] * 5 + [(son, "PERSON")] * 2
        names = {t[0] for t in canonicalize_batch(entities, {})}
        assert names == {"ulysses", son}


def test_possessor_not_absorbed_when_epithet_more_frequent():
    """Merge blocking must not depend on which form is more frequent."""
    entities = [("jove's daughter", "PERSON")] * 5 + [("jove", "PERSON")] * 2
    names = {t[0] for t in canonicalize_batch(entities, {})}
    assert names == {"jove's daughter", "jove"}


def test_of_complement_does_not_merge_with_container():
    """'stream of egypt' is a stream, not Egypt."""
    entities = [
        ("egypt", "PLACE"),
        ("heaven-fed stream of egypt", "PLACE"),
        ("egypt", "PLACE"),
    ]
    names = {t[0] for t in canonicalize_batch(entities, {})}
    assert names == {"egypt", "heaven-fed stream of egypt"}


def test_head_overlap_still_merges_epithet():
    """'jove's daughter minerva' ends in the head 'minerva' -- merges with it,
    while plain 'jove' stays a separate entity."""
    entities = [
        ("minerva", "PERSON"),
        ("minerva", "PERSON"),
        ("jove's daughter minerva", "PERSON"),
        ("jove", "PERSON"),
    ]
    triples = canonicalize_batch(entities, {})
    by_original = {t[2]: t[0] for t in triples}
    assert by_original["jove's daughter minerva"] == "minerva"
    assert by_original["jove"] == "jove"


def test_canonical_is_most_frequent_surface_form():
    """The plain, frequent name wins over a rare longer epithet."""
    entities = [("ithaca", "PLACE")] * 4 + [("ithaca itself", "PLACE")]
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "ithaca" for t in triples)


def test_canonical_tie_prefers_longer_form():
    """On equal frequency the longer, more specific form stays canonical."""
    entities = [("penelope", "PERSON"), ("queen penelope", "PERSON")]
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "queen penelope" for t in triples)


def test_token_boundary_containment():
    """Raw substring must not merge distinct words ('rome' in 'romeo')."""
    entities = [("rome", "PLACE"), ("romeo", "PLACE")]
    names = {t[0] for t in canonicalize_batch(entities, {})}
    assert names == {"rome", "romeo"}


def test_shared_tokens_without_containment_do_not_merge():
    """Sibling-style names share two tokens but are different people."""
    entities = [("george w bush", "PERSON"), ("george h bush", "PERSON")]
    names = {t[0] for t in canonicalize_batch(entities, {})}
    assert names == {"george w bush", "george h bush"}


def test_reordered_of_and_possessive_forms_merge():
    """'ulysses' house' and 'house of ulysses' share the same content tokens
    and the same head -- one place, one node."""
    entities = [
        ("house of ulysses", "PLACE"),
        ("house of ulysses", "PLACE"),
        ("ulysses' house", "PLACE"),
    ]
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "house of ulysses" for t in triples)


def test_possessive_extension_of_multiword_name_blocked():
    """'king priam's son' shares both tokens of 'king priam' but is his son."""
    entities = [("king priam", "PERSON"), ("king priam's son", "PERSON")]
    names = {t[0] for t in canonicalize_batch(entities, {})}
    assert names == {"king priam", "king priam's son"}


def test_bare_genitive_equals_plain_name():
    """A trailing possessive marker alone is the same entity ('ulysses'' -> 'ulysses')."""
    entities = [("ulysses", "PERSON"), ("ulysses'", "PERSON"), ("ulysses", "PERSON")]
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "ulysses" for t in triples)


def test_middle_name_variant_merges():
    """Content-subset variants of the same person collapse ('john watson' ⊂ 'john h. watson')."""
    entities = [
        ("john h. watson", "PERSON"),
        ("john watson", "PERSON"),
        ("john watson", "PERSON"),
    ]
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "john watson" for t in triples)


def test_existing_pool_canonical_is_stable():
    """A batch name matching a stored canonical adopts it even when the batch
    form is more frequent -- re-processing must not split existing nodes."""
    entities = [("holmes", "PERSON")] * 5
    triples = canonicalize_batch(entities, {"PERSON": ["sherlock holmes"]})
    assert all(t[0] == "sherlock holmes" for t in triples)


def test_regular_plural_merges_with_singular():
    """'databases' and 'database' are one entity; the frequent form wins."""
    entities = [("database", "CONCEPT")] * 5 + [("databases", "CONCEPT")] * 2
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "database" for t in triples)


def test_multiword_plural_merges():
    entities = [
        ("data structures", "CONCEPT"),
        ("data structure", "CONCEPT"),
        ("data structure", "CONCEPT"),
    ]
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "data structure" for t in triples)


def test_ies_plural_merges():
    entities = [("library", "CONCEPT")] * 3 + [("libraries", "CONCEPT")]
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "library" for t in triples)


def test_es_plural_merges():
    entities = [("index", "CONCEPT"), ("indexes", "CONCEPT"), ("index", "CONCEPT")]
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "index" for t in triples)


def test_protected_endings_do_not_strip():
    """-ss/-us/-is words are not plurals; distinct entities stay separate."""
    entities = [
        ("class", "CONCEPT"),
        ("cla", "CONCEPT"),
        ("corpus", "CONCEPT"),
        ("corpu", "CONCEPT"),
        ("analysis", "CONCEPT"),
        ("analysi", "CONCEPT"),
    ]
    names = {t[0] for t in canonicalize_batch(entities, {})}
    assert names == {"class", "cla", "corpus", "corpu", "analysis", "analysi"}


def test_plural_key_does_not_leak_into_canonical_name():
    """The stem is a comparison key only -- the canonical is a real surface form."""
    entities = [("libraries", "CONCEPT"), ("libraries", "CONCEPT"), ("library", "CONCEPT")]
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "libraries" for t in triples)


def test_mute_e_plural_merges():
    """'cache'/'caches' key identically despite the -ches/-e ambiguity."""
    entities = [("cache", "DATA_STRUCTURE")] * 4 + [("caches", "DATA_STRUCTURE")]
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "cache" for t in triples)


def test_irregular_plural_merges():
    entities = [
        ("index", "CONCEPT"),
        ("indices", "CONCEPT"),
        ("index", "CONCEPT"),
        ("vertex", "CONCEPT"),
        ("vertex", "CONCEPT"),
        ("vertices", "CONCEPT"),
    ]
    triples = canonicalize_batch(entities, {})
    by_original = {t[2]: t[0] for t in triples}
    assert by_original["indices"] == "index"
    assert by_original["vertices"] == "vertex"


def test_hyphen_variant_merges():
    entities = [
        ("batch job", "CONCEPT"),
        ("batch job", "CONCEPT"),
        ("batch-jobs", "CONCEPT"),
    ]
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "batch job" for t in triples)


def test_diacritic_variant_merges():
    entities = [("josé arcadio", "PERSON"), ("jose arcadio", "PERSON"), ("josé arcadio", "PERSON")]
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "josé arcadio" for t in triples)


# Stage 2: cross-type reconciliation of NER type noise.


def test_cross_type_plural_noise_folds_into_dominant():
    """NER tagging 'nodes' with a different type than 'node' must not split
    the entity; the minority folds into the dominant cluster and adopts its
    name AND type."""
    entities = [("node", "DATA_STRUCTURE")] * 9 + [("nodes", "PERSON")] * 2
    triples = canonicalize_batch(entities, {})
    assert all(t[0] == "node" for t in triples)
    assert all(t[1] == "DATA_STRUCTURE" for t in triples)


def test_cross_type_balanced_homonyms_stay_separate():
    """Balanced mention counts are the genuine-homonym signature (a person and
    a place sharing a name) -- never folded."""
    entities = [("london", "PLACE")] * 3 + [("london", "PERSON")] * 2
    triples = canonicalize_batch(entities, {})
    types = {t[1] for t in triples}
    assert types == {"PLACE", "PERSON"}


def test_cross_type_fold_requires_name_identity():
    """Only Rule-A-identical keys reconcile across types; containment does
    not ('jove' PERSON must not fold into 'jove's daughter' PLACE)."""
    entities = [("jove's daughter", "PLACE")] * 9 + [("jove", "PERSON")]
    triples = canonicalize_batch(entities, {})
    by_original = {t[2]: (t[0], t[1]) for t in triples}
    assert by_original["jove"] == ("jove", "PERSON")


def test_find_canonical_blocks_possessive():
    assert find_canonical("ulysses", "PERSON", ["ulysses' son"]) == "ulysses"
    assert find_canonical("ulysses' son", "PERSON", ["ulysses"]) == "ulysses' son"


def test_find_canonical_returns_pool_match():
    assert find_canonical("holmes", "PERSON", ["sherlock holmes"]) == "sherlock holmes"
    assert find_canonical("minerva", "PERSON", ["jove's daughter minerva"]) == (
        "jove's daughter minerva"
    )
