"""Unit tests for the evals.lib package introduced in S213."""

import json
import sys
from pathlib import Path

import pytest

# evals/ lives outside the backend tree -- expose it on sys.path so we can
# import the new evals.lib package as a top-level module.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib import (  # noqa: E402
    FlashcardGoldenEntry,
    IntentGoldenEntry,
    RetrievalGoldenEntry,
    SummaryGoldenEntry,
    append_history,
    compute_hit_rate_5,
    compute_mrr,
    load_golden,
)
from evals.lib.loader import GoldenValidationError  # noqa: E402
from pydantic import ValidationError  # noqa: E402

# ---------------------------------------------------------------------------
# RetrievalGoldenEntry: S226 multi-hint coercion + validation
# ---------------------------------------------------------------------------


def test_retrieval_golden_entry_accepts_str_hint():
    entry = RetrievalGoldenEntry(question="q", ground_truth_answer="a", context_hint="text")
    assert entry.context_hint == ["text"]


def test_retrieval_golden_entry_accepts_list_hint():
    entry = RetrievalGoldenEntry(
        question="q", ground_truth_answer="a", context_hint=["a", "b"]
    )
    assert entry.context_hint == ["a", "b"]


def test_retrieval_golden_entry_rejects_empty_list():
    with pytest.raises(ValidationError):
        RetrievalGoldenEntry(question="q", ground_truth_answer="a", context_hint=[])


def test_retrieval_golden_entry_rejects_non_str_element():
    with pytest.raises(ValidationError):
        RetrievalGoldenEntry(
            question="q", ground_truth_answer="a", context_hint=[1, "ok"]
        )


def test_retrieval_golden_entry_empty_str_becomes_empty_list():
    entry = RetrievalGoldenEntry(question="q", ground_truth_answer="a", context_hint="")
    assert entry.context_hint == []


# ---------------------------------------------------------------------------
# Family subclasses
# ---------------------------------------------------------------------------


def test_summary_golden_entry_requires_expected_themes():
    with pytest.raises(ValidationError):
        SummaryGoldenEntry(question="q", mode="executive")  # type: ignore[call-arg]


def test_summary_golden_entry_minimal():
    e = SummaryGoldenEntry(question="q", mode="executive", expected_themes=["theme1"])
    assert e.mode == "executive"
    assert e.expected_themes == ["theme1"]


def test_intent_golden_entry_requires_expected_route():
    with pytest.raises(ValidationError):
        IntentGoldenEntry(question="q")  # type: ignore[call-arg]


def test_intent_golden_entry_minimal():
    e = IntentGoldenEntry(question="q", expected_route="search")
    assert e.expected_route == "search"


def test_flashcard_golden_entry_minimal():
    e = FlashcardGoldenEntry(question="q", chunk_id_or_text="chunk-text-here")
    assert e.expected_card_count == 1


# ---------------------------------------------------------------------------
# load_golden: schema validation with file:line context
# ---------------------------------------------------------------------------


def test_load_golden_raises_on_bad_entry(tmp_path, monkeypatch):
    bad = tmp_path / "bad_dataset.jsonl"
    bad.write_text(
        '{"question": "ok", "ground_truth_answer": "a"}\n'
        '{"ground_truth_answer": "missing question"}\n'
    )
    import evals.lib.loader as loader_mod

    monkeypatch.setattr(loader_mod, "GOLDEN_DIR", tmp_path)

    with pytest.raises(GoldenValidationError) as exc_info:
        load_golden("bad_dataset")

    msg = str(exc_info.value)
    assert "bad_dataset.jsonl" in msg
    assert ":2:" in msg


def test_load_golden_raises_on_invalid_json(tmp_path, monkeypatch):
    bad = tmp_path / "broken.jsonl"
    bad.write_text("{not json\n")
    import evals.lib.loader as loader_mod

    monkeypatch.setattr(loader_mod, "GOLDEN_DIR", tmp_path)

    with pytest.raises(GoldenValidationError) as exc_info:
        load_golden("broken")
    assert ":1:" in str(exc_info.value)


def test_load_golden_passes_for_valid_file(tmp_path, monkeypatch):
    good = tmp_path / "good.jsonl"
    good.write_text(
        '{"question": "q1", "ground_truth_answer": "a1", "context_hint": "h1"}\n'
        '{"question": "q2", "ground_truth_answer": "a2", "context_hint": ["h2a", "h2b"]}\n'
    )
    import evals.lib.loader as loader_mod

    monkeypatch.setattr(loader_mod, "GOLDEN_DIR", tmp_path)

    rows = load_golden("good")
    assert len(rows) == 2
    assert rows[0]["context_hint"] == ["h1"]
    assert rows[1]["context_hint"] == ["h2a", "h2b"]


# ---------------------------------------------------------------------------
# append_history: eval_kind field
# ---------------------------------------------------------------------------


def test_append_history_writes_eval_kind(tmp_path):
    target = tmp_path / "scores.jsonl"
    append_history(
        "book_alice",
        "no-llm",
        {"hit_rate_5": 0.6, "mrr": 0.4},
        True,
        eval_kind="retrieval",
        path=target,
    )
    rows = [json.loads(line) for line in target.read_text().splitlines() if line]
    assert len(rows) == 1
    assert rows[0]["eval_kind"] == "retrieval"
    assert rows[0]["hr5"] == 0.6


def test_append_history_defaults_eval_kind_to_retrieval(tmp_path):
    target = tmp_path / "scores.jsonl"
    append_history("ds", "no-llm", {"hit_rate_5": 0.5, "mrr": 0.3}, False, path=target)
    rows = [json.loads(line) for line in target.read_text().splitlines() if line]
    assert rows[0]["eval_kind"] == "retrieval"


def test_append_history_with_summary_eval_kind(tmp_path):
    target = tmp_path / "scores.jsonl"
    append_history("ds", "judge", {}, True, eval_kind="summary", path=target)
    rows = [json.loads(line) for line in target.read_text().splitlines() if line]
    assert rows[0]["eval_kind"] == "summary"


def test_append_history_persists_citation_support_rate(tmp_path):
    target = tmp_path / "scores.jsonl"
    append_history(
        "ds",
        "judge",
        {"citation_support_rate": 0.875},
        True,
        eval_kind="citation",
        path=target,
    )
    rows = [json.loads(line) for line in target.read_text().splitlines() if line]
    assert rows[0]["eval_kind"] == "citation"
    assert rows[0]["citation_support_rate"] == 0.875


# ---------------------------------------------------------------------------
# Metric re-exports
# ---------------------------------------------------------------------------


def test_metrics_importable_from_lib():
    samples = [
        {
            "question": "q",
            "context_hint": ["needle"],
            "contexts": ["chunk has needle"],
            "ground_truths": ["GT"],
        }
    ]
    assert compute_hit_rate_5(samples) == 1.0
    assert compute_mrr(samples) == 1.0


def test_metrics_re_exported_from_run_eval():
    """Backwards-compat: run_eval.compute_hit_rate_5 must still work."""
    sys.path.insert(0, str(_REPO_ROOT / "evals"))
    from run_eval import compute_hit_rate_5 as _hr  # noqa: PLC0415
    from run_eval import compute_mrr as _mrr  # noqa: PLC0415

    samples = [{"context_hint": ["x"], "contexts": ["x is here"], "ground_truths": ["g"]}]
    assert _hr(samples) == 1.0
    assert _mrr(samples) == 1.0


# ---------------------------------------------------------------------------
# audit CLI smoke (in-process)
# ---------------------------------------------------------------------------


def test_audit_main_returns_zero_for_clean_dir(tmp_path, monkeypatch):
    good = tmp_path / "ds.jsonl"
    good.write_text('{"question": "q", "ground_truth_answer": "a"}\n')
    import evals.lib.audit as audit_mod
    import evals.lib.loader as loader_mod

    monkeypatch.setattr(audit_mod, "GOLDEN_DIR", tmp_path)
    monkeypatch.setattr(loader_mod, "GOLDEN_DIR", tmp_path)

    assert audit_mod.main() == 0


def test_audit_main_returns_one_when_a_file_is_bad(tmp_path, monkeypatch):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"ground_truth_answer": "missing question"}\n')
    import evals.lib.audit as audit_mod
    import evals.lib.loader as loader_mod

    monkeypatch.setattr(audit_mod, "GOLDEN_DIR", tmp_path)
    monkeypatch.setattr(loader_mod, "GOLDEN_DIR", tmp_path)

    assert audit_mod.main() == 1
