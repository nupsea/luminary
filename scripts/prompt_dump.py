#!/usr/bin/env python3
"""Print the prompt a task actually sends, and why each part is in it.

The `PromptSpec` refactor makes the real prompt exist only at runtime, which is a
genuine loss for anyone doing prompt work: you can no longer read the string in
the file and know what the model receives. This is the replacement, and it ships
with the refactor rather than after it.

Usage::

    uv run python ../scripts/prompt_dump.py --task flashcards
    uv run python ../scripts/prompt_dump.py --task flashcards --model ollama/llama3.2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.model_registry import (  # noqa: E402
    default_chat_model,
    default_vision_model,
    profile_for,
)
from app.services.document_tagger import DOCUMENT_TAG_SPEC  # noqa: E402
from app.services.flashcard_prompts import (  # noqa: E402
    FLASHCARD_USER_SPEC,
    NOTES_CONCEPT_EXTRACT_SPEC,
)
from app.services.image_enricher import VISION_SPEC  # noqa: E402
from app.services.intent import INTENT_CLASSIFY_SPEC  # noqa: E402
from app.services.note_tagger import NOTE_TAG_SPEC  # noqa: E402
from app.services.prompt_spec import describe, render  # noqa: E402
from app.services.suggestion_service import (  # noqa: E402
    CROSS_DOC_SUGGESTION_SPEC,
    SUGGESTION_SPEC,
)

# Every PromptSpec in the tree. `tests/test_prompt_spec.py` fails if one is
# defined and not listed here, because a prompt nobody can dump is a prompt that
# only exists at runtime -- which is the cost this script pays back.
SPECS = {
    spec.task: spec
    for spec in (
        FLASHCARD_USER_SPEC,
        NOTES_CONCEPT_EXTRACT_SPEC,
        DOCUMENT_TAG_SPEC,
        NOTE_TAG_SPEC,
        VISION_SPEC,
        INTENT_CLASSIFY_SPEC,
        SUGGESTION_SPEC,
        CROSS_DOC_SUGGESTION_SPEC,
    )
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", default="flashcards", choices=sorted(SPECS))
    ap.add_argument("--model", default=None, help="defaults to the configured chat model")
    args = ap.parse_args()

    spec = SPECS[args.task]
    model = args.model or (
        default_vision_model() if spec.task == "vision" else default_chat_model()
    )
    profile = profile_for(model)

    print(f"task   {spec.task}")
    print(f"model  {model}")
    if profile is None:
        print("       (not in the registry: no measured footprint or capability)")
    elif not profile.accommodations_measured:
        print("       (accommodations unmeasured: every one is kept)")
    print()
    print("--- rendered ---")
    print(render(spec, profile))
    print("--- accommodations ---")
    for row in describe(spec, profile):
        print(f"  [{row['applied']:>3}] {row['id']}  ({row['kind']})")
        print(f"        for      {row['introduced_for']}")
        print(f"        because  {row['because']}")
        print(f"        drop     {row['drop_when']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
