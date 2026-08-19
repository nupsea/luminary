"""Metric tiering for the model matrix — re-exported from the backend.

The definitions live in `app.services.eval_tiers` because both entry points need
them: the API the Quality UI drives, and `evals/run_model_matrix.py` on the
command line. `evals/` already imports from `app.*` and never the reverse, so
this is the direction that keeps one definition rather than two that drift.

Import from here or from `app.services.eval_tiers` -- they are the same objects.
"""

from __future__ import annotations

from app.services.eval_tiers import (
    COUNT_MIN_ABSOLUTE,
    COUNT_RELATIVE_MARGIN,
    EXCLUDED,
    LIBRARY_STATE_DEPENDENT,
    QUALITY,
    RATE_MARGIN,
    STRUCTURAL,
    differs,
    metric_name,
    separation,
    structural_metrics,
    tier,
    unmeasured_tasks,
)

__all__ = [
    "COUNT_MIN_ABSOLUTE",
    "COUNT_RELATIVE_MARGIN",
    "EXCLUDED",
    "LIBRARY_STATE_DEPENDENT",
    "QUALITY",
    "RATE_MARGIN",
    "STRUCTURAL",
    "differs",
    "metric_name",
    "separation",
    "structural_metrics",
    "tier",
    "unmeasured_tasks",
]
