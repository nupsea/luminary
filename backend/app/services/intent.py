"""Intent classification for the V2 agentic chat router.

classify_intent_heuristic — pure function, no imports from other app layers.
_llm_classify_fallback    — async, calls LiteLLM when heuristic confidence < 0.7.
"""

import logging

import litellm

logger = logging.getLogger(__name__)

_VALID_INTENTS: frozenset[str] = frozenset(
    {"summary", "factual", "relational", "comparative", "exploratory"}
)

# Keyword sets — order matters: checked top to bottom, first match wins.
_SUMMARY_KWS: frozenset[str] = frozenset(
    {
        "summarize",
        "summary",
        "overview",
        "what is this about",
        "what are the themes",
        "what are the main",
        "main theme",
        "main topics",
        "key theme",
        "major theme",
        "core theme",
        "main points",
        "key ideas",
        "synopsis",
        "brief me",
        "give me a summary",
        "tell me about",
        "what do these",
        "across all",
        "across my",
    }
)

_RELATIONAL_KWS: frozenset[str] = frozenset(
    {
        "how are",
        "relation between",
        "connection between",
        "what is the relationship",
    }
)

_COMPARATIVE_KWS: frozenset[str] = frozenset(
    {
        "compare",
        "difference between",
        "how is",
        "different",
        "versus",
        "vs.",
        "similarities",
    }
)

_FACTUAL_KWS: frozenset[str] = frozenset(
    {
        "explain",
        "what does",
        "who is",
        "where is",
        "when did",
        "which",
        "list all",
        "how many",
        "what happened",
    }
)


def classify_intent_heuristic(question: str) -> tuple[str, float]:
    """Pure function — no imports from other app layers.

    Keyword-match rules in priority order (first match wins):
      summary    confidence=0.9
      relational confidence=0.85
      comparative confidence=0.85
      factual    confidence=0.8
      exploratory confidence=0.5 (catch-all)

    Returns:
        (intent_str, confidence_float)
    """
    q = question.lower()

    if any(kw in q for kw in _SUMMARY_KWS):
        return ("summary", 0.9)
    if any(kw in q for kw in _RELATIONAL_KWS):
        return ("relational", 0.85)
    if any(kw in q for kw in _COMPARATIVE_KWS):
        return ("comparative", 0.85)
    if any(kw in q for kw in _FACTUAL_KWS):
        return ("factual", 0.8)
    return ("exploratory", 0.5)


async def _llm_classify_fallback(question: str, default: str, scope: str = "all") -> str:
    """Call LiteLLM to classify intent when heuristic confidence < 0.7.

    The model is asked to reply with exactly one of the five intent words.
    Falls back to 'factual' (not `default`) when the LLM is offline or
    returns an unrecognised token — because factual is the safest retrieval mode.

    Args:
        question: raw user question
        default: the heuristic's best guess (used only for logging)
        scope: 'single' (one document) or 'all' (entire library)

    Returns:
        intent string (one of the five valid intents)
    """
    from app.config import get_settings  # noqa: PLC0415

    scope_hint = (
        "The user is asking about their ENTIRE document library (all content)."
        if scope == "all"
        else "The user is asking about a SINGLE specific document."
    )
    try:
        model = get_settings().LITELLM_DEFAULT_MODEL
        response = await litellm.acompletion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{scope_hint} "
                        "Classify the question. Reply with exactly one word: "
                        "summary, factual, relational, comparative, or exploratory. "
                        "Use 'summary' for broad questions about themes, topics, patterns, "
                        "or overviews — especially when scope is the entire library."
                    ),
                },
                {"role": "user", "content": question},
            ],
            temperature=0.0,
        )
        result = (response.choices[0].message.content or "").strip().lower()
        if result in _VALID_INTENTS:
            logger.debug(
                "intent LLM: %r → %s (heuristic default was %s)", question[:60], result, default
            )
            return result
        logger.debug("intent LLM returned unrecognised %r, falling back to 'factual'", result)
        return "factual"
    except Exception:
        logger.warning(
            "intent LLM fallback failed (Ollama offline?), defaulting to 'factual'",
            exc_info=True,
        )
        return "factual"
