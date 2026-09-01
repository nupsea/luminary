"""DocumentProfile: one definition per policy, and the same answers as before.

The facets replace five disagreeing definitions of "is this technical", two of
which matched the document's title against a keyword list. This rung is meant to
be invisible, so most of the file asserts that every policy the profile now owns
returns what the table it replaced returned -- keyed off the real tables, not a
copy of their values, so a change to either side fails here rather than silently
diverging.

See docs/roadmap.md rung 0.9.0.
"""

import pytest

from app.types import (
    TECHNICAL_CONTENT_TYPES,
    DocumentProfile,
    is_technical_content,
)
from app.workflows.ingestion_nodes._shared import CHUNK_CONFIGS

# Every content type the legacy enum could hold, with the form it becomes.
_LEGACY = {
    "book": "prose",
    "epub": "prose",
    "paper": "paper",
    "tech_book": "reference",
    "tech_article": "article",
    "conversation": "dialogue",
    "audio": "dialogue",
    "video": "dialogue",
    "notes": "entries",
    "kindle_clippings": "entries",
    "code": "source_code",
}


@pytest.mark.parametrize(("content_type", "form"), sorted(_LEGACY.items()))
def test_every_legacy_content_type_maps_to_a_form(content_type: str, form: str) -> None:
    assert DocumentProfile.from_legacy(content_type).form == form


@pytest.mark.parametrize("content_type", sorted(_LEGACY))
def test_domain_agrees_with_is_technical_content(content_type: str) -> None:
    """NER must see the same answer it saw before the facets existed."""
    for flag in (None, True, False):
        profile = DocumentProfile.from_legacy(content_type, flag)
        assert profile.is_technical == is_technical_content(content_type, flag)


def test_an_unmeasured_domain_is_null_not_general() -> None:
    """`detect_technical_transcript` returns None when the probe fails, and
    nothing retries. Recording that as "general" would report a default as a
    finding and show the reader a classification that never happened.

    Four of the library's eight talks are in exactly this state.
    """
    unmeasured = DocumentProfile.from_legacy("audio", None)
    assert unmeasured.domain is None
    assert unmeasured.is_technical is False  # unchanged downstream

    measured_general = DocumentProfile.from_legacy("audio", False)
    assert measured_general.domain == "general"
    assert measured_general.is_technical is False

    # A plain book carries no subject either -- d2l is stored as one.
    assert DocumentProfile.from_legacy("book", None).domain is None
    # ...but a content type that names the subject does establish it.
    assert DocumentProfile.from_legacy("tech_book", None).domain == "technical"


def test_a_technical_talk_is_not_a_meeting() -> None:
    """The conversation strategy asks what was decided and who owns it. A
    recorded talk has neither; its value is the technique.

    Only a measured technical domain flips this, so a talk whose probe never
    answered keeps the previous answer rather than being guessed into a new one.
    """
    talk = DocumentProfile(form="dialogue", domain="technical")
    assert talk.card_genre == "technical"

    meeting = DocumentProfile(form="dialogue", domain="general")
    assert meeting.card_genre == "conversation"

    # An unmeasured domain yields no strategy at all. Defaulting here is how
    # "The Odyssey" came to be shown as non-fiction.
    unclassified = DocumentProfile(form="dialogue", domain=None)
    assert unclassified.card_genre is None


def test_the_persisted_flag_still_beats_the_content_type() -> None:
    """A technical talk keeps content_type 'audio' and carries the flag instead.

    This is the case content_type alone cannot express, and the reason the
    column exists at all.
    """
    assert DocumentProfile.from_legacy("audio", True).is_technical is True
    assert DocumentProfile.from_legacy("audio", True).domain == "technical"
    assert DocumentProfile.from_legacy("tech_book", False).is_technical is False


@pytest.mark.parametrize("content_type", sorted(_LEGACY))
def test_chunk_config_matches_the_config_it_replaces(content_type: str) -> None:
    """Sizing must not move in this rung.

    Read from CHUNK_CONFIGS rather than restated, so drift on either side fails.
    """
    legacy = CHUNK_CONFIGS.get(content_type)
    if legacy is None:
        pytest.skip(f"{content_type} had no chunk config of its own")
    assert DocumentProfile.from_legacy(content_type).chunk_config == legacy


def test_technical_content_types_are_exactly_the_technical_domain() -> None:
    """The tuple the five rival definitions were built from still holds."""
    for content_type in TECHNICAL_CONTENT_TYPES:
        assert DocumentProfile.from_legacy(content_type).domain == "technical"


def test_context_expansion_covers_the_same_documents() -> None:
    """`_EXPANSION_TYPES` was {book, conversation, notes}."""
    for content_type in ("book", "conversation", "notes"):
        assert DocumentProfile.from_legacy(content_type).expands_context is True
    for content_type in ("paper", "tech_book", "tech_article", "code"):
        assert DocumentProfile.from_legacy(content_type).expands_context is False


class TestCardGenre:
    """`_infer_genre` mapped content types to a flashcard prompt strategy."""

    def test_technical_material_asks_for_rules(self) -> None:
        for content_type in ("tech_book", "tech_article", "code"):
            assert DocumentProfile.from_legacy(content_type).card_genre == "technical"

    def test_a_paper_is_academic_even_though_it_is_technical(self) -> None:
        """Ordering matters: a paper is technical and still wants the academic
        prompt, which asks what was measured rather than what the rule is."""
        profile = DocumentProfile(form="paper", domain="technical")
        assert profile.is_technical is True
        assert profile.card_genre == "academic"

    def test_transcripts_ask_what_was_decided(self) -> None:
        for content_type in ("conversation", "audio", "video"):
            profile = DocumentProfile(form="dialogue", domain="general")
            assert profile.card_genre == "conversation"
            # ...but only once the domain has been measured.
            assert DocumentProfile.from_legacy(content_type).card_genre is None

    def test_plain_prose_is_non_fiction_until_register_says_otherwise(self) -> None:
        """Before the facets a prose book reached the technical prompt only by
        its title matching a keyword list, and 'narrative' was unreachable."""
        # No register measured: no strategy. The Odyssey was displayed as
        # non-fiction because this returned a default instead of admitting it
        # could not tell an epic from an essay.
        assert DocumentProfile.from_legacy("book").card_genre is None
        assert DocumentProfile(form="prose", domain="general").card_genre is None
        assert (
            DocumentProfile(form="prose", domain="general", register="narrative").card_genre
            == "narrative"
        )
        assert (
            DocumentProfile(form="prose", domain="general", register="expository").card_genre
            == "non-fiction"
        )

    def test_a_technical_prose_book_asks_for_rules(self) -> None:
        """What the title regex was reaching for, stated as a fact on the row."""
        assert DocumentProfile(form="prose", domain="technical").card_genre == "technical"


def test_tag_entity_types_follow_the_form() -> None:
    """Characters and settings are topics in prose and noise in a manual."""
    assert DocumentProfile.from_legacy("book").tag_entity_types == ("PERSON", "PLACE", "CONCEPT")
    assert DocumentProfile.from_legacy("notes").tag_entity_types == ("PERSON", "PLACE", "CONCEPT")
    for content_type in ("tech_book", "tech_article", "paper", "code", "conversation"):
        assert DocumentProfile.from_legacy(content_type).tag_entity_types == ("CONCEPT",)


def test_profiles_are_frozen() -> None:
    """A policy object that can be mutated in place is a rival definition
    waiting to happen."""
    import dataclasses

    profile = DocumentProfile(form="prose", domain="general")
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.form = "paper"  # type: ignore[misc]


def test_every_form_has_a_chunk_config() -> None:
    """A form with no sizing would fall back to a default nobody chose."""
    from typing import get_args

    from app.types import Form

    for form in get_args(Form):
        cfg = DocumentProfile(form=form, domain="general").chunk_config
        assert cfg["chunk_size"] > 0
        assert 0 < cfg["chunk_overlap"] < cfg["chunk_size"]
