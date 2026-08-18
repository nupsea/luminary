"""Does the answer follow from the passage the card was written from?

`grounding` proves a card quotes text that exists. It cannot prove the answer is
what that text says: a model can quote a real sentence and then write what it
already believed about a familiar document. That second question is semantic, so
unlike every other flashcard check it needs a model -- which makes *which* model
the load-bearing decision, not the prompt.

Measured 2026-08-18 on 59 live cards, identical passages, three-way verdict:

| judge                    | yes  | partial | no | agrees with the 14B |
|--------------------------|------|---------|----|---------------------|
| ollama/phi4-mini         |  54  |    2    |  3 | 0.41 on pass/fail   |
| ollama/granite3.2:8b     |  53  |    5    |  1 | 0.42 on pass/fail   |
| ollama/qwen2.5:14b       |  19  |   36    |  4 | --                  |

Two of the three pass 90% of everything: a gate built on either certifies the
cards it was added to catch. `gemma3:4b` failed earlier and more cheaply, calling
a reversed card ("the suitors undid Penelope's weaving") supported by a passage
that says Penelope did. So the checker is named in config and there is no default
small-model fallback -- an unnamed checker does not run at all, which is honest,
where a rubber stamp is not.

The checker may never be the model that wrote the card. A model asked whether its
own output follows from a passage agrees with itself, and the resulting verdict is
the system satisfying its own check (`.claude/rules/common/product-integrity.md`).
"""

from __future__ import annotations

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

FACTUALITY_UNCHECKED = "unchecked"
FACTUALITY_SUPPORTED = "supported"
FACTUALITY_UNSUPPORTED = "unsupported"
FACTUALITY_UNVERIFIABLE = "unverifiable"

FACTUALITY_STATES = frozenset(
    {
        FACTUALITY_UNCHECKED,
        FACTUALITY_SUPPORTED,
        FACTUALITY_UNSUPPORTED,
        FACTUALITY_UNVERIFIABLE,
    }
)

# Same three-way definition the eval judge uses, so a product verdict and an eval
# number mean the same thing. `partial` is not a pass: a card whose answer is half
# supported asserts something the passage does not, and a learner reviewing it for
# a year has no way to find out which half.
_SYSTEM = "You check whether a flashcard answer is supported by a passage. Answer with JSON only."

_PROMPT = """Does the ANSWER follow from the PASSAGE?

yes     -- every claim in the answer is stated in the passage or follows directly from it
partial -- part of the answer is supported by the passage and part is not
no      -- the answer contradicts the passage, reverses who did what, or adds facts
           the passage does not contain

Judge only against the passage. Do not use anything you know about the subject.

Return only: {{"verdict": "yes|partial|no"}}

PASSAGE:
{passage}

QUESTION:
{question}

ANSWER:
{answer}"""

# A passage longer than this is more than the checker needs to see and costs a
# reload under I-27 when it pushes past the model's context window.
_MAX_PASSAGE_CHARS = 6000


def factuality_model() -> str:
    """The configured checker, or empty when none is set."""
    return (get_settings().FLASHCARD_FACTUALITY_MODEL or "").strip()


def is_self_judging(checker: str, generator: str | None) -> bool:
    """Whether the checker would be grading its own work."""
    return bool(checker) and bool(generator) and checker.strip() == generator.strip()


def effective_generation_model() -> str:
    """The model that will actually write the cards.

    NOT `_generation_model()`, which returns None whenever nothing overrides the
    default -- and the default path is exactly where a checker collides with the
    generator. Comparing against the override let a 14B judge its own cards while
    the guard reported no self-judging.
    """
    from app.services.model_router import resolve  # noqa: PLC0415

    try:
        return resolve("generation").model or ""
    except Exception:  # noqa: BLE001 -- an unresolvable model cannot collide
        return ""


async def check_answer(
    question: str,
    answer: str,
    passage: str,
    *,
    checker: str,
    llm,
) -> str:
    """One card's factuality verdict. Never raises -- an unreachable checker
    yields `unverifiable`, because a card the product could not check is not a
    card the product may call false, and refusing to deliver anything when the
    checker is down would empty the deck instead of labelling it."""
    if not passage.strip() or not answer.strip():
        return FACTUALITY_UNVERIFIABLE
    prompt = _PROMPT.format(
        passage=passage[:_MAX_PASSAGE_CHARS], question=question, answer=answer
    )
    try:
        raw = await llm.generate(
            prompt,
            system=_SYSTEM,
            model=checker,
            stream=False,
            background=True,
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 -- any checker failure is the same verdict
        logger.warning("factuality checker unavailable (%s): %s", checker, exc)
        return FACTUALITY_UNVERIFIABLE

    verdict = _parse_verdict(raw)
    if verdict is None:
        logger.warning("factuality checker returned no verdict: %r", (raw or "")[:120])
        return FACTUALITY_UNVERIFIABLE
    return FACTUALITY_SUPPORTED if verdict == "yes" else FACTUALITY_UNSUPPORTED


def _parse_verdict(raw: str | None) -> str | None:
    """The verdict word, or None. Never defaults to a pass on unparseable output."""
    import json  # noqa: PLC0415
    import re  # noqa: PLC0415

    text = (raw or "").strip()
    if not text:
        return None
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            value = str(json.loads(match.group(0)).get("verdict", "")).strip().lower()
            if value in {"yes", "partial", "no"}:
                return value
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass
    # A model that ignored the JSON instruction still stated a verdict; read it
    # rather than discarding a real answer, but only when it is unambiguous.
    words = {w for w in re.findall(r"[a-z]+", text.lower()) if w in {"yes", "partial", "no"}}
    return words.pop() if len(words) == 1 else None
