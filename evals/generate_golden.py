"""Generate a golden Q&A dataset from any source document.

Document-agnostic: point it at any .md/.txt file and it produces a retrieval +
generation golden (question, ground_truth_answer, verbatim context_hint) using a
strong generator model, then cross-verifies every pair with one or more
independent models. Only unanimous-pass pairs are written; the rest land in a
`.flagged.jsonl` sidecar for human review.

This replaces the per-book one-off scripts (generate_alice_golden.py, …) with a
single reusable tool that reuses the same quality filters as the in-app
DB-backed generator (app.services.golden_quality).

Usage:
    uv run python evals/generate_golden.py \
        --source DATA/books/d2l_dive_into_deep_learning.md \
        --out evals/golden/d2l.jsonl \
        --generator-model openai/gpt-4.1 \
        --verify-models ollama/qwen2.5:14b-instruct ollama/mistral \
        --target 50
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (_REPO_ROOT, _REPO_ROOT / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import litellm  # noqa: E402

# GPT-5-class models reject some legacy params (e.g. temperature!=1); let litellm
# drop unsupported params instead of erroring on a one-shot generation run.
litellm.drop_params = True

from app.config import get_settings  # noqa: E402
from app.services.golden_quality import (  # noqa: E402
    build_generation_prompt,
    extract_json_object,
    is_structural_chunk,
    quality_filter,
)
from evals.lib.golden_relevance import find_graded_relevance  # noqa: E402
from evals.lib.golden_verify import (  # noqa: E402
    build_verify_prompt,
    cross_verify,
    failed_axes,
    parse_verdict,
)
from evals.lib.retrieval_metrics import _hint_key, _norm  # noqa: E402

_HEADING_RE = re.compile(r"^#{1,3}\s+\S", re.MULTILINE)

# Reader personas — the question *intents* real users bring to a document. Rotated
# across chunks so the golden reflects the spread of how a book is actually queried,
# not just uniform "what is X?" probes. Document-agnostic.
PERSONAS: list[tuple[str, str]] = [
    ("newcomer", "a beginner who wants a clear definition or basic explanation of a term or idea"),
    ("practitioner", "a hands-on practitioner asking when and how to apply something in practice"),
    ("decision_maker", "someone weighing trade-offs, comparing approaches, or asking why one"
                       " choice is preferred over another"),
    ("deep_diver", "a curious learner probing the intuition, cause, or reason behind a mechanism"),
    ("skeptic", "a skeptic asking about limitations, drawbacks, failure modes, or edge cases"),
]


def complete(model: str, prompt: str, *, timeout: float = 300.0) -> str:
    settings = get_settings()
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "timeout": timeout,
        "temperature": 0,
    }
    if model.startswith("ollama/"):
        kwargs["api_base"] = settings.OLLAMA_URL
        kwargs["num_ctx"] = 8192
    elif model.startswith("openai/"):
        kwargs["api_key"] = settings.OPENAI_API_KEY
    elif model.startswith("anthropic/"):
        kwargs["api_key"] = settings.ANTHROPIC_API_KEY
    resp = litellm.completion(**kwargs)
    return resp.choices[0].message.content or ""


_PG_START_RE = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*", re.I)
_PG_END_RE = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*", re.I)


def strip_gutenberg_boilerplate(text: str) -> str:
    """Cut the Project Gutenberg header/license via the standard markers.

    Ingestion strips this boilerplate, so it never becomes retrievable chunks --
    a golden question sampled from the license appendix is unfindable by
    construction (the alice regeneration produced 12/40 such questions).
    Keyed on the official PG markers only; a no-op for non-PG documents.
    """
    start = _PG_START_RE.search(text)
    end = _PG_END_RE.search(text)
    lo = start.end() if start else 0
    hi = end.start() if end else len(text)
    return text[lo:hi] if hi > lo else text


def chunk_source(text: str, *, min_chars: int = 700, max_chars: int = 3000) -> list[str]:
    """Section-aware chunking: split on markdown headings, then pack paragraphs
    into windows. Falls back to paragraph packing for heading-less text."""
    bounds = [m.start() for m in _HEADING_RE.finditer(text)]
    blocks = (
        [text[a:b] for a, b in zip(bounds, bounds[1:] + [len(text)], strict=False)]
        if bounds
        else [text]
    )
    chunks: list[str] = []
    for block in blocks:
        if len(block) <= max_chars:
            if len(block.strip()) >= min_chars:
                chunks.append(block.strip())
            continue
        buf = ""
        for para in re.split(r"\n\s*\n", block):
            if len(buf) + len(para) + 2 > max_chars and len(buf) >= min_chars:
                chunks.append(buf.strip())
                buf = ""
            buf += para + "\n\n"
        if len(buf.strip()) >= min_chars:
            chunks.append(buf.strip())
    return chunks


def hint_is_verbatim(hint: str, chunk_text: str) -> bool:
    return _hint_key(hint) in _norm(chunk_text)


def generate_for_chunk(chunk: str, *, model: str, ask: int, persona: str | None) -> list[dict]:
    try:
        raw = complete(model, build_generation_prompt(chunk, ask, persona))
        parsed = extract_json_object(raw)
        items = parsed.get("questions", [])
        return [q for q in items if isinstance(q, dict)] if isinstance(items, list) else []
    except Exception as exc:
        print(f"  WARN generation failed: {exc}", file=sys.stderr)
        return []


def make_judge():
    def judge(model: str, question: str, answer: str, context: str) -> dict:
        return parse_verdict(complete(model, build_verify_prompt(question, answer, context)))

    return judge


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate + cross-verify a golden Q&A dataset.")
    ap.add_argument("--source", required=True, type=Path, help="source .md/.txt document")
    ap.add_argument("--out", required=True, type=Path, help="output golden .jsonl path")
    ap.add_argument("--generator-model", default="openai/gpt-4.1", dest="generator_model")
    ap.add_argument(
        "--verify-models",
        nargs="*",
        default=["ollama/qwen2.5:14b-instruct", "ollama/mistral"],
        dest="verify_models",
        help="independent models that must all pass a pair (empty = no verification)",
    )
    ap.add_argument(
        "--verify-axes",
        nargs="*",
        default=["answerable", "answer_correct"],
        dest="verify_axes",
        help="axes the verifiers must all pass (self_contained is enforced upstream by default)",
    )
    ap.add_argument("--target", type=int, default=50, help="target accepted question count")
    ap.add_argument("--per-chunk", type=int, default=3, dest="per_chunk")
    ap.add_argument("--max-chunks", type=int, default=None, dest="max_chunks")
    ap.add_argument("--seed", type=int, default=42,
                    help="shuffle seed so sampling spans the whole document")
    ap.add_argument("--source-file-label", default=None, dest="source_file_label",
                    help="value written to each row's source_file (default: --source path)")
    args = ap.parse_args()

    text = strip_gutenberg_boilerplate(args.source.read_text(encoding="utf-8"))
    source_label = args.source_file_label or str(args.source)
    chunks = [c for c in chunk_source(text) if not is_structural_chunk(c)]
    # Shuffle so a candidate cap doesn't bias the golden toward early chapters.
    random.Random(args.seed).shuffle(chunks)
    if args.max_chunks:
        chunks = chunks[: args.max_chunks]
    print(f"Source: {args.source}  ({len(text):,} chars, {len(chunks)} content chunks)")

    # 1. Generate + quality-filter + verbatim-check per chunk (parallel; the
    #    generator is typically a hosted model that handles concurrency).
    candidates: list[dict] = []
    seen_questions: set[str] = set()

    def _gen(idx_chunk: tuple[int, str]) -> list[dict]:
        idx, chunk = idx_chunk
        persona_name, persona_desc = PERSONAS[idx % len(PERSONAS)]
        raw = generate_for_chunk(
            chunk, model=args.generator_model, ask=args.per_chunk * 2, persona=persona_desc
        )
        kept = quality_filter(raw, chunk)
        out = []
        for item in kept:
            if not hint_is_verbatim(item["context_hint"], chunk):
                continue
            out.append({**item, "_chunk": chunk, "_persona": persona_name})
        return out

    with ThreadPoolExecutor(max_workers=5) as pool:
        for i, batch in enumerate(pool.map(_gen, enumerate(chunks)), start=1):
            for item in batch:
                key = _norm(item["question"])
                if key in seen_questions:
                    continue
                seen_questions.add(key)
                candidates.append(item)
            print(f"  [{i}/{len(chunks)}] candidates so far: {len(candidates)}", file=sys.stderr)
            if len(candidates) >= args.target * 2:
                break

    print(f"Generated {len(candidates)} candidate pairs; cross-verifying with "
          f"{args.verify_models or '(none)'}")

    # 2. Cross-model verification (sequential — local verifiers serve one at a time).
    judge = make_judge()
    accepted: list[dict] = []
    flagged: list[dict] = []
    for idx, item in enumerate(candidates, start=1):
        if len(accepted) >= args.target:
            break
        if not args.verify_models:
            accepted.append(item)
            continue
        gate_axes = tuple(args.verify_axes)
        passed, verdicts = cross_verify(
            question=item["question"],
            answer=item["ground_truth_answer"],
            context=item["_chunk"],
            models=args.verify_models,
            judge=judge,
            gate_axes=gate_axes,
        )
        if passed:
            accepted.append(item)
        else:
            flagged.append(
                {**item, "_failed_axes": failed_axes(verdicts, gate_axes), "_verdicts": verdicts}
            )
        print(f"  [{idx}/{len(candidates)}] accepted={len(accepted)} flagged={len(flagged)}",
              file=sys.stderr)

    # 3. Write golden + flagged sidecar.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for item in accepted:
            f.write(json.dumps({
                "question": item["question"],
                "ground_truth_answer": item["ground_truth_answer"],
                "context_hint": item["context_hint"],
                "relevance": find_graded_relevance(
                    item["context_hint"],
                    item["ground_truth_answer"],
                    item["_chunk"],
                    chunks,
                ),
                "persona": item.get("_persona"),
                "source_file": source_label,
                "document_id": "TBD",
            }) + "\n")
    print(f"\nWrote {len(accepted)} verified pairs to {args.out}")

    # Provenance sidecar — how this golden was made (surfaced in the Quality UI).
    from datetime import UTC, datetime  # noqa: PLC0415

    meta = {
        "name": args.out.stem,
        "source_file": source_label,
        "generated_at": datetime.now(UTC).isoformat(),
        "generator_model": args.generator_model,
        "verify_models": args.verify_models,
        "verify_axes": args.verify_axes,
        "personas": [name for name, _ in PERSONAS],
        "target": args.target,
        "accepted": len(accepted),
        "flagged": len(flagged),
    }
    args.out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if flagged:
        sidecar = args.out.with_suffix(".flagged.jsonl")
        with sidecar.open("w", encoding="utf-8") as f:
            for item in flagged:
                row = {k: v for k, v in item.items() if k != "_chunk"}
                f.write(json.dumps(row) + "\n")
        print(f"Wrote {len(flagged)} flagged pairs (review) to {sidecar}")


if __name__ == "__main__":
    main()
