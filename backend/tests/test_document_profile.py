"""DocumentProfile: one definition per policy, read from the measured facets.

The facets replaced five disagreeing definitions of "is this technical", two of
which matched the document's title against a keyword list; the content type they
were first derived from is gone (#223). These pin each policy to the facets.
"""

import pytest

from app.types import DocumentProfile


def test_an_unmeasured_domain_is_null_not_general() -> None:
    """`detect_technical_transcript` returns None when the probe fails. Recording
    that as "general" would report a default as a finding and show the reader a
    classification that never happened."""
    unmeasured = DocumentProfile(form="dialogue")
    assert unmeasured.domain is None
    assert unmeasured.is_technical is False

    measured_general = DocumentProfile(form="dialogue", domain="general")
    assert measured_general.domain == "general"
    assert measured_general.is_technical is False


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


def test_context_expansion_follows_the_form() -> None:
    """Neighbouring chunks continue the same thought in prose, turns and entries."""
    for form in ("prose", "dialogue", "entries"):
        assert DocumentProfile(form=form).expands_context is True
    for form in ("paper", "reference", "article", "source_code"):
        assert DocumentProfile(form=form).expands_context is False


class TestCardGenre:
    """`_infer_genre` mapped content types to a flashcard prompt strategy."""

    def test_technical_material_asks_for_rules(self) -> None:
        for form in ("reference", "article"):
            assert DocumentProfile(form=form, domain="technical").card_genre == "technical"
        assert DocumentProfile(form="source_code").card_genre == "technical"

    def test_a_paper_is_academic_even_though_it_is_technical(self) -> None:
        """Ordering matters: a paper is technical and still wants the academic
        prompt, which asks what was measured rather than what the rule is."""
        profile = DocumentProfile(form="paper", domain="technical")
        assert profile.is_technical is True
        assert profile.card_genre == "academic"

    def test_transcripts_ask_what_was_decided(self) -> None:
        assert DocumentProfile(form="dialogue", domain="general").card_genre == "conversation"
        # ...but only once the domain has been measured.
        assert DocumentProfile(form="dialogue").card_genre is None

    def test_plain_prose_is_non_fiction_until_register_says_otherwise(self) -> None:
        """Before the facets a prose book reached the technical prompt only by
        its title matching a keyword list, and 'narrative' was unreachable."""
        # No register measured: no strategy. The Odyssey was displayed as
        # non-fiction because this returned a default instead of admitting it
        # could not tell an epic from an essay.
        assert DocumentProfile(form="prose").card_genre is None
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
        assert (
            DocumentProfile(form="prose", domain="technical", register="expository").card_genre
            == "technical"
        )

    def test_a_story_is_narrative_whatever_its_domain(self) -> None:
        """The Odyssey read `domain=technical` from its preface and got technical cards (#253)."""
        assert (
            DocumentProfile(form="prose", domain="technical", register="narrative").card_genre
            == "narrative"
        )


def test_tag_entity_types_follow_the_form() -> None:
    """Characters and settings are topics in prose and noise in a manual."""
    for form in ("prose", "entries", "script"):
        assert DocumentProfile(form=form).tag_entity_types == ("PERSON", "PLACE", "CONCEPT")
    for form in ("reference", "article", "paper", "source_code", "dialogue"):
        assert DocumentProfile(form=form).tag_entity_types == ("CONCEPT",)


def test_a_shape_that_settles_its_register_is_not_probed() -> None:
    """A research paper reports and a manual instructs; neither narrates.

    Asking a model costs ~2.6s a document on the dev host and can only agree.
    Every other form must still be measured -- `dialogue` above all, because a
    meeting explains and an audiobook narrates, and both arrive as speaker turns.
    """
    from app.types import register_for_form

    assert register_for_form("paper") == "expository"
    assert register_for_form("reference") == "expository"
    for form in ("prose", "article", "dialogue", "entries", "script", "source_code"):
        assert register_for_form(form) is None, f"{form} must still be measured"


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


class TestGenreWiring:
    """`_infer_genre` must read the measured facets, not re-derive them.

    `DocumentProfile.card_genre` and `_infer_genre` produce the same five
    labels from different evidence, and they disagreed: the legacy branches
    call a book technical from a keyword in its *title* and call every video a
    meeting. The facets are the measurement; these assert the generator uses it.
    """

    @staticmethod
    def _doc(**kwargs):
        from types import SimpleNamespace

        base = {
            "title": None,
            "format": "txt",
            "form": None,
            "domain": None,
            "register": None,
        }
        return SimpleNamespace(**{**base, **kwargs})

    def test_a_technical_talk_is_not_asked_what_was_decided(self) -> None:
        """The bug #105 fixed in the summarizer lived here too: a recorded
        technical talk was mapped by its media type to `conversation` -- the
        meeting strategy, which asks who owns the action item. A talk's value is
        the technique."""
        from app.services.flashcard_prompts import _infer_genre

        talk = self._doc(form="dialogue", domain="technical")
        assert _infer_genre(talk) == "technical"

        meeting = self._doc(form="dialogue", domain="general")
        assert _infer_genre(meeting) == "conversation"

    def test_a_measured_novel_is_not_called_technical_by_its_title(self) -> None:
        from app.services.flashcard_prompts import _infer_genre

        # "Neuromancer" trips no keyword, but the legacy path cannot tell an
        # epic from an essay at all -- it answers non-fiction for both.
        novel = self._doc(
            title="Neuromancer",
            form="prose",
            domain="general",
            register="narrative",
        )
        assert _infer_genre(novel) == "narrative"

    def test_what_the_facets_leave_open_falls_back_on_the_format(self) -> None:
        """A dialogue of unknown subject is a conversation unless it is a
        recording with no speaker labels: a talk carries none."""
        from app.services.flashcard_prompts import _infer_genre

        assert _infer_genre(self._doc(form="reference", domain="technical")) == "technical"
        assert _infer_genre(self._doc(form="paper")) == "academic"
        assert _infer_genre(self._doc(form="dialogue")) == "conversation"
        assert _infer_genre(self._doc(form="dialogue", format="mp3")) == "non-fiction"
        assert _infer_genre(self._doc(form="dialogue", format="mp3"), has_speakers=True) == (
            "conversation"
        )
        assert _infer_genre(None) == "non-fiction"

    def test_a_profile_that_determines_nothing_falls_through(self) -> None:
        """`card_genre` returns None where it cannot tell; that must reach the
        fallback rather than being read as a genre."""
        from app.services.flashcard_prompts import _infer_genre

        # No title keyword decides it any more: the title said nothing the facets did not.
        undetermined = self._doc(title="Distributed Systems", form="prose", domain="general")
        assert DocumentProfile(form="prose", domain="general").card_genre is None
        assert _infer_genre(undetermined) == "non-fiction"


class TestProfileOfStoredDocument:
    """`DocumentProfile.of` reads what classification measured (#223)."""

    @staticmethod
    def _row(form: str | None = None, domain: str | None = None, register: str | None = None):
        from types import SimpleNamespace

        return SimpleNamespace(form=form, domain=domain, register=register)

    def test_the_measured_facets_decide(self) -> None:
        textbook = DocumentProfile.of(self._row(form="reference", domain="technical"))
        assert textbook.form == "reference"
        assert textbook.is_technical
        assert not textbook.is_narrative_prose
        assert not textbook.expands_context

    def test_an_unclassified_row_reads_as_entries_and_keeps_its_domain(self) -> None:
        """Mid-ingest, or a parse that failed: the smallest chunks, nothing invented."""
        profile = DocumentProfile.of(self._row(domain="technical"))
        assert profile.form == "entries"
        assert profile.domain == "technical"

    def test_no_document_is_not_narrative_prose(self) -> None:
        assert not DocumentProfile.of(None).is_narrative_prose


class TestProfileOfState:
    """Mid-ingest the facets are in the state, not yet on the row."""

    def test_the_measured_form_and_domain_decide(self) -> None:
        from app.workflows.ingestion_nodes._shared import profile_of_state

        state = {"format": "pdf", "form": "reference", "domain": "technical"}
        profile = profile_of_state(state)
        assert (profile.form, profile.domain) == ("reference", "technical")

    def test_media_is_turns_until_its_transcript_is_measured(self) -> None:
        """classify_node measures nothing for media; `audio` once mapped to dialogue."""
        from app.workflows.ingestion_nodes._shared import profile_of_state

        assert profile_of_state({"format": "mp3"}).form == "dialogue"
        assert profile_of_state({"format": "mp4"}).form == "dialogue"
        assert profile_of_state({"format": "txt"}).form == "entries"
