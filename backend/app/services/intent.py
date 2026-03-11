"""Intent classification for the V2 agentic chat router.

classify_intent_heuristic — pure function, no imports from other app layers.
_llm_classify_fallback    — async, calls LiteLLM when heuristic confidence < 0.7.
"""

import logging

import litellm

logger = logging.getLogger(__name__)

_VALID_INTENTS: frozenset[str] = frozenset(
    {"summary", "factual", "relational", "comparative", "exploratory", "notes", "notes_gap",
     "socratic"}
)

# Keyword sets — order matters: checked top to bottom, first match wins.
# These are hints only; the LLM classifier handles ambiguous cases (threshold < 0.9).
_SOCRATIC_KWS: frozenset[str] = frozenset(
    {
        "quiz me",
        "test me",
        "ask me a question",
        "ask me questions",
        "socratic mode",
        "give me a question",
        "question me",
        "what should i know",
    }
)

_NOTES_GAP_KWS: frozenset[str] = frozenset(
    {
        "find gaps in my notes",
        "gaps in my notes",
        "what am i missing",
        "what am i missing from",
        "compare my notes",
        "compare notes with",
        "notes vs book",
        "gaps between my notes",
        "missing from my notes",
        "what have i missed",
        "notes against the book",
        "notes versus the book",
        "my notes vs",
    }
)

_NOTES_KWS: frozenset[str] = frozenset(
    {
        "my notes", "i wrote", "i noted", "i have noted",
        "according to my notes", "in my notes", "from my notes",
        "what did i note", "what have i noted", "what i wrote",
    }
)

_SUMMARY_KWS: frozenset[str] = frozenset(
    {
        # Explicit summary requests
        "summarize", "summary", "synopsis", "overview", "outline",
        "give me a summary", "give an overview", "brief me",
        # Theme/topic breadth
        "what are the themes", "what are the main", "what is this about",
        "main theme", "main topics", "main points", "main ideas",
        "key theme", "key ideas", "key takeaways", "key points",
        "major theme", "core theme", "central theme",
        "major topics", "important topics",
        # Big-picture language
        "big picture", "high level", "high-level",
        "across all", "across my",
        # Common phrasings
        "what does this book", "what does this document", "what is the book about",
        "what is the document about", "what covers",
    }
)

_RELATIONAL_KWS: frozenset[str] = frozenset(
    {
        # Explicit relationship words
        "relation between", "relationship between", "connection between",
        "what is the relationship", "what connects", "what links",
        # "related to" / "connected to"
        "related to", "connected to", "associated with",
        "link between", "ties between", "bond between",
        "interaction between",
        # How-phrased relational queries
        "how are", "how is", "how do",
        "how does", "how did",
    }
)

_COMPARATIVE_KWS: frozenset[str] = frozenset(
    {
        # Explicit comparison
        "compare", "comparison", "compare and contrast", "contrast",
        # Difference
        "difference between", "differences between", "what distinguishes",
        "how do they differ", "how are they different",
        # Similarity
        "similarities between", "what do they have in common", "in common",
        "alike", "similar to",
        # Versus
        "versus", "vs.", "vs ",
        # Better/worse
        "better than", "worse than", "superior to", "inferior to",
    }
)

_FACTUAL_KWS: frozenset[str] = frozenset(
    {
        # Who
        "who is", "who was", "who are", "who were", "who did",
        # What
        "what is", "what was", "what are", "what were",
        "what does", "what did", "what happened", "what happens",
        # Where / When
        "where is", "where was", "where are",
        "when did", "when was", "when is", "when does",
        # How (quantitative)
        "how many", "how much", "how long", "how often", "how old",
        # Lists and definitions
        "list all", "list the", "name all", "name the",
        "define", "definition of",
        # Description and explanation
        "describe", "explain", "what is the meaning", "what does it mean",
        # Examples
        "give an example", "examples of", "what are examples",
        # Which / other specifiers
        "which", "what year", "what time",
    }
)


def classify_intent_heuristic(question: str) -> tuple[str, float]:
    """Pure function — no imports from other app layers.

    Keyword-match rules in priority order (first match wins):
      summary    confidence=0.9  — bypasses LLM classifier (threshold=0.9)
      relational confidence=0.85 — falls through to LLM classifier as a hint
      comparative confidence=0.85 — falls through to LLM classifier as a hint
      factual    confidence=0.8  — falls through to LLM classifier as a hint
      exploratory confidence=0.5 (catch-all) — falls through to LLM classifier

    Returns:
        (intent_str, confidence_float)
    """
    q = question.lower()

    if any(kw in q for kw in _SOCRATIC_KWS):
        return ("socratic", 0.95)
    if any(kw in q for kw in _NOTES_GAP_KWS):
        return ("notes_gap", 0.95)
    if any(kw in q for kw in _NOTES_KWS):
        return ("notes", 0.95)
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
                        "summary, factual, relational, comparative, "
                        "exploratory, notes, notes_gap, or socratic. "
                        "Use 'socratic' for requests to be quizzed or tested. "
                        "Use 'notes_gap' for questions asking to compare notes against "
                        "a book or find gaps. "
                        "Use 'notes' for questions about the user's personal notes or annotations. "
                        "Use 'summary' for broad questions about themes, topics, patterns, "
                        "or overviews -- especially when scope is the entire library."
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
