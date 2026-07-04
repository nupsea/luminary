"""Cross-model verification of generated golden Q&A.

Document-agnostic. A candidate Q&A pair is judged independently by one or more
verifier models on three axes; only unanimous-pass candidates are kept, the rest
are set aside (flagged) for human review. The LLM call is injected so the logic
is unit-testable without a live model.
"""

from __future__ import annotations

import json
from collections.abc import Callable

VERIFY_AXES = ("answerable", "answer_correct", "self_contained")

# A judge takes (model, question, answer, context) and returns a verdict dict.
Judge = Callable[[str, str, str, str], dict]


def build_verify_prompt(question: str, answer: str, context: str) -> str:
    return (
        "You are auditing a single flashcard-style Q&A pair against the source"
        " passage it was drawn from. Judge ONLY from the passage.\n\n"
        f"PASSAGE:\n{context[:6000]}\n\n"
        f"QUESTION: {question}\n"
        f"PROPOSED ANSWER: {answer}\n\n"
        "Return ONLY JSON with three booleans:\n"
        '{"answerable": <can the question be answered from the passage?>,\n'
        ' "answer_correct": <is the proposed answer correct and supported by the passage?>,\n'
        ' "self_contained": <is the question understandable on its own, without'
        ' referring to "the text"/"the passage"/"the document"?>}'
    )


def parse_verdict(raw: str) -> dict:
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("verifier response had no JSON object")
    data = json.loads(stripped[start : end + 1])
    return {axis: bool(data.get(axis, False)) for axis in VERIFY_AXES}


def cross_verify(
    *,
    question: str,
    answer: str,
    context: str,
    models: list[str],
    judge: Judge,
    gate_axes: tuple[str, ...] = VERIFY_AXES,
) -> tuple[bool, dict[str, dict]]:
    """Return (passed, per-model verdicts). passed iff every model marks every
    *gate_axes* axis true. Verdicts always carry all axes for transparency, but
    only gate_axes decide acceptance — self_contained is already enforced
    lexically upstream, so gating it again on weak judges over-rejects. A model
    that errors out counts as a fail (conservative)."""
    verdicts: dict[str, dict] = {}
    passed = True
    for model in models:
        try:
            verdict = judge(model, question, answer, context)
        except Exception as exc:
            verdict = {axis: False for axis in VERIFY_AXES}
            verdict["error"] = str(exc)
        verdicts[model] = verdict
        if not all(verdict.get(axis) for axis in gate_axes):
            passed = False
    return passed, verdicts


def failed_axes(verdicts: dict[str, dict], gate_axes: tuple[str, ...] = VERIFY_AXES) -> list[str]:
    """Gated axes that at least one model rejected — explains a flagged pair."""
    out: list[str] = []
    for axis in gate_axes:
        if any(not v.get(axis) for v in verdicts.values()):
            out.append(axis)
    return out
