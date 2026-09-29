"""Staged flashcard generation (#191 Phase 2): select, ask, verify, rank.

The single-call path writes a question first and then finds a quote to justify it,
so a real quote can sit under a false claim. Here the fact is chosen first as a
verbatim span, a question is written for that fact, and a model that did not write
the card answers the question blind from the passage. Only a card whose blind
answer makes the same claim is delivered as supported.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.services import llm_output_stats
from app.services.flashcard_factuality import (
    FACTUALITY_SUPPORTED,
    FACTUALITY_UNCHECKED,
    FACTUALITY_UNSUPPORTED,
    FACTUALITY_UNVERIFIABLE,
    effective_generation_model,
    factuality_model,
    is_self_judging,
)
from app.services.flashcard_parsers import (
    GROUNDING_VERIFIED,
    _coerce_cards,
    _normalise_for_match,
    card_rejection,
    grounding_state,
)
from app.services.flashcard_prompts import _SEPARATE_EXCERPTS
from app.services.llm_json import parse_object_with_repairs

logger = logging.getLogger(__name__)

KINDS = ("definition", "event", "cause", "comparison", "code", "claim")

# The wire word each kind is stored under (`bloom_from` maps it to a level).
_KIND_DEPTH = {
    "definition": "fact",
    "event": "fact",
    "claim": "fact",
    "cause": "explain",
    "comparison": "relate",
    "code": "use",
}

REJECT_UNSTATED_CAUSE = "unstated_cause"
REJECT_LEAKS_ANSWER = "leaks_answer"

# A span may only carry a why-card when it states the reason itself. "She ate the
# apple because she was hungry" is a cause; "The queen gave her the apple" is not,
# and a why-question about it is a false premise.
_CAUSAL_MARKER = re.compile(
    r"\b(because|since|so that|therefore|thus|hence|due to|as a result|in order to|"
    r"caus(?:e|es|ed|ing)|lead(?:s)? to|led to|result(?:s|ed)? in|reason)\b",
    re.IGNORECASE,
)
_WHY_QUESTION = re.compile(r"^\W*(why|how come)\b", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")
_STOP_WORDS = (
    "the of to in on at by for with from and or but is are was were be been being it its "
    "this that these those as what which who whom whose when where why how does do did has "
    "have had not no into than then there their they them he she his her him because so "
    "since therefore thus"
)
_STOP = frozenset(_STOP_WORDS.split())
_SUFFIXES = (("ying", "y"), ("ied", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", ""))

# The blind answer's refusal. Kept verbatim from the Phase 1 roundtrip prompt.
NOT_IN_PASSAGE = "NOT IN PASSAGE"

_SELECT_SYSTEM = (
    _SEPARATE_EXCERPTS + "You choose the facts a learner should remember from a passage. You "
    "never add anything the passage does not say. Answer with JSON only."
)

_SELECT_PROMPT = """Choose up to {n} facts worth remembering from the passage, each from a
different sentence. For each fact return:
  span -- the sentence or clause that states it, copied word for word from the passage
  fact -- what the span states, as one short sentence that names its subject (no "he",
          "she", "it" or "they" without the name)
  kind -- definition | event | cause | comparison | code | claim

Use "cause" only when the span itself states the reason (because, so, therefore, due to).
Never infer a reason, a mechanism or a consequence the span does not state.

Return only: {{"units": [{{"span": "...", "fact": "...", "kind": "..."}}]}}

PASSAGE:
{passage}"""

_ASK_SYSTEM = "You write flashcard questions. Answer with JSON only."

_ASK_PROMPT = """Write one study question for each numbered fact. The fact is the question's
answer, so ask exactly what the fact states and assume nothing it does not say.

  definition -- ask what the thing is
  event      -- ask what happened, or what someone did
  cause      -- ask why
  comparison -- ask how the two things differ
  code       -- ask what the code does, or how to write it
  claim      -- ask what is true of the subject

Name the subject in the question. Never write "the passage", "the text", "the author", or a
pronoun without its name. Do not put the answer in the question.

Return only: {{"questions": [{{"id": 1, "question": "..."}}]}}

FACTS:
{facts}"""

_BLIND_PROMPT = """Answer each numbered question using ONLY the passage, in one sentence. If the
passage does not answer it, or the question assumes something the passage does not say, the
answer is exactly NOT IN PASSAGE.

Return only: {{"answers": [{{"id": 1, "answer": "..."}}]}}

PASSAGE:
{passage}

QUESTIONS:
{questions}"""

_SAME_PROMPT = """For each numbered item, do answers A and B make the same claim? B may be
shorter or worded differently.

Return only: {{"verdicts": [{{"id": 1, "same": "yes|no"}}]}}

{items}"""

_JSON_SYSTEM = "Answer with JSON only."


@dataclass(frozen=True)
class Unit:
    span: str
    fact: str
    kind: str


def _items(raw: str | None, key: str) -> list[dict]:
    parsed, _repairs = parse_object_with_repairs(raw or "")
    if isinstance(parsed, dict) and isinstance(parsed.get(key), list):
        items = parsed[key]
    else:
        items = _coerce_cards(parsed) or []
    return [i for i in items if isinstance(i, dict)]


def _by_id(items: list[dict], field: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for item in items:
        try:
            idx = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            out[idx] = value.strip()
    return out


def _root(word: str) -> str:
    for suffix, repl in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return (word[: -len(suffix)] + repl)[:5]
    return word[:5]


def _content_words(text: str) -> set[str]:
    return {_root(w) for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def leaks_answer(question: str, answer: str) -> bool:
    """Whether the question already states its answer.

    Brackets: "What is BM25?" / "BM25 is a ranking function scoring term frequency"
    adds five words and is a card; "Why did Snow White trust the old woman selling
    apples?" / "Snow White trusted the old woman" adds none and is not.
    """
    return len(_content_words(answer) - _content_words(question)) < 2


def _unit_from(item: dict, passage: str) -> Unit | None:
    span = str(item.get("span") or "").strip()
    fact = str(item.get("fact") or "").strip()
    kind = str(item.get("kind") or "").strip().lower()
    if not span or not fact or grounding_state(span, passage) != GROUNDING_VERIFIED:
        return None
    if kind not in KINDS:
        kind = "claim"
    if kind == "cause" and not _CAUSAL_MARKER.search(span):
        kind = "claim"
    return Unit(span=span, fact=fact, kind=kind)


def _overlaps(span: str, used: list[str]) -> bool:
    norm = _normalise_for_match(span)
    return any(norm in u or u in norm for u in used)


async def select_units(
    llm, passage: str, want: int, *, model: str | None, used_spans: list[str]
) -> list[Unit]:
    """About 2N verbatim-anchored facts, none repeating a span already carded."""
    raw = await llm.generate(
        _SELECT_PROMPT.format(n=max(2 * want, want + 2), passage=passage),
        system=_SELECT_SYSTEM,
        model=model,
        stream=False,
        response_format={"type": "json_object"},
    )
    used = [_normalise_for_match(s) for s in used_spans if s.strip()]
    units: list[Unit] = []
    for item in _items(raw, "units"):
        unit = _unit_from(item, passage)
        if unit is None or _overlaps(unit.span, used):
            continue
        used.append(_normalise_for_match(unit.span))
        units.append(unit)
    logger.info("flashcard.staged: %d units selected for %d cards", len(units), want)
    return units


def _card_rejection(question: str, unit: Unit, passage: str) -> tuple[str, str] | None:
    verdict = card_rejection(question, unit.fact, unit.span, passage)
    if verdict:
        return verdict
    if _WHY_QUESTION.match(question) and unit.kind != "cause":
        return REJECT_UNSTATED_CAUSE, "why-question on a span that states no cause"
    if leaks_answer(question, unit.fact):
        return REJECT_LEAKS_ANSWER, "question states its own answer"
    return None


async def ask(llm, units: list[Unit], passage: str, *, model: str | None) -> list[dict]:
    """One question per unit, in one call, then the deterministic gate."""
    if not units:
        return []
    facts = "\n".join(f"{i}. [{u.kind}] {u.fact}" for i, u in enumerate(units, 1))
    raw = await llm.generate(
        _ASK_PROMPT.format(facts=facts),
        system=_ASK_SYSTEM,
        model=model,
        stream=False,
        response_format={"type": "json_object"},
    )
    questions = _by_id(_items(raw, "questions"), "question")
    cards: list[dict] = []
    for i, unit in enumerate(units, 1):
        question = questions.get(i, "")
        verdict = _card_rejection(question, unit, passage)
        llm_output_stats.record_card_gate(verdict[0] if verdict else None)
        if verdict:
            logger.info("flashcard.staged: dropped card (%s): %r", verdict[1], question[:80])
            continue
        cards.append(
            {
                "question": question,
                "answer": unit.fact,
                "source_excerpt": unit.span,
                "depth": _KIND_DEPTH[unit.kind],
                "kind": unit.kind,
                "grounding": GROUNDING_VERIFIED,
            }
        )
    return cards


def _verdict_word(value: str | None) -> str | None:
    match = re.match(r"\W*([A-Za-z]+)", value or "")
    word = match.group(1).lower() if match else ""
    return word if word in {"yes", "no"} else None


async def _verifier_call(llm, prompt: str, verifier: str) -> str | None:
    try:
        return await llm.generate(
            prompt,
            system=_JSON_SYSTEM,
            model=verifier,
            stream=False,
            background=True,
            response_format={"type": "json_object"},
            temperature=0,
        )
    except Exception as exc:  # noqa: BLE001 -- any verifier failure is the same verdict
        logger.warning("flashcard.staged: verifier unavailable (%s): %s", verifier, exc)
        return None


async def verify(llm, cards: list[dict], passage: str) -> list[dict]:
    """Factored roundtrip (Alberti et al. 2019): the verifier answers every question
    blind, then says whether its answer and the card's make the same claim.

    Every card gets a verdict: an unconfigured or self-judging verifier leaves cards
    `unchecked` (I-35), and one that fails or returns no verdict leaves them
    `unverifiable`, never `supported`.
    """
    if not cards:
        return []
    verifier = factuality_model()
    if not verifier or is_self_judging(verifier, effective_generation_model()):
        if verifier:
            logger.error(
                "flashcard.staged: verifier %s is also the generation model; not checking",
                verifier,
            )
        return [{**c, "factuality": FACTUALITY_UNCHECKED} for c in cards]

    questions = "\n".join(f"{i}. {c['question']}" for i, c in enumerate(cards, 1))
    blind = _by_id(
        _items(
            await _verifier_call(
                llm, _BLIND_PROMPT.format(passage=passage, questions=questions), verifier
            ),
            "answers",
        ),
        "answer",
    )
    to_compare = {
        i: a for i, a in blind.items() if 1 <= i <= len(cards) and NOT_IN_PASSAGE not in a.upper()
    }
    same: dict[int, str] = {}
    if to_compare:
        items = "\n\n".join(
            f'{i}. Question: "{cards[i - 1]["question"]}"\nA: {cards[i - 1]["answer"]}\nB: {a}'
            for i, a in to_compare.items()
        )
        same = _by_id(
            _items(
                await _verifier_call(llm, _SAME_PROMPT.format(items=items), verifier), "verdicts"
            ),
            "same",
        )

    verified: list[dict] = []
    for i, card in enumerate(cards, 1):
        if i not in blind:
            verdict = FACTUALITY_UNVERIFIABLE
        elif i not in to_compare:
            verdict = FACTUALITY_UNSUPPORTED
        else:
            word = _verdict_word(same.get(i))
            verdict = (
                FACTUALITY_UNVERIFIABLE
                if word is None
                else FACTUALITY_SUPPORTED
                if word == "yes"
                else FACTUALITY_UNSUPPORTED
            )
        verified.append({**card, "factuality": verdict, "blind_answer": blind.get(i)})
    return verified


def rank(cards: list[dict], want: int) -> list[dict]:
    """Supported cards first, then the kinds interleaved so one kind cannot fill the deck."""
    kept = [c for c in cards if c["factuality"] != FACTUALITY_UNSUPPORTED]
    ordered: list[dict] = []
    for tier in (
        [c for c in kept if c["factuality"] == FACTUALITY_SUPPORTED],
        [c for c in kept if c["factuality"] != FACTUALITY_SUPPORTED],
    ):
        queues = {k: [c for c in tier if c["kind"] == k] for k in KINDS}
        while any(queues.values()):
            for k in KINDS:
                if queues[k]:
                    ordered.append(queues[k].pop(0))
    return ordered[:want]


async def staged_cards(
    llm, passage: str, want: int, *, model: str | None, used_spans: list[str]
) -> list[dict]:
    """Up to *want* cards from *passage*, four model calls at most."""
    units = await select_units(llm, passage, want, model=model, used_spans=used_spans)
    cards = await verify(llm, await ask(llm, units, passage, model=model), passage)
    for card in cards:
        llm_output_stats.record_factuality(card["factuality"])
        if card["factuality"] == FACTUALITY_UNSUPPORTED:
            logger.info(
                "flashcard.staged: dropped card the verifier could not reproduce: %r (blind: %r)",
                card["question"][:80],
                (card.get("blind_answer") or "")[:80],
            )
    return rank(cards, want)
