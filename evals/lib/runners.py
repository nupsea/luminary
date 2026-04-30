"""Abstract eval runner base classes.

Concrete runners (RetrievalEval implementation in run_eval.py CLI;
GenerationEval added in S214; ClassifierEval added in S218) implement
``.run(samples) -> dict`` and rely on ``.assert_thresholds`` to enforce
quality gates.
"""

import sys
from abc import ABC, abstractmethod


class _BaseEval(ABC):
    eval_kind: str = "base"

    @abstractmethod
    def run(self, samples: list[dict], **kwargs) -> dict:
        """Compute metrics for the given samples."""
        raise NotImplementedError

    def assert_thresholds(self, metrics: dict, thresholds: dict[str, float]) -> None:
        """Raise AssertionError if any metric falls below its threshold."""
        violations: list[str] = []
        for key, floor in thresholds.items():
            val = metrics.get(key)
            if val is None:
                continue
            if val < floor:
                violations.append(f"{key} {val:.4f} < {floor}")
        if violations:
            raise AssertionError("Quality gate failed: " + "; ".join(violations))


class RetrievalEval(_BaseEval):
    """Retrieval quality eval: HR@5 and MRR over /search results."""

    eval_kind = "retrieval"

    def run(self, samples: list[dict], **kwargs) -> dict:
        from evals.lib.retrieval_metrics import compute_hit_rate_5, compute_mrr  # noqa: PLC0415

        return {
            "hit_rate_5": compute_hit_rate_5(samples),
            "mrr": compute_mrr(samples),
        }


_EMPTY_GENERATION_METRICS = {
    "faithfulness": None,
    "answer_relevance": None,
    "context_precision": None,
    "context_recall": None,
}


class GenerationEval(_BaseEval):
    """LLM-judge generation eval (faithfulness, answer relevance).

    Implemented in S214 (RAGAS + local Ollama judge by default per I-16).
    """

    eval_kind = "generation"

    def run(self, samples: list[dict], **kwargs) -> dict:
        """Score *samples* with RAGAS using a LiteLLM-style ``judge_model``.

        Returns a dict with keys ``faithfulness``, ``answer_relevance``,
        ``context_precision``, ``context_recall``. On any failure (Ollama
        unreachable, ragas import error, malformed result), prints a warning
        to stderr and returns the same keys with ``None`` values (graceful
        skip per AC-7).
        """
        judge_model: str = kwargs.get("judge_model", "")
        if not judge_model:
            print(
                "WARNING: GenerationEval skipped -- no judge_model provided",
                file=sys.stderr,
            )
            return dict(_EMPTY_GENERATION_METRICS)

        try:
            from datasets import Dataset  # noqa: PLC0415
            from langchain_community.chat_models import ChatOllama  # noqa: PLC0415
            from ragas import evaluate  # noqa: PLC0415
            from ragas.llms import LangchainLLMWrapper  # noqa: PLC0415
            from ragas.metrics import (  # noqa: PLC0415
                answer_relevancy,
                context_precision,
                context_recall,
                faithfulness,
            )

            ollama_model = (
                judge_model.split("/", 1)[1]
                if judge_model.startswith("ollama/")
                else judge_model
            )
            wrapper = LangchainLLMWrapper(ChatOllama(model=ollama_model))
            metrics_list = [faithfulness, answer_relevancy, context_precision, context_recall]
            for metric in metrics_list:
                metric.llm = wrapper

            dataset_hf = Dataset.from_list(
                [
                    {
                        "question": s["question"],
                        "answer": s["answer"],
                        "contexts": s["contexts"],
                        "ground_truths": s["ground_truths"],
                    }
                    for s in samples
                ]
            )
            result = evaluate(dataset=dataset_hf, metrics=metrics_list)
            scores_df = result.to_pandas()

            out = dict(_EMPTY_GENERATION_METRICS)
            for col in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
                if col in scores_df.columns:
                    val = float(scores_df[col].mean())
                    key = "answer_relevance" if col == "answer_relevancy" else col
                    out[key] = val
            return out
        except Exception as exc:
            print(
                f"WARNING: RAGAS scoring failed (judge unreachable?): {exc}",
                file=sys.stderr,
            )
            return dict(_EMPTY_GENERATION_METRICS)


class ClassifierEval(_BaseEval):
    """Routing/intent classifier eval (accuracy over expected_route labels).

    Concrete implementation lands in S218 (chat-graph routing accuracy).
    """

    eval_kind = "classifier"

    def run(self, samples: list[dict], **kwargs) -> dict:  # pragma: no cover - implemented in S218
        raise NotImplementedError("ClassifierEval.run is implemented by S218")
