"""A card is filed under the section its quote is in, and a section scope reads that section only.

One generation call reads windows from across a document. Every card it wrote used to take the
call's first chunk as `chunk_id`, which is what files a card under a section, so a Gita card
quoting Chapter V showed Chapter II's passage and counted towards Chapter II. A section scope
named by a tidied heading found no section and read the whole book instead.
"""

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.exceptions import NotFound
from app.main import app
from app.models import FlashcardModel
from app.services.flashcard import FlashcardService
from app.services.flashcard_repair import refile_cards
from app.services.flashcard_units import bare_passage, names_not_in, unit_quote
from tests.factories import make_card, make_chunk, make_document, make_section

pytestmark = pytest.mark.usefixtures("card_documents")

_TEXTS = {
    "c0": "Engines of the northern mills turn slowly through winter. Millers grind barley "
    "into coarse flour for the long season ahead.",
    "c1": "Granaries along the river store that flour behind heavy oak doors. Keepers count "
    "every sack twice before the spring thaw arrives.",
    "c2": "Ferrymen on the southern crossing charge a copper coin per traveller. Their rafts "
    "carry carts across when the water runs low and calm.",
    "c3": "Bridges replaced most ferries after the great flood washed the old landings away. "
    "Stonemasons rebuilt the crossing with granite from the hills.",
}
_SECTION_OF = {"c0": "s1", "c1": "s1", "c2": "s2", "c3": "s2"}


@pytest.fixture
def factory(memory_db):
    return memory_db.factory


async def _seed(session) -> None:
    session.add(make_document(id="doc-1", title="Rivers", form="article", format="txt"))
    session.add(make_section(id="s1", document_id="doc-1", heading="CHAPTER I", section_order=0))
    session.add(make_section(id="s2", document_id="doc-1", heading="CHAPTER II", section_order=1))
    for index, (cid, text) in enumerate(_TEXTS.items()):
        session.add(
            make_chunk(
                id=cid,
                document_id="doc-1",
                section_id=_SECTION_OF[cid],
                text=text,
                token_count=len(text.split()),
                chunk_index=index,
            )
        )
    await session.commit()


def _unit_llm(prompts: list[str]) -> MagicMock:
    """Answers the unit-first prompt with one card per numbered sentence, quoting it whole."""

    async def generate(prompt, **_kwargs):
        prompts.append(prompt)
        listed = re.findall(r"^(\d+)\. (.+)$", prompt.split("Sentences:", 1)[-1], re.M)
        cards = [
            {
                "id": int(n),
                "question": f"what is true of {' '.join(sentence.lower().split()[:3])}?",
                "answer": sentence,
            }
            for n, sentence in listed
        ]
        return json.dumps({"cards": cards})

    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=generate)
    return llm


async def _generate(session, prompts: list[str], **kwargs):
    with (
        patch(
            "app.services.flashcard_generators._get_llm_service", return_value=_unit_llm(prompts)
        ),
        patch(
            "app.services.flashcard._fetch_existing_embeddings",
            new=AsyncMock(return_value=([], None)),
        ),
        patch("app.services.embedder.get_embedding_service", return_value=None),
    ):
        return await FlashcardService().generate(document_id="doc-1", session=session, **kwargs)


@pytest.mark.asyncio
async def test_each_card_is_filed_under_the_section_its_quote_is_in(factory):
    async with factory() as session:
        await _seed(session)
        cards = await _generate(session, [], scope="full", section_heading=None, count=4)

    assert cards, "the run must write cards for this check to mean anything"
    homes = set()
    for card in cards:
        quoted = next(cid for cid, text in _TEXTS.items() if card.source_excerpt in text)
        assert _SECTION_OF[card.chunk_id] == _SECTION_OF[quoted], card.source_excerpt
        assert card.section_heading == (
            "CHAPTER I" if _SECTION_OF[quoted] == "s1" else "CHAPTER II"
        )
        homes.add(_SECTION_OF[quoted])
    assert homes == {"s1", "s2"}, "the run must span both sections, or filing is not tested"


@pytest.mark.asyncio
async def test_a_section_named_by_id_reads_that_section_alone(factory):
    prompts: list[str] = []
    async with factory() as session:
        await _seed(session)
        cards = await _generate(
            session, prompts, scope="section", section_heading=None, section_id="s2", count=2
        )

    assert cards
    assert prompts and all("Engines of the northern mills" not in p for p in prompts)
    assert all(_SECTION_OF[c.chunk_id] == "s2" for c in cards)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "where",
    [
        {"section_heading": "CHAPTER I:"},  # a display tidied the stored heading
        {"section_id": "no-such-section"},
    ],
)
async def test_a_section_that_cannot_be_found_is_an_error_never_the_whole_book(factory, where):
    prompts: list[str] = []
    async with factory() as session:
        await _seed(session)
        with pytest.raises(NotFound):
            await _generate(
                session, prompts, scope="section", count=2, **{"section_heading": None, **where}
            )
    assert prompts == []


@pytest.mark.asyncio
async def test_another_documents_section_is_not_found(factory):
    async with factory() as session:
        await _seed(session)
        session.add(make_document(id="doc-2", title="Other", form="article", format="txt"))
        session.add(make_section(id="s9", document_id="doc-2", heading="CHAPTER I"))
        await session.commit()
        with pytest.raises(NotFound):
            await _generate(
                session, [], scope="section", section_heading=None, section_id="s9", count=1
            )


def test_a_name_only_our_section_label_carries_does_not_ground_a_question():
    """The Gita's label "CHAPTER V — Arjuna." let a card credit Krishna's words to Arjuna."""
    passage = bare_passage(
        ["[the_gita > CHAPTER V — Arjuna.] This world's Lord makes neither the work nor its fruit."]
    )
    assert names_not_in("According to Arjuna, who makes the work?", passage) == ["Arjuna"]
    assert names_not_in("Who makes neither the work nor its fruit?", passage) == []


def test_a_stored_quote_carries_no_section_label():
    unit = "[CHAPTER V] [the_gita > CHAPTER V] The embodied sage sits godlike."
    assert unit_quote(unit) == "The embodied sage sits godlike."
    assert unit_quote("[1] cited claims stand.") == "cited claims stand."


@pytest.mark.asyncio
async def test_a_misfiled_card_is_moved_to_its_quotes_section_once(factory):
    quote = "Stonemasons rebuilt the crossing with granite from the hills."
    async with factory() as session:
        await _seed(session)
        session.add(
            make_card(
                id="misfiled",
                document_id="doc-1",
                chunk_id="c0",
                section_heading="CHAPTER I",
                source_excerpt=quote,
                source_chunk_ids=["c0", "c2", "c3"],
            )
        )
        # Quoted text in two windows names no passage, so it stays where it is.
        session.add(
            make_card(
                id="ambiguous",
                document_id="doc-1",
                chunk_id="c0",
                source_excerpt="the",
                source_chunk_ids=["c0", "c2"],
            )
        )
        session.add(
            make_card(
                id="gap",
                document_id="doc-1",
                source="gap",
                chunk_id="c0",
                source_excerpt=quote,
                source_chunk_ids=["c3"],
            )
        )
        await session.commit()

        assert await refile_cards(session) == 1
        await session.commit()
        assert await refile_cards(session) == 0

        moved = await session.get(FlashcardModel, "misfiled")
        untouched = await session.get(FlashcardModel, "ambiguous")
        gap = await session.get(FlashcardModel, "gap")
    assert (moved.chunk_id, moved.section_heading) == ("c3", "CHAPTER II")
    assert untouched.chunk_id == "c0"
    assert gap.chunk_id == "c0"


@pytest.mark.asyncio
async def test_the_source_panel_shows_the_cards_quote_and_its_section(factory):
    quote = "Ferrymen on the southern crossing charge a copper coin per traveller."
    async with factory() as session:
        await _seed(session)
        session.add(
            make_card(
                id="card-1",
                document_id="doc-1",
                chunk_id="c0",
                source_excerpt=quote,
                source_chunk_ids=["c0", "c2"],
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/flashcards/card-1/source-context")

    assert resp.status_code == 200
    body = resp.json()
    assert (body["section_id"], body["section_heading"]) == ("s2", "CHAPTER II")
    assert body["quote"] == quote
