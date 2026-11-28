"""Reading a model's quiz replies, and the checks that need no model.

Every refusal is a named kind with a message, logged and counted, so a gate that never fires on
real output shows up as one (`.claude/rules/common/product-integrity.md`). A question is refused
whole; a wrong answer is dropped alone, and the question is refused only when too few survive.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.services.flashcard_parsers import (
    _normalise_for_match,
    _pointing_message,
    excerpt_is_verbatim,
)
from app.services.flashcard_units import _content, names_not_in
from app.services.llm_json import parse_llm_json_object
from app.services.quiz_prompts import LETTERS, MISTAKE_CODES, PROMPT_PLACEHOLDERS
from app.types import QuizKind

# Whole-question refusals.
REFUSE_UNPARSED = "unparsed"
REFUSE_SHAPE = "shape"
REFUSE_POINTING = "points_at_source"
REFUSE_INVENTED_NAME = "invented_name"
REFUSE_VAGUE_SUBJECT = "vague_subject"
REFUSE_OFF_KEY = "answer_off_key"
REFUSE_UNSUPPORTED_WHY = "why_without_reason"
REFUSE_OTHER_SCRIPT = "other_script"
REFUSE_ANSWER_IN_STEM = "answer_in_stem"
REFUSE_COUNT_IN_STEM = "count_in_stem"
REFUSE_TOO_FEW_WRONG = "too_few_wrong"
REFUSE_DUPLICATE = "duplicate_options"
REFUSE_RIGHT_IS_LONGEST = "right_is_longest"
REFUSE_NOT_ANSWERABLE = "not_answerable"
REFUSE_GUESSABLE = "guessable"

# Single wrong answers dropped.
DROP_STATED = "wrong_stated"
DROP_ENTAILED = "wrong_entailed"
DROP_TRUE_ELSEWHERE = "wrong_true_elsewhere"
DROP_ABSOLUTE = "wrong_absolute"
DROP_LENGTH = "wrong_length"
DROP_REFERS_TO_OPTIONS = "wrong_refers_to_options"
DROP_REPEATED = "wrong_repeated"
DROP_FIRST_PERSON = "wrong_first_person"
DROP_UNTESTED_ITEM = "wrong_untested_item"

# Code decides the counts (single: 4 options, 1 right; multi: 5 options, 2 or 3 right).
OPTION_COUNT: dict[QuizKind, int] = {"single": 4, "multi": 5}
RIGHT_COUNTS: dict[QuizKind, tuple[int, ...]] = {"single": (1,), "multi": (2, 3)}
# Wrong answers asked for beyond those needed, so one dropped does not cost a call.
SPARE_WRONG = 3

# Words a test-wise reader takes as the mark of a wrong option (Haladyna's item-writing
# guidelines); allowed in a wrong answer only when the right answer uses one too.
_ABSOLUTE = re.compile(
    r"\b(?:always|never|only|all|every|completely|entirely|none|solely|universally)\b", re.I
)
# A multi-answer stem that counts its answers hands over the count.
_COUNT = re.compile(r"\b(?:two|three|four|[2-4])\b", re.I)
_REFERS_TO_OPTIONS = re.compile(
    r"\b(?:all|none|both|neither) of (?:the )?(?:above|these|those|options|answers)\b", re.I
)
# A first-person narrator's "me" carried into a wrong answer, when the right one speaks of them in
# the third person, marks that answer as made up from the passage's wording.
# A wrong option on a list question that shares this much with an item the question leaves out,
# the stem's own words aside, is that true item with a word changed, and the change need not make
# it false ("up to date with performance patches" of "up to date, including security patches").
# NLI scores that one contradicted (0.84), like a real swap (0.95), so the overlap decides.
# Bracketed on runs 6 to 8: 0.50 ("security patches are user-installed") dropped, 0.38 kept.
_ECHOES_UNTESTED = 0.4
_FIRST_PERSON = re.compile(r"\b(?:I|[Mm]e|[Mm]y|[Mm]yself|[Ww]e|us|[Oo]urs?)\b")
# Wrong answers far shorter or longer than the right one are told apart by their length.
# Unbracketed: no measured pair has yet decided either bound.
_LENGTH_BAND = (0.5, 1.8)
# Single-answer: a right answer longer than every wrong one by this much is found by its length.
# Unbracketed.
_LONGEST_RIGHT = 1.25
# The stem carries most of the answer's content words: the question answers itself. Unbracketed.
_STEM_COVERS_ANSWER = 0.8


@dataclass
class ParsedOption:
    text: str
    correct: bool
    explanation: str = ""
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
    """A question refused by a named gate."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _reply(raw: str | None) -> dict:
    data = parse_llm_json_object(raw or "")
    if not isinstance(data, dict):
        raise QuizRefusal(REFUSE_UNPARSED, "no JSON object in the reply")
    return data


def _answers(data: dict, n_keys: int) -> list[str]:
    answers = data.get("answers") if n_keys > 1 else [data.get("answer")]
    if not isinstance(answers, list):
        raise QuizRefusal(REFUSE_UNPARSED, "no answers list")
    texts = [_text(a) for a in answers]
    if len(texts) != n_keys or any(not a or a in PROMPT_PLACEHOLDERS for a in texts):
        raise QuizRefusal(REFUSE_SHAPE, f"{len(texts)} answers where {n_keys} were asked for")
    return texts


# A clause crediting the source, at either end of a question that stands without it. Cutting it
# adds no word of ours; every check still runs on what is left.
_SOURCE_NOUN = (
    r"(?:the|this)\s+(?:material|text|passage|excerpt|story|reading|account|discussion|author"
    r"|narrator|writer)"
)
_SOURCE_LEAD = re.compile(
    rf"^\s*(?:according\s+to|as\s+(?:described|stated|explained)\s+in|based\s+on)\s+"
    rf"{_SOURCE_NOUN}\s*,\s*",
    re.I,
)
_SOURCE_TRAIL = re.compile(
    rf",?\s+(?:according\s+to|as\s+(?:described|stated|explained)\s+in|based\s+on|in)\s+"
    rf"{_SOURCE_NOUN}(?=\s*\?\s*$)",
    re.I,
)


def without_source_clause(stem: str) -> str:
    cut = _SOURCE_TRAIL.sub("", _SOURCE_LEAD.sub("", stem, count=1), count=1)
    return cut[:1].upper() + cut[1:] if cut != stem else stem


def parse_question(raw: str | None, n_keys: int) -> tuple[str, list[str]]:
    """The question and one right answer per key sentence, or a refusal."""
    data = _reply(raw)
    stem = without_source_clause(_text(data.get("question")))
    answers = _answers(data, n_keys)
    if not stem or stem in PROMPT_PLACEHOLDERS:
        raise QuizRefusal(REFUSE_SHAPE, "no question of its own")
    if not stem.rstrip(" \"'\u201d\u2019)]").endswith("?"):
        raise QuizRefusal(REFUSE_SHAPE, f"the stem is not a question ({stem[:60]!r})")
    return stem, answers


def parse_wrong(raw: str | None, slots: Sequence[str]) -> list[ParsedOption]:
    """Wrong answers in slot order. Each keeps its slot's mistake unless the model named another
    the level offers."""
    data = _reply(raw)
    entries = data.get("wrong")
    if not isinstance(entries, list):
        raise QuizRefusal(REFUSE_UNPARSED, "no wrong list")
    options = []
    for i, entry in enumerate(entries[: len(slots)]):
        if not isinstance(entry, dict):
            continue
        text = _text(entry.get("text"))
        code = _text(entry.get("mistake")).lower()
        code = code if code in slots else slots[i]
        if text and text not in PROMPT_PLACEHOLDERS:
            options.append(ParsedOption(text=text, correct=False, trap=MISTAKE_CODES[code]))
    return options


def parse_letters(raw: str | None, n_options: int) -> set[int]:
    """The option indices a model chose; empty when it chose none it was offered."""
    try:
        data = _reply(raw)
    except QuizRefusal:
        return set()
    picked = data.get("answer")
    picked = picked if isinstance(picked, list) else [picked]
    return {
        LETTERS.index(c)
        for c in (str(p).strip().upper()[:1] for p in picked)
        if c and c in LETTERS[:n_options]
    }


# A "why" question about a sentence that gives no reason makes up its premise: "Why does the whale
# attempt to impale itself?" of a whale that meant to leap the ship (run 3 of #571).
_WHY = re.compile(r"^\s*why\b", re.I)
_REASON = re.compile(
    r"\b(?:because|since|so that|so|in order to|therefore|thus|hence|due to|as a result"
    r"|which means|means that|leads? to|caus\w+|reason)\b",
    re.I,
)
# Sources the card check does not name, which quiz stems used: "According to the story, why ..."
# and "... according to the discussion on fault tolerance?" (runs 3 and 4 of #571). "Mentioned"
# always means mentioned in the material: "the duties mentioned", "what attempts are mentioned".
_STORY_SOURCE = re.compile(
    r"\b(?:according\s+to|as\s+(?:told|described|discussed|mentioned)\s+in|in)\s+the\s+"
    r"(?:story|account|discussion|narrative|description|tale|reading|introduction)\b"
    r"|\bmentioned\b"
    r"|\bthe\s+(?:story|account|discussion|narrative|narrator|author|writer)\s+"
    r"(?:says|said|describes|described|mentions|mentioned|suggests|tells|claims)\b"
    # The source as the one acting, with verbs the card check lacks: "What comparison does the
    # text make", "What events does the text use" (run 10). "The document model makes" stands.
    r"|\bthe\s+(?:text|passage|excerpt|material|book|chapter|author|writer|narrator)\s+"
    r"(?:us|mak|giv|offer|compar|illustrat|provid|portray|depict|paint|draw|focus|reveal|convey)\w*\b"
    r"|\bkey\s+sentences?\b",
    re.I,
)
# A stand-in for the particular person or group a question is about. The learner cannot tell
# which one is meant, unless the key sentence itself speaks this generally.
_STAND_IN = re.compile(
    r"\b(?:someone|somebody|anyone|anybody|a person|a man|a woman|individuals|people)\b", re.I
)
# Letters outside the Latin and Greek blocks: an answer that drifted into another script.
_OTHER_SCRIPT = re.compile(r"[\u0400-\u04ff\u0590-\u06ff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")


def _vague_subject(stem: str, keys: Sequence[str]) -> str | None:
    found = _STAND_IN.search(stem)
    if not found or re.search(rf"\b{found.group(0)}\b", " ".join(keys), re.I):
        return None
    return found.group(0)


def _stem_refusal(stem: str, keys: Sequence[str], passage: str) -> QuizRefusal | None:
    pointing = _pointing_message(stem)
    if pointing:
        return QuizRefusal(REFUSE_POINTING, pointing)
    story = _STORY_SOURCE.search(stem)
    if story:
        return QuizRefusal(REFUSE_POINTING, f"question points at its source ({story.group(0)!r})")
    invented = names_not_in(stem, passage)
    if invented:
        return QuizRefusal(REFUSE_INVENTED_NAME, f"the question names {', '.join(invented)}")
    vague = _vague_subject(stem, keys)
    if vague:
        return QuizRefusal(REFUSE_VAGUE_SUBJECT, f"the question says {vague!r}, not who it means")
    if len(keys) > 1 and _COUNT.search(stem):
        return QuizRefusal(REFUSE_COUNT_IN_STEM, f"the stem counts its answers ({stem[:60]!r})")
    if _WHY.match(stem) and not any(_REASON.search(k) for k in keys):
        return QuizRefusal(REFUSE_UNSUPPORTED_WHY, "asks why of a sentence that gives no reason")
    return None


def _answer_refusal(answer: str, stem_words: set[str], passage: str) -> QuizRefusal | None:
    if _OTHER_SCRIPT.search(answer) and not _OTHER_SCRIPT.search(passage):
        return QuizRefusal(REFUSE_OTHER_SCRIPT, f"{answer[:60]!r} is in another script")
    words = _content(answer)
    if words and len(words & stem_words) >= _STEM_COVERS_ANSWER * len(words):
        return QuizRefusal(REFUSE_ANSWER_IN_STEM, f"the stem already says {answer[:60]!r}")
    return None


def check_question(stem: str, answers: Sequence[str], keys: Sequence[str], passage: str) -> None:
    """A question that stands alone, names only people the material names, asks why only of a
    reason, and whose answers are not stated by the stem. That each answer says what its key
    sentence says needs the entailment model (`quiz_builder`)."""
    refusal = _stem_refusal(stem, keys, passage)
    stem_words = _content(stem)
    for answer in answers:
        refusal = refusal or _answer_refusal(answer, stem_words, passage)
    if refusal:
        raise refusal


def _only_in_option(pattern: re.Pattern[str], option: str, rights: Sequence[str]) -> bool:
    return bool(pattern.search(option)) and not any(pattern.search(r) for r in rights)


def _echoes_untested(option: str, stem: str, untested: Sequence[str]) -> bool:
    subject = _content(stem)
    words = _content(option) - subject
    return bool(words) and any(
        len(words & (_content(u) - subject)) >= _ECHOES_UNTESTED * len(words) for u in untested
    )


def drop_reason(
    option: ParsedOption,
    rights: Sequence[str],
    passage: str,
    *,
    stem: str = "",
    untested: Sequence[str] = (),
) -> str | None:
    """Why one wrong answer cannot stand, by the checks that need no model. *untested* are the
    other items of the list a multi-answer question was picked from."""
    if excerpt_is_verbatim(option.text, passage):
        return DROP_STATED
    if _only_in_option(_ABSOLUTE, option.text, rights):
        return DROP_ABSOLUTE
    mean = sum(len(r.split()) for r in rights) / len(rights)
    low, high = _LENGTH_BAND
    if not low * mean <= len(option.text.split()) <= high * mean:
        return DROP_LENGTH
    if _REFERS_TO_OPTIONS.search(option.text):
        return DROP_REFERS_TO_OPTIONS
    if _only_in_option(_FIRST_PERSON, option.text, rights):
        return DROP_FIRST_PERSON
    if _echoes_untested(option.text, stem, untested):
        return DROP_UNTESTED_ITEM
    return None


def distinct(options: Sequence[ParsedOption], rights: Sequence[str]) -> list[ParsedOption]:
    """*options* without one that repeats a right answer or an earlier wrong one."""
    seen = {_normalise_for_match(r) for r in rights}
    kept = []
    for option in options:
        key = _normalise_for_match(option.text)
        if key not in seen:
            seen.add(key)
            kept.append(option)
    return kept


def check_lengths(item: ParsedItem, kind: QuizKind) -> None:
    if kind != "single":
        return
    right = len(item.right[0].text)
    longest_wrong = max(len(o.text) for o in item.wrong)
    if right > _LONGEST_RIGHT * longest_wrong:
        raise QuizRefusal(
            REFUSE_RIGHT_IS_LONGEST, f"right answer is {right} characters against {longest_wrong}"
        )
