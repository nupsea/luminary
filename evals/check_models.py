"""Which models an eval run will use, and whether they are all there.

Run this before an eval, not after it fails. The suite reaches for up to three
models and each one goes missing differently: a judge that is not pulled raises
inside a swallowed counter, a vision model that is absent leaves figures
uncaptioned during ingestion, and an answering model chosen in Settings is not
the one `config.py` names.

Two supported shapes, and this prints which one is in force:

  one model    everything -- answering, generation, judging -- is the same id.
               Legal and normal on a laptop. The judged metrics are then scored
               by the model that wrote the answers, which biases them upward;
               the run records `self_judged` and the deterministic metrics
               (retrieval, HHEM grounding, ingestion) are unaffected.

  two models   a text model plus a separate vision model, which is what a
               corpus with figures needs: the vision model captions images at
               ingestion time, and nothing else uses it.

Usage::

    uv run python check_models.py [--backend-url ...] [--judge-model ...]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.lib.environment import capture, self_judging  # noqa: E402


def _installed(ollama_url: str) -> set[str] | None:
    """Model ids Ollama has locally, or None when it cannot be reached."""
    try:
        resp = httpx.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=10.0)
        resp.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return None
    names = set()
    for model in resp.json().get("models", []):
        name = model.get("name") or ""
        names.add(name)
        # `qwen2.5:14b-instruct` and `qwen2.5:14b-instruct:latest` are the same
        # model; the tag is only present in one of the two listings.
        names.add(name.removesuffix(":latest"))
    return names


def _local_id(model: str) -> str | None:
    return model.removeprefix("ollama/") if model.startswith("ollama/") else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend-url", default="http://localhost:7820")
    ap.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    ap.add_argument("--judge-model", default="", help="the judge this run would use")
    args = ap.parse_args()

    env = capture(args.backend_url, judge_model=args.judge_model or None)
    if env.get("capture_error"):
        print(f"backend not reachable: {env['capture_error']}", file=sys.stderr)
        return 1

    roles = {
        "answering (chat)": env["chat_model"],
        "generation": env["generation_model"],
        "background": env["background_model"],
        "vision": env["vision_model"],
    }
    if args.judge_model:
        roles["judge"] = args.judge_model

    installed = _installed(args.ollama_url)
    distinct = {m for m in roles.values() if m}

    print(f"\n  backend {env['backend_version']}  mode={env['llm_mode']}")
    print(f"  corpus  {env['library']['documents']} documents, {env['library']['chunks']} chunks\n")

    missing: list[str] = []
    for role, model in roles.items():
        local = _local_id(model)
        if installed is None or local is None:
            state = "not checked" if local else "remote"
        elif local in installed:
            state = "installed"
        else:
            state = "MISSING"
            missing.append(model)
        print(f"  {role:<18} {model:<34} {state}")

    print(f"\n  {len(distinct)} distinct model(s) in use")
    same = self_judging(env)
    if same:
        print(f"  one model answers and judges ({same}): judged metrics are biased upward,")
        print("  and comparing them to a run judged by another model is not meaningful.")
    if installed is None:
        print(f"  WARNING: Ollama not reachable at {args.ollama_url}; availability unchecked.")
    if missing:
        print(f"\n  FAILED: not installed -- {', '.join(missing)}", file=sys.stderr)
        print("  Pull them, or point the run at models this machine has.", file=sys.stderr)
        return 1
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
