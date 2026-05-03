"""Abstract eval runner base classes.

Concrete runners (RetrievalEval implementation in run_eval.py CLI;
GenerationEval added in S214; ClassifierEval added in S218) implement
``.run(samples) -> dict`` and rely on ``.assert_thresholds`` to enforce
quality gates.
"""

import sys
from abc import ABC, abstractmethod
from typing import Any

# Module-level singletons -- HuggingFace embedding model and the LangChain
# wrappers around it are expensive to instantiate (~5-10s cold start). Reuse
# them across calls so back-to-back eval runs in the same process don't pay
# the cost twice.
_CACHED_EMBEDDINGS: Any = None
_CACHED_HF_MODEL: Any = None


_PREWARMED_OLLAMA_MODELS: set[str] = set()


def _prewarm_ollama(model: str) -> None:
    """Issue a tiny generate to make Ollama load the model into memory.

    The first real RAGAS call would otherwise pay a 10-30s cold-start tax
    *while holding* the per-call timeout, which on heavy prompts is what
    pushes runs into the timeout->retry->NaN spiral.
    """
    if model in _PREWARMED_OLLAMA_MODELS:
        return
    try:
        import os  # noqa: PLC0415

        import httpx  # noqa: PLC0415

        base = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        if not base.startswith("http"):
            base = f"http://{base}"
        httpx.post(
            f"{base}/api/generate",
            json={"model": model, "prompt": "ok", "stream": False, "options": {"num_predict": 1}},
            timeout=120.0,
        )
        _PREWARMED_OLLAMA_MODELS.add(model)
    except Exception as exc:
        print(
            f"NOTE: Ollama prewarm failed for {model}: {exc} -- continuing.",
            file=sys.stderr,
        )


def _get_cached_embeddings() -> Any:
    global _CACHED_EMBEDDINGS, _CACHED_HF_MODEL  # noqa: PLW0603
    if _CACHED_EMBEDDINGS is None:
        from langchain_huggingface import HuggingFaceEmbeddings  # noqa: PLC0415
        from ragas.embeddings import LangchainEmbeddingsWrapper  # noqa: PLC0415

        _CACHED_HF_MODEL = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
        _CACHED_EMBEDDINGS = LangchainEmbeddingsWrapper(_CACHED_HF_MODEL)
    return _CACHED_EMBEDDINGS


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

        # Drop context_precision/context_recall by default -- they roughly
        # duplicate the HR@5/MRR signal already produced by RetrievalEval and
        # double the judge-call count. Re-enable with full_metrics=True.
        full_metrics: bool = bool(kwargs.get("full_metrics", False))

        try:
            from datasets import Dataset  # noqa: PLC0415
            from ragas import evaluate  # noqa: PLC0415
            from ragas.llms import LangchainLLMWrapper  # noqa: PLC0415
            from ragas.metrics import (  # noqa: PLC0415
                answer_relevancy,
                context_precision,
                context_recall,
                faithfulness,
            )

            is_openai = judge_model.startswith("openai/")
            is_ollama = judge_model.startswith("ollama/")

            # Ollama defaults that make small-model judges actually finish
            # without truncation or malformed JSON:
            #   num_ctx=8192  -- RAGAS faithfulness sends answer + 5 chunks +
            #                    decomposition prompt; default 2048 truncates
            #                    silently and produces NaN scores.
            #   temperature=0 -- deterministic structured output.
            #   timeout=300   -- some 3B/7B JSON-decomposition prompts genuinely
            #                    take >60s on CPU.
            #   num_predict=2048 -- room for the model to emit full JSON.
            ollama_kwargs = dict(
                temperature=0.0,
                num_ctx=8192,
                num_predict=2048,
                timeout=300,
            )

            if is_ollama:
                try:
                    from langchain_ollama import ChatOllama  # noqa: PLC0415
                except ImportError:
                    from langchain_community.chat_models import ChatOllama  # noqa: PLC0415
                ollama_model = judge_model.split("/", 1)[1]
                chat_llm = ChatOllama(model=ollama_model, **ollama_kwargs)
                _prewarm_ollama(ollama_model)
            elif is_openai:
                from langchain_openai import ChatOpenAI  # noqa: PLC0415
                openai_model = judge_model.split("/", 1)[1]
                chat_llm = ChatOpenAI(model=openai_model, temperature=0.0)
            else:
                # Generic fallback: assume an Ollama-compatible local model.
                try:
                    from langchain_ollama import ChatOllama  # noqa: PLC0415
                except ImportError:
                    from langchain_community.chat_models import ChatOllama  # noqa: PLC0415
                chat_llm = ChatOllama(model=judge_model, **ollama_kwargs)
                _prewarm_ollama(judge_model)

            llm_wrapper = LangchainLLMWrapper(chat_llm)
            embed_wrapper = _get_cached_embeddings()
            metrics_list = [faithfulness, answer_relevancy]
            if full_metrics:
                metrics_list.extend([context_precision, context_recall])
            for metric in metrics_list:
                metric.llm = llm_wrapper
                if hasattr(metric, "embeddings"):
                    metric.embeddings = embed_wrapper

            dataset_hf = Dataset.from_list(
                [
                    {
                        "question": s["question"],
                        "answer": s["answer"],
                        "contexts": s["contexts"],
                        "ground_truths": s["ground_truths"],
                        "reference": s["ground_truths"][0] if s["ground_truths"] else "",
                    }
                    for s in samples
                ]
            )
            import math  # noqa: PLC0415

            from ragas.run_config import RunConfig  # noqa: PLC0415

            # OpenAI's API handles real concurrency; local Ollama serves one
            # generation at a time -- max_workers>1 just causes queue stalls
            # and retry timeouts. Force sequential for Ollama.
            workers = 8 if is_openai else 1
            # Per-call timeout: small Ollama models on CPU can take 1-2 min on
            # the heavier RAGAS prompts.
            per_call_timeout = 300 if is_openai else 900
            run_config = RunConfig(
                timeout=per_call_timeout, max_retries=3, max_workers=workers
            )
            result = evaluate(
                dataset=dataset_hf, metrics=metrics_list, run_config=run_config
            )
            scores_df = result.to_pandas()

            out = dict(_EMPTY_GENERATION_METRICS)
            total = len(scores_df)
            for col in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
                if col in scores_df.columns:
                    series = scores_df[col]
                    nan_count = int(series.isna().sum())
                    if total > 0 and nan_count > 0:
                        pct = nan_count / total
                        marker = "WARNING" if pct >= 0.5 else "NOTE"
                        print(
                            f"{marker}: {col} -- {nan_count}/{total} judge "
                            f"calls failed ({pct:.0%}). Score is mean of "
                            f"successful rows only.",
                            file=sys.stderr,
                        )
                    val = float(series.mean())
                    key = "answer_relevance" if col == "answer_relevancy" else col
                    out[key] = None if math.isnan(val) else val
            return out
        except Exception as exc:
            print(
                f"WARNING: RAGAS scoring failed: {type(exc).__name__}: {exc}",
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
