"""Card generation honours a per-request model, the way /qa already does.

Study had no way to say which model wrote a card, and no way to show it: the
request carried no model at all, so a card that came back wrong gave the user
nothing to change. The override is per request -- omitting it keeps following the
model chosen in Settings, so the default path is unchanged.

A bad id fails at the edge rather than falling back silently, because a silent
fallback would make "generated with X" a claim the app cannot support.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import ChunkModel, DocumentModel


@pytest.fixture()
async def test_db(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'cards.db'}")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "_engine", engine)
    monkeypatch.setattr(db_module, "_session_factory", factory)
    yield factory
    await engine.dispose()


async def _seed_document(factory, content_type: str = "book") -> str:
    doc_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            DocumentModel(
                id=doc_id,
                title="the_odyssey",
                format="txt",
                content_type=content_type,
                word_count=500,
                page_count=1,
                file_path="/tmp/the_odyssey.txt",
                stage="complete",
                tags=[],
            )
        )
        session.add(
            ChunkModel(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                section_id=None,
                text=(
                    "Penelope set up a great web in her house and told the suitors she "
                    "would choose a husband when it was finished, but she undid her work "
                    "each night for three years."
                ),
                token_count=40,
                page_number=1,
                chunk_index=0,
            )
        )
        await session.commit()
    return doc_id


_PASSAGE = (
    "Penelope set up a great web in her house and told the suitors she would choose "
    "a husband when it was finished, but she undid her work each night for three "
    "years, so the weaving was never done and no choice was ever forced on her."
)

_CARD_JSON = (
    '{"flashcards": [{"question": "How did Penelope delay the suitors?", '
    '"answer": "She unravelled her weaving each night so it was never finished.", '
    '"source_excerpt": "", "bloom_level": 3}]}'
)


@pytest.mark.asyncio
async def test_requested_model_is_the_one_asked_to_write_the_cards(test_db):
    doc_id = await _seed_document(test_db)
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_CARD_JSON)

    with patch("app.services.flashcard.get_llm_service", return_value=llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/flashcards/generate",
                json={
                    "document_id": doc_id,
                    "count": 1,
                    "model": "ollama/phi4-mini",
                    "context": _PASSAGE,
                },
            )

    assert resp.status_code == 201, resp.text
    models = {call.kwargs.get("model") for call in llm.generate.await_args_list}
    assert models == {"ollama/phi4-mini"}, (
        f"the requested model must be the one that generates; saw {models}"
    )


@pytest.mark.asyncio
async def test_omitting_the_model_keeps_following_settings(test_db, monkeypatch):
    """With no generation override configured, the request pins nothing.

    The override is established here rather than assumed. Reading it from the
    ambient environment made this test fail on any machine with
    LITELLM_GENERATION_MODEL set -- a supported configuration, so the test was
    wrong rather than the machine. Same monkeypatch as
    `test_model_registry.test_generation_follows_settings_when_no_override_is_configured`.
    """
    from app.services import model_router

    monkeypatch.setattr(model_router, "configured_generation_override", lambda: None)

    doc_id = await _seed_document(test_db)
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_CARD_JSON)

    with patch("app.services.flashcard.get_llm_service", return_value=llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/flashcards/generate",
                json={"document_id": doc_id, "count": 1, "context": _PASSAGE},
            )

    assert resp.status_code == 201, resp.text
    # None means "let LLMService route it", which is what carries the Settings
    # choice and the offline reroute. Pinning an id here would lose both.
    assert all(call.kwargs.get("model") is None for call in llm.generate.await_args_list)


@pytest.mark.asyncio
async def test_a_configured_override_generates_with_that_model(test_db, monkeypatch):
    """The other half of the same rule, which nothing covered.

    LITELLM_GENERATION_MODEL exists to send generation somewhere other than chat.
    A request that names no model must follow it -- and the earlier assertion,
    which expected None unconditionally, would have called that behaviour a bug.
    """
    from app.services import model_router

    monkeypatch.setattr(
        model_router, "configured_generation_override", lambda: "ollama/some-other-model"
    )

    doc_id = await _seed_document(test_db)
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=_CARD_JSON)

    with patch("app.services.flashcard.get_llm_service", return_value=llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/flashcards/generate",
                json={"document_id": doc_id, "count": 1, "context": _PASSAGE},
            )

    assert resp.status_code == 201, resp.text
    models = {call.kwargs.get("model") for call in llm.generate.await_args_list}
    assert models == {"ollama/some-other-model"}, f"saw {models}"


@pytest.mark.asyncio
async def test_a_malformed_model_id_is_refused_rather_than_ignored(test_db):
    doc_id = await _seed_document(test_db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/flashcards/generate",
            json={"document_id": doc_id, "count": 1, "model": "qwen3.5:4b"},
        )
    assert resp.status_code == 422, "a provider-less id must not reach LiteLLM"


@pytest.mark.asyncio
async def test_technical_generation_takes_the_override_too(test_db):
    doc_id = await _seed_document(test_db, content_type="tech_book")
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=(
            '[{"question": "What does the web delay?", "answer": "The demand of the suitors.", '
            '"flashcard_type": "concept", "bloom_level": 3}]'
        )
    )

    with patch("app.services.flashcard.get_llm_service", return_value=llm):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/flashcards/generate-technical",
                json={"document_id": doc_id, "count": 1, "model": "ollama/phi4-mini"},
            )

    assert resp.status_code == 201, resp.text
    models = {call.kwargs.get("model") for call in llm.generate.await_args_list}
    assert models == {"ollama/phi4-mini"}, f"saw {models}"
