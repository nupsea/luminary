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

    ragas_llms_mod = types.ModuleType("ragas.llms")
    ragas_llms_mod.LangchainLLMWrapper = lambda llm: llm

    ragas_metrics_mod = types.ModuleType("ragas.metrics")
    for name in ("answer_relevancy", "context_precision", "context_recall", "faithfulness"):
        setattr(ragas_metrics_mod, name, types.SimpleNamespace(llm=None))

    datasets_mod = types.ModuleType("datasets")
    datasets_mod.Dataset = type("Dataset", (), {"from_list": classmethod(lambda cls, rows: rows)})

    langchain_mod = types.ModuleType("langchain_community")
    chat_models_mod = types.ModuleType("langchain_community.chat_models")
    chat_models_mod.ChatOllama = lambda model: object()

    sys.modules["ragas"] = ragas_mod
    sys.modules["ragas.llms"] = ragas_llms_mod
    sys.modules["ragas.metrics"] = ragas_metrics_mod
    sys.modules["datasets"] = datasets_mod
    sys.modules["langchain_community"] = langchain_mod
    sys.modules["langchain_community.chat_models"] = chat_models_mod


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
assert THRESHOLDS["faithfulness"] == 0.65
assert THRESHOLDS["answer_relevance"] == 0.50


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
