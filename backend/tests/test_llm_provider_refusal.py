"""A cloud provider that refuses a call is asked again, named, and never hidden (#514).

The bodies are Gemini's: a per-minute limit names a 12 s retryDelay, a daily quota
names 31 s with nothing left until tomorrow. litellm raised the daily one as a
ServiceUnavailableError in the field, which the app called "unreachable".
"""

import json
from unittest.mock import MagicMock, patch

import litellm
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import connectivity, enrichment_outcome
from app.services import llm as llm_module
from app.services import settings_service as ss
from app.services.llm import LLMService, describe_llm_failure, provider_refusal
from tests.factories import make_document


def _gemini_body(quota_id: str, delay: str, message: str) -> str:
    return json.dumps(
        {
            "error": {
                "code": 429,
                "message": message,
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": quota_id}],
                    },
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay},
                ],
            }
        }
    )


def per_minute(delay: str = "12s") -> Exception:
    return litellm.RateLimitError(
        message="geminiException - "
        + _gemini_body(
            "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
            delay,
            "You exceeded your current quota. Please retry in 12.4s.",
        ),
        llm_provider="gemini",
        model="gemini-3.8-flash",
    )


def daily_quota_as_unavailable() -> Exception:
    return litellm.ServiceUnavailableError(
        message="geminiException - "
        + _gemini_body(
            "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "31s",
            "Quota exceeded for metric: generate_content_free_tier_requests, limit: 20",
        ),
        llm_provider="gemini",
        model="gemini-3.8-flash",
    )


def overloaded() -> Exception:
    return litellm.ServiceUnavailableError(
        message='geminiException - {"error": {"code": 503, "message": "The model is '
        'overloaded. Please try again later.", "status": "UNAVAILABLE"}}',
        llm_provider="gemini",
        model="gemini-3.8-flash",
    )


def unreachable() -> Exception:
    try:
        raise litellm.InternalServerError(
            message="geminiException - Connection error", llm_provider="gemini", model="x"
        ) from ConnectionError("Cannot connect to host generativelanguage.googleapis.com:443")
    except litellm.InternalServerError as exc:
        return exc


def _response(text: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=text))]
    response.usage = None
    return response


@pytest.fixture(autouse=True)
def gemini_routing(monkeypatch):
    connectivity.reset_cache()
    monkeypatch.setattr(connectivity, "provider_reachable", lambda model: True)
    original = dict(ss._cache)
    ss._cache.update(
        {
            "llm_mode": "cloud",
            "cloud_provider": "gemini",
            "cloud_model": "gemini-3.8-flash",
            "google_api_key": "not-a-real-key",
        }
    )
    yield
    ss._cache.clear()
    ss._cache.update(original)
    connectivity.reset_cache()


@pytest.fixture
def waits(monkeypatch):
    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(llm_module, "_pause", _sleep)
    return slept


def _calls(*outcomes):
    """litellm.acompletion that answers each call with the next outcome."""
    calls: list[str] = []

    async def side_effect(**kwargs):
        calls.append(kwargs["model"])
        outcome = outcomes[min(len(calls), len(outcomes)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return _response(outcome)

    return side_effect, calls


async def test_a_rate_limit_is_asked_again_after_its_stated_delay(waits):
    side_effect, calls = _calls(per_minute(), "cloud answer")
    with patch("litellm.acompletion", side_effect=side_effect):
        assert await LLMService().complete([{"role": "user", "content": "hi"}]) == "cloud answer"

    assert calls == ["gemini/gemini-3.8-flash"] * 2
    assert waits == [12.0]


async def test_an_overloaded_provider_is_asked_again_before_the_local_model(waits):
    side_effect, calls = _calls(overloaded(), overloaded(), overloaded(), "local answer")
    with patch("litellm.acompletion", side_effect=side_effect):
        assert await LLMService().complete([{"role": "user", "content": "hi"}]) == "local answer"

    assert calls[:3] == ["gemini/gemini-3.8-flash"] * 3
    assert calls[3].startswith("ollama/")
    assert len(waits) == 2


async def test_a_spent_quota_is_not_waited_for_or_sent_to_the_local_model(waits):
    side_effect, calls = _calls(daily_quota_as_unavailable(), "local answer")
    with (
        patch("litellm.acompletion", side_effect=side_effect),
        pytest.raises(litellm.ServiceUnavailableError) as raised,
    ):
        await LLMService().complete([{"role": "user", "content": "hi"}])

    assert calls == ["gemini/gemini-3.8-flash"]
    assert waits == []
    assert describe_llm_failure(raised.value, "gemini/gemini-3.8-flash") == (
        "gemini/gemini-3.8-flash refused the calls: its quota is used up"
    )


async def test_a_wait_past_a_minute_is_not_taken(waits):
    side_effect, calls = _calls(per_minute("3600s"), "cloud answer")
    with (
        patch("litellm.acompletion", side_effect=side_effect),
        pytest.raises(litellm.RateLimitError),
    ):
        await LLMService().complete([{"role": "user", "content": "hi"}])
    assert calls == ["gemini/gemini-3.8-flash"]
    assert waits == []


async def test_a_host_without_local_inference_gets_the_providers_error(monkeypatch, waits):
    monkeypatch.setattr(llm_module, "_local_inference_supported", lambda: False)
    side_effect, calls = _calls(unreachable(), "local answer")
    with (
        patch("litellm.acompletion", side_effect=side_effect),
        pytest.raises(litellm.InternalServerError),
    ):
        await LLMService().complete([{"role": "user", "content": "hi"}])
    assert calls == ["gemini/gemini-3.8-flash"]


def test_refusals_are_told_apart_from_an_outage():
    assert provider_refusal(per_minute()).kind == "rate_limit"
    assert provider_refusal(daily_quota_as_unavailable()).kind == "quota"
    assert provider_refusal(overloaded()).kind == "overloaded"
    assert provider_refusal(unreachable()) is None
    assert describe_llm_failure(unreachable(), "gemini/x") == "gemini/x could not be reached"


async def test_a_document_left_unenriched_says_why_until_the_work_exists(memory_db, waits):
    doc = make_document(title="Art of Unix, ch. 1")
    async with memory_db.factory() as session:
        session.add(doc)
        await session.commit()

    side_effect, _ = _calls(daily_quota_as_unavailable())
    with (
        patch("litellm.acompletion", side_effect=side_effect),
        enrichment_outcome.for_document(doc.id),
        pytest.raises(litellm.ServiceUnavailableError),
    ):
        await LLMService().complete([{"role": "user", "content": "summarise"}], background=True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        notice = (await client.get(f"/documents/{doc.id}")).json()["enrichment_notice"]
        assert notice.startswith(
            "No summaries were written for this document: "
            "gemini/gemini-3.8-flash refused the calls: its quota is used up."
        )

        from app.models import SummaryModel  # noqa: PLC0415

        async with memory_db.factory() as session:
            session.add(SummaryModel(id="s1", document_id=doc.id, mode="executive", content="x"))
            await session.commit()
        assert (await client.get(f"/documents/{doc.id}")).json()["enrichment_notice"] is None
