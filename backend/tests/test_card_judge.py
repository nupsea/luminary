"""The local card judge's verdicts must point at real text, or count as no verdict."""

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.card_quality.card_judge import (  # noqa: E402
    PROMPT_SUPPLIED,
    JudgeRefused,
    checked_verdict,
)

PASSAGE = (
    "Penelope told the suitors she would marry once she finished weaving a shroud. "
    "Each night she secretly undid the day's weaving."
)
ANSWER = "Penelope unravelled her weaving each night."
WRONG = "The suitors unravelled the weaving each night."
SUPPORT = "Each night she secretly undid the day's weaving."


def _reply(**overrides) -> str:
    verdict = {
        "correct": "yes",
        "wrong_person": False,
        "added_claim": False,
        "truncated": False,
        "support_quote": SUPPORT,
        "claim_span": "",
    }
    return json.dumps({**verdict, **overrides})


def test_a_pointed_verdict_stands():
    assert checked_verdict(_reply(), answer=ANSWER, passage=PASSAGE)["correct"] == "yes"


def test_a_wrong_person_verdict_may_name_one_word():
    """A one-name span ("suitors") is under the 12-character quote floor and must still count."""
    reply = _reply(correct="no", wrong_person=True, support_quote="", claim_span="suitors")
    assert checked_verdict(reply, answer=WRONG, passage=PASSAGE)["wrong_person"] is True


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"support_quote": "Penelope wove a tapestry for her father-in-law."}, "support_quote"),
        ({"support_quote": next(iter(PROMPT_SUPPLIED))}, "support_quote"),
        ({"support_quote": "weaving"}, "support_quote"),
        ({"correct": "partial", "claim_span": ""}, "claim_span"),
        ({"wrong_person": True, "claim_span": "Telemachus"}, "claim_span"),
        ({"wrong_person": True, "claim_span": "her"}, "claim_span"),
        ({"wrong_person": True, "claim_span": "unravel"}, "claim_span"),
        ({"correct": "mostly"}, "unusable correct"),
        ({"truncated": "no"}, "not a boolean"),
    ],
)
def test_each_refusal_fires(overrides, why):
    with pytest.raises(JudgeRefused, match=why):
        checked_verdict(_reply(**overrides), answer=ANSWER, passage=PASSAGE)


def test_a_missing_field_is_refused_not_defaulted():
    reply = json.loads(_reply())
    del reply["added_claim"]
    with pytest.raises(JudgeRefused, match="added_claim"):
        checked_verdict(json.dumps(reply), answer=ANSWER, passage=PASSAGE)


@pytest.mark.parametrize(
    ("doc", "chapter", "held"),
    [
        ("the_odyssey", "BOOK X AEOLUS, THE LAESTRYGONES, CIRCE", True),
        ("the_odyssey", "BOOK XIX TELEMACHUS AND ULYSSES REMOVE THE ARMOUR", False),
        ("the_odyssey", "BOOK IX ULYSSES DECLARES HIMSELF AND BEGINS HIS STORY", False),
        ("designing-data-intensive-applications", "Chapter 6. Partitioning", True),
        ("DDIA", "6. Partitioning", True),
        ("ddia", "Chapter 60", False),
        ("ddia", "Chapter 3. Storage and Retrieval", False),
    ],
)
def test_step_four_chapters_never_reach_calibration(doc, chapter, held):
    """Real headings carry a title after the number; an exact match let a held book through."""
    from evals.card_quality.judge_panel import refuse_held_out  # noqa: PLC0415

    cards = [{"card_id": "c", "doc": doc, "chapter": chapter}]
    if held:
        with pytest.raises(SystemExit, match="held-out"):
            refuse_held_out(cards)
    else:
        refuse_held_out(cards)


def test_an_over_long_passage_is_refused_not_cut():
    from evals.card_quality.card_judge import MAX_PASSAGE_CHARS, judge_card  # noqa: PLC0415

    with pytest.raises(ValueError, match="exceeds"):
        judge_card("q", ANSWER, "x" * (MAX_PASSAGE_CHARS + 1), "ollama/any")


@pytest.mark.parametrize(
    ("caught", "false_flags", "beats"),
    [(6, 2, True), (5, 2, False), (6, 3, False), (9, 0, True)],
)
def test_the_panel_must_beat_the_14b_on_both_sides(caught, false_flags, beats):
    """The 14B caught 5 of 9 wrong-person cards at 2 of 59 false flags."""
    from evals.card_quality.calibrate import beats_baseline  # noqa: PLC0415

    assert beats_baseline(caught, false_flags) is beats


def test_a_retry_reasks_only_refusals_and_keeps_the_old_row(tmp_path, monkeypatch):
    from evals.card_quality import judge_panel  # noqa: PLC0415

    cards = [
        {"card_id": cid, "question": "q", "answer": ANSWER, "passage": p}
        for cid, p in (("ok", PASSAGE), ("bad", PASSAGE + " "))
    ]
    asked = []

    def fake(q, a, passage, judge):
        asked.append(passage)
        if len(asked) == 2:
            raise JudgeRefused("support_quote is not a verbatim span of the passage")
        return {"correct": "yes"}

    monkeypatch.setattr(judge_panel, "judge_card", fake)
    judge_panel.judge_all(cards, "ollama/j", 1, tmp_path)
    judge_panel.judge_all(cards, "ollama/j", 1, tmp_path)
    assert len(asked) == 2  # a plain rerun asks nothing cached, refused or not
    judge_panel.judge_all(cards, "ollama/j", 1, tmp_path, retry_refused=True)

    assert asked[2:] == [PASSAGE + " "]
    path = judge_panel.cache_path("ollama/j", 1, tmp_path)
    assert len(path.read_text().splitlines()) == 3
    assert all(r["verdict"] for r in judge_panel.load_cache(path).values())


def test_prose_is_refused():
    with pytest.raises(JudgeRefused, match="not JSON"):
        checked_verdict("The answer is correct.", answer=ANSWER, passage=PASSAGE)
