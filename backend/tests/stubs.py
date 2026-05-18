"""Deterministic service stubs for tests (Belief #25).

Use these instead of MagicMock for domain services.
Reserve MagicMock for true external boundaries (LiteLLM, httpx, SQLAlchemy).
"""


class MockEmbeddingService:
    """Returns a deterministic 1024-dim vector for any input text."""

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1024 for _ in texts]


class MockLLMService:
    """Deterministic LLM stub for unit tests.

    Mirrors services.llm.LLMService surface: generate(prompt, system, stream=...),
    complete(messages, ...), stream_messages(messages, ...).
    """

    def __init__(self, response: str = "mock response", tokens: list[str] | None = None):
        self._response = response
        self._tokens = tokens or [response]
        self.call_count = 0

    async def generate(
        self, prompt: str, system: str = "", stream: bool = False, model=None, **kwargs
    ):
        self.call_count += 1
        if stream:
            return self._token_gen()
        return self._response

    async def complete(self, messages, **kwargs):
        self.call_count += 1
        return self._response

    async def stream_messages(self, messages, **kwargs):
        self.call_count += 1
        return self._token_gen()

    async def _token_gen(self):
        for t in self._tokens:
            yield t


class CapturingLLMService(MockLLMService):
    """Extends MockLLMService to record arguments passed to the LLM."""

    def __init__(self, response: str = "ok", tokens: list[str] | None = None):
        super().__init__(response=response, tokens=tokens)
        self.captured_prompts: list[str] = []
        self.captured_systems: list[str] = []
        self.captured_messages: list[list[dict]] = []

    async def generate(
        self, prompt: str, system: str = "", stream: bool = False, model=None, **kwargs
    ):
        self.captured_prompts.append(prompt)
        self.captured_systems.append(system)
        return await super().generate(prompt, system, stream, model)

    async def complete(self, messages, **kwargs):
        self.captured_messages.append(messages)
        return await super().complete(messages, **kwargs)

    async def stream_messages(self, messages, **kwargs):
        self.captured_messages.append(messages)
        return await super().stream_messages(messages, **kwargs)
