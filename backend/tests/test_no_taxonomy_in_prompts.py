"""No generation prompt names a taxonomy (I-28), on any surface.

A label is not a specification. The model pattern-matches the word to the
register it has seen it in, which is how "6 questions at Bloom taxonomy level 5
(Evaluate)" produced exam papers -- "Evaluate how X's reliance on Y can be
advantageous" -- that no reader would type, and which the intent classifier then
read as a learner's explanation.

The reason this is an invariant rather than a fix is portability: what a label
resolves to is a property of the model reading it, so a prompt built on one means
something different on the next model, and the difference is invisible in any
output-quality score.

`test_suggestions.test_prompts_carry_no_taxonomy_verb` has guarded the
suggestions surface since I-28 was written. The flashcard prompts were the
documented gap -- `flashcard_prompts.py` opened with "creating flashcards based
on Bloom's Taxonomy" and annotated every card type with "(L1)" through "(L6)",
and the gap-fill prompt asked for "an UNDERSTANDING question" and "an EVALUATION
question". This closes it.
"""

import pytest

# Terms that name the taxonomy or one of its levels. `apply`, `create` and
# `remember` are ordinary English words, so they are matched with word
# boundaries: a prompt may say "applies" or "created" without naming a level.
_TAXONOMY_TERMS = (
    "bloom",
    "taxonomy",
    "bloom_level",
    "understanding question",
    "evaluation question",
    "analysis question",
    "synthesis question",
    "application question",
)

_LEVEL_VERBS = ("evaluate", "analyse", "analyze", "synthesise", "synthesize")

# `(L1)` ... `(L6)`, the annotation the technical prompt used to carry.
_LEVEL_TAGS = tuple(f"(l{n})" for n in range(1, 7))


def _rendered_prompts() -> dict[str, str]:
    """Every prompt that reaches a model on a card-writing path."""
    from app.services.flashcard_audit import (
        _AUDIT_FILL_SYSTEM,
        _BLOOM_LEVEL_INSTRUCTIONS,
    )
    from app.services.flashcard_prompts import (
        CLOZE_SYSTEM,
        FLASHCARD_SYSTEM,
        GRAPH_FLASHCARD_SYSTEM,
        TECH_FLASHCARD_SYSTEM,
        flashcard_user_tmpl,
    )

    prompts = {
        "FLASHCARD_SYSTEM": FLASHCARD_SYSTEM,
        "TECH_FLASHCARD_SYSTEM": TECH_FLASHCARD_SYSTEM,
        "flashcard_user_tmpl": flashcard_user_tmpl(),
        "CLOZE_SYSTEM": CLOZE_SYSTEM,
        "GRAPH_FLASHCARD_SYSTEM": GRAPH_FLASHCARD_SYSTEM,
        "_AUDIT_FILL_SYSTEM": _AUDIT_FILL_SYSTEM,
    }
    for level, text in _BLOOM_LEVEL_INSTRUCTIONS.items():
        prompts[f"_BLOOM_LEVEL_INSTRUCTIONS[{level}]"] = text
    return prompts


@pytest.mark.parametrize("name", sorted(_rendered_prompts()))
def test_no_prompt_names_the_taxonomy(name: str):
    text = _rendered_prompts()[name].lower()
    for term in _TAXONOMY_TERMS:
        assert term not in text, f"{name} leaks taxonomy term {term!r}"


@pytest.mark.parametrize("name", sorted(_rendered_prompts()))
def test_no_prompt_names_a_level_verb(name: str):
    text = _rendered_prompts()[name].lower()
    for verb in _LEVEL_VERBS:
        assert verb not in text, f"{name} leaks level verb {verb!r}"


@pytest.mark.parametrize("name", sorted(_rendered_prompts()))
def test_no_prompt_carries_a_level_tag(name: str):
    """`definition (L1)` teaches the same ordering the word would."""
    text = _rendered_prompts()[name].lower()
    for tag in _LEVEL_TAGS:
        assert tag not in text, f"{name} annotates a card type with {tag!r}"


def test_the_level_is_derived_rather_than_asked_for():
    """The stored column stays; only the ask goes away.

    A card's level now comes from its type (technical path) or its `depth` word
    (generic path). Asking a model for a number it can disagree with was both
    taxonomy-naming and redundant -- the type-to-level mapping was already
    written down in the prompt.
    """
    from app.services.flashcard_prompts import TYPE_TO_BLOOM, bloom_from

    assert bloom_from({"flashcard_type": "trace"}) == TYPE_TO_BLOOM["trace"]
    assert bloom_from({"depth": "relate"}) == 4
    assert bloom_from({}) is None, "an unlabelled card has no level, rather than a default one"
    # A card written before this still has its stored number honoured.
    assert bloom_from({"bloom_level": 5}) == 5
    # The type is the codebase's decision, so it wins over anything the model says.
    assert bloom_from({"flashcard_type": "definition", "depth": "build"}) == 1


def test_every_declared_card_type_maps_to_a_level():
    """A type the prompt offers but the mapping does not know would silently
    produce a card with no level, and the coverage audit reads that column."""
    import re

    from app.services.flashcard_prompts import TECH_FLASHCARD_SYSTEM, TYPE_TO_BLOOM

    match = re.search(
        r"flashcard types:\s*(.+?)\.\s", TECH_FLASHCARD_SYSTEM.replace("\n", " ")
    )
    assert match, "the technical prompt no longer lists its card types"
    declared = {t.strip() for t in match.group(1).split(",") if t.strip()}
    assert declared <= set(TYPE_TO_BLOOM), (
        f"types offered to the model with no level mapping: {declared - set(TYPE_TO_BLOOM)}"
    )
