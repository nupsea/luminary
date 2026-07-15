"""Abstract eval runner base classes.

Concrete runners (RetrievalEval implementation in run_eval.py CLI;
GenerationEval added in S214; ClassifierEval added in S218) implement
``.run(samples) -> dict`` and rely on ``.assert_thresholds`` to enforce
quality gates.
"""

import re
import sys
from abc import ABC, abstractmethod
from typing import Any

# Split an answer into claim-level units. HHEM scores a single (premise,
# hypothesis) pair, and a whole multi-sentence answer collapses to a near-zero
# score the moment ONE sentence is unsupported -- even when every other sentence
# is strongly entailed. Faithfulness is therefore measured claim-by-claim (as
# RAGAS does) and averaged, so an unsupported sentence costs 1/N, not the whole
# answer. Strip leading markdown list markers so bullet points score as claims.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_LIST_MARKER = re.compile(r"^\s*([-*+]|\d+[.)])\s+")


def _split_claims(answer: str) -> list[str]:
    claims: list[str] = []
    for raw_line in answer.splitlines():
        line = _LIST_MARKER.sub("", raw_line.strip())
        if not line:
            continue
        for raw_sentence in _SENTENCE_SPLIT.split(line):
            sentence = raw_sentence.strip()
            if len(sentence) >= 12:
                claims.append(sentence)
    return claims

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


# Default HHEM-2.1-Open; swap via FAITHFULNESS_MODEL env var.
_HHEM_MODEL = "vectara/hallucination_evaluation_model"

# HHEM-2.1-Open has no context limit (unlike 1.0's 512 cap), so the tokenizer's
# "longer than 512" warning is flan-t5-base's nominal default and is safe to
# ignore. Memory is the real constraint: predict() pads every pair to the batch
# longest and runs them in ONE forward, and T5 attention costs
# batch * heads * seq^2 * 4B per layer -- a 4.7k-token premise over ~350 pairs
# asks for ~377GB in a single allocation, which the OS answers by killing
# unrelated apps rather than raising OOM. Batches are therefore sized adaptively
# against a fixed attention budget so peak memory stays flat as seq grows.
_FAITH_ATTN_BUDGET = 32 * 512 * 512  # ~0.4GB/layer on flan-t5-base
_FAITH_MAX_BATCH = 32
# Backstop only: real context units run ~477 tok (p95 819), so this should never
# bite. It exists so one pathological premise cannot resurrect the blowup.
_FAITH_MAX_TOKENS = 2048
_PROMPT_OVERHEAD_TOKENS = 32  # the "Determine if the hypothesis..." wrapper
_faith_scorer: "_NliFaithfulnessScorer | None" = None


def _models_cache_dir(model_name: str) -> Any:
    # Same $DATA_DIR/models/<slug> tree as the reranker; standalone evals have no
    # app config, so resolve DATA_DIR from env, falling back to backend/.luminary.
    import os  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    repo_root = Path(__file__).resolve().parents[2]
    data_dir = os.environ.get("LUMINARY_DATA_DIR") or str(repo_root / "backend" / ".luminary")
    slug = model_name.rsplit("/", 1)[-1].lower()
    cache_dir = Path(data_dir).expanduser() / "models" / slug
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


class _NliFaithfulnessScorer:
    def __init__(self, model_name: str | None = None) -> None:
        import os  # noqa: PLC0415

        self._model: Any = None
        self._model_name = model_name or os.environ.get("FAITHFULNESS_MODEL", _HHEM_MODEL)

    @property
    def model_name(self) -> str:
        return self._model_name

    def _load(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoModelForSequenceClassification  # noqa: PLC0415

        cache_dir = _models_cache_dir(self._model_name)
        # trust_remote_code: HHEM ships a custom model class. Pin a revision if
        # this ever runs outside the eval harness.
        self._model = AutoModelForSequenceClassification.from_pretrained(
            self._model_name,
            trust_remote_code=True,
            cache_dir=str(cache_dir),
        )
        print(f"Loaded NLI faithfulness model {self._model_name}", file=sys.stderr)

    def _tokenizer(self) -> Any:
        # HHEM's custom class misspells the attribute (`tokenzier`); fall back to
        # the foundation tokenizer if a swapped-in model spells it correctly.
        tok = getattr(self._model, "tokenzier", None) or getattr(self._model, "tokenizer", None)
        if tok is None:
            from transformers import AutoTokenizer  # noqa: PLC0415

            tok = AutoTokenizer.from_pretrained(self._model.config.foundation)
        return tok

    def _n_tokens(self, text: str) -> int:
        return len(self._tokenizer()(text, add_special_tokens=False)["input_ids"])

    def _truncate(self, text: str, budget: int) -> str:
        if budget <= 0:
            return ""
        tok = self._tokenizer()
        ids = tok(text, add_special_tokens=False)["input_ids"]
        if len(ids) <= budget:
            return text
        return tok.decode(ids[:budget], skip_special_tokens=True)

    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[float]:
        """Score (premise, hypothesis) pairs -> per-pair consistency in [0, 1].

        Batched to bound peak memory; see _FAITH_ATTN_BUDGET. Pairs are sorted by
        length so padding tracks each batch's longest rather than the global
        longest, and each batch is sized so batch * seq^2 stays under budget --
        keeping peak memory flat whether the premises are 200 or 2000 tokens.
        """
        if not pairs:
            return []
        self._load()

        prepared: list[tuple[str, str, int]] = []
        for raw_premise, raw_hypothesis in pairs:
            hypothesis = self._truncate(raw_hypothesis, _FAITH_MAX_TOKENS // 2)
            hyp_n = self._n_tokens(hypothesis)
            budget = _FAITH_MAX_TOKENS - hyp_n - _PROMPT_OVERHEAD_TOKENS
            premise = self._truncate(raw_premise, budget)
            seq = self._n_tokens(premise) + hyp_n + _PROMPT_OVERHEAD_TOKENS
            prepared.append((premise, hypothesis, seq))

        scores: list[float] = [0.0] * len(pairs)
        order = sorted(range(len(prepared)), key=lambda i: prepared[i][2])

        def flush(idxs: list[int]) -> None:
            raw = self._model.predict([(prepared[i][0], prepared[i][1]) for i in idxs])
            for i, score in zip(idxs, raw, strict=True):
                scores[i] = float(score)

        batch: list[int] = []
        for i in order:
            # Ascending order means `i` is the longest in the batch, so it alone
            # sets the padded width.
            seq = prepared[i][2]
            if batch and (
                len(batch) >= _FAITH_MAX_BATCH
                or (len(batch) + 1) * seq * seq > _FAITH_ATTN_BUDGET
            ):
                flush(batch)
                batch = []
            batch.append(i)
        if batch:
            flush(batch)
        return scores


def _get_faithfulness_scorer() -> _NliFaithfulnessScorer:
    global _faith_scorer  # noqa: PLW0603
    if _faith_scorer is None:
        _faith_scorer = _NliFaithfulnessScorer()
    return _faith_scorer


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
    """Retrieval quality eval: HR@5, MRR@5 and nDCG@10 over /search results."""

    eval_kind = "retrieval"

    def run(self, samples: list[dict], **kwargs) -> dict:
        from evals.lib.retrieval_metrics import (  # noqa: PLC0415
            compute_hit_rate_5,
            compute_mrr,
            compute_ndcg_10,
        )

        return {
            "hit_rate_5": compute_hit_rate_5(samples),
            "mrr": compute_mrr(samples),
            "ndcg_10": compute_ndcg_10(samples),
        }


class NliFaithfulnessEval(_BaseEval):
    """Deterministic NLI faithfulness (no judge): premise=chunk, hypothesis=claim.

    Each claim is scored against every context chunk INDIVIDUALLY and takes its
    best match -- a claim is grounded if any one chunk supports it. Scoring
    against the chunks joined into one ~4.7k-token premise is what HHEM's
    quadratic attention turns into a multi-hundred-GB allocation; per-chunk
    premises keep seq at ~477 tok, and dilute the signal less. Per-answer score
    is the mean over claims, so one unsupported claim costs 1/N rather than the
    whole answer, and answers are weighted equally so a verbose answer does not
    dominate the dataset metric.
    """

    eval_kind = "generation"

    def run(self, samples: list[dict], **kwargs) -> dict:
        scored = [s for s in samples if s.get("answer", "").strip()]
        if not scored:
            return {"faithfulness": None, "faithfulness_model": None}
        try:
            scorer = _get_faithfulness_scorer()
            pairs: list[tuple[str, str]] = []
            layout: list[list[tuple[int, int]]] = []
            for s in scored:
                contexts = [c for c in (s.get("contexts") or []) if c and c.strip()]
                claims = _split_claims(s["answer"]) or [s["answer"]]
                claim_spans: list[tuple[int, int]] = []
                for claim in claims:
                    start = len(pairs)
                    pairs.extend((ctx, claim) for ctx in contexts)
                    claim_spans.append((start, len(pairs)))
                layout.append(claim_spans)
            values = scorer.score_pairs(pairs)
            per_answer: list[float] = []
            for claim_spans in layout:
                # A claim with no context to score against (retrieval returned
                # nothing, yet the pipeline still answered) is by definition
                # ungrounded -> 0.0. Skipping it instead would let a pipeline
                # that retrieves nothing and hallucinates freely drop out of the
                # metric rather than be penalised by it.
                best = [max(values[a:b]) if b > a else 0.0 for a, b in claim_spans]
                if best:
                    per_answer.append(sum(best) / len(best))
            faith = sum(per_answer) / len(per_answer) if per_answer else None
            return {"faithfulness": faith, "faithfulness_model": scorer.model_name}
        except Exception as exc:
            print(
                f"WARNING: NLI faithfulness failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return {"faithfulness": None, "faithfulness_model": None}


_EMPTY_GENERATION_METRICS = {
    "faithfulness": None,
    "answer_relevance": None,
    "context_precision": None,
    "context_recall": None,
}


class GenerationEval(_BaseEval):
    """LLM-judge answer relevance; faithfulness lives in NliFaithfulnessEval (include_faithfulness=True restores the RAGAS path)."""  # noqa: E501

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
            # NliFaithfulnessEval owns faithfulness; skip it here by default.
            include_faithfulness: bool = bool(kwargs.get("include_faithfulness", False))
            metrics_list = [answer_relevancy]
            if include_faithfulness:
                metrics_list.insert(0, faithfulness)
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
            failed_calls = 0
            total_calls = 0
            for col in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
                if col in scores_df.columns:
                    series = scores_df[col]
                    nan_count = int(series.isna().sum())
                    failed_calls += nan_count
                    total_calls += total
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
            # Failure accounting rides along so scores dropped to NaN are
            # visible in the UI instead of silently shrinking the mean's basis.
            out["judge_failed_calls"] = failed_calls
            out["judge_total_calls"] = total_calls
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
