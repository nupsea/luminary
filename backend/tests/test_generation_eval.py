"""Unit tests for evals.lib.runners.GenerationEval (S214).

Patches are applied to symbols *imported inside* GenerationEval.run() via
the lazy-import-and-patch-where-it-lives convention -- but for symbols that
are imported lazily inside the method body, patch the source module
(``ragas.evaluate``, etc.) directly.
"""

import sys
import types
from pathlib import Path
from unittest.mock import Mock

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


def _install_fake_generation_modules(monkeypatch, evaluate_func) -> None:
    """Install minimal fake RAGAS/langchain/datasets modules for isolated unit tests."""
    ragas_mod = types.ModuleType("ragas")
    ragas_mod.evaluate = evaluate_func

    ragas_llms_mod = types.ModuleType("ragas.llms")

    class _FakeWrapper:
        def __init__(self, llm) -> None:
            self.llm = llm

    ragas_llms_mod.LangchainLLMWrapper = _FakeWrapper

    ragas_metrics_mod = types.ModuleType("ragas.metrics")
    for name in ("answer_relevancy", "context_precision", "context_recall", "faithfulness"):
        setattr(ragas_metrics_mod, name, types.SimpleNamespace(llm=None))

    datasets_mod = types.ModuleType("datasets")

    class _FakeDataset:
        @classmethod
        def from_list(cls, rows):
            return rows

    datasets_mod.Dataset = _FakeDataset

    langchain_mod = types.ModuleType("langchain_community")
    chat_models_mod = types.ModuleType("langchain_community.chat_models")

    class _FakeChatOllama:
        def __init__(self, model: str, **kwargs) -> None:
            self.model = model
            self.kwargs = kwargs

    chat_models_mod.ChatOllama = _FakeChatOllama

    # Mirror the install path used by langchain_ollama (preferred) and skip
    # the prewarm side-effect to keep the unit test hermetic.
    langchain_ollama_mod = types.ModuleType("langchain_ollama")
    langchain_ollama_mod.ChatOllama = _FakeChatOllama
    monkeypatch.setitem(sys.modules, "langchain_ollama", langchain_ollama_mod)

    # Embeddings stubs -- langchain_huggingface / ragas.embeddings aren't
    # installed in backend's venv (they live in evals/), so mock them.
    langchain_hf_mod = types.ModuleType("langchain_huggingface")

    class _FakeHFEmbeddings:
        def __init__(self, *_, **__) -> None:
            pass

    langchain_hf_mod.HuggingFaceEmbeddings = _FakeHFEmbeddings
    monkeypatch.setitem(sys.modules, "langchain_huggingface", langchain_hf_mod)

    ragas_embeddings_mod = types.ModuleType("ragas.embeddings")

    class _FakeEmbedWrapper:
        def __init__(self, embeddings) -> None:
            self.embeddings = embeddings

    ragas_embeddings_mod.LangchainEmbeddingsWrapper = _FakeEmbedWrapper
    monkeypatch.setitem(sys.modules, "ragas.embeddings", ragas_embeddings_mod)

    ragas_run_config_mod = types.ModuleType("ragas.run_config")

    class _FakeRunConfig:
        def __init__(self, **kwargs) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

    ragas_run_config_mod.RunConfig = _FakeRunConfig
    monkeypatch.setitem(sys.modules, "ragas.run_config", ragas_run_config_mod)

    import evals.lib.runners as _runners_mod  # noqa: PLC0415
    # Reset the embeddings cache so this test gets fresh fakes (some other
    # test may have populated it with real instances).
    monkeypatch.setattr(_runners_mod, "_CACHED_EMBEDDINGS", None)
    monkeypatch.setattr(_runners_mod, "_CACHED_HF_MODEL", None)
    monkeypatch.setattr(_runners_mod, "_prewarm_ollama", lambda _model: None)

    monkeypatch.setitem(sys.modules, "ragas", ragas_mod)
    monkeypatch.setitem(sys.modules, "ragas.llms", ragas_llms_mod)
    monkeypatch.setitem(sys.modules, "ragas.metrics", ragas_metrics_mod)
    monkeypatch.setitem(sys.modules, "datasets", datasets_mod)
    monkeypatch.setitem(sys.modules, "langchain_community", langchain_mod)
    monkeypatch.setitem(sys.modules, "langchain_community.chat_models", chat_models_mod)


def test_generation_eval_metrics_flow_from_ragas_to_dict(monkeypatch):
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
    mock_eval = Mock(return_value=_FakeResult(fake_df))

    def _fake_evaluate(**kwargs):
        return mock_eval(**kwargs)

    _install_fake_generation_modules(monkeypatch, _fake_evaluate)
    # full_metrics=True opts back into context_precision/context_recall, which
    # are skipped in the default fast/reliable path.
    out = GenerationEval().run(
        _SAMPLES, judge_model="ollama/test-model", full_metrics=True
    )

    assert mock_eval.called
    assert out["faithfulness"] == pytest.approx(0.80)
    assert out["answer_relevance"] == pytest.approx(0.70)
    assert out["context_precision"] == pytest.approx(0.75)
    assert out["context_recall"] == pytest.approx(0.60)


def test_generation_eval_graceful_skip_on_judge_unreachable(monkeypatch):
    """When the judge raises (e.g. Ollama down), all metrics are None."""
    def _raise_connection_error(**kwargs):
        raise ConnectionRefusedError("ollama down")

    _install_fake_generation_modules(monkeypatch, _raise_connection_error)
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
