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

    Returns fixed content for any prompt. Handles both streaming (stream=True)
    and non-streaming modes. Tracks call_count for assertion purposes.
    """

    def __init__(self, response: str = "mock response", tokens: list[str] | None = None):
        self._response = response
        self._tokens = tokens or [response]
        self.call_count = 0

    async def generate(
        self, prompt: str, system: str = "", stream: bool = False, model=None
    ):
        self.call_count += 1
        if stream:

            async def _gen():
                for t in self._tokens:
                    yield t

            return _gen()
        return self._response


class CapturingLLMService(MockLLMService):
    """Extends MockLLMService to record every prompt and system argument.

    Use when a test needs to assert on what was passed to the LLM
    (e.g. verifying that the right instruction mode is in the system prompt).
    """

    def __init__(self, response: str = "ok", tokens: list[str] | None = None):
        super().__init__(response=response, tokens=tokens)
        self.captured_prompts: list[str] = []
        self.captured_systems: list[str] = []

    async def generate(
        self, prompt: str, system: str = "", stream: bool = False, model=None
    ):
        self.captured_prompts.append(prompt)
        self.captured_systems.append(system)
        return await super().generate(prompt, system, stream, model)
