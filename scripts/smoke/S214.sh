#!/usr/bin/env bash
# Smoke test for S214: local-judge generation eval wiring.
#
# Verifies without requiring a live backend or Ollama:
#   1. run_eval.py documents --judge-model and --max-questions.
#   2. evals/pyproject.toml pins ragas and datasets.
#   3. GenerationEval flows mocked RAGAS scores into the metrics dict.
#   4. GenerationEval gracefully skips when the judge raises.
#   5. Thresholds include faithfulness and answer_relevance gates.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

HELP="$(cd "$ROOT/evals" && uv run --no-sync python run_eval.py --help)"
grep -q -- "--judge-model" <<<"$HELP"
grep -q -- "--max-questions" <<<"$HELP"
grep -q -- "Answer-" <<<"$HELP"
grep -q -- "Relevance >= 0.50" <<<"$HELP"

grep -q 'ragas==0.4.3' "$ROOT/evals/pyproject.toml"
grep -q 'datasets==4.5.0' "$ROOT/evals/pyproject.toml"

uv run --project "$ROOT/backend" --no-sync python - <<'PY'
import sys
import types
from pathlib import Path

import pandas as pd

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evals"))

from evals.lib.runners import GenerationEval
from run_eval import THRESHOLDS


class FakeResult:
    def __init__(self, df):
        self._df = df

    def to_pandas(self):
        return self._df


def install_fake_modules(evaluate_func):
    ragas_mod = types.ModuleType("ragas")
    ragas_mod.evaluate = evaluate_func
    # A namespace package: without __path__, `from ragas.run_config import ...`
    # fails with "'ragas' is not a package" even though the submodule is in
    # sys.modules.
    ragas_mod.__path__ = []

    ragas_llms_mod = types.ModuleType("ragas.llms")
    ragas_llms_mod.LangchainLLMWrapper = lambda llm, *args, **kwargs: llm

    ragas_metrics_mod = types.ModuleType("ragas.metrics")
    for name in ("answer_relevancy", "context_precision", "context_recall", "faithfulness"):
        setattr(ragas_metrics_mod, name, types.SimpleNamespace(llm=None))

    datasets_mod = types.ModuleType("datasets")
    datasets_mod.Dataset = type("Dataset", (), {"from_list": classmethod(lambda cls, rows: rows)})

    # Fakes take whatever the caller passes. `ChatOllama(model=...)` grew
    # `temperature` and the runner's other ollama kwargs, and a stub pinned to one
    # positional argument turned that into "RAGAS scoring failed: TypeError" --
    # a stub signature drifting from its caller, reported as a scoring failure.
    langchain_mod = types.ModuleType("langchain_community")
    chat_models_mod = types.ModuleType("langchain_community.chat_models")
    chat_models_mod.ChatOllama = lambda *args, **kwargs: object()

    # The runner prefers langchain_ollama and falls back to langchain_community;
    # stub both so the test does not depend on which one is installed.
    langchain_ollama_mod = types.ModuleType("langchain_ollama")
    langchain_ollama_mod.ChatOllama = lambda *args, **kwargs: object()

    langchain_openai_mod = types.ModuleType("langchain_openai")
    langchain_openai_mod.ChatOpenAI = lambda *args, **kwargs: object()

    # The runner also builds an embeddings wrapper, which would otherwise pull
    # langchain_huggingface and load bge-small just to reach the scoring call
    # this script is about.
    langchain_hf_mod = types.ModuleType("langchain_huggingface")
    langchain_hf_mod.HuggingFaceEmbeddings = lambda *args, **kwargs: object()

    ragas_embeddings_mod = types.ModuleType("ragas.embeddings")
    ragas_embeddings_mod.LangchainEmbeddingsWrapper = lambda emb, *a, **k: emb

    ragas_run_config_mod = types.ModuleType("ragas.run_config")
    ragas_run_config_mod.RunConfig = lambda *args, **kwargs: object()

    sys.modules["ragas"] = ragas_mod
    sys.modules["ragas.llms"] = ragas_llms_mod
    sys.modules["ragas.metrics"] = ragas_metrics_mod
    sys.modules["datasets"] = datasets_mod
    sys.modules["langchain_community"] = langchain_mod
    sys.modules["langchain_community.chat_models"] = chat_models_mod
    sys.modules["langchain_ollama"] = langchain_ollama_mod
    sys.modules["langchain_openai"] = langchain_openai_mod
    sys.modules["langchain_huggingface"] = langchain_hf_mod
    sys.modules["ragas.embeddings"] = ragas_embeddings_mod
    sys.modules["ragas.run_config"] = ragas_run_config_mod


samples = [{
    "question": "q",
    "answer": "a",
    "contexts": ["a supporting context"],
    "ground_truths": ["a"],
}]


def ok_evaluate(**kwargs):
    return FakeResult(pd.DataFrame([{
        "faithfulness": 0.91,
        "answer_relevancy": 0.82,
        "context_precision": 0.73,
        "context_recall": 0.64,
    }]))


install_fake_modules(ok_evaluate)
metrics = GenerationEval().run(samples, judge_model="ollama/test-model")
assert metrics["faithfulness"] == 0.91
assert metrics["answer_relevance"] == 0.82
assert metrics["context_precision"] == 0.73
assert metrics["context_recall"] == 0.64
# 0.65 was the RAGAS LLM-judge bar and is meaningless for HHEM NLI, which scores
# grounding in the retrieved context rather than truth: measured on d2l, nothing
# scored above 0.66 and 0.65 would have passed 1 answer of 12. The gate is 0.30 --
# a collapse detector, not a quality bar -- and run_eval.py carries the reasoning.
# Pinning the old number here asserted a threshold the harness had deliberately left.
assert THRESHOLDS["faithfulness"] == 0.30, THRESHOLDS["faithfulness"]
assert THRESHOLDS["answer_relevance"] == 0.50, THRESHOLDS["answer_relevance"]


def failing_evaluate(**kwargs):
    raise ConnectionRefusedError("ollama down")


install_fake_modules(failing_evaluate)
metrics = GenerationEval().run(samples, judge_model="ollama/test-model")
assert metrics == {
    "faithfulness": None,
    "answer_relevance": None,
    "context_precision": None,
    "context_recall": None,
}

print("PASS: S214 -- local judge flags, pins, mocked RAGAS flow, and graceful skip are green")
PY
