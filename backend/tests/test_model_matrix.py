"""The model matrix: which metrics may decide a swap, and when it may decide.

The failure this guards is not a wrong number, it is a confident one. A matrix
that mixes prompt arms, or that lets a retrieval metric or a judged score into
the decision, produces a model choice that cannot be defended -- which is how
the previous comparison ended up choosing on hope.
"""

# ruff: noqa: E402, I001

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "evals"))
sys.path.insert(0, str(REPO_ROOT))

import run_model_matrix
from evals.lib.matrix import separation, structural_metrics, tier


def test_retrieval_metrics_are_excluded_outright():
    """hit_rate and MRR have no generation-model term: including them lets
    retrieval noise be attributed to a model."""
    for key in ("hit_rate_5", "hr5", "mrr", "ndcg_10"):
        assert tier(key) == "excluded", key


def test_judged_scores_are_reported_never_gating():
    for key in ("faithfulness", "factuality", "no_hallucination", "citation_support_rate"):
        assert tier(key) == "quality", key


def test_repair_counters_and_delivery_are_structural():
    for key in ("first_pass_rate", "repair_fenced", "parses", "generation_rate", "answer_rate"):
        assert tier(key) == "structural", key


def test_routing_accuracy_gates_because_its_ground_truth_is_labelled():
    assert tier("routing_accuracy") == "structural"


def test_library_state_metrics_are_reported_but_cannot_separate():
    """`cards_returned` falls with every re-run on the same library: the
    near-duplicate filter, not the model."""
    metrics = {"flashcards.cards_returned": 44, "flashcards.first_pass_rate": 0.5}

    assert "flashcards.cards_returned" not in structural_metrics(metrics)
    assert "flashcards.first_pass_rate" in structural_metrics(metrics)


def test_a_quality_difference_alone_does_not_separate_two_models():
    verdict = separation(
        {"qa.faithfulness": 0.44, "qa.answer_rate": 0.95},
        {"qa.faithfulness": 0.89, "qa.answer_rate": 0.95},
    )

    assert verdict["separated"] is False
    assert verdict["separating_metrics"] == []


def test_a_structural_difference_separates_two_models():
    verdict = separation(
        {"flashcards.first_pass_rate": 0.00, "flashcards.generation_rate": 0.99},
        {"flashcards.first_pass_rate": 0.92, "flashcards.generation_rate": 0.99},
    )

    assert verdict["separated"] is True
    assert verdict["separating_metrics"] == ["flashcards.first_pass_rate"]


def test_one_call_in_forty_is_not_a_difference_between_models():
    verdict = separation({"qa.qa_failed_calls": 0}, {"qa.qa_failed_calls": 1})

    assert verdict["separated"] is False


def test_identical_models_are_not_separated():
    metrics = {"intent.routing_accuracy": 0.5862, "flashcards.first_pass_rate": 0.0}

    assert separation(metrics, dict(metrics))["separated"] is False


def test_a_run_flattens_repairs_and_drops_the_history_bookkeeping():
    rows = [
        {
            "timestamp": "now",
            "dataset": "flashcards",
            "model": "no-judge",
            "eval_kind": "flashcard",
            "passed": True,
            "environment": {"chat_model": "ollama/llama3.2"},
            "cards_requested": 105,
            "mrr": None,
            "output_repairs": {"parses": 38, "repair_fenced": 38},
        }
    ]

    metrics = run_model_matrix._metrics_from_rows(rows)

    assert metrics == {"cards_requested": 105, "parses": 38, "repair_fenced": 38}


def test_a_model_id_that_could_be_reparsed_as_a_flag_is_refused():
    """A value spread into a child's argv must not be able to start with `-`."""
    assert run_model_matrix._valid_model_id("ollama/qwen3.5:4b")
    assert not run_model_matrix._valid_model_id("--out")
    assert not run_model_matrix._valid_model_id("ollama/x y")
    assert not run_model_matrix._valid_model_id("")


def test_repairs_are_the_movement_between_two_snapshots():
    moved = run_model_matrix._repairs_between(
        {"counts": {"parses": 10, "parses_first_pass": 4, "repair_fenced": 6}},
        {"counts": {"parses": 20, "parses_first_pass": 4, "repair_fenced": 16}},
    )

    assert moved["counts"] == {"parses": 10, "repair_fenced": 10}
    assert moved["first_pass_rate"] == 0.0


def test_the_matrix_refuses_to_run_against_the_wrong_prompt_arm(monkeypatch, capsys):
    """A matrix that straddles the shipped and bare arms measures neither."""
    monkeypatch.setattr(
        run_model_matrix, "_environment", lambda url: {"prompt_arm": "shipped"}
    )
    monkeypatch.setattr(sys, "argv", ["run_model_matrix.py", "--models", "a,b", "--arm", "bare"])

    assert run_model_matrix.main() == 1
    assert "prompt arm" in capsys.readouterr().err


def test_the_matrix_refuses_a_model_that_is_not_installed(monkeypatch, capsys):
    monkeypatch.setattr(
        run_model_matrix, "_environment", lambda url: {"prompt_arm": "shipped"}
    )
    monkeypatch.setattr(
        run_model_matrix, "_installed_models", lambda url: ["ollama/llama3.2"]
    )
    monkeypatch.setattr(
        sys, "argv", ["run_model_matrix.py", "--models", "ollama/llama3.2,ollama/absent"]
    )

    assert run_model_matrix.main() == 1
    assert "not installed" in capsys.readouterr().err


def test_asserting_separation_needs_two_models(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_model_matrix.py", "--models", "ollama/llama3.2", "--assert-separation"],
    )

    assert run_model_matrix.main() == 1
    assert "two models" in capsys.readouterr().err


def test_an_unmeasurable_matrix_fails_the_gate(monkeypatch, tmp_path, capsys):
    """Two models that score alike fail --assert-separation: the instrument is
    blind, and a model chosen on a blind instrument is what this stage exists
    to prevent."""
    same = {"flashcards.first_pass_rate": 0.0, "flashcards.generation_rate": 0.99}

    monkeypatch.setattr(
        run_model_matrix,
        "_environment",
        lambda url: {"prompt_arm": "shipped", "local_chat_model": "ollama/llama3.2"},
    )
    monkeypatch.setattr(run_model_matrix, "_installed_models", lambda url: [])
    monkeypatch.setattr(run_model_matrix, "_switch_model", lambda url, model: model)
    monkeypatch.setattr(
        run_model_matrix,
        "run_model",
        lambda model, tasks, url: {
            "model": model,
            "tasks": [],
            "metrics": dict(same),
            "environment": {"prompt_arm": "shipped"},
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_model_matrix.py",
            "--models",
            "ollama/small,ollama/large",
            "--assert-separation",
            "--out",
            str(tmp_path / "matrix.jsonl"),
        ],
    )

    assert run_model_matrix.main() == 1
    assert "MATRIX GATE FAILED" in capsys.readouterr().err


@pytest.mark.parametrize("task", ["intent", "flashcards", "summary", "qa"])
def test_every_task_is_invoked_the_way_make_invokes_its_runner(task):
    """A matrix that ran a runner differently from `make` would measure a
    different thing from the gate."""
    spec = run_model_matrix._tasks("http://localhost:7820")[task]

    assert spec.argv[0] == "uv"
    assert "--backend-url" in spec.argv
    assert spec.cwd.exists()
