"""Unit tests for evals.lib.runners.GenerationEval (S214).

Patches are applied to symbols *imported inside* GenerationEval.run() via
the lazy-import-and-patch-where-it-lives convention -- but for symbols that
are imported lazily inside the method body, patch the source module
(``ragas.evaluate``, etc.) directly.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.runners import GenerationEval  # noqa: E402

_SAMPLES = [
    {
        "question": "What is 2+2?",
        "answer": "4",
        "contexts": ["Two plus two is four."],
        "ground_truths": ["4"],
    }
]


class _FakeResult:
    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    def to_pandas(self) -> pd.DataFrame:
        return self._df


def test_generation_eval_metrics_flow_from_ragas_to_dict():
    """faithfulness + answer_relevancy from RAGAS land in the result dict."""
    fake_df = pd.DataFrame(
        [
            {
                "faithfulness": 0.80,
                "answer_relevancy": 0.70,
                "context_precision": 0.75,
                "context_recall": 0.60,
            }
        ]
    )
    with (
        patch("ragas.evaluate", return_value=_FakeResult(fake_df)) as mock_eval,
        patch("langchain_community.chat_models.ChatOllama") as mock_chat,
    ):
        mock_chat.return_value = object()  # opaque; LangchainLLMWrapper just stores it
        out = GenerationEval().run(_SAMPLES, judge_model="ollama/test-model")

    assert mock_eval.called
    assert out["faithfulness"] == pytest.approx(0.80)
    assert out["answer_relevance"] == pytest.approx(0.70)
    assert out["context_precision"] == pytest.approx(0.75)
    assert out["context_recall"] == pytest.approx(0.60)


def test_generation_eval_graceful_skip_on_judge_unreachable():
    """When the judge raises (e.g. Ollama down), all metrics are None."""
    with patch("ragas.evaluate", side_effect=ConnectionRefusedError("ollama down")):
        out = GenerationEval().run(_SAMPLES, judge_model="ollama/test-model")

    assert out == {
        "faithfulness": None,
        "answer_relevance": None,
        "context_precision": None,
        "context_recall": None,
    }


def test_generation_eval_skips_without_judge_model():
    """Empty judge_model short-circuits to all-None without importing ragas."""
    out = GenerationEval().run(_SAMPLES, judge_model="")
    assert out == {
        "faithfulness": None,
        "answer_relevance": None,
        "context_precision": None,
        "context_recall": None,
    }


@pytest.mark.slow
def test_generation_eval_live_judge():
    """Live test against local Ollama. Requires Ollama running."""
    out = GenerationEval().run(_SAMPLES, judge_model="ollama/gemma4")
    assert set(out.keys()) == {
        "faithfulness",
        "answer_relevance",
        "context_precision",
        "context_recall",
    }
