"""Intent classification for the V2 agentic chat router.

classify_intent_heuristic — pure function, no imports from other app layers.
_llm_classify_fallback    — async, calls LiteLLM when heuristic confidence < 0.7.
"""

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

_VALID_INTENTS: frozenset[str] = frozenset(
    {
        "summary",
        "factual",
        "relational",
        "comparative",
        "exploratory",
        "notes",
        "notes_gap",
        "socratic",
        "teach_back",
    }
)

# Intents the LLM classifier may not choose. Each of these switches the chat out
# of question-answering and into an interactive mode: teach_back grades the
# message as a learner's explanation, socratic answers with a question, and the
# notes modes read personal notes instead of the document. A mode is only right
# when the user's own phrasing asks for it -- which the heuristic already detects
# at 0.95 and returns without ever consulting the LLM. So by construction the LLM
# is only asked about questions that are NOT a mode request, and any mode answer
# it gives is a misfire: a plain question ("To what extent can Lloyd's algorithm
# ...") came back as teach_back and was graded as an explanation the user never
# wrote, producing an empty "what you got right / misconceptions / gaps" card.
_MODE_INTENTS: frozenset[str] = frozenset(
    {"teach_back", "socratic", "notes", "notes_gap"}
)

_LLM_SELECTABLE_INTENTS: frozenset[str] = _VALID_INTENTS - _MODE_INTENTS

# Keyword sets — order matters: checked top to bottom, first match wins.
# These are hints only; the LLM classifier handles ambiguous cases (threshold < 0.9).
_TEACH_BACK_KWS: frozenset[str] = frozenset(
    {
        "let me explain",
        "i think this means",
        "i understand this as",
        "my understanding is",
        "in my own words",
        "i believe that",
        "if i understand correctly",
        "here is my understanding",
    }
)

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
        "my notes",
        "i wrote",
        "i noted",
        "i have noted",
        "according to my notes",
        "in my notes",
        "from my notes",
        "what did i note",
        "what have i noted",
        "what i wrote",
    }
)

_SUMMARY_KWS: frozenset[str] = frozenset(
    {
        # Explicit summary requests
        "summarize",
        "summary",
        "synopsis",
        "overview",
        "outline",
        "give me a summary",
        "give an overview",
        "brief me",
        # Theme/topic breadth
        "what are the themes",
        "what are the main",
        "what is this about",
        "main theme",
        "main topics",
        "main points",
        "main ideas",
        "key theme",
        "key ideas",
        "key takeaways",
        "key points",
        "major theme",
        "core theme",
        "central theme",
        "major topics",
        "important topics",
        # Big-picture language
        "big picture",
        "high level",
        "high-level",
        "across all",
        "across my",
        # Common phrasings
        "what does this book",
        "what does this document",
        "what is the book about",
        "what is the document about",
        "what covers",
        # Summary words that lived only in qa.py's parallel list. Two sets for one
        # concept disagreed: "Recap the document" routed to search here while
        # counting as summary intent there.
        "recap",
        "gist",
        "tldr",
        "tl;dr",
    }
)

# Some intents are a sentence shape rather than a phrase. "What is <this|the>
# <noun> about?" is combinatorial in the determiner and in the noun -- and the
# noun is whatever the user calls their own document, which no corpus can
# enumerate. Matching the shape generalises to documents the goldens never saw;
# listing the phrasings only ever fits the goldens.
_SUMMARY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bwhat(?:'s|s| is| are)\s+(?:this|that|the|it|these|those)\b"
        r"[\w\s-]{0,24}\babout\b"
    ),
    re.compile(r"\bwhat\s+(?:is|are)\s+[\w\s-]{0,24}\b(?:mainly|broadly|generally)\s+about\b"),
)

_RELATIONAL_KWS: frozenset[str] = frozenset(
    {
        # Explicit relationship words
        "relation between",
        "relationship between",
        "connection between",
        "what is the relationship",
        # "what <relation verb>" — a family, completed. The set already held
        # connects/links while "ties" existed only as the noun "ties between", so
        # "What ties X to Y?" matched nothing and fell through to search.
        "what connects",
        "what links",
        "what ties",
        "what relates",
        "what binds",
        "what joins",
        # "related to" / "connected to"
        "related to",
        "connected to",
        "associated with",
        "link between",
        "ties between",
        "bond between",
        "interaction between",
        # How-phrased relational queries. These are question openers rather than
        # relationship words, and they carry graph queries that name no relation
        # word ("how are the Eloi and the Morlocks connected" is caught by
        # "connected to", but many are not). Removing them cost graph recall
        # 0.9231 -> 0.6154, so they stay: the defect was never that they exist,
        # only that first-match-wins let "how do" outrank the longer, more
        # specific "how do they differ".
        "how are",
        "how is",
        "how do",
        "how does",
        "how did",
    }
)

# Some intents are a sentence shape, not a phrase. These carry the questions that
# state an intent WITHOUT its keyword -- a comparison with no "compare", a
# relation with no "connect" -- which fell through to search: on the adversarial
# routing set, comparative recall was 0.29 and graph 0.33 while both held perfect
# precision, the signature of a trigger that only fires on its own word.
#
# Slots are bounded and stop at "?" so a shape cannot span two questions. Each
# one names a structure, never a subject: what a user calls their own topics is
# not enumerable, which is the whole reason keywords ran out.
_COMPARATIVE_SHAPES: tuple[re.Pattern[str], ...] = (
    # "Which of X and Y ...", "which one of X or Y ..." -- choosing between
    # named alternatives is a comparison whatever verb follows.
    re.compile(r"\bwhich (?:one )?of\b[^?]{0,70}\b(?:and|or)\b"),
    # "if I had to choose between X and Y", "deciding between X and Y".
    re.compile(
        r"\b(?:choose|choosing|chose|decide|deciding|pick|picking|select|prefer)\b"
        r"[^?]{0,30}\bbetween\b"
    ),
    # A polar question offering two alternatives: "Is X or Y the better fit?".
    # Anchored at the start so a mid-sentence "or" in an ordinary question does
    # not qualify.
    re.compile(
        r"^\s*(?:is|are|was|were|do|does|did|should|would|will|can|could)\b"
        r"[^?]{0,80}\bor\b[^?]{0,80}"
    ),
    # Two subjects and a verb of (dis)agreement: "where do X and Y disagree",
    # "the points where A and B diverge". The family completed the way the
    # relation verbs were -- `differ` was already a keyword, its siblings were
    # not.
    re.compile(
        r"\b(?:and|or)\b[^?]{0,50}\b(?:disagree|agrees?|agreed|diverge[sd]?|"
        r"converge[sd]?|overlaps?|conflict|clash)\b"
    ),
)

_RELATIONAL_SHAPES: tuple[re.Pattern[str], ...] = (
    # "What sits between X and Y", "the step between X and Y" -- `between ... and`
    # asks about what lies across two things. A comparison phrased this way
    # ("difference between X and Y") matches a comparative keyword too, and the
    # more specific match already wins.
    re.compile(r"\bbetween\b[^?]{0,50}\band\b"),
    # The relation-verb family, extended from "what connects" to the same verbs
    # used in the middle of a sentence: "X leads into Y", "how A feeds into B".
    re.compile(
        r"\b(?:leads?|led|feeds?|fed|flows?|points?|ties?|links?|connects?|relates?|"
        r"contributes?|builds?|follows?)\s+(?:in)?to\b"
    ),
    # "What does X have to do with Y" -- an idiom whose slots are the subjects,
    # matched as a shape for the same reason "what is <this> <noun> about" is.
    re.compile(r"\b(?:have|has|had|having)\s+to\s+do\s+with\b"),
    # A path between two things: "from X through to Y", "from A into B". Plain
    # "from X to Y" is deliberately excluded -- it is how page and date ranges
    # are written, and it would take ordinary lookups into the graph route.
    re.compile(r"\bfrom\b[^?]{0,60}\b(?:through to|into|onto|towards?)\b"),
)

_COMPARATIVE_KWS: frozenset[str] = frozenset(
    {
        # Explicit comparison
        "compare",
        "comparison",
        "compare and contrast",
        "contrast",
        # Difference. The word forms are listed rather than a "differ" stem
        # because matching is word-boundary anchored, and they are what catches a
        # comparison of named subjects: the set previously held only the pronoun
        # phrasings ("how do THEY differ"), so "How are Penelope and Minerva
        # different?" matched nothing here and fell to the relational openers.
        "differ",
        "differs",
        "different",
        "difference between",
        "differences between",
        "what distinguishes",
        # Similarity
        "similarity",
        "similarities",
        "similarities between",
        "what do they have in common",
        "in common",
        "alike",
        "similar to",
        # Versus
        "versus",
        "vs.",
        "vs ",
        # Better/worse
        "better than",
        "worse than",
        "superior to",
        "inferior to",
    }
)

# Generative-synthesis requests ("write a kids story based on ...", "turn this
# into a poem"). These match no question keyword and would otherwise fall to the
# exploratory catch-all at 0.5, deferring to the LLM classifier -- which mislabels
# them teach_back/notes and routes AWAY from retrieval, so the grounding content is
# never fetched. They are open-ended generation grounded in the corpus: route to
# search_node with confidence high enough to skip the LLM.
_GENERATIVE_KWS: frozenset[str] = frozenset(
    {
        "write a",
        "write an",
        "write me",
        "write us",
        "generate a",
        "generate an",
        "create a",
        "create an",
        "compose a",
        "compose an",
        "compose me",
        "make up a",
        "make me a",
        "draft a",
        "draft an",
        "draft me",
        "turn this into",
        "turn it into",
        "turn these into",
        "tell me a story",
        "tell a story",
    }
)

_FACTUAL_KWS: frozenset[str] = frozenset(
    {
        # Who
        "who is",
        "who was",
        "who are",
        "who were",
        "who did",
        # What
        "what is",
        "what was",
        "what are",
        "what were",
        "what does",
        "what did",
        "what happened",
        "what happens",
        # Where / When
        "where is",
        "where was",
        "where are",
        "when did",
        "when was",
        "when is",
        "when does",
        # How (quantitative)
        "how many",
        "how much",
        "how long",
        "how often",
        "how old",
        # Lists and definitions
        "list all",
        "list the",
        "name all",
        "name the",
        "define",
        "definition of",
        # Description and explanation
        "describe",
        "explain",
        "what is the meaning",
        "what does it mean",
        # Examples
        "give an example",
        "examples of",
        "what are examples",
        # Which / other specifiers
        "which",
        "what year",
        "what time",
        "discuss",
        "talk about",
    }
)


# A keyword only routes when nothing negates it. "I don't need the whole
# overview, just tell me what year it was published" asked for a fact and got a
# summary, because `overview` matched and the `don't` in front of it did not
# count. Negation is a rule about the sentence, not a phrase to add to a list:
# any of these markers governing any keyword suppresses that occurrence.
_NEGATION_RE = re.compile(
    r"\b(?:not|no|never|none|don'?t|doesn'?t|didn'?t|won'?t|can'?t|cannot|"
    r"skip|forget|omit|avoid|besides|rather than|instead of|other than|without)\b"
)

# Negation reaches only to the end of its own clause. Without this, "I don't
# understand this document, can you summarise it?" would read as a negated
# summary request, when the negation governs `understand` and the request that
# follows the comma is exactly what it asks for.
_CLAUSE_BREAK_RE = re.compile(r"[,;:.!?]|\bbut\b|\bjust\b|\bhowever\b|\balthough\b|\byet\b")

# How far back a negation reaches inside its clause, in words. Five covers
# "don't give me the long summary" without spanning a whole sentence.
_NEGATION_WINDOW_WORDS = 5


def _is_negated_at(text: str, start: int) -> bool:
    """True when a negation governs the keyword occurrence beginning at *start*."""
    prefix = text[:start]
    breaks = list(_CLAUSE_BREAK_RE.finditer(prefix))
    clause = prefix[breaks[-1].end() :] if breaks else prefix
    recent = " ".join(clause.split()[-_NEGATION_WINDOW_WORDS:])
    return bool(_NEGATION_RE.search(recent))


def mentions(text: str, pattern: re.Pattern[str]) -> bool:
    """True when *pattern* matches somewhere it is not negated.

    Every occurrence has to be negated for the mention to be suppressed: "no
    summary of chapter 1, give me the summary of chapter 2" still asks for a
    summary.
    """
    return any(not _is_negated_at(text, m.start()) for m in pattern.finditer(text))


def mentions_substring(text: str, keyword: str) -> bool:
    """`keyword in text`, minus the occurrences a negation governs.

    Substring, not word-boundary: the summary keywords are written to catch
    their own inflections -- "outline" has to match "outlines", and "central
    theme" has to match "central themes". Tightening this to a word boundary
    silently drops every plural, which is a matching change wearing a negation
    fix's clothes.
    """
    starts = []
    at = text.find(keyword)
    while at != -1:
        starts.append(at)
        at = text.find(keyword, at + 1)
    return any(not _is_negated_at(text, start) for start in starts)


@lru_cache(maxsize=512)
def _kw_regex(kw: str) -> re.Pattern[str]:
    """Word-boundary matcher for one keyword.

    Bare `kw in question` matches inside a longer word: "ties between" is a
    substring of "similari|ties between", which routed every "similarities
    between X and Y" question to relational. The boundary is only asserted on the
    side where the keyword itself ends in a word character, so entries like
    "vs " and "vs." keep matching what they were written to match.
    """
    pre = r"(?<![a-z0-9])" if kw[:1].isalnum() else ""
    post = r"(?![a-z0-9])" if kw[-1:].isalnum() else ""
    return re.compile(pre + re.escape(kw) + post)


def matches_summary_request(question: str) -> bool:
    """True when the question asks for the document as a whole.

    The one predicate for "is this a summary request". `qa.py` decides whether to
    attach the executive summary from this plus a few looser words; keeping that
    a superset of this is what stops the two from disagreeing, as they did when
    each carried its own list and "Recap the document" was a summary to one and a
    search to the other.
    """
    q = question.lower()
    return any(mentions_substring(q, kw) for kw in _SUMMARY_KWS) or any(
        mentions(q, p) for p in _SUMMARY_PATTERNS
    )


def _best_match(question: str, keywords: frozenset[str]) -> str | None:
    """Longest keyword matching *question* on word boundaries, or None."""
    hits = [kw for kw in keywords if mentions(question, _kw_regex(kw))]
    return max(hits, key=len) if hits else None


def classify_intent_heuristic(question: str) -> tuple[str, float]:
    """Pure function — no imports from other app layers.

    Keyword-match rules in priority order (first match wins):
      teach_back  confidence=0.95 — bypasses LLM classifier (threshold=0.9)
      socratic    confidence=0.95 — bypasses LLM classifier
      notes_gap   confidence=0.95 — bypasses LLM classifier
      notes       confidence=0.95 — bypasses LLM classifier
      summary     confidence=0.9  — bypasses LLM classifier
      relational  confidence=0.85 — falls through to LLM classifier as a hint
      comparative confidence=0.85 — falls through to LLM classifier as a hint
      factual     confidence=0.8  — falls through to LLM classifier as a hint
      generative  confidence=0.75 — "write a story based on ..." → search_node,
                                     bypasses the LLM (which mislabels these)
      exploratory confidence=0.5 (catch-all) — falls through to LLM classifier

    Returns:
        (intent_str, confidence_float)
    """
    q = question.lower()

    if any(kw in q for kw in _TEACH_BACK_KWS):
        return ("teach_back", 0.95)
    if any(kw in q for kw in _SOCRATIC_KWS):
        return ("socratic", 0.95)
    if any(kw in q for kw in _NOTES_GAP_KWS):
        return ("notes_gap", 0.95)
    if any(kw in q for kw in _NOTES_KWS):
        return ("notes", 0.95)
    if matches_summary_request(question):
        return ("summary", 0.9)
    # Relational and comparative share a confidence, so set order was deciding
    # between them: "how do" (relational) outranked "how do they differ"
    # (comparative) purely by being checked first. The more specific keyword wins
    # instead, which is order-independent and survives either set growing.
    relational = _best_match(q, _RELATIONAL_KWS)
    comparative = _best_match(q, _COMPARATIVE_KWS)
    # A shape decides only when neither family matched a keyword: a keyword names
    # the intent outright, a shape infers it from structure, and an inference
    # must not outrank a statement.
    comparative_shape = any(mentions(q, p) for p in _COMPARATIVE_SHAPES)
    relational_shape = any(mentions(q, p) for p in _RELATIONAL_SHAPES)
    if relational or comparative:
        if comparative and (relational is None or len(comparative) >= len(relational)):
            return ("comparative", 0.85)
        return ("relational", 0.85)
    if comparative_shape or relational_shape:
        # Comparative first: "which of X and Y" is also "between X and Y" read
        # loosely, and choosing between two things is the narrower reading.
        return ("comparative" if comparative_shape else "relational", 0.8)
    if any(kw in q for kw in _FACTUAL_KWS):
        return ("factual", 0.8)
    if any(kw in q for kw in _GENERATIVE_KWS):
        return ("exploratory", 0.75)
    return ("exploratory", 0.5)


# Below this the heuristic is guessing and the LLM decides. Shared so the chat
# graph and anything measuring it cannot drift apart.
LLM_FALLBACK_BELOW = 0.7


async def _llm_classify_fallback(question: str, default: str, scope: str = "all") -> str:
    """Call LiteLLM to classify intent when heuristic confidence < 0.7.

    Chooses only among the retrieval intents; see _MODE_INTENTS for why the
    interactive modes are the heuristic's alone to pick. Falls back to 'factual'
    (not `default`) when the LLM is offline or returns anything unrecognised or
    out of bounds — because factual is the safest retrieval mode.

    Args:
        question: raw user question
        default: the heuristic's best guess (used only for logging)
        scope: 'single' (one document) or 'all' (entire library)

    Returns:
        one of _LLM_SELECTABLE_INTENTS
    """
    from app.services.llm import get_llm_service  # noqa: PLC0415

    # Scope says WHERE to look, never WHAT is being asked. It used to add
    # "especially when scope is the entire library" to the summary rule, which made
    # every bare topic under scope='all' classify as `summary`: "Apache Iceberg"
    # returned the library summary (or a "being generated" placeholder) instead of
    # what the library says about Iceberg. The same query scoped to one document
    # correctly returned `factual`.
    scope_hint = (
        "The user is searching their ENTIRE document library (all content)."
        if scope == "all"
        else "The user is searching a SINGLE specific document."
    )
    try:
        content = await get_llm_service().complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{scope_hint} "
                        "The user has asked a question about their documents. Decide how to "
                        "look the answer up. Reply with exactly one word: "
                        "summary, factual, relational, comparative, or exploratory. "
                        "Use 'summary' ONLY when the user explicitly asks to summarize, or "
                        "for an overview of a whole body of work. Breadth of scope is not a "
                        "request for a summary. "
                        "Use 'factual' for questions about specific people, facts, concepts, "
                        "or entities, even if phrased as what they 'discuss' or 'explain'. "
                        "A bare topic or entity name with no verb (e.g. 'Apache Iceberg') is "
                        "'factual', whatever the scope."
                    ),
                },
                {"role": "user", "content": question},
            ],
            temperature=0.0,
        )
        result = content.strip().lower().strip("\"'`.,:;!?*")
        if result in _LLM_SELECTABLE_INTENTS:
            logger.debug(
                "intent LLM: %r → %s (heuristic default was %s)", question[:60], result, default
            )
            return result
        if result in _MODE_INTENTS:
            logger.info(
                "intent LLM chose the interactive mode %r for a plain question; "
                "modes are keyword-gated, using 'factual'",
                result,
            )
            return "factual"
        logger.debug("intent LLM returned unrecognised %r, falling back to 'factual'", result)
        return "factual"
    except Exception:
        logger.warning(
            "intent LLM classification failed (LLM unavailable or model error),"
            " defaulting to 'factual'",
            exc_info=True,
        )
        return "factual"
