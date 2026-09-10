"""The evaluator's lists, kept in the shape the store and the schema agree on.

The prompt asks each of `correct_points`, `missing_points` and `misconceptions`
for a list of strings. A model answered one nesting deeper --
`"misconceptions": [["a", "b"]]` -- and the row was written verbatim, so every
later read of that session failed `TeachbackResultItem` with a 500. One
malformed verdict took out the whole run's results, and a reader could not start
a teach-back on that document again: the deck's "Explain it" reported "Could not
start the run. Is the backend reachable?" while the backend was fine.

Flattening happens on the way in, so no new row can carry the shape, and on the
way out, so a row already holding it is readable rather than fatal.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

import app.database as db_module
from app.database import make_engine
from app.db_init import create_all_tables
from app.main import app
from app.models import TeachbackResultModel
from app.routers.study import _string_list


def test_a_nested_list_is_flattened():
    assert _string_list([["a", "b"], "c"]) == ["a", "b", "c"]


def test_strings_survive_unchanged():
    assert _string_list(["one point", "another"]) == ["one point", "another"]


def test_blanks_and_none_are_dropped():
    assert _string_list(None) == []
    assert _string_list(["", "  ", "kept"]) == ["kept"]


def test_a_scalar_is_not_silently_lost():
    """A number in the list is shown, not dropped: what the model said is data."""
    assert _string_list([1, "two"]) == ["1", "two"]


@pytest.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    await create_all_tables(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    orig_engine = db_module._engine
    orig_factory = db_module._session_factory
    db_module._engine = engine
    db_module._session_factory = factory

    yield engine, factory, tmp_path

    db_module._engine = orig_engine
    db_module._session_factory = orig_factory
    get_settings.cache_clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_session_holding_a_nested_verdict_still_reads(test_db):
    """The row that used to 500 the endpoint comes back, flattened."""
    _engine, factory, _tmp = test_db
    session_id = str(uuid.uuid4())
    async with factory() as db:
        db.add(
            TeachbackResultModel(
                id=str(uuid.uuid4()),
                flashcard_id=str(uuid.uuid4()),
                user_explanation="Concepts are tags in a list.",
                score=40,
                correct_points=["named the concept layer"],
                missing_points=[],
                misconceptions=[["Concepts are just tags", "stored in a list"]],
                status="complete",
                session_id=session_id,
                created_at=datetime.now(UTC),
            )
        )
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/study/sessions/{session_id}/teachback-results")

    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["misconceptions"] == ["Concepts are just tags", "stored in a list"]
