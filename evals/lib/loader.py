"""Golden dataset loader with Pydantic schema validation."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from evals.lib.schemas import RetrievalGoldenEntry

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "golden"


class GoldenValidationError(ValueError):
    """Raised when a golden file entry fails schema validation.

    Message format: ``<path>:<lineno>: <pydantic-error>``. Inherits from
    ValueError so callers using broad `except ValueError` (e.g. CLI runners)
    catch it; the chained ``__cause__`` is the original pydantic ValidationError.
    """


def load_golden(
    dataset: str,
    schema: type[BaseModel] = RetrievalGoldenEntry,
) -> list[dict[str, Any]]:
    """Load and validate a JSONL golden dataset.

    Each line is parsed and validated through *schema*. Returns a list of
    dicts (model_dump) so existing callers indexing into rows continue to
    work unchanged. Raises GoldenValidationError (a ValueError subclass)
    with a message that includes the file path and 1-based line number on
    invalid entry.
    """
    path = GOLDEN_DIR / f"{dataset}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"golden file not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                entry = schema.model_validate(payload)
            except json.JSONDecodeError as exc:
                raise GoldenValidationError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            except ValidationError as exc:
                raise GoldenValidationError(f"{path}:{lineno}: {exc}") from exc
            rows.append(entry.model_dump())
    return rows
