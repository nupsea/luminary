"""Reading a model's quiz item, and the checks that need no model.

Every refusal is a named kind with a message, logged and counted, so a gate that never fires on
real output shows up as one (`.claude/rules/common/product-integrity.md`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.flashcard_parsers import (
    GROUNDING_VERIFIED,
    _normalise_for_match,
    _pointing_message,
    excerpt_is_verbatim,
    grounding_state,
)
from app.services.llm_json import parse_llm_json_object
from app.services.quiz_prompts import MISTAKE_CODES, PROMPT_PLACEHOLDERS
from app.types import QUIZ_TRAPS, QuizKind

REFUSE_UNPARSED = "unparsed"
REFUSE_SHAPE = "shape"
REFUSE_UNGROUNDED = "ungrounded"
REFUSE_STATED_WRONG = "wrong_option_stated"
REFUSE_GIVEAWAY = "giveaway"
REFUSE_POINTING = "points_at_source"
REFUSE_LONGEST_RIGHT = "right_is_longest"
REFUSE_DUPLICATE = "duplicate_options"
REFUSE_JUDGED_WRONG = "right_option_unsupported"
REFUSE_JUDGED_RIGHT = "wrong_option_supported"
REFUSE_LEVEL = "off_level"

# Code decides the counts (single: 4 options, 1 right; multi: 5 options, 2 or 3 right).
OPTION_COUNT: dict[QuizKind, int] = {"single": 4, "multi": 5}
RIGHT_COUNTS: dict[QuizKind, tuple[int, ...]] = {"single": (1,), "multi": (2, 3)}

# A wrong option copied from the passage is a true statement. Below five words a copied span is
# a phrase any passage on the topic repeats; the judge, not this rule, checks those. Unbracketed:
# it did not fire in 171 real writes (docs/quiz.md).
_MIN_COPIED_WORDS = 5

# Single-answer only: a right option much longer than every wrong one is found by its length.
# Unbracketed: in 17 real single items the right option was at most 1.06 times the longest wrong.
LONGEST_RIGHT_RATIO = 1.6

_GIVEAWAY = re.compile(
    r"\b(?:all|none|both|neither) of (?:the )?(?:above|these|those|options|answers)\b"
    r"|\b(?:options?|answers?) [a-e]\b(?: and [a-e]\b)?"
    r"|^\s*[a-e]\s+and\s+[a-e]\s*$",
    re.IGNORECASE,
)


@dataclass
class ParsedOption:
    text: str
    correct: bool
    explanation: str
    quote: str | None = None
    trap: str | None = None


@dataclass
class ParsedItem:
    stem: str
    options: list[ParsedOption] = field(default_factory=list)

    @property
    def right(self) -> list[ParsedOption]:
        return [o for o in self.options if o.correct]

    @property
    def wrong(self) -> list[ParsedOption]:
        return [o for o in self.options if not o.correct]


class QuizRefusal(Exception):
    """An item refused by a named gate."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message


def _field(item: dict, *names: str) -> str:
    for name in names:
        value = item.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _is_true(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1", "right", "correct"}


def _option(entry: object) -> ParsedOption:
    if not isinstance(entry, dict):
        raise QuizRefusal(REFUSE_UNPARSED, "an option is not an object")
    code = _field(entry, "mistake", "trap", "error").lower()
    return ParsedOption(
        text=_field(entry, "text", "option", "statement"),
        correct=_is_true(entry.get("correct", entry.get("is_correct"))),
        explanation=_field(entry, "why", "explanation", "reason"),
        quote=_field(entry, "quote", "evidence") or None,
        trap=MISTAKE_CODES.get(code, code) or None,
    )


def parse_item(raw: str | None) -> ParsedItem:
    """The model's item, or a refusal. Field names a model commonly swaps in are accepted."""
    data = parse_llm_json_object(raw or "")
    if not isinstance(data, dict):
        raise QuizRefusal(REFUSE_UNPARSED, "no JSON object in the reply")
    stem = _field(data, "question", "stem", "q")
    raw_options = data.get("options") or data.get("choices") or data.get("answers")
    if not stem or not isinstance(raw_options, list):
        raise QuizRefusal(REFUSE_UNPARSED, "no question or no options list")
    return ParsedItem(stem=stem, options=[_option(entry) for entry in raw_options])


def settle_traps(item: ParsedItem, offered: tuple[str, ...]) -> None:
    """Where the level offers one mistake code, that code is the level's definition, so a wrong
    option the model labelled with a code of its own invention takes it."""
    if len(offered) != 1:
        return
    for option in item.wrong:
        if option.trap not in QUIZ_TRAPS:
            option.trap = MISTAKE_CODES[offered[0]]


def _check_counts(item: ParsedItem, kind: QuizKind) -> None:
    if not item.stem.rstrip(" \"'\u201d\u2019)]").endswith("?"):
        raise QuizRefusal(REFUSE_SHAPE, f"the stem is not a question ({item.stem[:60]!r})")
    if len(item.options) != OPTION_COUNT[kind]:
        raise QuizRefusal(
            REFUSE_SHAPE, f"{len(item.options)} options where {OPTION_COUNT[kind]} were asked for"
        )
    if len(item.right) not in RIGHT_COUNTS[kind]:
        raise QuizRefusal(
            REFUSE_SHAPE, f"{len(item.right)} right options for a {kind}-answer question"
        )


def _check_option(option: ParsedOption) -> None:
    if not option.text or option.text in PROMPT_PLACEHOLDERS:
        raise QuizRefusal(REFUSE_SHAPE, "an option has no text of its own")
    if option.correct and not option.quote:
        raise QuizRefusal(REFUSE_SHAPE, f"right option without a quote ({option.text[:50]!r})")
    if not option.correct and option.trap not in QUIZ_TRAPS:
        raise QuizRefusal(REFUSE_SHAPE, f"wrong option with no known mistake ({option.trap!r})")


def check_shape(item: ParsedItem, kind: QuizKind) -> None:
    """The counts code asked for, a question, a quote on every right option and a known trap on
    every wrong one."""
    _check_counts(item, kind)
    for option in item.options:
        _check_option(option)
    texts = [_normalise_for_match(o.text) for o in item.options]
    if len(set(texts)) < len(texts):
        raise QuizRefusal(REFUSE_DUPLICATE, "two options are the same text")


# A model wraps a quote as it would a JSON string ('"the words",') and copies a typesetter's
# line-break hyphen inside a word, which the matcher joins in the passage. Neither trimming nor
# joining can turn invented words into a match.
_QUOTE_WRAPPING = "\"'\u201c\u201d\u2018\u2019,;:. "
_BREAK_HYPHENS = str.maketrans("", "", "\u2010\u00ad")


def _quote_found(quote: str, passage: str) -> bool:
    # A newline escaped twice arrives as the two characters backslash and n.
    trimmed = quote.replace("\\n", " ").strip(_QUOTE_WRAPPING)
    return any(
        grounding_state(q, passage) == GROUNDING_VERIFIED
        for q in dict.fromkeys((trimmed, trimmed.translate(_BREAK_HYPHENS)))
    )


def check_grounding(item: ParsedItem, passage: str) -> None:
    """Every right option quotes the passage; no wrong option is copied from it."""
    for option in item.right:
        quote = option.quote or ""
        if quote in PROMPT_PLACEHOLDERS or not _quote_found(quote, passage):
            raise QuizRefusal(
                REFUSE_UNGROUNDED, f"right option's quote is not in the passage ({quote[:60]!r})"
            )
    for option in item.wrong:
        if len(option.text.split()) >= _MIN_COPIED_WORDS and excerpt_is_verbatim(
            option.text, passage
        ):
            raise QuizRefusal(
                REFUSE_STATED_WRONG, f"wrong option is stated in the passage ({option.text[:60]!r})"
            )


def check_giveaways(item: ParsedItem, kind: QuizKind) -> None:
    """Nothing a test-wise reader could answer without knowing the material."""
    pointing = _pointing_message(item.stem)
    if pointing:
        raise QuizRefusal(REFUSE_POINTING, pointing)
    for option in item.options:
        if _GIVEAWAY.search(option.text):
            raise QuizRefusal(REFUSE_GIVEAWAY, f"option refers to other options ({option.text!r})")
    if kind == "single":
        right = len(item.right[0].text)
        longest_wrong = max(len(o.text) for o in item.wrong)
        if right > LONGEST_RIGHT_RATIO * longest_wrong:
            raise QuizRefusal(
                REFUSE_LONGEST_RIGHT,
                f"right option is {right} characters against at most {longest_wrong}",
            )


def check_structure(
    item: ParsedItem, kind: QuizKind, passage: str, offered: tuple[str, ...] = ()
) -> None:
    settle_traps(item, offered)
    check_shape(item, kind)
    check_grounding(item, passage)
    check_giveaways(item, kind)
