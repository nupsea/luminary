"""The quiz-item prompt: code fixes the passage, the kind, the option counts and the level.

Difficulty is described by what the wrong options do, never by a label (I-28). The mistake
codes are defined in plain words where they are offered, and each level offers only its own.
"""

from __future__ import annotations

from app.types import QuizLevel

QUIZ_ITEM_SYSTEM = (
    "You write one multiple-choice question about some material, with right and wrong options, "
    "and answer with JSON only."
)

# Model-facing code -> stored trap. Short words, so a small model copies them exactly.
MISTAKE_CODES: dict[str, str] = {
    "detail": "near_miss_detail",
    "swap": "swapped_relation",
    "condition": "wrong_condition",
    "broader": "overgeneralised",
    "neighbour": "related_but_different",
    "belief": "common_misconception",
}

_CODE_MEANING = {
    "detail": "one specific detail changed: a number, a name, an amount, or who did it",
    "swap": "cause and effect, or who does what to whom, reversed",
    "condition": "the right idea, applied under the wrong condition or in the wrong situation",
    "broader": "a true point stretched too far, made always, every or only",
    "neighbour": "true of something related, but not of what the question asks about",
    "belief": "a common misunderstanding of this topic that the material does not support",
}

_WRONG_RULE: dict[QuizLevel, tuple[str, tuple[str, ...]]] = {
    "easy": (
        "is about the same subject as the question, but anyone who has read the material "
        "rejects it at once",
        ("neighbour",),
    ),
    "medium": (
        "is a plausible claim about the same topic that the material does not make; at least "
        "one of them is a common misunderstanding of the topic",
        ("belief", "broader", "neighbour"),
    ),
    "hard": (
        "repeats something the material states with exactly one decisive detail changed: who "
        "does it, what causes what, under which condition, how much, or how widely it applies. "
        "It must read as true to someone who skimmed the material",
        ("detail", "swap", "condition"),
    ),
}

_USER_TMPL = """Write one multiple-choice question from the material below.

MATERIAL:
\"\"\"
{passage}
\"\"\"

Ask about something the material states, the way an exam asks: about the subject itself, so the \
question makes sense to someone who has never seen this material. Never mention a passage, text, \
author, document, book, chapter, excerpt or material, and call people by the names the \
material gives them, never "the narrator" or "the speaker". The question has exactly \
{n_options} options, and exactly {n_right} of them {right_verb} right.

Each right option says something the material states, in your own words, and carries "quote": \
words from the material that show it is right, copied character for character, spelling \
included, at least four words long.

Each wrong option {wrong_rule}. A wrong option is never stated anywhere in the material. It \
carries "mistake", one of these codes for the kind of mistake it sets up:
{codes}

Every option is one statement, of about the same length and style as the others. No option is \
"all of the above", "none of the above" or a combination of other options. Every option carries \
"why": one sentence, from the material, on why it is right or wrong.

Return only JSON with exactly {n_options} options, in this shape:
{shape}"""

_RIGHT_SLOT = (
    '{"text": "<option>", "correct": true, "quote": "<words from the material>", "why": "<reason>"}'
)
_WRONG_SLOT = '{"text": "<option>", "correct": false, "mistake": "<code>", "why": "<reason>"}'

# The shape example's placeholders: an option or quote equal to one is the prompt's text.
PROMPT_PLACEHOLDERS = frozenset(
    {"<question>", "<option>", "<words from the material>", "<reason>", "<code>"}
)


def level_codes(level: QuizLevel) -> tuple[str, ...]:
    return _WRONG_RULE[level][1]


def quiz_item_prompt(passage: str, level: QuizLevel, n_options: int, n_right: int) -> str:
    rule, codes = _WRONG_RULE[level]
    return _USER_TMPL.format(
        passage=passage,
        n_options=n_options,
        n_right=n_right,
        right_verb="is" if n_right == 1 else "are",
        wrong_rule=rule,
        codes="\n".join(f'- "{c}": {_CODE_MEANING[c]}' for c in codes),
        shape=_shape(n_options, n_right),
    )


def _shape(n_options: int, n_right: int) -> str:
    """The JSON skeleton with one slot per option, so the count is copied, not counted."""
    slots = [_RIGHT_SLOT] * n_right + [_WRONG_SLOT] * (n_options - n_right)
    return '{"question": "<question>", "options": [\n  ' + ",\n  ".join(slots) + "\n]}"
