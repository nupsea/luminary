"""Summarization prompts must fit the context window they are generated in.

Ollama's num_ctx bounds prompt + generation and truncates the prompt from the
FRONT, so an over-budget summarization input silently discards the system
message. The model then free-associates on a tail slice of the source ("It
sounds like you've shared a transcript...") instead of summarizing it.
"""

import uuid
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.services.summarizer import (
    _CHARS_PER_TOKEN,
    SummarizationService,
    _input_token_budget,
    _summary_num_ctx,
)


class _RecordingLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, prompt, system="", model=None, stream=False, **kwargs):
        self.calls.append({"prompt": prompt, "system": system, **kwargs})
        if stream:

            async def _gen():
                yield "summary"

            return _gen()
        return "summary"


def test_input_budget_leaves_room_for_system_and_output():
    assert _input_token_budget() < _summary_num_ctx()


def test_num_ctx_is_the_generation_window():
    assert _summary_num_ctx() == get_settings().OLLAMA_GENERATION_NUM_CTX


@pytest.mark.asyncio
async def test_stream_summary_passes_num_ctx_and_stays_in_budget(monkeypatch):
    svc = SummarizationService()
    llm = _RecordingLLM()

    oversized = "word " * (_input_token_budget() * _CHARS_PER_TOKEN)

    async def _no_cache(*args, **kwargs):
        return None

    async def _sections(*args, **kwargs):
        return oversized

    async def _store(*args, **kwargs):
        return str(uuid.uuid4())

    monkeypatch.setattr(svc, "_fetch_cached", _no_cache)
    monkeypatch.setattr(svc, "_build_section_summary_input", _sections)
    monkeypatch.setattr(svc, "_store_summary", _store)

    with patch("app.services.summarizer.get_llm_service", return_value=llm):
        _ = [e async for e in svc.stream_summary("doc-1", "executive", None)]

    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert call["num_ctx"] == _summary_num_ctx()
    assert call["system"], "system prompt must be sent"

    prompt_tokens = len(call["prompt"]) // _CHARS_PER_TOKEN
    assert prompt_tokens <= _input_token_budget()


@pytest.mark.asyncio
async def test_pregenerate_passes_num_ctx(monkeypatch):
    svc = SummarizationService()
    llm = _RecordingLLM()

    async def _no_cache(*args, **kwargs):
        return None

    async def _sections(*args, **kwargs):
        return "## Heading\nsome section summary text"

    async def _store(*args, **kwargs):
        return str(uuid.uuid4())

    monkeypatch.setattr(svc, "_fetch_cached", _no_cache)
    monkeypatch.setattr(svc, "_build_section_summary_input", _sections)
    monkeypatch.setattr(svc, "_store_summary", _store)

    with patch("app.services.summarizer.get_llm_service", return_value=llm):
        await svc.pregenerate("doc-1")

    assert llm.calls, "pregenerate made no LLM call"
    assert all(c["num_ctx"] == _summary_num_ctx() for c in llm.calls)
