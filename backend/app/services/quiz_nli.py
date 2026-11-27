"""Whether material states a quiz option: entailment from a local NLI model, never a judge model.

A wrong option the material entails is a true statement the quiz would mark wrong. Scored against
three-sentence windows, so a long passage does not dilute a one-sentence claim. Runs on CPU.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from typing import Any

from app.services import model_prefetch
from app.services.model_loading import MODEL_LOAD_LOCK, offline_model_load

logger = logging.getLogger(__name__)

# Measured with facebook/bart-large-mnli; another model needs its own brackets. Wrong options
# against their passage (first rated run, 101 options): the lowest true "wrong" option scored 0.84
# (t-digest, DDIA ch. 1), the highest false one 0.68. Right answers against their key sentence
# (v2 run 3, 92 answers): the lowest clean paraphrase scored 0.90, the highest answer that added a
# claim 0.46; two defensible answers at 0.70 and 0.76 are lost to it.
ENTAILED = 0.8

_WINDOW_SENTENCES = 3
_MAX_TOKENS = 512
_SENTENCE = re.compile(r"(?<=[.!?”\"])\s+(?=[“\"A-Z(•])")


def windows(text: str) -> list[str]:
    """Overlapping runs of three sentences, each sentence once."""
    # A list item is a claim of its own, though it rarely ends with a full stop.
    flat = re.sub(r"\s*\u2022\s*", ". \u2022 ", re.sub(r"\s+", " ", text)).strip(" .")
    sentences = list(dict.fromkeys(p.strip() for p in _SENTENCE.split(flat) if p.strip()))
    if len(sentences) <= _WINDOW_SENTENCES:
        return [" ".join(sentences)] if sentences else []
    return [
        " ".join(sentences[i : i + _WINDOW_SENTENCES])
        for i in range(len(sentences) - _WINDOW_SENTENCES + 1)
    ]


class _Nli:
    def __init__(self) -> None:
        self._model: Any = None
        self._tokenizer: Any = None
        self._entail_index = 0

    def _load(self) -> None:
        if self._model is not None:
            return
        spec = model_prefetch.spec_for("nli")
        if spec is None:
            raise RuntimeError("no NLI model spec")
        cache_dir = model_prefetch.cache_dir(spec)
        model_prefetch.require_snapshot(cache_dir, spec.repo_id)
        with MODEL_LOAD_LOCK, offline_model_load():
            if self._model is not None:
                return
            from transformers import (  # noqa: PLC0415
                AutoModelForSequenceClassification,
                AutoTokenizer,
            )

            kwargs = {"cache_dir": str(cache_dir), "local_files_only": True}
            tokenizer = AutoTokenizer.from_pretrained(spec.repo_id, **kwargs)
            model = AutoModelForSequenceClassification.from_pretrained(spec.repo_id, **kwargs)
            labels = {v.lower(): k for k, v in model.config.id2label.items()}
            self._entail_index = labels["entailment"]
            self._tokenizer, self._model = tokenizer, model.eval()
            logger.info("Loaded quiz NLI model %s", spec.repo_id)

    def entailment(self, premises: Sequence[str], hypothesis: str) -> float:
        """The highest probability that one of *premises* entails *hypothesis*."""
        self._load()
        if not premises:
            return 0.0
        import torch  # noqa: PLC0415

        enc = self._tokenizer(
            list(premises),
            [hypothesis] * len(premises),
            return_tensors="pt",
            padding=True,
            truncation="only_first",
            max_length=_MAX_TOKENS,
        )
        with torch.no_grad():
            probs = self._model(**enc).logits.softmax(-1)
        return float(probs[:, self._entail_index].max())


_nli: _Nli | None = None


def _get() -> _Nli:
    global _nli
    if _nli is None:
        _nli = _Nli()
    return _nli


async def entailment(premises: Sequence[str], hypothesis: str) -> float:
    return await asyncio.to_thread(_get().entailment, premises, hypothesis)
