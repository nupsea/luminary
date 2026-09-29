"""Staged generation (#191 Phase 2): each check fires once on the card it exists to stop."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import make_engine
from app.db_init import create_all_tables
from app.models import ChunkModel, DocumentModel
from app.services import flashcard_staged as staged
from app.services.flashcard_factuality import (
    FACTUALITY_SUPPORTED,
    FACTUALITY_UNCHECKED,
    FACTUALITY_UNSUPPORTED,
    FACTUALITY_UNVERIFIABLE,
)

PASSAGE = (
    "The queen was jealous of Snow White. She sent a huntsman to take Snow White into the "
    "forest. The huntsman let her go because he pitied the girl. Snow White found a cottage "
    "where seven dwarfs lived."
)

_HUNTSMAN = {
    "span": "The huntsman let her go because he pitied the girl.",
    "fact": "The huntsman let Snow White go because he pitied her.",
    "kind": "cause",
}
_COTTAGE = {
    "span": "Snow White found a cottage where seven dwarfs lived.",
    "fact": "Snow White found a cottage where seven dwarfs lived.",
    "kind": "event",
}


class _Script:
    """A fake LLM answering each stage from its prompt, and recording which model was asked."""

    def __init__(self, units, questions, blind=None, same=None, *, fail_verifier=False):
        self.units, self.questions = units, questions
        self.blind, self.same = blind or {}, same or {}
        self.fail_verifier = fail_verifier
        self.models: list[str | None] = []

    async def generate(self, prompt, **kw):
        self.models.append(kw.get("model"))
        if prompt.startswith("Choose up to"):
            return json.dumps({"units": self.units})
        if prompt.startswith("Write one study question"):
            return json.dumps(
                {"questions": [{"id": i, "question": q} for i, q in self.questions.items()]}
            )
        if self.fail_verifier:
            raise ConnectionError("verifier down")
        if prompt.startswith("Answer each numbered question"):
            return json.dumps({"answers": [{"id": i, "answer": a} for i, a in self.blind.items()]})
        return json.dumps({"verdicts": [{"id": i, "same": s} for i, s in self.same.items()]})


def _llm(script: _Script):
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=script.generate)
    return llm


@pytest.fixture()
def verifier(monkeypatch):
    monkeypatch.setattr(staged, "factuality_model", lambda: "openai/gpt-5.4-mini")
    monkeypatch.setattr(staged, "effective_generation_model", lambda: "ollama/qwen3.5:4b")


class TestSelect:
    @pytest.mark.asyncio
    async def test_a_paraphrased_span_is_not_a_unit(self):
        units = [
            _COTTAGE,
            {**_COTTAGE, "span": "Snow White discovered the dwarfs' little house."},
        ]
        got = await staged.select_units(
            _llm(_Script(units, {})), PASSAGE, 2, model=None, used_spans=[]
        )
        assert [u.span for u in got] == [_COTTAGE["span"]]

    @pytest.mark.asyncio
    async def test_a_cause_the_span_does_not_state_becomes_a_claim(self):
        unit = {
            "span": "The queen was jealous of Snow White.",
            "fact": "The queen was jealous of Snow White.",
            "kind": "cause",
        }
        got = await staged.select_units(
            _llm(_Script([unit, _HUNTSMAN], {})), PASSAGE, 2, model=None, used_spans=[]
        )
        assert [u.kind for u in got] == ["claim", "cause"]

    @pytest.mark.asyncio
    async def test_a_span_already_carded_is_not_selected_again(self):
        got = await staged.select_units(
            _llm(_Script([_COTTAGE, _HUNTSMAN], {})),
            PASSAGE,
            2,
            model=None,
            used_spans=[_COTTAGE["span"]],
        )
        assert [u.span for u in got] == [_HUNTSMAN["span"]]


class TestAsk:
    @pytest.mark.asyncio
    async def test_a_why_question_needs_a_stated_cause(self):
        units = [staged.Unit(_COTTAGE["span"], _COTTAGE["fact"], "event")]
        cards = await staged.ask(
            _llm(_Script([], {1: "Why did Snow White hide in the dwarfs' cottage?"})),
            units,
            PASSAGE,
            model=None,
        )
        assert cards == []

    @pytest.mark.asyncio
    async def test_a_question_that_states_its_answer_is_dropped(self):
        units = [staged.Unit(_HUNTSMAN["span"], _HUNTSMAN["fact"], "cause")]
        cards = await staged.ask(
            _llm(_Script([], {1: "Why did the huntsman, pitying Snow White, let her go?"})),
            units,
            PASSAGE,
            model=None,
        )
        assert cards == []

    @pytest.mark.asyncio
    async def test_the_answer_is_the_selected_fact_and_the_quote_its_span(self):
        units = [staged.Unit(_HUNTSMAN["span"], _HUNTSMAN["fact"], "cause")]
        cards = await staged.ask(
            _llm(_Script([], {1: "Why did the huntsman spare Snow White in the forest?"})),
            units,
            PASSAGE,
            model=None,
        )
        assert cards[0]["answer"] == _HUNTSMAN["fact"]
        assert cards[0]["source_excerpt"] == _HUNTSMAN["span"]
        assert cards[0]["depth"] == "explain"


def test_leak_brackets():
    assert not staged.leaks_answer(
        "What is BM25?", "BM25 is a ranking function scoring term frequency"
    )
    assert staged.leaks_answer(
        "Why did Snow White trust the old woman selling apples?",
        "Snow White trusted the old woman",
    )


def _cards():
    return [
        {"question": "Why did the huntsman spare Snow White?", "answer": _HUNTSMAN["fact"]},
        {"question": "Where did Snow White find shelter?", "answer": _COTTAGE["fact"]},
        {"question": "What did the queen feed Snow White?", "answer": "A poisoned comb."},
    ]


class TestVerify:
    @pytest.mark.asyncio
    async def test_the_roundtrip_decides_each_card(self, verifier):
        script = _Script(
            [],
            {},
            blind={
                1: "He pitied her.",
                2: "A cottage where seven dwarfs lived.",
                3: "NOT IN PASSAGE",
            },
            same={1: "yes", 2: "no"},
        )
        got = await staged.verify(_llm(script), _cards(), PASSAGE)
        assert [c["factuality"] for c in got] == [
            FACTUALITY_SUPPORTED,
            FACTUALITY_UNSUPPORTED,
            FACTUALITY_UNSUPPORTED,
        ]
        assert set(script.models) == {"openai/gpt-5.4-mini"}

    @pytest.mark.asyncio
    async def test_the_verifier_never_sees_the_cards_answers_when_answering(self, verifier):
        script = _Script([], {}, blind={1: "x y z"}, same={1: "yes"})
        llm = _llm(script)
        await staged.verify(llm, _cards()[:1], PASSAGE)
        blind_prompt = llm.generate.await_args_list[0].args[0]
        assert _HUNTSMAN["fact"] not in blind_prompt

    @pytest.mark.asyncio
    async def test_no_verdict_is_unverifiable_never_supported(self, verifier):
        script = _Script([], {}, blind={1: "He pitied her.", 2: "A cottage."}, same={1: "maybe"})
        got = await staged.verify(_llm(script), _cards()[:2], PASSAGE)
        assert [c["factuality"] for c in got] == [FACTUALITY_UNVERIFIABLE] * 2

    @pytest.mark.asyncio
    async def test_an_unreachable_verifier_is_unverifiable(self, verifier):
        got = await staged.verify(_llm(_Script([], {}, fail_verifier=True)), _cards(), PASSAGE)
        assert {c["factuality"] for c in got} == {FACTUALITY_UNVERIFIABLE}

    @pytest.mark.asyncio
    async def test_no_verifier_leaves_cards_unchecked_and_costs_no_call(self, monkeypatch):
        monkeypatch.setattr(staged, "factuality_model", lambda: "")
        llm = _llm(_Script([], {}))
        got = await staged.verify(llm, _cards(), PASSAGE)
        assert {c["factuality"] for c in got} == {FACTUALITY_UNCHECKED}
        llm.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_generator_may_not_verify_its_own_cards(self, monkeypatch):
        monkeypatch.setattr(staged, "factuality_model", lambda: "ollama/qwen3.5:4b")
        monkeypatch.setattr(staged, "effective_generation_model", lambda: "ollama/qwen3.5:4b")
        llm = _llm(_Script([], {}))
        got = await staged.verify(llm, _cards(), PASSAGE)
        assert {c["factuality"] for c in got} == {FACTUALITY_UNCHECKED}
        llm.generate.assert_not_awaited()


def test_rank_puts_supported_first_and_spreads_kinds():
    cards = [
        {"kind": "event", "factuality": FACTUALITY_UNVERIFIABLE, "n": 1},
        {"kind": "event", "factuality": FACTUALITY_SUPPORTED, "n": 2},
        {"kind": "event", "factuality": FACTUALITY_SUPPORTED, "n": 3},
        {"kind": "cause", "factuality": FACTUALITY_SUPPORTED, "n": 4},
        {"kind": "claim", "factuality": FACTUALITY_UNSUPPORTED, "n": 5},
    ]
    assert [c["n"] for c in staged.rank(cards, 4)] == [2, 4, 3, 1]


@pytest.mark.asyncio
async def test_the_flag_routes_document_generation_through_the_stages(tmp_path, verifier):
    from app.config import get_settings
    from app.services.flashcard import FlashcardService

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'staged.db'}")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    script = _Script(
        [_HUNTSMAN, _COTTAGE],
        {
            1: "Why did the huntsman spare Snow White in the forest?",
            2: "Where did Snow White find shelter after the forest?",
        },
        blind={1: "He pitied her.", 2: "NOT IN PASSAGE"},
        same={1: "yes"},
    )
    async with factory() as session:
        session.add(
            DocumentModel(
                id="d",
                title="Snow White",
                format="txt",
                content_type="notes",
                stage="complete",
                file_path="/tmp/d.txt",
            )
        )
        session.add(
            ChunkModel(
                id="c0", document_id="d", text=PASSAGE, token_count=60, page_number=1, chunk_index=0
            )
        )
        await session.commit()
        with (
            patch.object(get_settings(), "FLASHCARD_PIPELINE", "staged"),
            patch("app.services.flashcard_generators._get_llm_service", return_value=_llm(script)),
            patch(
                "app.services.flashcard._fetch_existing_embeddings",
                new=AsyncMock(return_value=([], None)),
            ),
            patch("app.services.embedder.get_embedding_service", return_value=None),
        ):
            cards = await FlashcardService().generate(
                document_id="d", scope="full", section_heading=None, count=2, session=session
            )
    await engine.dispose()

    assert [c.answer for c in cards] == [_HUNTSMAN["fact"]]
    assert cards[0].factuality == FACTUALITY_SUPPORTED
    assert cards[0].source_excerpt == _HUNTSMAN["span"]
