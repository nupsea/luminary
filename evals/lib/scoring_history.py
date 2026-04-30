"""Local scores_history.jsonl append helper."""

import json
from datetime import UTC, datetime
from pathlib import Path

SCORES_HISTORY_PATH = Path(__file__).resolve().parent.parent / "scores_history.jsonl"


def append_history(
    dataset: str,
    model: str,
    metrics: dict,
    passed: bool,
    eval_kind: str = "retrieval",
    *,
    path: Path | None = None,
) -> None:
    """Append one eval run to scores_history.jsonl.

    *eval_kind* defaults to "retrieval" so existing callers continue working.
    *path* override is for unit testing against a tmp file.
    """
    target = path if path is not None else SCORES_HISTORY_PATH
    entry = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "dataset": dataset,
        "model": model,
        "eval_kind": eval_kind,
        "hr5": metrics.get("hit_rate_5"),
        "mrr": metrics.get("mrr"),
        "faithfulness": metrics.get("faithfulness"),
        "passed": passed,
    }
    with target.open("a") as f:
        f.write(json.dumps(entry) + "\n")
