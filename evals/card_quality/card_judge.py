"""One local judge's correctness verdict on one chapter card.

Eval-only: these judges are 30B-class models run on a 64 GB dev host, never a product default.
Correctness is split into the error classes the card-quality plan found (wrong person, added
claim, truncated) rather than one score, and every verdict must point at text: `support_quote`
in the passage, `claim_span` in the answer. Both are checked verbatim, so a judge that invents
its evidence yields no verdict instead of a pass.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (REPO_ROOT, REPO_ROOT / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.services.flashcard_parsers import (  # noqa: E402
    GROUNDING_VERIFIED,
    grounding_state,
)
from evals.lib.flashcard_metrics import json_judge_reply  # noqa: E402

PROMPT_VERSION = "cj-1"

# The prompt's own field descriptions; a judge that echoes one back has quoted us, not the text.
PROMPT_SUPPLIED = frozenset(
    {
        "the passage sentence that supports the answer, copied exactly",
        "the words of the answer that are wrong, copied exactly",
    }
)

_SYSTEM = "You are a strict fact-checker for study flashcards. Answer with JSON only."

# The yes/partial/no wording is flashcard_factuality's, so a judge verdict and a product verdict
# mean the same thing.
_PROMPT = """Check the flashcard ANSWER against the PASSAGE it was written from.
Judge only against the passage. Do not use anything you know about the subject.

correct:
  yes     -- every claim in the answer is stated in the passage or follows directly from it
  partial -- part of the answer is supported by the passage and part is not
  no      -- the answer contradicts the passage, reverses who did what, or adds facts
             the passage does not contain
wrong_person: true if the card credits a statement, action or idea to a different person,
  character or group than the passage does
added_claim: true if the answer states something the passage does not say (a paraphrase of
  what the passage says is NOT an added claim)
truncated: true if the answer stops mid-thought or is cut off

Return only JSON with exactly these keys:
  "correct": "yes" | "partial" | "no",
  "wrong_person": true | false,
  "added_claim": true | false,
  "truncated": true | false,
  "support_quote": "the passage sentence that supports the answer, copied exactly",
  "claim_span": "the words of the answer that are wrong, copied exactly"
support_quote is "" only when nothing in the passage supports the answer.
claim_span is "" only when correct is "yes".

PASSAGE:
{passage}

QUESTION:
{question}

ANSWER:
{answer}"""

# Ollama silently drops the start of a prompt past num_ctx, so the window is set, not defaulted,
# and an over-long passage is refused rather than cut. A chapter window (3,500 chars) fits with
# room for a thinking trace; past 24,000 chars (~8k tokens) a trace can overrun 16k.
JUDGE_NUM_CTX = 16384
MAX_PASSAGE_CHARS = 24000

# A wrong-words span made only of these points at nothing ("the", "of the").
_FUNCTION_WORDS = frozenset(
    {
        *("a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "and", "or", "but"),
        *("is", "was", "are", "were", "be", "it", "its", "his", "her", "their", "this", "that"),
    }
)


class JudgeRefused(ValueError):
    """The judge replied, but its verdict does not stand up; never counted as any verdict."""

    # Kept so a change to the checks can be rescored without asking the judge again.
    raw: str = ""


def judge_card(question: str, answer: str, passage: str, judge_model: str) -> dict:
    """The judge's verdict, every field checked; raises rather than defaulting."""
    if len(passage) > MAX_PASSAGE_CHARS:
        raise ValueError(f"passage of {len(passage)} chars exceeds {MAX_PASSAGE_CHARS}")
    extra = {"num_ctx": JUDGE_NUM_CTX} if judge_model.startswith("ollama/") else {}
    prompt = _PROMPT.format(passage=passage, question=question, answer=answer)
    raw = json_judge_reply(_SYSTEM, prompt, judge_model, **extra)
    try:
        return checked_verdict(raw, answer=answer, passage=passage)
    except JudgeRefused as exc:
        exc.raw = raw
        raise


def checked_verdict(raw: str, *, answer: str, passage: str) -> dict:
    """Parse and verify one reply. Split from the call so every refusal can be fired in a test."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JudgeRefused(f"not JSON: {raw[:80]!r}") from exc
    if not isinstance(parsed, dict):
        raise JudgeRefused("not an object")

    correct = str(parsed.get("correct", "")).strip().lower()
    if correct not in {"yes", "partial", "no"}:
        raise JudgeRefused(f"unusable correct: {correct!r}")
    flags = {}
    for key in ("wrong_person", "added_claim", "truncated"):
        if not isinstance(parsed.get(key), bool):
            raise JudgeRefused(f"{key} is not a boolean: {parsed.get(key)!r}")
        flags[key] = parsed[key]
    support = str(parsed.get("support_quote") or "").strip()
    span = str(parsed.get("claim_span") or "").strip()

    if correct != "no" and not _points_at(support, passage):
        raise JudgeRefused("support_quote is not a verbatim span of the passage")
    faulted = correct != "yes" or flags["wrong_person"] or flags["added_claim"]
    if faulted and not _names_part_of(span, answer):
        raise JudgeRefused("claim_span is not a verbatim span of the answer")
    return {"correct": correct, **flags, "support_quote": support, "claim_span": span}


def _points_at(quote: str, passage: str) -> bool:
    if quote.lower() in PROMPT_SUPPLIED:
        return False
    return grounding_state(quote, passage) == GROUNDING_VERIFIED


def _names_part_of(span: str, answer: str) -> bool:
    # No length floor: a wrong-person span is often one name ("suitors"). Whole words only, and
    # not function words alone, so "the" or "he" inside "there" names nothing.
    words = _words(span)
    if not words or span.lower() in PROMPT_SUPPLIED or set(words) <= _FUNCTION_WORDS:
        return False
    return f" {' '.join(words)} " in f" {' '.join(_words(answer))} "


def _words(text: str) -> list[str]:
    return re.findall(r"[\w'-]+", text.lower())
