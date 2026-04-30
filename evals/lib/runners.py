"""Abstract eval runner base classes.

Concrete runners (RetrievalEval implementation in run_eval.py CLI;
GenerationEval added in S214; ClassifierEval added in S218) implement
``.run(samples) -> dict`` and rely on ``.assert_thresholds`` to enforce
quality gates.
"""

from abc import ABC, abstractmethod


class _BaseEval(ABC):
    eval_kind: str = "base"

    @abstractmethod
    def run(self, samples: list[dict]) -> dict:
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

    def run(self, samples: list[dict]) -> dict:
        from evals.lib.retrieval_metrics import compute_hit_rate_5, compute_mrr

        return {
            "hit_rate_5": compute_hit_rate_5(samples),
            "mrr": compute_mrr(samples),
        }


class GenerationEval(_BaseEval):
    """LLM-judge generation eval (faithfulness, answer relevance).

    Concrete implementation lands in S214 (RAGAS + local Ollama judge).
    """

    eval_kind = "generation"

    def run(self, samples: list[dict]) -> dict:  # pragma: no cover - implemented in S214
        raise NotImplementedError("GenerationEval.run is implemented by S214")


class ClassifierEval(_BaseEval):
    """Routing/intent classifier eval (accuracy over expected_route labels).

    Concrete implementation lands in S218 (chat-graph routing accuracy).
    """

    eval_kind = "classifier"

    def run(self, samples: list[dict]) -> dict:  # pragma: no cover - implemented in S218
        raise NotImplementedError("ClassifierEval.run is implemented by S218")
