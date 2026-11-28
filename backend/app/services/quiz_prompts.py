"""Quiz prompts, one small task each: phrase a question about sentences code chose, write wrong
answers to it, and answer it (with the material, and without it).

Difficulty is described by what the wrong answers do, never by a label (I-28). The mistake codes
are defined in plain words where they are offered, and each level offers only its own.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.types import QuizLevel

QUIZ_SYSTEM = "You write exam questions about study material and answer with JSON only."

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
    "detail": "one specific detail changed: a number, a name, an amount, or who does it",
    "swap": "cause and effect, or who does what to whom, reversed",
    "condition": "the right idea, applied under the wrong condition or in the wrong situation",
    "broader": "a true point stretched further than the material takes it",
    "belief": "a common misunderstanding of this topic that the material corrects or contradicts",
}

# No level offers "neighbour" (true of something else the material discusses): as a statement it
# is true, and a wrong option must be false according to the material.
_WRONG_RULE: dict[QuizLevel, tuple[str, tuple[str, ...]]] = {
    "easy": (
        "Someone who has read the material rejects it at once, but it is about the same subject "
        "and sounds reasonable to someone who has not.",
        ("belief", "broader"),
    ),
    "medium": (
        "It is a believable answer that someone who half-remembers the material might pick; "
        "the material shows it is wrong.",
        ("belief", "broader", "condition"),
    ),
    "hard": (
        "It is the right answer, or another statement of the material, with exactly one decisive "
        "detail changed: who does it, what causes what, under which condition, or how much. It "
        "reads as true to someone who skimmed the material.",
        ("detail", "swap", "condition"),
    ),
}

_SOURCE_RULE = (
    "The question makes sense to someone who has never seen this material: it names its subject, "
    "and never says passage, text, author, document, book, chapter, excerpt, material, "
    '"the narrator" or "this".'
)

_QUESTION_SINGLE = """MATERIAL:
\"\"\"
{passage}
\"\"\"

KEY SENTENCE, from the material:
\"\"\"
{key}
\"\"\"

Write one exam question that the key sentence answers, and its answer.

- Ask about the idea in the key sentence: what it is, what happens, what it causes, or how it \
works. Ask why only when the key sentence itself gives the reason.
- {source_rule}
- The question does not give away its answer.
- The answer is one sentence of at most 25 words, in your own words, and says only what the key \
sentence says.
{refused}
Return only JSON: {{"question": "<question>", "answer": "<answer>"}}"""

_QUESTION_MULTI = """MATERIAL:
\"\"\"
{passage}
\"\"\"

A LIST, from the material, and {n} of its items:
\"\"\"
{lead_in}
\"\"\"
{keys}

Write one exam question that asks which of several answers belong to this list, so that each of \
the {n} items above is a right answer.

- The question asks about what the list's opening line introduces, and names its subject.
- {source_rule}
- The question does not say how many answers are right.
- Each answer is one sentence of at most 25 words, in your own words, and says only what its list \
item says.
{refused}
Return only JSON: {{"question": "<question>", "answers": [{slots}]}}"""

_WRONG = """MATERIAL:
\"\"\"
{passage}
\"\"\"

QUESTION: {question}
{right_label}:
{rights}

Write {n} wrong answers to this question.

Every wrong answer:
- answers the question directly, in the same form as the right answer and about {words} words long;
- is false according to the material, and is not anything else the material says;
- {rule}
- uses none of the words always, never, only, all, every, completely, entirely or none, unless the \
right answer does.

Write each wrong answer in its slot below; the slot's "mistake" names the kind of mistake it \
sets up:
{codes}

Return only JSON: {{"wrong": [
  {slots}
]}}"""

_WRONG_SLOT = '{{"mistake": "{code}", "text": "<wrong answer>"}}'

_ANSWER = """{material}QUESTION: {question}

{options}

{ask}

Return only JSON: {{"answer": ["<letter>"]}}"""

# The JSON skeletons' placeholders: an answer equal to one is the prompt's text, not the model's.
PROMPT_PLACEHOLDERS = frozenset({"<question>", "<answer>", "<wrong answer>", "<code>", "<letter>"})

LETTERS = "ABCDE"


def level_codes(level: QuizLevel) -> tuple[str, ...]:
    return _WRONG_RULE[level][1]


def question_prompt(passage: str, keys: Sequence[str], lead_in: str = "", refused: str = "") -> str:
    """A single-answer question about one key sentence, or a multi-answer one about list items.
    *refused* is why the previous question about these keys was refused."""
    context = {
        "passage": passage,
        "source_rule": _SOURCE_RULE,
        "refused": f"\nYour last question about this was refused: {refused}. Write a new one.\n"
        if refused
        else "",
    }
    if len(keys) == 1:
        return _QUESTION_SINGLE.format(key=keys[0], **context)
    return _QUESTION_MULTI.format(
        lead_in=lead_in,
        keys="\n".join(f'{i}. """{k}"""' for i, k in enumerate(keys, 1)),
        n=len(keys),
        slots=", ".join('"<answer>"' for _ in keys),
        **context,
    )


def slot_codes(level: QuizLevel, n: int) -> list[str]:
    """The mistake each wrong-answer slot sets up: code spreads them over the level's kinds."""
    codes = level_codes(level)
    return [codes[i % len(codes)] for i in range(n)]


def wrong_prompt(
    passage: str, question: str, rights: Sequence[str], level: QuizLevel, n: int
) -> str:
    rule, codes = _WRONG_RULE[level]
    words = round(sum(len(r.split()) for r in rights) / len(rights))
    return _WRONG.format(
        passage=passage,
        question=question,
        right_label="RIGHT ANSWER" if len(rights) == 1 else "RIGHT ANSWERS",
        rights="\n".join(f"- {r}" for r in rights),
        n=n,
        words=words,
        rule=rule,
        codes="\n".join(f'- "{c}": {_CODE_MEANING[c]}' for c in codes),
        slots=",\n  ".join(_WRONG_SLOT.format(code=c) for c in slot_codes(level, n)),
    )


def answer_prompt(question: str, options: Sequence[str], n_right: int, passage: str | None) -> str:
    """The question as a learner sees it. With *passage* it is the judge's open-book check;
    without, the guess a test-wise reader makes."""
    material = f'MATERIAL:\n"""\n{passage}\n"""\n\n' if passage is not None else ""
    basis = "Using only the material, choose" if passage is not None else "Choose"
    ask = f"{basis} the one right answer." if n_right == 1 else f"{basis} every right answer."
    if passage is not None:
        ask += (
            " If no option is right according to the material, or the question assumes something"
            " the material does not say, return an empty list."
        )
    return _ANSWER.format(
        material=material,
        question=question,
        options="\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(options)),
        ask=ask,
    )
